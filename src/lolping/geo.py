"""Hong Kong geography/weather data and the angular model of the JARVIS rings.

The ``jarvis`` theme draws three quarter-arc "windows" that rotate at different
speeds around the ping wheel:

* inner  - Hong Kong elevation contours (150 degree window, fixed on the track)
* middle - landmarks, visible only where the middle window covers the inner one
* outer  - isotherms + wind vanes for 2026-11-17 14:00 HKT

Everything here is pure Python (no Qt) so the geometry can be unit tested and so
``tools/bake_jarvis_assets.py`` can pre-render the dense contour textures.
"""

from __future__ import annotations

import math

__all__ = [
    "BAND_INNER",
    "BAND_MIDDLE",
    "BAND_OUTER",
    "FLICKER_SECONDS",
    "LANDMARKS",
    "LINE_SECONDS",
    "NAME_SECONDS",
    "PEAKS",
    "PHASE_INNER",
    "PHASE_MIDDLE",
    "PHASE_OUTER",
    "REF_SIZE",
    "REF_WHEEL",
    "SPEED_INNER",
    "SPEED_MIDDLE",
    "SPEED_OUTER",
    "TEXTURE_SPEED",
    "WEATHER",
    "WINDOW_SPAN",
    "angle_for_lon",
    "heightfield",
    "in_interval",
    "isotherm_segments",
    "lens_intervals",
    "overlap_intervals",
    "radius_factor",
    "reveal",
    "window",
]

# ---------------------------------------------------------------- map bounds
LON_MIN, LAT_MIN = 113.85, 22.15
LON_MAX, LAT_MAX = 114.45, 22.55

# ---------------------------------------------------------------- ring model
#: Band radii as fractions of the wheel radius (inner edge, outer edge).
BAND_INNER: tuple[float, float] = (1.20, 1.72)
BAND_MIDDLE: tuple[float, float] = (1.78, 2.30)
BAND_OUTER: tuple[float, float] = (2.36, 2.88)

#: Default window span (middle and outer rings).
WINDOW_SPAN = 90.0
#: The inner ring was widened to 150 degrees in the v0.4.0 follow-up.
WINDOW_SPAN_INNER = 150.0

#: The data painted on the rings drifts clockwise at this rate.
TEXTURE_SPEED = 3.0

#: All three windows turn the same way, at different speeds (degrees / second).
SPEED_INNER = 3.0
SPEED_MIDDLE = 7.5  # +25 % in the v0.4.0 follow-up
SPEED_OUTER = 2.0

#: Phase offset of each window at t = 0, so the three rings start spread out.
PHASE_INNER = 120.0
PHASE_MIDDLE = 120.0
PHASE_OUTER = 40.0

#: Reveal timing (seconds): the trace grows first, then the name lights up and
#: flickers like an unstable lamp before settling. Leaving plays it backwards.
LINE_SECONDS = 0.100
NAME_SECONDS = 0.015
FLICKER_SECONDS = 0.30
LEAVE_SECONDS = 0.160

#: Reference canvas used by the baked textures (px) and its wheel radius.
REF_SIZE = 2048.0
#: The widest band reaches 2.88 R, so half the canvas must hold ~2.95 R.
REF_WHEEL = REF_SIZE / 5.9

# ---------------------------------------------------------------- elevation
#: (name, latitude, longitude, height in metres) - approximate real peaks.
PEAKS: tuple[tuple[str, float, float, float], ...] = (
    ("Tai Mo Shan", 22.4108, 114.1247, 957.0),
    ("Lantau Peak", 22.2492, 113.9115, 934.0),
    ("Sunset Peak", 22.2590, 113.9530, 869.0),
    ("Victoria Peak", 22.2754, 114.1436, 552.0),
    ("Ma On Shan", 22.4070, 114.2430, 702.0),
    ("Lion Rock", 22.3510, 114.1850, 495.0),
    ("Castle Peak", 22.3860, 113.9530, 583.0),
    ("Fei Ngo Shan", 22.3410, 114.2230, 602.0),
    ("Grassy Hill", 22.4020, 114.1600, 647.0),
    ("Needle Hill", 22.3800, 114.1700, 532.0),
    ("Mount Parker", 22.2680, 114.2200, 532.0),
    ("Mount Davis", 22.2760, 114.1200, 269.0),
    ("Jardine's Lookout", 22.2670, 114.1940, 433.0),
    ("Tai Tam", 22.2560, 114.2220, 436.0),
    ("Tsing Yi Peak", 22.3450, 114.0900, 334.0),
    ("Lo Fu Tau", 22.2200, 113.9800, 465.0),
    ("The Hunchbacks", 22.2400, 113.9800, 343.0),
    ("Tai Sheung Tok", 22.3550, 114.2450, 399.0),
    ("Pai Tau", 22.3960, 114.1900, 346.0),
    ("Kowloon Peak", 22.3410, 114.2230, 602.0),
)

