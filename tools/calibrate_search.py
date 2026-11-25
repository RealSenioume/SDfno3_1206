"""Calibrate the search thresholds on a folder of real screenshots.

Run:
    python tools/calibrate_search.py --folder "%APPDATA%\\lolping-desktop\\regions" --csv out.csv

It prints one row per image with the OCR score, the number of lines and the
best query. Use it to relabel / tune ``ocr.HIGH_CONFIDENCE`` and
``ocr.LOW_CONFIDENCE``.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lolping import ocr  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score screenshots with the search OCR")
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args(argv)

    images = sorted(
        image for image in args.folder.iterdir()
        if image.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")
    )
    if not images:
        print("no PNG files in", args.folder)
        return 1
    rows = []
    for image in images:
        result = ocr.recognize(image)
        score, query = ocr.usability(result)
        lines = len(result.lines) if result else 0
        rows.append(
            {
                "file": image.name,
                "score": score,
                "lines": lines,
                "query": query.replace("\n", " ")[:60],
            }
        )
        print(f"{score:3d}  lines={lines:2d}  {image.name}  {query[:50]!r}")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["file", "score", "lines", "query"])
            writer.writeheader()
            writer.writerows(rows)
        print("csv ->", args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
