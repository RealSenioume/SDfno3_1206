"""The ping wheel overlay: one transparent always-on-top window per screen.

``OverlayManager`` owns a lazily created ``OverlayWindow`` for every ``QScreen``
and drives it with global (logical pixel) cursor positions.  A window draws two
things:

* the wheel itself, eight pie sectors whose radius and colour follow a smoothed
  per-sector weight (port of the accepted ``pingWheel_BETA`` prototype), with
  optional slice icons and a 0.13 s ease-out open animation, and
* the burst left behind by a committed ping: two expanding rings, five
  directional streaks, a popping slice icon and the sector name, fading out
  over ``config.mark_duration_ms``.

The module is presentation only: it never inspects the input devices.  ``app.py``
turns hook events into ``begin_at`` / ``commit`` / ``cancel`` calls.

Threading: every method must run on the GUI thread.  The 60 Hz timer is only
alive while a window is visible, so an idle overlay costs nothing.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from functools import partial

try:  # pragma: no cover - the project targets Windows
    import ctypes

    _USER32 = ctypes.windll.user32  # type: ignore[attr-defined]
except (ImportError, AttributeError):  # pragma: no cover
    _USER32 = None

from PyQt5.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QScreen,
)
from PyQt5.QtWidgets import QWidget

from . import actions, assets, geo
from .config import Config
from .jarvis import JarvisRenderer
from .geometry import (
    approach,
    clamp,
    sector_center_angle,
    sector_index,
    sector_label_point,
    sector_span,
)

log = logging.getLogger(__name__)

__all__ = ["OverlayManager", "OverlayWindow", "THEME_ACCENTS"]

#: Accent colour per ``Config.theme`` value.
THEME_ACCENTS: dict[str, tuple[int, int, int]] = {
    "jarvis": (255, 190, 96),
}

_DEFAULT_ACCENT = THEME_ACCENTS["jarvis"]

_FRAME_INTERVAL_MS = 16  # ~60 Hz
_MAX_FRAME_DT = 0.05  # clamp dt so a stalled frame does not jump the animation
_RADIUS_GROWTH = 8.0  # extra radius of a fully highlighted sector
_GLOW_WIDTH = 12.0  # width of the translucent halo behind the hovered sector
_CENTRE_RADIUS = 42.0
_CENTRE_TEXT_WIDTH = 68.0
_LABEL_RADIUS_FACTOR = 0.72
_LABEL_RADIUS_WITH_ICONS = 0.80
_LABEL_POINT_SIZE = 8
_CENTRE_POINT_SIZE = 10
_MARK_LABEL_POINT_SIZE = 9
_MARK_LABEL_MAX_WIDTH = 160.0
_MIN_POINT_SIZE = 6

# --- v0.3 wheel open animation -------------------------------------------------
_OPEN_DURATION = 0.13  # seconds from "invisible small wheel" to full size
_OPEN_START_SCALE = 0.70  # sector radius at the first frame, as a fraction of R

# --- v0.3 slice icons ----------------------------------------------------------
_ICON_RADIUS_FACTOR = 0.60  # icon centre, as a fraction of the slice radius
_ICON_HOVER_GROWTH = 0.10  # hovered icon is 10 % bigger
_ICON_IDLE_COLOUR = (235, 235, 235)
_ICON_IDLE_ALPHA = 200

# --- v0.4.0 jarvis ring choreography -------------------------------------------
_JARVIS_SPANS = (geo.WINDOW_SPAN_INNER, geo.WINDOW_SPAN, geo.WINDOW_SPAN)
_JARVIS_SPEEDS = (geo.SPEED_INNER, geo.SPEED_MIDDLE, geo.SPEED_OUTER)
_JARVIS_FOCUS_TIME = 0.5      # drag-selection shrink
_JARVIS_FOCUS_SPAN = 60.0     # span while a slice is selected
_JARVIS_COMMIT_TIME = 0.2     # release shrink
_JARVIS_COMMIT_SPAN = 45.0    # the selected slice's own span
_JARVIS_COMMIT_FADE = 0.2
_JARVIS_CANCEL_RESTORE = 0.3
_JARVIS_CANCEL_FADE = 0.5
_JARVIS_CENTRE_TIME = 0.5
_JARVIS_RESTORE_TIME = 0.3
#: Commit shrink + fade, plus a frame of slack; used by the DSH bridge.
COMMIT_ANIMATION_MS = int((_JARVIS_COMMIT_TIME + _JARVIS_COMMIT_FADE) * 1000.0) + 50

# --- search-sector frames -----------------------------------------------------
_SEARCH_CAPTURE = (640, 360)  # outer frame: what the screenshot covers
_SEARCH_DECIDE = (320, 180)   # inner frame: what OCR looks at
_SEARCH_FADE_IN = 0.15
_SEARCH_FADE_OUT = 0.20
_SEARCH_DIM = 0.22            # wheel opacity while the frames are visible

# --- v0.3.2 click-to-ping ------------------------------------------------------
_CLICK_MAX_DISTANCE = 8.0  # travel from the centre still treated as a click
_BASIC_PING_NAME = "Ping"  # the centre action's name in logs and marks

# --- v0.3 release burst --------------------------------------------------------
_BURST_ANGLES = (-18.0, -9.0, 0.0, 9.0, 18.0)  # degrees around the slice centre
_BURST_START_RADIUS = 46.0
_BURST_MAX_RADIUS = 92.0
_BURST_LINE_LENGTH = 26.0
_BURST_LINE_ALPHA = 220


@dataclass
class _Mark:
    """One burst left behind by a committed ping."""

    name: str
    pos: QPoint
    start: float
    duration: float
    sector: int = -1


class OverlayWindow(QWidget):
    """A full-screen transparent wheel window for a single ``QScreen``.

    The window never takes focus and never lets the opening click reach the
    application underneath (``WA_TransparentForMouseEvents`` is deliberately
    *not* set).
    """

    committed = pyqtSignal(str)  # sector name
    cancelled = pyqtSignal()
    hover_changed = pyqtSignal(int)  # hovered slice index, -1 in the dead zone

    def __init__(self, screen: QScreen, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._screen: QScreen | None = screen
        self._config = config
        self._count = max(1, int(config.sector_count))
        self._weights: list[float] = [0.0] * self._count
        self._center = QPoint()
        self._hover = -1
        self._open = False
        self._marks: list[_Mark] = []
        self._last_tick = time.perf_counter()
        self._opened_at = 0.0
        self._captured = False
        self._warmed = False
        self._max_distance = 0.0  # furthest the pointer travelled this gesture
        self._jarvis = JarvisRenderer()
        self._jarvis.warm_labels(float(config.wheel_radius))
        self._jarvis_frost: QPixmap | None = None
        self._jarvis_rot = [geo.PHASE_INNER, geo.PHASE_MIDDLE, geo.PHASE_OUTER]
        self._jarvis_shift = 0.0
        self._jarvis_last = time.perf_counter()
        self._jarvis_mode = "idle"
        self._jarvis_mode_start = 0.0
        self._jarvis_focus_angle = 0.0
        self._jarvis_from: tuple[tuple[float, float], ...] | None = None
        self._jarvis_opacity = 1.0
        self._jarvis_ring_scale = 1.0
        self._search_frames_alpha = 0.0
        self._search_frames_hold = False
        # Continuous clock: the rings keep turning between openings and while
        # the cursor idles in the dead zone.
        self._jarvis_born = time.perf_counter()

        self._setup_window()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(_FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self.tick)

        self._apply_geometry()
        self.hide()

    # ------------------------------------------------------------------- setup
    def _setup_window(self) -> None:
        """Apply the flags/attributes required by docs/00-interfaces.md section 6."""
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("lolping overlay")
        # Not setting WA_TransparentForMouseEvents: the window must swallow the
        # click that opened it so the game/app below does not also react.

    def target_screen(self) -> QScreen | None:
        """Return the screen this window was created for (may have gone stale)."""
        return self._screen

    def refit(self) -> None:
        """Re-apply ``screen.geometry()``; harmless when the screen is gone."""
        self._apply_geometry()

    def _screen_rect(self) -> QRect | None:
        """Best-effort geometry of our screen, never raising on a stale object."""
        screen = self._screen
        if screen is not None:
            try:
                rect = screen.geometry()
            except RuntimeError:  # the C++ QScreen was destroyed under us
                self._screen = None
                log.debug("overlay screen disappeared, falling back to the primary screen")
            else:
                if rect.width() > 0 and rect.height() > 0:
                    return rect

        candidates: list[QScreen | None] = []
        try:
            candidates.append(QGuiApplication.screenAt(QPoint(self._center)))
        except (TypeError, AttributeError, RuntimeError):
            log.debug("QGuiApplication.screenAt unavailable", exc_info=True)
        candidates.append(QGuiApplication.primaryScreen())
        for candidate in candidates:
            if candidate is None or candidate is screen:
                continue
            try:
                rect = candidate.geometry()
            except RuntimeError:
                continue
            if rect.width() > 0 and rect.height() > 0:
                return rect
        return None

    def _apply_geometry(self) -> None:
        rect = self._screen_rect()
        if rect is None:
            return
        try:
            if self.geometry() != rect:
                self.setGeometry(rect)
        except RuntimeError:  # pragma: no cover - window already destroyed
            log.debug("cannot apply overlay geometry", exc_info=True)

    # ----------------------------------------------------------------- public
    def set_config(self, config: Config) -> None:
        """Apply new settings; a wheel that is already open updates in place."""
        self._config = config
        count = max(1, int(config.sector_count))
        if count != self._count:
            self._count = count
            self._weights = [0.0] * count
        self._jarvis.warm_labels(float(config.wheel_radius))
        if self._open:
            self._hover = self._hovered_sector()
            self.update()
        self._jarvis_frost = None

    def begin(self, global_pos: QPoint) -> None:
        """Show the wheel centred on ``global_pos`` and start the animation."""
        self._apply_geometry()
        self._center = QPoint(global_pos)
        self._open = True
        self._hover = -1
        self._weights = [0.0] * self._count
        self._last_tick = time.perf_counter()
        self._opened_at = self._last_tick  # drives the 0.13 s open animation
        self._max_distance = 0.0
        self._jarvis.reset()
        self._jarvis_frost = None
        # Rotation is intentionally *not* reset: the rings keep turning in real
        # time between gestures, so releasing or cancelling never snaps them
        # back to the initial phase.
        gap = max(0.0, min(600.0, self._opened_at - self._jarvis_last))
        if gap > 0.0:
            self._jarvis_rot = [
                (rot + speed * gap) % 360.0
                for rot, speed in zip(self._jarvis_rot, _JARVIS_SPEEDS)
            ]
            self._jarvis_shift = (self._jarvis_shift + geo.TEXTURE_SPEED * gap) % 360.0
        self._jarvis_last = self._opened_at
        self._jarvis_mode = "open"
        self._jarvis_mode_start = self._opened_at + 0.001
        self._jarvis_opacity = 1.0
        self._jarvis_ring_scale = 1.0
        self._jarvis_from = None
        self._search_frames_alpha = 0.0
        self._search_frames_hold = False
        if str(self._config.theme).lower() == "jarvis":
            # Capture before show(): the overlay is still hidden, so the grab is
            # the desktop that the glass will sit on.
            self._jarvis_frost = self._capture_frost()

        # Take the capture before painting. Every millisecond between the press
        # and the capture is a millisecond in which the application underneath
        # can still start a drag or a rubber-band selection, so the native handle
        # is created first and the capture re-asserted after the window is shown.
        self._take_pointer_capture()
        self.show()
        self.raise_()
        self._take_pointer_capture()
        # Paint the first frame synchronously: the latency probe measures the
        # time from mouse-down to the first painted frame.
        self.repaint()
        if not self._timer.isActive():
            self._timer.start()

    def _capture_frost(self) -> "QPixmap | None":
        """Blurred desktop under the wheel, feathered like the plate.

        Returns ``None`` when the grab fails (offscreen platform, locked
        desktop, wheel partly off screen); the renderer then falls back to the
        procedural frost texture.
        """
        screen = self._screen
        if screen is None:
            return None
        geometry = screen.geometry()
        dpr = float(screen.devicePixelRatio() or 1.0)
        # Screen-local position of the wheel centre (window may not start at 0,0
        # during previews or on secondary monitors).
        local_x = self._center.x() - geometry.x()
        local_y = self._center.y() - geometry.y()
        radius = max(20.0, float(self._config.wheel_radius)) * 2.88 * 1.02
        side_logical = max(16, int(round(radius * 2.0)))
        left = int(round(local_x - side_logical / 2.0))
        top = int(round(local_y - side_logical / 2.0))
        try:
            # Grab the plate region at native resolution: the blurred desktop
            # must stay anchored to its real position, so it may never be
            # stretched or magnified when the wheel size changes.
            shot = screen.grabWindow(0, left, top, side_logical, side_logical)
        except (RuntimeError, TypeError):
            return None
        if shot.isNull():
            return None
        side = max(16, int(round(side_logical * dpr)))
        canvas = shot.toImage()
        if canvas.width() != side or canvas.height() != side:
            canvas = canvas.scaled(side, side, Qt.IgnoreAspectRatio,
                                   Qt.SmoothTransformation)
        small = canvas.scaled(
            max(8, side // 14), max(8, side // 14),
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
        blurred = small.scaled(
            side, side, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        # radial feather, aligned with the plate: opaque to 1.78 R, fade to 2.88 R
        mask = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        mask.fill(Qt.transparent)
        mask_painter = QPainter(mask)
        try:
            gradient = QRadialGradient(QPointF(side / 2.0, side / 2.0), side / 2.0)
            gradient.setColorAt(0.0, QColor(0, 0, 0, 255))
            gradient.setColorAt(1.78 / 2.88, QColor(0, 0, 0, 255))
            gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
            mask_painter.fillRect(0, 0, side, side, gradient)
        finally:
            mask_painter.end()
        composited = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        composited.fill(Qt.transparent)
        comp = QPainter(composited)
        try:
            comp.drawImage(0, 0, blurred)
            comp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            comp.drawImage(0, 0, mask)
        finally:
            comp.end()
        result = QPixmap.fromImage(composited)
        result.setDevicePixelRatio(dpr)
        return result

    def warm_up(self) -> None:
        """Pay the first-gesture costs now, invisibly.

        The first wheel of a session costs about 100 ms (native window, backing
        store, font database, glyph cache) while later ones cost about 5 ms.
        Nothing is competing for the mouse at start-up, so paying that cost here
        shrinks the window in which the application underneath can start a drag
        before the capture is taken.

        Two separate paths are warmed, and neither can be seen:

        1. the native surface, by showing the window once while it paints only a
           fully transparent frame (nothing is drawn when no wheel is open);
        2. the painting path, by rendering a complete wheel into an offscreen
           image, which initialises the font database, glyph cache, icon paths
           and text metrics.

        Window opacity is deliberately *not* used: a platform plugin that ignores
        it would flash a full-screen wheel at start-up.
        """
        if self.isVisible() or self._open or self._marks:
            return
        try:
            # 1. native surface
            self._apply_geometry()
            self.show()
            self.repaint()
            self.hide()

            # 2. painting path, offscreen and invisible
            self._open = True
            self._hover = min(1, self._count - 1)
            self._weights = [1.0] * self._count
            self._opened_at = time.perf_counter() - 1.0  # open animation finished
            image = QImage(
                max(1, self.width()),
                max(1, self.height()),
                QImage.Format_ARGB32_Premultiplied,
            )
            image.fill(Qt.transparent)
            painter = QPainter(image)
            try:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                self._paint_wheel(painter, time.perf_counter())
            finally:
                painter.end()
            self._warmed = True
        except Exception:  # pragma: no cover - never let a warm-up break startup
            log.debug("overlay warm-up failed", exc_info=True)
        finally:
            self._open = False
            self._hover = -1
            self._weights = [0.0] * self._count
            self._marks.clear()
            if self.isVisible():
                self.hide()

    @property
    def warmed_up(self) -> bool:
        """Whether the disposable first-gesture costs have been paid."""
        return self._warmed

    # ----------------------------------------------------------- mouse capture
    # The press that opens the wheel has already been delivered to whatever was
    # under the cursor, because a global observer cannot withhold input. What can
    # be fixed is the rest of the gesture: by taking the mouse capture, Windows
    # sends WM_CAPTURECHANGED to the application that received the press, and
    # well-behaved applications abort the drag or selection they had started. The
    # move and the release then arrive at this window and never complete a click
    # in the window underneath.
    def _take_pointer_capture(self) -> None:
        if _USER32 is None:
            return
        try:
            _USER32.SetCapture(int(self.winId()))
            self._captured = True
        except Exception:  # pragma: no cover - platform/window edge case
            log.debug("SetCapture failed", exc_info=True)

    def _release_pointer_capture(self) -> None:
        self._captured = False
        if _USER32 is None:
            return
        try:
            _USER32.ReleaseCapture()
        except Exception:  # pragma: no cover
            log.debug("ReleaseCapture failed", exc_info=True)

    def cancel(self) -> None:
        """Close the wheel without a ping; emits ``cancelled`` if it was open."""
        if not self._open:
            return
        self._open = False
        self._hover = -1
        self._weights = [0.0] * self._count
        self._release_pointer_capture()
        self._jarvis_start_cancel(time.perf_counter())
        self.cancelled.emit()
        self._finish_if_idle()

    def commit(self) -> str | None:
        """Resolve the sector under the cursor right now and ping it.

        Returns the sector name, or ``None`` when the cursor is inside the dead
        zone (which cancels the wheel, like the prototype did).
        """
        if not self._open:
            return None
        index = self._hovered_sector()
        if index < 0:
            # No slice: either the user clicked in place (basic ping, like the
            # reference tool's "Alt + click places a ping") or released inside
            # the dead zone after dragging, which cancels.
            if (
                self._config.click_places_ping
                and self._max_distance <= _CLICK_MAX_DISTANCE
            ):
                return self._commit_basic_ping()
            self.cancel()
            return None

        name = self._sector_name(index)
        centre = QPoint(self._center)

        # Rings first: collapse onto the selected slice, then fade.
        self._jarvis_start_commit(
            time.perf_counter(), sector_center_angle(index, self._count)
        )
        # Drop the burst first so the window stays busy animating it, then clear
        # the wheel state and repaint once so the wheel vanishes immediately.
        self.add_mark(name, centre, index)
        self._open = False
        self._hover = -1
        self._weights = [0.0] * self._count
        self._release_pointer_capture()
        self.repaint()
        self.committed.emit(name)
        return name

    def _commit_basic_ping(self) -> str:
        """Commit the centre action: a click without dragging."""
        centre = QPoint(self._center)
        self._jarvis_start_centre(time.perf_counter())
        self.add_mark(_BASIC_PING_NAME, centre, -1)
        self._open = False
        self._hover = -1
        self._weights = [0.0] * self._count
        self._release_pointer_capture()
        self.repaint()
        self.committed.emit(_BASIC_PING_NAME)
        return _BASIC_PING_NAME

    def add_mark(self, name: str, global_pos: QPoint, sector: int = -1) -> None:
        """Animate a ping burst at ``global_pos``.

        ``sector`` is the committed slice index (used for the directional
        streaks and the icon pop); it is optional so callers from v0.2 that pass
        only ``(name, global_pos)`` keep working.
        """
        duration = max(0.05, float(self._config.mark_duration_ms) / 1000.0)
        self._marks.append(
            _Mark(
                name=str(name),
                pos=QPoint(global_pos),
                start=time.perf_counter(),
                duration=duration,
                sector=int(sector),
            )
        )
        self._apply_geometry()
        if not self.isVisible():
            # A mark may outlive the last visible frame; make sure it is seen.
            self.show()
            self.raise_()
        if not self._timer.isActive():
            self._last_tick = time.perf_counter()
            self._timer.start()
        self.update()

    def is_open(self) -> bool:
        return self._open

    # --------------------------------------------------------------- animation
    def tick(self) -> None:
        """Advance weights/marks by one frame; called by the 60 Hz timer."""
        now = time.perf_counter()
        dt = clamp(now - self._last_tick, 0.0, _MAX_FRAME_DT)
        self._last_tick = now

        if not self.isVisible():
            self._timer.stop()
            return

        self._jarvis_advance(now, dt)
        self._advance_search_frames(dt)
        elapsed = now - self._jarvis_mode_start
        if self._jarvis_mode == "restore" and elapsed >= _JARVIS_RESTORE_TIME:
            self._jarvis_mode = "open"
        elif self._jarvis_mode == "commit" and elapsed >= (
            _JARVIS_COMMIT_TIME + _JARVIS_COMMIT_FADE
        ):
            self._jarvis_mode = "idle"
            self._jarvis.reset()
        elif self._jarvis_mode == "cancel" and elapsed >= (
            _JARVIS_CANCEL_RESTORE + _JARVIS_CANCEL_FADE
        ):
            self._jarvis_mode = "idle"
            self._jarvis.reset()
        elif self._jarvis_mode == "centre" and elapsed >= _JARVIS_CENTRE_TIME:
            self._jarvis_mode = "idle"
            self._jarvis.reset()

        # Screen hot-plug/resolution changes are cheap to notice here and far
        # more robust than keeping QScreen signal connections alive.
        self._apply_geometry()

        if self._open:
            hover = self._hovered_sector()
            if hover != self._hover:
                self._hover = hover
                # Sound layer in app.py listens to this; emit only on changes.
                self.hover_changed.emit(hover)
                if hover >= 0:
                    self._jarvis_start_focus(
                        now, sector_center_angle(hover, self._count)
                    )
                elif self._jarvis_mode == "focus":
                    self._jarvis_start_restore(now)
            # Track how far the pointer ever travelled from the centre: a release
            # near the centre after a real drag is a cancel, a release near the
            # centre without moving is a click and sends the basic ping.
            cursor = QCursor.pos()
            travelled = math.hypot(
                cursor.x() - self._center.x(), cursor.y() - self._center.y()
            )
            self._max_distance = max(self._max_distance, travelled)
            tau = max(float(self._config.animation_tau), 0.001)
            weights = self._weights
            for index in range(self._count):
                target = 1.0 if index == self._hover else 0.0
                weights[index] = approach(weights[index], target, dt, tau)

        if self._marks:
            self._marks = [mark for mark in self._marks if now - mark.start < mark.duration]

        if (self._open or self._marks or self._jarvis_active()
                or self._search_frames_alpha > 0.02 or self._search_frames_hold):
            self.update()
        else:
            self._finish_if_idle()

    def _finish_if_idle(self) -> None:
        """Stop the timer and hide once neither the wheel nor a mark is left."""
        if (self._open or self._marks or self._jarvis_active()
                or self._search_frames_alpha > 0.02 or self._search_frames_hold):
            return
        self._timer.stop()
        if self.isVisible():
            # Clear the backing store before hiding, like the prototype did,
            # otherwise a stale wheel can flash on screen again.
            self.update()
            self.repaint()
            self.hide()

    # ------------------------------------------------------------- Qt overrides
    def showEvent(self, event) -> None:  # noqa: N802 - Qt name
        self._last_tick = time.perf_counter()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt name
        self._timer.stop()
        self._open = False
        self._hover = -1
        self._weights = [0.0] * self._count
        self._marks.clear()
        self._search_frames_hold = False
        self._search_frames_alpha = 0.0
        self._release_pointer_capture()
        callback = getattr(self, "_hidden_callback", None)
        if callback is not None:
            callback()  # defensive: never leave the mouse captured
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        self._timer.stop()
        self._open = False
        self._marks.clear()
        super().closeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        # Swallow the trigger click; the global hook owns the gesture.
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt name
        event.accept()

    def shutdown(self) -> None:
        """Stop all activity and release the native window (manager cleanup)."""
        self._timer.stop()
        self._open = False
        self._hover = -1
        self._marks.clear()
        self._weights = [0.0] * self._count
        self._release_pointer_capture()
        try:
            self.hide()
            self.close()
        except RuntimeError:  # pragma: no cover - already destroyed
            return
        self.deleteLater()

    # ------------------------------------------------------- v0.4 jarvis anim
    @staticmethod
    def _jarvis_ease(progress: float) -> float:
        progress = clamp(progress, 0.0, 1.0)
        return progress * progress * (3.0 - 2.0 * progress)

    def _jarvis_base_windows(self):
        return tuple(
            (rot, rot + span) for rot, span in zip(self._jarvis_rot, _JARVIS_SPANS)
        )

    def _jarvis_windows(self, now: float):
        """Current (start, span) for the three rings and the fade/scale factors."""
        mode = self._jarvis_mode
        base = self._jarvis_base_windows()
        if mode in ("idle", "open"):
            return base, 1.0, 1.0
        elapsed = max(0.0, now - self._jarvis_mode_start)
        if mode == "focus":
            p = self._jarvis_ease(elapsed / _JARVIS_FOCUS_TIME)
            target = tuple(
                (
                    self._jarvis_focus_angle - _JARVIS_FOCUS_SPAN / 2.0,
                    self._jarvis_focus_angle + _JARVIS_FOCUS_SPAN / 2.0,
                )
                for _ in range(3)
            )
            return self._jarvis_lerp(self._jarvis_from or base, target, p), 1.0, 1.0
        if mode == "restore":
            p = self._jarvis_ease(elapsed / _JARVIS_RESTORE_TIME)
            return self._jarvis_lerp(self._jarvis_from or base, base, p), 1.0, 1.0
        if mode == "commit":
            p = self._jarvis_ease(elapsed / _JARVIS_COMMIT_TIME)
            target = tuple(
                (
                    self._jarvis_focus_angle - _JARVIS_COMMIT_SPAN / 2.0,
                    self._jarvis_focus_angle + _JARVIS_COMMIT_SPAN / 2.0,
                )
                for _ in range(3)
            )
            windows = self._jarvis_lerp(self._jarvis_from or target, target, p)
            fade = clamp((elapsed - _JARVIS_COMMIT_TIME) / _JARVIS_COMMIT_FADE, 0.0, 1.0)
            return windows, 1.0 - fade, 1.0
        if mode == "cancel":
            p = self._jarvis_ease(elapsed / _JARVIS_CANCEL_RESTORE)
            windows = self._jarvis_lerp(self._jarvis_from or base, base, p)
            fade = clamp(
                (elapsed - _JARVIS_CANCEL_RESTORE) / _JARVIS_CANCEL_FADE, 0.0, 1.0
            )
            return windows, 1.0 - fade, 1.0
        if mode == "centre":
            p = self._jarvis_ease(elapsed / _JARVIS_CENTRE_TIME)
            return base, 1.0 - p, max(0.0, 1.0 - p)
        if mode == "done":
            return base, 0.0, 0.0
        return base, 1.0, 1.0

    @staticmethod
    def _jarvis_lerp(from_windows, to_windows, progress: float):
        out = []
        for (start_a, end_a), (start_b, end_b) in zip(from_windows, to_windows):
            span_a = end_a - start_a
            span_b = end_b - start_b
            centre_a = start_a + span_a / 2.0
            centre_b = start_b + span_b / 2.0
            delta = ((centre_b - centre_a + 180.0) % 360.0) - 180.0
            centre = centre_a + delta * progress
            span = span_a + (span_b - span_a) * progress
            out.append((centre - span / 2.0, centre + span / 2.0))
        return tuple(out)

    def _jarvis_start_focus(self, now: float, angle: float) -> None:
        current, _opacity, _scale = self._jarvis_windows(now)
        self._jarvis_from = current
        self._jarvis_focus_angle = angle % 360.0
        self._jarvis_mode = "focus"
        self._jarvis_mode_start = now

    def _jarvis_start_restore(self, now: float) -> None:
        self._jarvis_from, _o, _s = self._jarvis_windows(now)
        self._jarvis_mode = "restore"
        self._jarvis_mode_start = now

    def _jarvis_start_commit(self, now: float, angle: float) -> None:
        self._jarvis_from, _o, _s = self._jarvis_windows(now)
        self._jarvis_focus_angle = angle % 360.0
        self._jarvis_mode = "commit"
        self._jarvis_mode_start = now

    def _jarvis_start_cancel(self, now: float) -> None:
        self._jarvis_from, _o, _s = self._jarvis_windows(now)
        self._jarvis_mode = "cancel"
        self._jarvis_mode_start = now

    def _jarvis_start_centre(self, now: float) -> None:
        self._jarvis_from, _o, _s = self._jarvis_windows(now)
        self._jarvis_mode = "centre"
        self._jarvis_mode_start = now

    def _jarvis_active(self) -> bool:
        return self._jarvis_mode in (
            "focus", "restore", "commit", "cancel", "centre",
        )

    # ------------------------------------------------- search frames
    def _search_sector_active(self) -> bool:
        """True while the hovered slice is the injected search action."""
        if not bool(getattr(self._config, "dsh_mode", False)):
            return False
        if not (0 <= self._hover < self._count):
            return False
        return actions.sector_action(self._sector_name(self._hover)) == actions.OPEN_SEARCH

    def _advance_search_frames(self, dt: float) -> None:
        target = 1.0 if (self._search_frames_hold or self._search_sector_active()) else 0.0
        alpha = self._search_frames_alpha
        if target > alpha:
            alpha = min(target, alpha + dt / _SEARCH_FADE_IN)
        else:
            alpha = max(target, alpha - dt / _SEARCH_FADE_OUT)
        self._search_frames_alpha = alpha

    def begin_search_frames(self) -> None:
        """Keep the frames up across the capture/OCR phase."""
        self._search_frames_hold = True
        if not self.isVisible():
            self.show()
            self.raise_()
        if not self._timer.isActive():
            self._last_tick = time.perf_counter()
            self._timer.start()
        self.update()

    def end_search_frames(self) -> None:
        """Let the frames fade out; the window hides itself afterwards."""
        self._search_frames_hold = False
        self.update()

    def _paint_search_frames(self, painter: QPainter, now: float) -> None:
        alpha = self._search_frames_alpha
        if alpha <= 0.01:
            return
        centre = self.mapFromGlobal(self._center)
        cx, cy = float(centre.x()), float(centre.y())
        capture_w, capture_h = _SEARCH_CAPTURE
        decide_w, decide_h = _SEARCH_DECIDE
        amber = QColor(255, 190, 96)
        white = QColor(232, 236, 244)
        painter.save()
        try:
            painter.setOpacity(alpha)
            painter.setBrush(Qt.NoBrush)
            outer = QRectF(cx - capture_w / 2.0, cy - capture_h / 2.0, capture_w, capture_h)
            inner = QRectF(cx - decide_w / 2.0, cy - decide_h / 2.0, decide_w, decide_h)
            painter.setPen(QPen(QColor(228, 234, 242, 200), 1.0))
            painter.drawRect(outer)
            painter.setPen(QPen(QColor(255, 214, 145, 235), 1.0))
            painter.drawRect(inner)
            # corner brackets on the capture frame
            painter.setPen(QPen(amber, 2.0))
            length = 24.0
            for sx, sy in ((outer.left(), outer.top()), (outer.right(), outer.top()),
                           (outer.left(), outer.bottom()), (outer.right(), outer.bottom())):
                dx = 1.0 if sx == outer.left() else -1.0
                dy = 1.0 if sy == outer.top() else -1.0
                painter.drawLine(QPointF(sx, sy), QPointF(sx + dx * length, sy))
                painter.drawLine(QPointF(sx, sy), QPointF(sx, sy + dy * length))
            # inner brackets
            painter.setPen(QPen(QColor(255, 232, 185, 235), 1.0))
            short = 12.0
            for sx, sy in ((inner.left(), inner.top()), (inner.right(), inner.top()),
                           (inner.left(), inner.bottom()), (inner.right(), inner.bottom())):
                dx = 1.0 if sx == inner.left() else -1.0
                dy = 1.0 if sy == inner.top() else -1.0
                painter.drawLine(QPointF(sx, sy), QPointF(sx + dx * short, sy))
                painter.drawLine(QPointF(sx, sy), QPointF(sx, sy + dy * short))
            # crosshair
            painter.setPen(QPen(white, 1.0))
            painter.drawLine(QPointF(cx - 12, cy), QPointF(cx + 12, cy))
            painter.drawLine(QPointF(cx, cy - 12), QPointF(cx, cy + 12))
            # labels
            painter.setFont(QFont("Consolas", 10, QFont.Bold))
            painter.setPen(QColor(232, 236, 244, 235))
            painter.drawText(QPointF(outer.left() + 8, outer.top() - 8),
                             "CAPTURE  640 x 360")
            painter.setFont(QFont("Consolas", 8, QFont.Bold))
            painter.setPen(QColor(255, 214, 145, 255))
            painter.drawText(QPointF(inner.left() + 6, inner.top() - 6),
                             "DECIDE  320 x 180  ·  OCR")
            painter.setFont(QFont("Consolas", 9, QFont.Bold))
            painter.setPen(QColor(255, 210, 140, 230))
            painter.drawText(QPointF(cx - 78, outer.bottom() + 24),
                             "ON MY WAY  ·  RELEASE TO CAPTURE")
        finally:
            painter.restore()

    def _paint_dimmed_wheel(self, painter: QPainter, now: float, dim: float) -> None:
        """Render the whole wheel to an image, then paint it at ``dim`` opacity."""
        dpr = self._device_pixel_ratio()
        image = QImage(
            max(1, int(self.width() * dpr)),
            max(1, int(self.height() * dpr)),
            QImage.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.transparent)
        image.setDevicePixelRatio(dpr)
        off = QPainter(image)
        try:
            off.setRenderHint(QPainter.Antialiasing, True)
            off.setRenderHint(QPainter.TextAntialiasing, True)
            self._paint_wheel(off, now)
        finally:
            off.end()
        painter.setOpacity(max(0.0, min(1.0, dim)))
        painter.drawImage(0, 0, image)
        painter.setOpacity(1.0)

    def _jarvis_paint(
        self, painter, now: float, cx: float, cy: float, radius: float, ease: float,
    ) -> None:
        windows, opacity, ring_scale = self._jarvis_windows(now)
        telemetry = self._telemetry_values(windows)
        self._jarvis.draw(
            painter,
            cx,
            cy,
            radius * max(0.0, ring_scale),
            elapsed=now - self._jarvis_born,
            ease=ease,
            backdrop=max(0.0, min(1.0, float(self._config.jarvis_backdrop) / 100.0)),
            frost=self._jarvis_frost,
            windows=windows,
            data_shift=self._jarvis_shift,
            opacity=opacity,
            telemetry=telemetry,
        )

    def _telemetry_values(self, windows) -> dict:
        """The ten cells of the telemetry band (all sizes scale with the wheel)."""
        aperture = windows[1][1] - windows[1][0]
        sector = self._sector_name(self._hover) if 0 <= self._hover < self._count else "--"
        observed = self._jarvis.observed_count()
        shift = int(self._jarvis_shift) % 360
        clock = time.strftime("%H:%M:%S")
        cells = [
            ("APERTURE", f"{aperture:.0f}", (230, 190, 120), aperture / 180.0),
            ("SECTOR", sector[:13].upper(), (255, 200, 120), None),
            ("GEO", "114.16/22.30", (170, 178, 190), None),
            ("WEATHER", "26.4C 117", (170, 178, 190), None),
            ("OBSERVED", f"{observed}/16", (170, 178, 190), observed / 16.0),
            ("CLOCK", clock, (140, 146, 158), None),
            ("SPAN", "150/90/90", (140, 146, 158), None),
            ("DRIFT", f"{shift}", (140, 146, 158), shift / 360.0),
            ("DANGER", "ARMED", (255, 120, 100), None),
            ("PING", "READY", (140, 146, 158), None),
        ]
        return {"cells": cells}

    def _jarvis_advance(self, now: float, dt: float) -> None:
        """Movement clock: turns while idle, pauses during the drag shrink."""
        if self._jarvis_mode in ("open", "restore", "commit", "cancel"):
            self._jarvis_rot = [
                (rot + speed * dt) % 360.0
                for rot, speed in zip(self._jarvis_rot, _JARVIS_SPEEDS)
            ]
            self._jarvis_shift = (self._jarvis_shift + geo.TEXTURE_SPEED * dt) % 360.0
        if self._jarvis_mode == "done":
            self._jarvis_mode = "idle"
        self._jarvis_last = now

    # ------------------------------------------------------------------ helpers
    def _sector_available(self, index: int) -> bool:
        """In DSH mode, only slices with an injected action are selectable."""
        if not bool(getattr(self._config, "dsh_mode", False)):
            return True
        return actions.sector_action(self._sector_name(index)) is not None

    def _hovered_sector(self) -> int:
        """Hit-test the global cursor against the wheel using ``geometry``."""
        cursor = QCursor.pos()
        dx = float(cursor.x() - self._center.x())
        dy = float(cursor.y() - self._center.y())
        try:
            index = sector_index(dx, dy, float(self._config.dead_zone), self._count)
        except ValueError:  # pragma: no cover - config is clamped by config.py
            log.debug("invalid sector maths input; treating the cursor as dead centre")
            return -1
        if index >= 0 and not self._sector_available(index):
            return -1
        return index

    def _sector_name(self, index: int) -> str:
        sectors = self._config.sectors
        if 0 <= index < len(sectors):
            name = str(sectors[index]).strip()
            if name:
                return name
        return f"Sector {index + 1}"

    def _accent(self) -> QColor:
        rgb = THEME_ACCENTS.get(str(self._config.theme).lower(), _DEFAULT_ACCENT)
        return QColor(rgb[0], rgb[1], rgb[2])

    def _sector_arc(self, index: int) -> tuple[int, int]:
        """Qt ``drawPie`` start/span in 1/16 degree (counter-clockwise)."""
        start, end = sector_span(index, self._count)
        span = end - start
        return int(round(-(start + span) * 16.0)), int(round(span * 16.0))

    @staticmethod
    def _pie_rect(cx: float, cy: float, radius: float) -> QRect:
        r = max(1, int(round(radius)))
        return QRect(int(round(cx)) - r, int(round(cy)) - r, r * 2, r * 2)

    # ------------------------------------------------- v0.3 animation/icon aids
    def _open_ease(self, now: float) -> float:
        """Ease-out progress of the wheel open animation, in ``[0, 1]``."""
        if not self._open:
            return 1.0
        progress = clamp((now - self._opened_at) / _OPEN_DURATION, 0.0, 1.0)
        return 1.0 - (1.0 - progress) ** 3

    @staticmethod
    def _ease_out_back(progress: float) -> float:
        """Overshooting ease-out used by the icon pop (peaks near 1.1)."""
        c1 = 1.70158
        c3 = c1 + 1.0
        shifted = progress - 1.0
        return 1.0 + c3 * shifted**3 + c1 * shifted**2

    def _device_pixel_ratio(self) -> float:
        try:
            return float(self.devicePixelRatioF())
        except AttributeError:  # pragma: no cover - Qt < 5.6
            return 1.0

    def _draw_slice_icon(
        self,
        painter: QPainter,
        index: int,
        cx: float,
        cy: float,
        size: float,
        colour: QColor,
        opacity: float = 1.0,
    ) -> None:
        """Draw slice ``index``'s user image or vector icon, centred and masked.

        A user-supplied image is clipped to a circle so a rectangular PNG still
        reads as a slice icon; a missing or broken image falls back to the
        vector icon from :mod:`lolping.assets`.
        """
        if size < 1.0:
            return

        config = self._config
        images = config.sector_images or []
        path = str(images[index]).strip() if 0 <= index < len(images) else ""
        if path:
            pixmap = assets.load_pixmap(
                path, max(1, int(round(size))), self._device_pixel_ratio()
            )
            if pixmap is not None and not pixmap.isNull():
                ratio = float(pixmap.devicePixelRatio()) or 1.0
                width = pixmap.width() / ratio
                height = pixmap.height() / ratio
                painter.save()
                try:
                    painter.setOpacity(clamp(opacity, 0.0, 1.0))
                    clip = QPainterPath()
                    clip.addEllipse(QRectF(cx - size / 2.0, cy - size / 2.0, size, size))
                    painter.setClipPath(clip)
                    painter.drawPixmap(
                        QPointF(cx - width / 2.0, cy - height / 2.0), pixmap
                    )
                finally:
                    painter.restore()
                return

        icon_id = assets.resolve_icon(config.sector_icons, index)
        # A PNG in the user's local icon folder overrides the vector icon; the
        # file is git-ignored, so the repository itself still ships no artwork.
        pixmap = assets.load_icon_image(
            icon_id, max(1, int(round(size))), self._device_pixel_ratio()
        )
        if pixmap is not None and not pixmap.isNull():
            ratio = float(pixmap.devicePixelRatio()) or 1.0
            painter.save()
            try:
                painter.setOpacity(clamp(opacity, 0.0, 1.0))
                painter.drawPixmap(
                    QPointF(
                        cx - pixmap.width() / ratio / 2.0,
                        cy - pixmap.height() / ratio / 2.0,
                    ),
                    pixmap,
                )
            finally:
                painter.restore()
            return

        assets.draw_icon(
            painter,
            icon_id,
            QRectF(cx - size / 2.0, cy - size / 2.0, size, size),
            colour,
        )

    # ------------------------------------------------------------- lol skin
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt name
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            # Transparent frame: explicitly clear the backing store so hiding a
            # window can never resurrect pixels from a previous frame.
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            now = time.perf_counter()
            frames = self._search_frames_alpha
            if self._open:
                if frames > 0.01:
                    dim = 1.0 - (1.0 - _SEARCH_DIM) * frames
                    self._paint_dimmed_wheel(painter, now, dim)
                else:
                    self._paint_wheel(painter, now)
            elif self._jarvis_active():
                centre = self.mapFromGlobal(self._center)
                self._jarvis_paint(
                    painter,
                    now,
                    float(centre.x()),
                    float(centre.y()),
                    max(20.0, float(self._config.wheel_radius)),
                    1.0,
                )
            if frames > 0.01:
                self._paint_search_frames(painter, now)
            if self._marks:
                for mark in self._marks:
                    self._paint_mark(painter, mark, now)
        finally:
            painter.end()

    def _paint_wheel(self, painter: QPainter, now: float) -> None:
        config = self._config
        count = self._count
        centre = self.mapFromGlobal(self._center)
        cx = float(centre.x())
        cy = float(centre.y())
        ease = self._open_ease(now)
        base_radius = max(20.0, float(config.wheel_radius))
        accent = self._accent()
        jarvis = str(config.theme).lower() == "jarvis"
        if jarvis:
            self._jarvis_paint(painter, now, cx, cy, base_radius, ease)
        gray = (40.0, 30.0, 18.0) if jarvis else (60.0, 60.0, 60.0)
        weights = self._weights
        # Open animation: grow from 70 % to 100 % of the radius and fade in.
        radius_scale = _OPEN_START_SCALE + (1.0 - _OPEN_START_SCALE) * ease
        radii = [
            (base_radius + _RADIUS_GROWTH * weights[index]) * radius_scale
            for index in range(count)
        ]

        # 1) Translucent glow pass behind every visible sector.
        painter.setPen(Qt.NoPen)
        for index in range(count):
            weight = weights[index]
            if weight < 0.02:
                continue
            radius = radii[index] + _GLOW_WIDTH
            start16, span16 = self._sector_arc(index)
            glow = QColor(accent)
            dim = 1.0 if self._sector_available(index) else 0.28
            glow.setAlpha(int(round(90 * weight * ease * dim)))
            painter.setBrush(glow)
            painter.drawPie(self._pie_rect(cx, cy, radius), start16, span16)

        # 2) Sectors, lightest first so the hovered one ends up on top.
        for index in sorted(range(count), key=lambda item: weights[item]):
            weight = weights[index]
            radius = radii[index]
            start16, span16 = self._sector_arc(index)

            fill = QColor(
                int(round(gray[0] + (accent.red() - gray[0]) * weight)),
                int(round(gray[1] + (accent.green() - gray[1]) * weight)),
                int(round(gray[2] + (accent.blue() - gray[2]) * weight)),
            )
            dim = 1.0 if self._sector_available(index) else 0.28
            fill.setAlpha(int(round((110 + (240 - 110) * weight) * ease * dim)))

            pen_colour = QColor(255, 255, 255)
            pen_colour.setAlpha(int(round((80 + (255 - 80) * weight) * ease * dim)))

            painter.setBrush(fill)
            painter.setPen(QPen(pen_colour, 1.0 + 2.0 * weight))
            painter.drawPie(self._pie_rect(cx, cy, radius), start16, span16)

        # 3) Slice icons on the 0.60 R circle, when enabled.
        if config.show_icons:
            icon_base = float(config.icon_size)
            for index in range(count):
                weight = weights[index]
                size = icon_base * (1.0 + _ICON_HOVER_GROWTH * weight) * ease
                if size < 1.0:
                    continue
                angle = math.radians(sector_center_angle(index, count))
                icon_radius = radii[index] * _ICON_RADIUS_FACTOR
                icon_x = cx + icon_radius * math.cos(angle)
                icon_y = cy + icon_radius * math.sin(angle)
                dim = 1.0 if self._sector_available(index) else 0.28
                if weight > 0.5:
                    colour = QColor(accent)
                    colour.setAlpha(int(round(255 * ease * dim)))
                else:
                    colour = QColor(*_ICON_IDLE_COLOUR)
                    colour.setAlpha(int(round(_ICON_IDLE_ALPHA * ease * dim)))
                self._draw_slice_icon(painter, index, icon_x, icon_y, size, colour, ease)

        # 4) Sector labels, pushed outwards when the icons claim the inner ring.
        #    Hidden while the cursor sits in the dead zone.
        if config.show_labels and 0 <= self._hover < count:
            label_factor = (
                _LABEL_RADIUS_WITH_ICONS if config.show_icons else _LABEL_RADIUS_FACTOR
            )
            for index in range(count):
                label_x, label_y = sector_label_point(
                    cx, cy, index, radii[index] * label_factor, count
                )
                colour = QColor(255, 255, 255)
                dim = 1.0 if self._sector_available(index) else 0.28
                colour.setAlpha(
                    int(round((255 if index == self._hover else 190) * ease * dim))
                )
                max_width = max(28.0, radii[index] * 0.60)
                self._draw_centred_text(
                    painter,
                    self._sector_name(index),
                    label_x,
                    label_y,
                    _LABEL_POINT_SIZE,
                    max_width,
                    colour,
                )

        # 5) Dark centre disc with the current sector name. It fades to 25 % of
        #    its alpha instead of zero so the wheel never blinks out completely.
        disc = max(0.25, ease)
        disc_colour = QColor(9, 6, 3) if jarvis else QColor(30, 30, 30)
        painter.setBrush(QColor(disc_colour.red(), disc_colour.green(),
                                disc_colour.blue(), int(round(230 * disc))))
        painter.setPen(QPen(QColor(255, 255, 255, int(round(255 * disc))), 2.0))
        painter.drawEllipse(QPointF(cx, cy), _CENTRE_RADIUS, _CENTRE_RADIUS)

        text = self._sector_name(self._hover) if self._hover >= 0 else "Caution"
        text_colour = QColor(255, 255, 255) if self._hover < 0 else QColor(accent)
        text_colour.setAlpha(int(round(255 * disc)))
        self._draw_centred_text(
            painter,
            text,
            cx,
            cy,
            _CENTRE_POINT_SIZE,
            _CENTRE_TEXT_WIDTH,
            text_colour,
        )

    def _paint_mark(self, painter: QPainter, mark: _Mark, now: float) -> None:
        elapsed = now - mark.start
        duration = max(mark.duration, 0.001)
        progress = clamp(elapsed / duration, 0.0, 1.0)
        if progress >= 1.0:
            return

        point = self.mapFromGlobal(mark.pos)
        px = float(point.x())
        py = float(point.y())
        accent = self._accent()
        outer_radius = 18.0

        # a) Two expanding rings, the second one slightly delayed.
        for delay in (0.0, 0.14):
            if progress < delay:
                continue
            window = max(0.001, 1.0 - delay)
            local = clamp((progress - delay) / window, 0.0, 1.0)
            radius = 18.0 + 78.0 * (1.0 - (1.0 - local) ** 2)
            outer_radius = max(outer_radius, radius)
            ring_colour = QColor(accent)
            ring_colour.setAlpha(int(round(235 * (1.0 - local))))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(ring_colour, 4.0 - 3.0 * local))
            painter.drawEllipse(QPointF(px, py), radius, radius)

        # b) Five short streaks flying outwards along the committed slice.
        if mark.sector >= 0:
            flight = clamp((progress - 0.05) / 0.50, 0.0, 1.0)
            if progress >= 0.05 and flight < 1.0:
                eased = 1.0 - (1.0 - flight) ** 2
                inner = _BURST_START_RADIUS + (
                    _BURST_MAX_RADIUS - _BURST_LINE_LENGTH - _BURST_START_RADIUS
                ) * eased
                inner = min(inner, _BURST_MAX_RADIUS - _BURST_LINE_LENGTH)
                outer = min(_BURST_MAX_RADIUS, inner + _BURST_LINE_LENGTH)
                streak_colour = QColor(accent)
                streak_colour.setAlpha(int(round(_BURST_LINE_ALPHA * (1.0 - flight))))
                painter.setPen(QPen(streak_colour, 3.0, Qt.SolidLine, Qt.RoundCap))
                centre_angle = sector_center_angle(mark.sector, self._count)
                for offset in _BURST_ANGLES:
                    angle = math.radians(centre_angle + offset)
                    cos_angle = math.cos(angle)
                    sin_angle = math.sin(angle)
                    painter.drawLine(
                        QPointF(px + cos_angle * inner, py + sin_angle * inner),
                        QPointF(px + cos_angle * outer, py + sin_angle * outer),
                    )

        # c) The committed slice icon pops at the centre, then fades out.
        tail = clamp((1.0 - progress) / 0.40, 0.0, 1.0)
        if mark.sector >= 0 and tail > 0.01:
            pop = min(1.12, max(0.0, self._ease_out_back(clamp(progress / 0.30, 0.0, 1.0))))
            icon_size = float(self._config.icon_size) * pop
            if icon_size >= 1.0:
                icon_colour = QColor(accent)
                icon_colour.setAlpha(int(round(255 * tail)))
                self._draw_slice_icon(
                    painter, mark.sector, px, py, icon_size, icon_colour, tail
                )

        # d) Name above the outer ring, fading with the same tail.
        if mark.name and tail > 0.02:
            font, metrics = self._fitted_font(
                painter, mark.name, _MARK_LABEL_POINT_SIZE, _MARK_LABEL_MAX_WIDTH
            )
            width = metrics.horizontalAdvance(mark.name)
            baseline = py - outer_radius - 14.0 + metrics.ascent() / 2.0
            left = px - width / 2.0
            painter.setFont(font)
            halo = QColor(0, 0, 0, int(round(170 * tail)))
            painter.setPen(halo)
            for offset_x, offset_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(QPointF(left + offset_x, baseline + offset_y), mark.name)
            label = QColor(255, 255, 255)
            label.setAlpha(int(round(255 * tail)))
            painter.setPen(label)
            painter.drawText(QPointF(left, baseline), mark.name)

    # -------------------------------------------------------------- text helpers
    @staticmethod
    def _fitted_font(
        painter: QPainter, text: str, point_size: int, max_width: float
    ) -> tuple[QFont, QFontMetrics]:
        """Return a bold font (and its metrics) small enough for ``max_width``."""
        font = QFont("Arial", point_size, QFont.Bold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        while metrics.horizontalAdvance(text) > max_width and font.pointSize() > _MIN_POINT_SIZE:
            font.setPointSize(font.pointSize() - 1)
            painter.setFont(font)
            metrics = painter.fontMetrics()
        return font, metrics

    def _draw_centred_text(
        self,
        painter: QPainter,
        text: str,
        x: float,
        y: float,
        point_size: int,
        max_width: float,
        colour: QColor,
    ) -> None:
        font, metrics = self._fitted_font(painter, text, point_size, max_width)
        painter.setFont(font)
        painter.setPen(colour)
        baseline = y + (metrics.ascent() - metrics.descent()) / 2.0
        painter.drawText(QPointF(x - metrics.horizontalAdvance(text) / 2.0, baseline), text)


class OverlayManager(QObject):
    """Owns one ``OverlayWindow`` per screen and relays its public signals."""

    committed = pyqtSignal(str, object)  # (sector name, global QPoint centre)
    hover_changed = pyqtSignal(int)  # hovered slice index of the active wheel
    #: Emitted once when a wheel appears (True) and once when the last
    #: animation has ended and its window hid (False). No polling needed.
    wheel_active_changed = pyqtSignal(bool)

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        # app.py passes its controller (a plain object) as parent in one place;
        # tolerate that instead of failing to start the tray app.
        if parent is not None and not isinstance(parent, QObject):
            log.debug("ignoring non-QObject overlay parent %r", type(parent).__name__)
            parent = None
        super().__init__(parent)

        self._config = config
        # Keyed by (screen name, id(screen)): the name is the readable key and
        # object identity breaks ties for duplicate/empty screen names.
        self._windows: dict[tuple[str, int], OverlayWindow] = {}
        self._centres: dict[OverlayWindow, QPoint] = {}
        self._active: OverlayWindow | None = None
        self._app: QGuiApplication | None = None

        application = QGuiApplication.instance()
        if isinstance(application, QGuiApplication):
            self._app = application
            try:
                application.screenAdded.connect(self._on_screen_added)
                application.screenRemoved.connect(self._on_screen_removed)
            except (TypeError, RuntimeError):  # pragma: no cover - exotic Qt
                log.debug("cannot connect to QGuiApplication screen signals", exc_info=True)

    # ------------------------------------------------------------------ public
    def _capture_frost(self) -> "QPixmap | None":
        """Blurred desktop under the wheel, feathered like the plate.

        Returns ``None`` when the grab fails (offscreen platform, locked
        desktop, wheel partly off screen); the renderer then falls back to the
        procedural frost texture.
        """
        screen = self._screen
        if screen is None:
            return None
        try:
            shot = screen.grabWindow(0)
        except (RuntimeError, TypeError):
            return None
        if shot.isNull():
            return None
        dpr = float(shot.devicePixelRatio() or 1.0)
        local = self.mapFromGlobal(self._center)
        radius = max(20.0, float(self._config.wheel_radius)) * 2.88 * 1.02
        side = max(16, int(round(radius * 2.0 * dpr)))
        left = int(round(local.x() * dpr - side / 2.0))
        top = int(round(local.y() * dpr - side / 2.0))
        canvas = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        canvas.fill(QColor(0, 0, 0))
        painter = QPainter(canvas)
        try:
            painter.drawPixmap(-left, -top, shot)
        finally:
            painter.end()
        small = canvas.scaled(
            max(8, side // 14), max(8, side // 14),
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
        blurred = small.scaled(
            side, side, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        # radial feather, aligned with the plate: opaque to 1.78 R, fade to 2.88 R
        mask = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        mask.fill(Qt.transparent)
        mask_painter = QPainter(mask)
        try:
            gradient = QRadialGradient(QPointF(side / 2.0, side / 2.0), side / 2.0)
            gradient.setColorAt(0.0, QColor(0, 0, 0, 255))
            gradient.setColorAt(1.78 / 2.88, QColor(0, 0, 0, 255))
            gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
            mask_painter.fillRect(0, 0, side, side, gradient)
        finally:
            mask_painter.end()
        composited = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        composited.fill(Qt.transparent)
        comp = QPainter(composited)
        try:
            comp.drawImage(0, 0, blurred)
            comp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            comp.drawImage(0, 0, mask)
        finally:
            comp.end()
        result = QPixmap.fromImage(composited)
        result.setDevicePixelRatio(dpr)
        return result

    def warm_up(self) -> None:
        """Create and pre-paint one window per screen.

        Called once at start-up. It moves the first-gesture cost (native window
        creation, backing store, font and glyph caches - measured at about 100 ms
        against 5 ms for later gestures) to a moment when no gesture is in
        flight, which closes most of the race that let the application underneath
        start a drag before the capture was taken.
        """
        for screen in QGuiApplication.screens():
            try:
                self._window_for(screen).warm_up()
            except Exception:  # pragma: no cover - a broken screen must not stop start-up
                log.debug("warm-up failed for screen %r", screen, exc_info=True)

    def _notify_hidden(self) -> None:
        self.wheel_active_changed.emit(False)

    def busy(self) -> bool:
        """True while any overlay window is showing the wheel or its afterglow."""
        for window in self._windows.values():
            try:
                if (
                    window.isVisible()
                    or window._open
                    or bool(window._marks)
                    or window._search_frames_hold
                    or window._search_frames_alpha > 0.02
                    or window._jarvis_active()
                ):
                    return True
            except RuntimeError:  # pragma: no cover - window died with its screen
                continue
        return False

    def hold_search_frames(self, global_pos: QPoint) -> None:
        """Keep the capture frames visible while the app grabs the screen."""
        screen = self._screen_at(QPoint(global_pos))
        if screen is None:
            return
        try:
            self._window_for(screen).begin_search_frames()
        except RuntimeError:  # pragma: no cover - window died with its screen
            log.debug("cannot hold search frames", exc_info=True)

    def end_search_frames(self) -> None:
        for window in list(self._windows.values()):
            try:
                window.end_search_frames()
            except RuntimeError:  # pragma: no cover
                pass

    def hide_all(self) -> None:
        """Hide every overlay window at once (used before a region capture)."""
        for window in list(self._windows.values()):
            try:
                window.hide()
            except RuntimeError:  # pragma: no cover - window died with its screen
                pass
        self._active = None

    def set_config(self, config: Config) -> None:
        """Store the config and let every live window pick it up immediately."""
        self._config = config
        for key, window in list(self._windows.items()):
            try:
                window.set_config(config)
            except RuntimeError:  # pragma: no cover - window died with its screen
                self._drop_window(key, window)

    def begin_at(self, global_pos: QPoint) -> None:
        """Open the wheel centred on ``global_pos`` on the screen under it."""
        position = QPoint(global_pos)
        screen = self._screen_at(position)
        if screen is None:
            log.warning(
                "no screen found at (%s, %s); cannot open the wheel",
                position.x(),
                position.y(),
            )
            return

        previous = self._active
        if previous is not None and previous.is_open():
            self._active = None
            try:
                previous.cancel()
            except RuntimeError:  # pragma: no cover
                log.debug("previous overlay window vanished", exc_info=True)

        window = self._window_for(screen)
        window.set_config(self._config)
        self._centres[window] = position
        self._active = window
        window.begin(position)
        self.wheel_active_changed.emit(True)

    def cancel(self) -> None:
        """Close whichever wheel is open, without emitting ``committed``."""
        active = self._active
        if active is not None:
            self._active = None
            try:
                active.cancel()
            except RuntimeError:  # pragma: no cover
                log.debug("overlay window vanished during cancel", exc_info=True)
            return
        for window in list(self._windows.values()):
            try:
                if window.is_open():
                    window.cancel()
            except RuntimeError:  # pragma: no cover
                continue

    def commit(self) -> str | None:
        """Commit the active wheel; returns the sector name or ``None``."""
        window = self._active
        if window is None:
            return None
        try:
            name = window.commit()
        except RuntimeError:  # pragma: no cover - window died mid-gesture
            log.debug("overlay window vanished during commit", exc_info=True)
            self._active = None
            return None
        if name is None:
            self._active = None
        return name

    def is_open(self) -> bool:
        if self._active is None:
            return False
        try:
            return self._active.is_open()
        except RuntimeError:  # pragma: no cover
            self._active = None
            return False

    def shutdown(self) -> None:
        """Release all overlay windows and disconnect from the screen signals."""
        for key, window in list(self._windows.items()):
            self._drop_window(key, window)
        self._windows.clear()
        self._centres.clear()
        self._active = None

        application = self._app
        self._app = None
        if application is None:
            return
        try:
            signals = (
                (application.screenAdded, self._on_screen_added),
                (application.screenRemoved, self._on_screen_removed),
            )
        except RuntimeError:  # pragma: no cover - application already destroyed
            log.debug("application vanished before the overlay shutdown", exc_info=True)
            return
        for signal, slot in signals:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):  # pragma: no cover - already gone
                log.debug("screen signal already disconnected", exc_info=True)

    # ----------------------------------------------------------------- internal
    @staticmethod
    def _screen_at(position: QPoint) -> QScreen | None:
        try:
            screen = QGuiApplication.screenAt(position)
        except (TypeError, AttributeError, RuntimeError):
            screen = None
            log.debug("QGuiApplication.screenAt failed", exc_info=True)
        if screen is not None:
            return screen

        try:
            screens = QGuiApplication.screens()
        except (AttributeError, RuntimeError):  # pragma: no cover - no GUI at all
            screens = []
        for candidate in screens:
            try:
                if candidate.geometry().contains(position):
                    return candidate
            except RuntimeError:
                continue
        return QGuiApplication.primaryScreen()

    @staticmethod
    def _screen_key(screen: QScreen) -> tuple[str, int]:
        name = ""
        try:
            name = str(screen.name() or "")
        except RuntimeError:  # pragma: no cover - destroyed screen wrapper
            log.debug("cannot read QScreen.name()", exc_info=True)
        return (name, id(screen))

    def _window_for(self, screen: QScreen) -> OverlayWindow:
        """Lazily create (or reuse) the window belonging to ``screen``."""
        key = self._screen_key(screen)
        window = self._windows.get(key)
        if window is not None and window.target_screen() is screen:
            return window

        # A screen may be re-registered under a different name; reuse by identity.
        for other_key, other in list(self._windows.items()):
            if other.target_screen() is screen:
                self._windows.pop(other_key, None)
                self._windows[key] = other
                return other

        window = OverlayWindow(screen, self._config)
        window._hidden_callback = self._notify_hidden
        window.committed.connect(partial(self._relay_committed, window))
        window.cancelled.connect(self._clear_active)
        window.hover_changed.connect(partial(self._relay_hover, window))
        self._windows[key] = window
        log.debug("created overlay window for screen %r", key[0])
        return window

    def _relay_committed(self, window: OverlayWindow, name: str) -> None:
        centre = self._centres.get(window)
        centre = QPoint(centre) if centre is not None else QPoint()
        if self._active is window:
            self._active = None
        self.committed.emit(str(name), centre)

    def _relay_hover(self, window: OverlayWindow, hover: int) -> None:
        """Only the wheel that is currently open may drive the hover signal."""
        if self._active is window and window.is_open():
            self.hover_changed.emit(int(hover))

    def _clear_active(self) -> None:
        active = self._active
        if active is not None and not active.is_open():
            self._active = None

    def _drop_window(self, key: tuple[str, int], window: OverlayWindow) -> None:
        self._windows.pop(key, None)
        self._centres.pop(window, None)
        if self._active is window:
            self._active = None
        try:
            window.shutdown()
        except RuntimeError:  # pragma: no cover - already destroyed
            log.debug("overlay window already destroyed", exc_info=True)

    # ------------------------------------------------------------- screen events
    def _on_screen_added(self, screen: QScreen) -> None:
        log.debug("screen added")
        self._refit_all()

    def _on_screen_removed(self, screen: QScreen) -> None:
        log.debug("screen removed")
        for key, window in list(self._windows.items()):
            if window.target_screen() is screen:
                self._drop_window(key, window)
        self._refit_all()

    def _refit_all(self) -> None:
        for key, window in list(self._windows.items()):
            try:
                window.refit()
            except RuntimeError:  # pragma: no cover - window died with its screen
                self._drop_window(key, window)