#: (name, latitude, longitude, kind) - kind: b=building, s=school, r=road.
LANDMARKS: tuple[tuple[str, float, float, str], ...] = (
    ("IFC", 22.2850, 114.1590, "b"),
    ("ICC", 22.3050, 114.1610, "b"),
    ("Central Plaza", 22.2800, 114.1730, "b"),
    ("HKCEC", 22.2830, 114.1730, "b"),
    ("Peak Tower", 22.2710, 114.1500, "b"),
    ("HKU", 22.2840, 114.1370, "s"),
    ("CUHK", 22.4190, 114.2070, "s"),
    ("PolyU", 22.3050, 114.1800, "s"),
    ("CityU", 22.3370, 114.1720, "s"),
    ("HKUST", 22.3370, 114.2630, "s"),
    ("Baptist U", 22.3400, 114.1810, "s"),
    ("Tsing Ma Br", 22.3510, 114.0740, "r"),
    ("Nathan Rd", 22.3100, 114.1710, "r"),
    ("Temple St", 22.3070, 114.1700, "r"),
    ("Kai Tak", 22.3280, 114.1910, "r"),
    ("West Kowloon", 22.3020, 114.1580, "r"),
)

#: (latitude, longitude, temperature C, wind km/h, wind direction deg)
#: Sampled by Open-Meteo for 2026-11-17 14:00 Asia/Hong_Kong.
WEATHER: tuple[tuple[float, float, float, float, float], ...] = (
    (22.24956, 113.89463, 27.5, 9.0, 134.0),
    (22.31986, 114.19856, 26.4, 8.5, 117.0),
    (22.39016, 114.31677, 26.3, 7.6, 98.0),
)
WEATHER_STAMP = "2026-11-17 14:00 HKT"


# ---------------------------------------------------------------- mapping
def angle_for_lon(lon: float) -> float:
    """Longitude -> screen angle in degrees (clockwise from 3 o'clock)."""
    return clamp01((lon - LON_MIN) / (LON_MAX - LON_MIN)) * 360.0


def radius_factor(lat: float, band: tuple[float, float]) -> float:
    """Latitude -> radius as a fraction of the wheel radius, inside ``band``."""
    t = clamp01((lat - LAT_MIN) / (LAT_MAX - LAT_MIN))
    return band[0] + t * (band[1] - band[0])


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def window(phase: float, t: float, speed: float,
           span: float = WINDOW_SPAN) -> tuple[float, float]:
    """Start/end angle of a rotating window at time ``t``."""
    start = (phase + speed * t) % 360.0
    return start, start + span


def in_interval(angle: float, start: float, end: float, feather: float = 2.0) -> float:
    """Soft membership in a possibly wrapping angular interval (degrees)."""
    a = angle % 360.0
    s = start % 360.0
    e = end % 360.0
    if s <= e:
        inside = s <= a <= e
        distance = min(a - s, e - a) if inside else 0.0
    else:
        inside = a >= s or a <= e
        distance = min((a - s) % 360.0, (e - a) % 360.0) if inside else 0.0
    if not inside:
        return 0.0
    if feather <= 0.0:
        return 1.0
    return clamp01(distance / feather)


def _split(start: float, end: float) -> list[tuple[float, float]]:
    s, e = start % 360.0, end % 360.0
    return [(s, e)] if s <= e else [(s, 360.0), (0.0, e)]


def overlap_intervals(
    first: tuple[float, float], second: tuple[float, float]
) -> list[tuple[float, float]]:
    """Intersection of two angular intervals; may be empty, one or two pieces."""
    pieces: list[tuple[float, float]] = []
    for s1, e1 in _split(first[0], first[1]):
        for s2, e2 in _split(second[0], second[1]):
            start, end = max(s1, s2), min(e1, e2)
            if end > start + 1e-9:
                pieces.append((start, end))
    return pieces


def lens_intervals(inner: tuple[float, float], middle: tuple[float, float]) -> list[tuple[float, float]]:
    """The observable piece(s): the middle window covering the inner window."""
    return overlap_intervals(inner, middle)


