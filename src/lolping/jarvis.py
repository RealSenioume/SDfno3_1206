"""Rendering of the ``jarvis`` theme: three rotating observation windows.

The model, as specified for v0.4.0:

* each ring owns a fixed 90 degree window that turns at its own speed;
* the **data is fixed on the track** (the baked contour / isotherm textures and
  the landmark angles never move), so a window reveals whatever lies under it;
* the middle ring is the *observable region* of the inner one: a landmark is
  drawn only where the middle window covers the inner window (an angular
  intersection, no radial overlap involved);
* the trace to a landmark arrives **radially**, with Manhattan segments before
  it, a hollow circle at the name and "dash + gap + hollow circle" at the inner
  end; latitude/longitude ride along the horizontal run;
* entering plays trace (0.1 s) -> name (15 ms) -> flicker -> steady; leaving
  plays the same sequence backwards.

The renderer is pure painting: it owns no window and never touches the input
layer.  ``OverlayWindow`` calls :meth:`JarvisRenderer.draw` once per frame.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QGuiApplication,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QPixmap,
    QPolygonF,
)

from . import assets, geo

log = logging.getLogger(__name__)

__all__ = ["JarvisRenderer"]

GOLD = (255, 190, 96)
AMBER = (255, 140, 70)
WHITE = (255, 246, 220)
CYAN = (150, 225, 255)

_INNER = geo.BAND_INNER
_MIDDLE = geo.BAND_MIDDLE
_OUTER = geo.BAND_OUTER

#: How much wider than the wheel the baked textures extend (widest band + margin).
_TEXTURE_SPAN = geo.BAND_OUTER[1] * 1.03

#: Telemetry band: a continuous ring outside the outer window (radii in R).
_TELEMETRY_BAND = (3.02, 3.32)
_TELEMETRY_CELLS = 10


_KIND_COLOUR = {
    "b": (255, 205, 120),   # buildings
    "s": (150, 210, 255),   # schools
    "r": (255, 160, 110),   # roads
}


def _rgba(colour: tuple[int, int, int], alpha: float) -> QColor:
    out = QColor(*colour)
    out.setAlpha(max(0, min(255, int(round(255.0 * alpha)))))
    return out


def _point(cx: float, cy: float, angle_deg: float, radius: float) -> QPointF:
    angle = math.radians(angle_deg)
    return QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle))


@dataclass
class _Reveal:
    """Per-landmark reveal state (enter/leave timestamps)."""

    entering: bool
    since: float


class JarvisRenderer:
    """Owns the band textures, the landmark reveal states and the paint code."""

    def __init__(self) -> None:
        self._states: dict[str, _Reveal] = {}
        self._scaled: dict[tuple[str, int], QPixmap] = {}
        # Text is the expensive part of the label pass: cache the font objects,
        # the per-glyph pixmaps and the arc layout instead of reshaping text
        # every frame.
        self._fonts: dict[int, tuple[QFont, QFontMetrics]] = {}
        self._glyphs: dict[tuple[str, int], tuple[QPixmap, float, float]] = {}
        self._arc_layouts: dict[tuple[str, int, float], tuple[list[float], list[float], float]] = {}
        self._warmed_radius: float | None = None

    # ------------------------------------------------------------------ setup
    def reset(self) -> None:
        self._states.clear()

    def clear_cache(self) -> None:
        self._scaled.clear()
        self._fonts.clear()
        self._glyphs.clear()
        self._arc_layouts.clear()
        self._warmed_radius = None
        assets.clear_caches()

    def warm_labels(self, radius: float) -> None:
        """Build the label fonts/glyphs/layouts before an animation needs them.

        The first landmark reveal used to pay for dozens of glyph pixmaps inside
        a single frame (a visible ~60 ms hitch); warming up moves that cost to
        wheel creation.
        """
        radius = max(20.0, float(radius))
        if self._warmed_radius is not None and abs(self._warmed_radius - radius) < 0.5:
            return
        self._warmed_radius = radius
        label_size = max(5, int(round(radius * 0.045)))
        tiny = max(4, int(round(radius * 0.032)))
        header = max(5, int(round(radius * 0.043)))
        value = max(6, int(round(radius * 0.058)))
        label_r = (_MIDDLE[0] + 0.72 * (_MIDDLE[1] - _MIDDLE[0])) * radius
        for name, *_rest in geo.LANDMARKS:
            self._arc_layout(name, label_size, label_r)
            for char in set(name):
                if not char.isspace():
                    self._glyph(char, label_size)
        for size in (tiny, header, value):
            self._font_pair(size)

    def _font_pair(self, size: int) -> tuple[QFont, QFontMetrics]:
        pair = self._fonts.get(size)
        if pair is None:
            font = QFont("Consolas", size)
            pair = (font, QFontMetrics(font))
            self._fonts[size] = pair
        return pair

    def _glyph(self, char: str, size: int) -> tuple[QPixmap, float, float]:
        key = (char, size)
        cached = self._glyphs.get(key)
        if cached is not None:
            return cached
        font, metrics = self._font_pair(size)
        ascent = max(2.0, float(metrics.ascent()))
        width = max(1.0, float(metrics.horizontalAdvance(char)))
        height = ascent + max(1.0, float(metrics.descent()))
        dpr = 1.0
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                dpr = max(1.0, float(screen.devicePixelRatio()))
        except (AttributeError, RuntimeError):  # pragma: no cover - headless edge
            dpr = 1.0
        pixmap = QPixmap(
            max(1, int(math.ceil(width * dpr))),
            max(1, int(math.ceil(height * dpr))),
        )
        pixmap.fill(Qt.transparent)
        pixmap.setDevicePixelRatio(dpr)
        glyph_painter = QPainter(pixmap)
        try:
            glyph_painter.setRenderHint(QPainter.TextAntialiasing, True)
            glyph_painter.setFont(font)
            glyph_painter.setPen(QColor(255, 255, 255))
            glyph_painter.drawText(QPointF(0.0, ascent), char)
        finally:
            glyph_painter.end()
        result = (pixmap, width, ascent)
        self._glyphs[key] = result
        return result

    def _arc_layout(
        self, text: str, size: int, radius: float
    ) -> tuple[list[float], list[float], float]:
        key = (text, size, round(radius, 2))
        layout = self._arc_layouts.get(key)
        if layout is None:
            _font, metrics = self._font_pair(size)
            widths = [max(1.0, float(metrics.horizontalAdvance(ch))) for ch in text]
            total = sum(widths)
            offsets: list[float] = []
            cursor = -total / 2.0
            for width in widths:
                offsets.append(cursor + width / 2.0)
                cursor += width
            deg_per_px = 360.0 / (2.0 * math.pi * radius)
            layout = (offsets, widths, deg_per_px)
            self._arc_layouts[key] = layout
        return layout

    # ------------------------------------------------------------------ paint
    def draw(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        radius: float,
        elapsed: float = 0.0,
        *,
        ease: float = 1.0,
        backdrop: float = 0.5,
        frost: QPixmap | None = None,
        windows: tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None = None,
        data_shift: float | None = None,
        opacity: float = 1.0,
        telemetry: dict | None = None,
    ) -> None:
        if radius <= 4.0:
            return
        now = elapsed
        # The rings' own data drifts clockwise, independently of the windows.
        shift = (geo.TEXTURE_SPEED * now) % 360.0 if data_shift is None else data_shift % 360.0
        if windows is not None:
            inner_win, middle_win, outer_win = windows
        else:
            inner_win = geo.window(geo.PHASE_INNER, now, geo.SPEED_INNER, geo.WINDOW_SPAN_INNER)
            middle_win = geo.window(geo.PHASE_MIDDLE, now, geo.SPEED_MIDDLE)
            outer_win = geo.window(geo.PHASE_OUTER, now, geo.SPEED_OUTER)
        lens = geo.lens_intervals(inner_win, middle_win)

        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setOpacity(max(0.0, min(1.0, opacity)))
            if backdrop > 0.0:
                alpha = max(0.0, min(1.0, backdrop)) * ease
                plate_radius = radius * _OUTER[1]
                # Opaque behind the wheel and the inner/middle bands, then a
                # radial feather from the middle band's inner edge out to the
                # outer band's rim.
                inner_stop = _MIDDLE[0] / _OUTER[1]
                gradient = QRadialGradient(QPointF(cx, cy), plate_radius)
                gradient.setColorAt(0.0, QColor(0, 0, 0, int(round(255.0 * alpha))))
                gradient.setColorAt(inner_stop, QColor(0, 0, 0, int(round(255.0 * alpha))))
                gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.setPen(Qt.NoPen)
                painter.setBrush(gradient)
                painter.drawEllipse(
                    QPointF(cx, cy),
                    plate_radius,
                    plate_radius,
                )
            if frost is not None:
                # Blurred desktop under the black glass: drawn 1:1 with the
                # screen so the background content keeps its real position and
                # scale. Only the plate radius (the extent) follows the wheel.
                dpr = float(frost.devicePixelRatio() or 1.0)
                logical = frost.width() / dpr
                half = logical / 2.0
                clip = QPainterPath()
                clip.addEllipse(QPointF(cx, cy),
                                radius * _OUTER[1], radius * _OUTER[1])
                painter.save()
                try:
                    painter.setClipPath(clip)
                    base_opacity = painter.opacity()
                    painter.setOpacity(max(0.0, min(1.0, base_opacity * ease)))
                    # Point overload: drawPixmap honours the pixmap DPR and
                    # paints its logical size, whereas a source rectangle is
                    # read in device pixels and showed only the top-left
                    # quarter on a 150-200 % display.
                    painter.drawPixmap(QPointF(cx - half, cy - half), frost)
                finally:
                    painter.restore()
            else:
                # Fallback: procedural frost texture on top of the plate.
                self._draw_frost(painter, cx, cy, radius, ease, backdrop)
            self._draw_tracks(painter, cx, cy, radius, middle_win, ease)
            self._draw_texture(painter, "contours", cx, cy, radius, inner_win, ease, shift)
            self._draw_texture(painter, "isotherms", cx, cy, radius, outer_win, ease, shift)
            self._draw_highlight(painter, cx, cy, radius, lens, ease)
            self._draw_landmarks(painter, cx, cy, radius, now, middle_win, lens, ease, shift)
            if telemetry is not None:
                self._draw_telemetry(painter, cx, cy, radius, telemetry)
        finally:
            painter.restore()

    # ------------------------------------------------------------- primitives
    @staticmethod
    def _annulus(
        cx: float, cy: float, r0: float, r1: float,
        start: float | None = None, span: float | None = None,
    ) -> QPainterPath:
        """Annulus (optionally one angular sector). Angles are screen-clockwise.

        The sector is built as an explicit polygon: Qt's arc paths can self
        intersect for wide sweeps, and the fill then covers the whole ring.
        """
        path = QPainterPath()
        if start is None or span is None:
            path.addEllipse(QRectF(cx - r1, cy - r1, r1 * 2.0, r1 * 2.0))
            path.addEllipse(QRectF(cx - r0, cy - r0, r0 * 2.0, r0 * 2.0))
            path.setFillRule(Qt.OddEvenFill)
            return path
        steps = max(8, int(abs(span) / 3.0))
        outer = [
            _point(cx, cy, start + span * index / steps, r1) for index in range(steps + 1)
        ]
        inner = [
            _point(cx, cy, start + span * index / steps, r0)
            for index in range(steps, -1, -1)
        ]
        path.addPolygon(QPolygonF(outer + inner))
        path.closeSubpath()
        return path

    def _draw_frost(
        self, painter: QPainter, cx: float, cy: float, radius: float,
        ease: float, backdrop: float,
    ) -> None:
        """Milky grain over the dark plate so it reads as frosted glass."""
        if backdrop <= 0.0:
            return
        pixmap = self._texture_pixmap("frost", radius)
        if pixmap is None:
            return
        side = pixmap.width()
        rect = QRectF(cx - side / 2.0, cy - side / 2.0, side, side)
        clip = QPainterPath()
        # Only the solid part of the plate is frosted; the feathered rim stays
        # a clean radial fade.
        clip.addEllipse(QPointF(cx, cy), radius * _MIDDLE[0], radius * _MIDDLE[0])
        painter.save()
        try:
            base_opacity = painter.opacity()
            painter.setClipPath(clip)
            painter.setOpacity(
                max(0.0, min(1.0, base_opacity * ease))
                * max(0.0, min(1.0, backdrop)) * 0.80
            )
            painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
        finally:
            painter.restore()

    def _draw_tracks(
        self, painter: QPainter, cx: float, cy: float, radius: float,
        middle_win: tuple[float, float], ease: float,
    ) -> None:
        # inner ring: always-on dim band
        painter.fillPath(
            self._annulus(cx, cy, _INNER[0] * radius, _INNER[1] * radius),
            _rgba(GOLD, 0.028 * ease),
        )
        # middle ring: the thick line stays visible, brighter inside its window
        painter.fillPath(
            self._annulus(cx, cy, _MIDDLE[0] * radius, _MIDDLE[1] * radius),
            _rgba(GOLD, 0.045 * ease),
        )
        painter.fillPath(
            self._annulus(
                cx, cy, _MIDDLE[0] * radius, _MIDDLE[1] * radius,
                middle_win[0], middle_win[1] - middle_win[0],
            ),
            _rgba(GOLD, 0.12 * ease),
        )

    def _texture_pixmap(self, name: str, radius: float) -> QPixmap | None:
        source = assets.jarvis_pixmap(name)
        if source is None:
            return None
        side = max(8, int(round(radius * _TEXTURE_SPAN * 2.0)))
        key = (name, side)
        cached = self._scaled.get(key)
        if cached is not None:
            return cached
        scaled = source.scaled(
            side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._scaled[key] = scaled
        return scaled

    def _draw_texture(
        self, painter: QPainter, name: str, cx: float, cy: float, radius: float,
        window: tuple[float, float], ease: float, shift: float = 0.0,
    ) -> None:
        pixmap = self._texture_pixmap(name, radius)
        if pixmap is None:
            return
        span = pixmap.width()
        rect = QRectF(cx - span / 2.0, cy - span / 2.0, span, span)
        clip = self._annulus(
            cx, cy, radius * 0.98, radius * _TEXTURE_SPAN,
            window[0], window[1] - window[0],
        )
        painter.save()
        try:
            base_opacity = painter.opacity()
            painter.setClipPath(clip)
            painter.setOpacity(max(0.0, min(1.0, base_opacity * ease)))
            painter.translate(cx, cy)
            painter.rotate(shift)
            painter.translate(-cx, -cy)
            painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
        finally:
            painter.restore()

    def _draw_highlight(
        self, painter: QPainter, cx: float, cy: float, radius: float,
        lens: list[tuple[float, float]], ease: float,
    ) -> None:
        """Feathered highlight: only the covered part of the inner ring lights up."""
        if ease <= 0.01:
            return
        for start, end in lens:
            span = end - start
            for expand, alpha in ((6.0, 0.05), (3.0, 0.08), (0.0, 0.13)):
                path = self._annulus(
                    cx, cy, _INNER[0] * radius, _INNER[1] * radius,
                    start - expand, span + 2.0 * expand,
                )
                painter.fillPath(path, _rgba(GOLD, alpha * ease))

    # -------------------------------------------------------------- landmarks
    def _update_state(
        self, now: float, shift: float, lens: list[tuple[float, float]],
    ) -> None:
        # The lens must be the animated one (60/45 degrees while focusing),
        # otherwise labels outside the visible window stay alive.
        for name, lat, lon, kind in geo.LANDMARKS:
            angle = (geo.angle_for_lon(lon) + shift) % 360.0
            covered = bool(self._coverage(angle, lens))
            state = self._states.get(name)
            if covered and (state is None or not state.entering):
                self._states[name] = _Reveal(entering=True, since=now)
            elif not covered and state is not None and state.entering:
                self._states[name] = _Reveal(entering=False, since=now)

    @staticmethod
    def _coverage(angle: float, lens: list[tuple[float, float]], feather: float = 3.0) -> float:
        return max(
            (geo.in_interval(angle, start, end, feather) for start, end in lens),
            default=0.0,
        )

    def _draw_landmarks(
        self, painter: QPainter, cx: float, cy: float, radius: float,
        now: float, middle_win: tuple[float, float],
        lens: list[tuple[float, float]], ease: float, shift: float = 0.0,
    ) -> None:
        self._update_state(now, shift, lens)
        stub = radius * 0.16
        gap = radius * 0.030
        for index, (name, lat, lon, kind) in enumerate(geo.LANDMARKS):
            state = self._states.get(name)
            if state is None:
                continue
            elapsed = now - state.since
            line, visible, flicker = geo.reveal_progress(elapsed, state.entering)
            if not state.entering and line <= 0.0:
                self._states.pop(name, None)
                continue
            if line <= 0.0 and visible <= 0.0:
                continue
            angle = (geo.angle_for_lon(lon) + shift) % 360.0
            offset = 5.0 if index % 2 else -5.0
            label_angle = angle + offset
            inner_r = geo.radius_factor(lat, _INNER) * radius
            label_r = (_MIDDLE[0] + 0.72 * (_MIDDLE[1] - _MIDDLE[0])) * radius
            p_label = _point(cx, cy, label_angle, label_r)
            p_inner = _point(cx, cy, angle, inner_r)
            p_stub = _point(cx, cy, angle, inner_r + stub)
            p_dash = _point(cx, cy, angle, inner_r + gap)
            mid_y = p_label.y() + (p_stub.y() - p_label.y()) * 0.55
            route = [
                p_label,
                QPointF(p_label.x(), mid_y),
                QPointF(p_stub.x(), mid_y),
                p_stub,
            ]
            self._stroke_route(painter, route, line * ease)
            if line > 0.0:
                # radial leg towards the centre, then the hollow circle with a gap
                leg_end = QPointF(
                    p_stub.x() + (p_dash.x() - p_stub.x()) * line * ease,
                    p_stub.y() + (p_dash.y() - p_stub.y()) * line * ease,
                )
                painter.setPen(QPen(_rgba(GOLD, 0.55 * ease), max(1.0, radius * 0.012)))
                painter.drawLine(p_stub, leg_end)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(_rgba(WHITE, 0.65 * ease), max(1.0, radius * 0.012)))
                painter.drawEllipse(p_label, radius * 0.035, radius * 0.035)
                painter.drawEllipse(p_inner, radius * 0.028, radius * 0.028)
            if visible > 0.02:
                alpha = visible * flicker * ease
                small = max(5, int(round(radius * 0.045)))
                self._draw_arc_text(
                    painter,
                    cx,
                    cy,
                    label_angle,
                    label_r,
                    name,
                    self._font_pair(small)[0],
                    _rgba(WHITE, 0.85 * alpha),
                )
                # latitude / longitude ride along the horizontal run
                tiny = max(4, int(round(radius * 0.032)))
                painter.setFont(self._font_pair(tiny)[0])
                painter.setPen(_rgba(CYAN, 0.55 * alpha))
                painter.drawText(
                    QPointF((p_label.x() + p_stub.x()) / 2.0, mid_y - radius * 0.045),
                    f"{lon:.2f}",
                )
                painter.setPen(_rgba(WHITE, 0.40 * alpha))
                painter.drawText(
                    QPointF((p_label.x() + p_stub.x()) / 2.0, mid_y + radius * 0.055),
                    f"{lat:.2f}",
                )

    @staticmethod
    def _stroke_route(painter: QPainter, route: list[QPointF], progress: float) -> None:
        """Draw the Manhattan part of the trace up to ``progress`` of its length."""
        if progress <= 0.0 or len(route) < 2:
            return
        lengths = []
        total = 0.0
        for first, second in zip(route, route[1:]):
            piece = math.hypot(second.x() - first.x(), second.y() - first.y())
            lengths.append(piece)
            total += piece
        if total <= 0.0:
            return
        budget = total * min(1.0, progress)
        painter.setBrush(Qt.NoBrush)
        for index, (first, second) in enumerate(zip(route, route[1:])):
            if budget <= 0.0:
                break
            piece = lengths[index]
            part = min(1.0, budget / piece) if piece > 0 else 1.0
            end = QPointF(
                first.x() + (second.x() - first.x()) * part,
                first.y() + (second.y() - first.y()) * part,
            )
            painter.setPen(QPen(_rgba(GOLD, 0.55), max(1.0, 1.0)))
            painter.drawLine(first, end)
            budget -= piece * part

    # ------------------------------------------------------------------ extras
    def _draw_readout(
        self, painter: QPainter, cx: float, cy: float, radius: float,
        middle_win: tuple[float, float], lens: list[tuple[float, float]], ease: float,
    ) -> None:
        if ease <= 0.2:
            return
        aperture = sum(end - start for start, end in lens)
        if aperture > 0.5:
            mid = (lens[0][0] + lens[0][1]) / 2.0
            pos = _point(cx, cy, mid, (_MIDDLE[1] + 0.10) * radius)
            text = f"APERTURE {aperture:.0f} DEG"
            colour = _rgba((255, 210, 140), 0.55 * ease)
        else:
            pos = _point(cx, cy, middle_win[0] + 45.0, (_MIDDLE[1] + 0.10) * radius)
            text = "NO OBSERVATION"
            colour = _rgba((255, 170, 120), 0.55 * ease)
        painter.setFont(self._font_pair(max(5, int(round(radius * 0.038))))[0])
        painter.setPen(colour)
        painter.drawText(pos, text)


    def observed_count(self) -> int:
        return sum(1 for state in self._states.values() if state.entering)

    # --------------------------------------------------------- telemetry band
    def _draw_telemetry(
        self, painter: QPainter, cx: float, cy: float, radius: float,
        values: dict,
    ) -> None:
        r0, r1 = _TELEMETRY_BAND[0] * radius, _TELEMETRY_BAND[1] * radius
        band = self._annulus(cx, cy, r0, r1)
        painter.save()
        try:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(6, 7, 8, 235))
            painter.drawPath(band)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(_rgba((150, 158, 172), 0.35), max(1.0, radius * 0.008)))
            painter.drawEllipse(QPointF(cx, cy), r0, r0)
            painter.drawEllipse(QPointF(cx, cy), r1, r1)
            span = 360.0 / _TELEMETRY_CELLS
            header_font = self._font_pair(max(5, int(round(radius * 0.043))))[0]
            value_font = self._font_pair(max(6, int(round(radius * 0.058))))[0]
            value_font.setBold(True)
            mid_r = (r0 + r1) / 2.0
            for index, (title, value, accent, fill) in enumerate(values["cells"]):
                start = -90.0 + index * span
                # radial dividers: one continuous band, not separate boxes
                for edge in (start, start + span):
                    painter.setPen(QPen(_rgba((120, 128, 142), 0.35), max(1.0, radius * 0.006)))
                    painter.drawLine(
                        _point(cx, cy, edge, r0), _point(cx, cy, edge, r1)
                    )
                angle = start + span / 2.0
                painter.save()
                try:
                    painter.translate(_point(cx, cy, angle, mid_r))
                    upside = 90.0 < (angle % 360.0) < 270.0
                    painter.rotate(angle + 90.0 + (180.0 if upside else 0.0))
                    painter.setPen(_rgba(accent, 0.85))
                    painter.setFont(header_font)
                    painter.drawText(
                        QRectF(-radius * 0.20, -radius * 0.095, radius * 0.40, radius * 0.06),
                        int(Qt.AlignCenter), title,
                    )
                    painter.setPen(_rgba((236, 240, 246), 0.95))
                    painter.setFont(value_font)
                    painter.drawText(
                        QRectF(-radius * 0.20, -radius * 0.035, radius * 0.40, radius * 0.08),
                        int(Qt.AlignCenter), value,
                    )
                    if fill is not None:
                        bar_w = radius * 0.26
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(_rgba((80, 86, 98), 0.5))
                        painter.drawRect(QRectF(-bar_w / 2.0, radius * 0.045, bar_w, radius * 0.008))
                        painter.setBrush(_rgba(accent, 0.9))
                        painter.drawRect(
                            QRectF(-bar_w / 2.0, radius * 0.045,
                                   bar_w * max(0.0, min(1.0, fill)), radius * 0.008)
                        )
                finally:
                    painter.restore()
        finally:
            painter.restore()

    def _draw_arc_text(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        centre_angle: float,
        radius: float,
        text: str,
        font: QFont,
        colour: QColor,
    ) -> None:
        """Lay cached glyph pixmaps on the arc, rotated to the tangent."""
        if not text or radius <= 1.0:
            return
        size = font.pointSize()
        offsets, widths, deg_per_px = self._arc_layout(text, size, radius)
        painter.save()
        try:
            painter.setOpacity(painter.opacity() * colour.alphaF())
            for char, offset, width in zip(text, offsets, widths):
                if char.isspace():
                    continue
                angle = centre_angle + offset * deg_per_px
                rad = math.radians(angle)
                glyph, glyph_width, ascent = self._glyph(char, size)
                painter.save()
                try:
                    painter.translate(
                        cx + radius * math.cos(rad), cy + radius * math.sin(rad)
                    )
                    painter.rotate(angle + 90.0)
                    painter.drawPixmap(QPointF(-glyph_width / 2.0, -ascent), glyph)
                finally:
                    painter.restore()
        finally:
            painter.restore()
