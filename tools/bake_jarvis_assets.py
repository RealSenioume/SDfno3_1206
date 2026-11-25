"""Bake the dense JARVIS band textures (Hong Kong contours / isotherms + wind).

Development tool only: needs Pillow. Run with the bundled Python:

    <deps>\\python.exe tools\\bake_jarvis_assets.py

It writes ``assets/jarvis/contours.png`` and ``assets/jarvis/isotherms.png``; the
runtime simply draws those two images clipped to the rotating windows.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import lolping.geo as geo  # noqa: E402

OUT_DIR = ROOT / "assets" / "jarvis"
SIZE = int(geo.REF_SIZE)
C = SIZE / 2.0
W = geo.REF_WHEEL

GOLD = (255, 190, 96)
AMBER = (255, 140, 70)
CYAN = (150, 225, 255)
WHITE = (255, 246, 220)

FONT_SMALL = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 11)
FONT_TINY = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 9)


def polar(lon: float, lat: float, band: tuple[float, float]) -> tuple[float, float]:
    angle = math.radians(geo.angle_for_lon(lon))
    radius = geo.radius_factor(lat, band) * W
    return C + radius * math.cos(angle), C + radius * math.sin(angle)


def blend(colour: tuple[int, int, int], alpha: int):
    return (*colour, max(0, min(255, int(alpha))))


def draw_contours(draw: ImageDraw.ImageDraw) -> None:
    segments = list(geo.contour_segments(100))
    for index, (level, (p, q)) in enumerate(segments):
        x1, y1 = polar(p[0], p[1], geo.BAND_INNER)
        x2, y2 = polar(q[0], q[1], geo.BAND_INNER)
        draw.line((x1, y1, x2, y2), fill=blend(GOLD, 165), width=2)
        if index % 41 == 0:
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            draw.text((mx + 3, my - 3), str(level), fill=blend((255, 215, 140), 150),
                      anchor="mm", font=FONT_TINY)


def draw_isotherms(draw: ImageDraw.ImageDraw) -> None:
    segments = list(geo.isotherm_segments(0.5))
    for index, (level, (p, q)) in enumerate(segments):
        x1, y1 = polar(p[0], p[1], geo.BAND_OUTER)
        x2, y2 = polar(q[0], q[1], geo.BAND_OUTER)
        draw.line((x1, y1, x2, y2), fill=blend(AMBER, 150), width=2)
        if index % 53 == 0:
            draw.text((x1 + 3, y1 - 3), f"{level:.1f}", fill=blend((255, 180, 110), 150),
                      anchor="mm", font=FONT_TINY)
    # wind vanes just outside the outer band
    for step in range(12):
        angle_deg = step * 30.0
        nearest = min(
            geo.WEATHER,
            key=lambda item: abs(item[1] - (geo.LON_MIN + angle_deg / 360.0 * (geo.LON_MAX - geo.LON_MIN))),
        )
        lat, lon, temp, wind, direction = nearest
        angle = math.radians(angle_deg)
        radius = geo.BAND_OUTER[1] * W + 26.0
        x = C + radius * math.cos(angle)
        y = C + radius * math.sin(angle)
        downwind = math.radians(direction + 180.0)
        length = 18.0
        ex = x + length * math.cos(downwind)
        ey = y + length * math.sin(downwind)
        draw.line((x, y, ex, ey), fill=blend(CYAN, 170), width=2)
        for side in (-0.5, 0.5):
            draw.line((ex, ey, ex - 7 * math.cos(downwind + side), ey - 7 * math.sin(downwind + side)),
                      fill=blend(CYAN, 170), width=2)
        draw.text((x, y + 12), f"{wind:.0f}", fill=blend(CYAN, 150), anchor="mm", font=FONT_TINY)


def draw_frost(size: int = 384) -> None:
    """Procedural frosted glass: cloudy low frequency + fine grain + cool sheen."""
    import numpy as np

    rng = np.random.default_rng(17)
    clouds = rng.random((24, 24)).astype(np.float32)
    cloud_image = Image.fromarray((clouds * 255).astype(np.uint8)).resize(
        (size, size), Image.BICUBIC
    )
    cloud = np.asarray(cloud_image, dtype=np.float32) / 255.0
    cloud = np.asarray(
        cloud_image.filter(ImageFilter.GaussianBlur(3)), dtype=np.float32
    ) / 255.0
    grain = rng.normal(0.0, 0.06, (size, size)).astype(np.float32)

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    diagonal = (xx + yy) / (2.0 * size)  # 0..1 across the plate

    intensity = 0.55 + 0.25 * (cloud - 0.5) + grain + 0.10 * (diagonal - 0.5)
    intensity = np.clip(intensity, 0.0, 1.0)
    alpha = np.clip(0.09 + 0.15 * intensity, 0.0, 1.0)

    rgb = np.stack(
        [
            intensity * 205.0 + 25.0,
            intensity * 210.0 + 25.0,
            intensity * 220.0 + 28.0,
        ],
        axis=2,
    )
    rgba = np.concatenate([np.clip(rgb, 0, 255), (alpha * 255.0)[..., None]], axis=2)
    Image.fromarray(rgba.astype(np.uint8), "RGBA").save(OUT_DIR / "frost.png")
    print("wrote", OUT_DIR / "frost.png")


def bake() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    draw_frost()
    for name, painter in (("contours", draw_contours), ("isotherms", draw_isotherms)):
        image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        painter(ImageDraw.Draw(image))
        path = OUT_DIR / f"{name}.png"
        image.save(path)
        print("wrote", path, f"{path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    bake()