def reveal_progress(elapsed: float, entering: bool) -> tuple[float, float, float]:
    """Return (line, name, flicker) for a landmark revealed ``elapsed`` seconds ago.

    Entering: the trace grows during ``LINE_SECONDS``, then the name fades in over
    ``NAME_SECONDS`` and flickers for ``FLICKER_SECONDS`` before settling.
    Leaving: the same schedule backwards over ``LEAVE_SECONDS``.
    """
    if elapsed < 0.0:
        return 0.0, 0.0, 0.0
    if not entering:
        total = LINE_SECONDS + NAME_SECONDS + LEAVE_SECONDS
        t = elapsed / total
        if t >= 1.0:
            return 0.0, 0.0, 0.0
        line = 1.0 - clamp01((elapsed - NAME_SECONDS) / LINE_SECONDS)
        name = clamp01((total - elapsed) / LEAVE_SECONDS)
        flicker = 1.0
        return line, name, flicker
    line = clamp01(elapsed / LINE_SECONDS)
    name = clamp01((elapsed - LINE_SECONDS) / NAME_SECONDS) if elapsed > LINE_SECONDS else 0.0
    if elapsed <= LINE_SECONDS + FLICKER_SECONDS:
        phase = (elapsed - LINE_SECONDS) / FLICKER_SECONDS
        flicker = 1.0 - 0.35 * abs(math.sin(phase * math.pi * 3.0)) * (1.0 - phase)
    else:
        flicker = 1.0
    return line, name, flicker


# ---------------------------------------------------------------- fields
def _grid(n_lon: int = 150, n_lat: int = 110):
    lons = [LON_MIN + (LON_MAX - LON_MIN) * i / (n_lon - 1) for i in range(n_lon)]
    lats = [LAT_MIN + (LAT_MAX - LAT_MIN) * i / (n_lat - 1) for i in range(n_lat)]
    return lons, lats


def heightfield(n_lon: int = 150, n_lat: int = 110):
    """Gaussian-sum terrain from the real peaks, normalised to 957 m."""
    lons, lats = _grid(n_lon, n_lat)
    field = [[0.0] * n_lon for _ in range(n_lat)]
    for _name, plat, plon, peak in PEAKS:
        for j, lat in enumerate(lats):
            dy = (lat - plat) / 0.026
            if abs(dy) > 3.0:
                continue
            for i, lon in enumerate(lons):
                dx = (lon - plon) / 0.030
                if abs(dx) > 3.0:
                    continue
                field[j][i] += peak * math.exp(-(dx * dx + dy * dy) / 2.0)
    top = max(max(row) for row in field)
    if top > 0.0:
        scale = 957.0 / top
        field = [[value * scale for value in row] for row in field]
    return lons, lats, field


def marching_squares(field, xs, ys, level: float):
    """Yield contour segments ((lon1,lat1),(lon2,lat2)) for one level."""
    ny = len(field)
    nx = len(field[0])
    for j in range(ny - 1):
        for i in range(nx - 1):
            corners = (field[j][i], field[j][i + 1], field[j + 1][i + 1], field[j + 1][i])
            points = []
            coords = ((xs[i], ys[j]), (xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1]))
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                va, vb = corners[a], corners[b]
                if (va >= level) != (vb >= level):
                    t = (level - va) / (vb - va) if vb != va else 0.5
                    xa, ya = coords[a]
                    xb, yb = coords[b]
                    points.append((xa + t * (xb - xa), ya + t * (yb - ya)))
            if len(points) == 2:
                yield points[0], points[1]
            elif len(points) == 4:
                yield points[0], points[1]
                yield points[2], points[3]


def contour_segments(step: float = 100.0):
    """All elevation contour segments, level by level."""
    lons, lats, field = heightfield()
    for level in range(int(step), 1000, int(step)):
        for segment in marching_squares(field, lons, lats, float(level)):
            yield int(level), segment


def temperature_field():
    """IDW from the three 2026-11-17 samples minus a lapse rate on terrain."""
    lons, lats, height = heightfield()
    samples = [(lat, lon, temp) for lat, lon, temp, _s, _d in WEATHER]
    field = []
    for j, lat in enumerate(lats):
        row = []
        for i, lon in enumerate(lons):
            weight_sum = 0.0
            temp_sum = 0.0
            for slat, slon, temp in samples:
                w = 1.0 / (1e-6 + (lat - slat) ** 2 + (lon - slon) ** 2)
                weight_sum += w
                temp_sum += w * temp
            row.append(temp_sum / weight_sum - 6.5 * height[j][i] / 1000.0)
        field.append(row)
    return lons, lats, field


def isotherm_segments(step: float = 0.5):
    lons, lats, field = temperature_field()
    levels = [23.5 + step * k for k in range(int(6 / step) + 1)]
    for level in levels:
        for segment in marching_squares(field, lons, lats, level):
            yield round(level, 1), segment
