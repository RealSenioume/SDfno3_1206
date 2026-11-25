"""Windows OCR (offline, no Python dependencies) + text usability scoring.

The Windows OCR engine is reached through Windows PowerShell 5.1 + WinRT. The
image is fed through an in-memory stream (``StorageFile`` refuses paths outside
the app-container white list). One call costs about 0.4-0.6 s, which fits after
the commit animation.

Output quality is scored with heuristics instead of a model, so the default
search path costs nothing and never leaves the machine.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import app_data_dir

log = logging.getLogger(__name__)

#: How long one OCR call may take before it is abandoned.
OCR_TIMEOUT_S = 6.0

#: Thresholds on the 0-100 usability score.
HIGH_CONFIDENCE = 60
LOW_CONFIDENCE = 25

_PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
$ImagePath = '__IMAGE_PATH__'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
try {
    $bytes = [System.IO.File]::ReadAllBytes($ImagePath)
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $writer = New-Object Windows.Storage.Streams.DataWriter($stream)
    $writer.WriteBytes($bytes)
    $null = Await ($writer.StoreAsync()) ([uint32])
    $writer.DetachStream() | Out-Null
    $stream.Seek(0)
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { throw 'no OCR engine' }
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($line in $result.Lines) {
        $words = @($line.Words)
        $first = $words[0]
        $last = $words[-1]
        $x = $first.BoundingRect.X
        $y = $first.BoundingRect.Y
        $w = ($last.BoundingRect.X + $last.BoundingRect.Width) - $x
        $h = $last.BoundingRect.Y + $last.BoundingRect.Height - $y
        $lines += [pscustomobject]@{ text = $line.Text; x = $x; y = $y; w = $w; h = $h }
    }
    $payload = [pscustomobject]@{
        ok = $true; text = $result.Text; width = $decoder.PixelWidth; height = $decoder.PixelHeight; lines = $lines
    }
} catch {
    $payload = [pscustomobject]@{ ok = $false; error = $_.Exception.Message; text = ''; lines = @() }
}
$json = $payload | ConvertTo-Json -Depth 4 -Compress
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output $json
"""


@dataclass
class OCRResult:
    """What the local OCR found in one image."""

    text: str = ""
    lines: list[str] = field(default_factory=list)
    #: (x, y, w, h) per line, in image pixels; empty when unavailable.
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    width: int = 0
    height: int = 0

    @property
    def empty(self) -> bool:
        return not self.text.strip() and not any(line.strip() for line in self.lines)


def recognize(png_path: str | Path) -> OCRResult | None:
    """Run Windows OCR on ``png_path``. ``None`` means "OCR unavailable"."""
    image = Path(png_path)
    if not image.is_file():
        return None
    literal = str(image).replace("'", "''")
    script = _PS_TEMPLATE.replace("__IMAGE_PATH__", literal)
    try:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        completed = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded,
            ],
            capture_output=True,
            timeout=OCR_TIMEOUT_S,
            check=False,
        )
        output = completed.stdout.decode("utf-8", errors="replace").strip()
        if not output:
            log.debug("OCR helper produced no output (rc=%s)", completed.returncode)
            return None
        payload = json.loads(output.splitlines()[-1])
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        log.debug("OCR call failed", exc_info=True)
        return None
    if not payload.get("ok"):
        log.debug("OCR engine error: %s", payload.get("error"))
        return None
    lines: list[str] = []
    boxes: list[tuple[float, float, float, float]] = []
    for item in payload.get("lines", []):
        if isinstance(item, dict):
            lines.append(str(item.get("text", "")).strip())
            boxes.append(
                (
                    float(item.get("x", 0.0)),
                    float(item.get("y", 0.0)),
                    float(item.get("w", 0.0)),
                    float(item.get("h", 0.0)),
                )
            )
        else:
            lines.append(str(item).strip())
            boxes.append((0.0, 0.0, 0.0, 0.0))
    return OCRResult(
        text=str(payload.get("text", "")).strip(),
        lines=[line for line in lines if line],
        boxes=[box for line, box in zip(lines, boxes) if line],
        width=int(payload.get("width", 0) or 0),
        height=int(payload.get("height", 0) or 0),
    )


# ----------------------------------------------------------------- scoring
_URL_RE = re.compile(r"^(https?://|www\.)|\.(com|cn|net|org)(/|$)", re.I)
_NOISE_RE = re.compile(r"^[\W_]+$")
_CJK = "\u4e00-\u9fff"
_CJK_SPACE_RE = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])")


def normalize(text: str) -> str:
    """Collapse whitespace and drop the spaces OCR inserts between CJK glyphs."""
    value = (text or "").replace("\u3000", " ")
    while _CJK_SPACE_RE.search(value):
        value = _CJK_SPACE_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


_LABEL_RE = re.compile(r"(专辑|歌手|作者|搜索|评分)\s*[:：]\s*")


def clean_query(text: str) -> str:
    """Strip OCR label prefixes and single-glyph icon noise from a line."""
    value = normalize(text)
    value = _LABEL_RE.sub("", value)
    value = re.sub(r"^[A-Za-z0-9]\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"^[\u4e00-\u9fff]\s+(?=[A-Za-z0-9])", "", value)
    value = re.sub(r"^[\W_]+|[\W_]+$", "", value)
    return value.strip()


def _clean_ratio(text: str) -> float:
    useful = sum(1 for ch in text if ch.isalnum() or _CJK[0] <= ch <= _CJK[-1])
    return useful / max(1, len(text))


def line_score(line: str) -> float:
    """0-100 heuristic: is this line usable as a search query?"""
    text = normalize(line)
    if len(text) < 2:
        return 0.0
    if _NOISE_RE.match(text):
        return 0.0
    clean = _clean_ratio(text)
    length_factor = 1.0 if 2 <= len(text) <= 40 else max(0.25, 40.0 / len(text))
    url_penalty = 0.15 if _URL_RE.search(text) else 1.0
    punctuation = sum(
        1 for ch in text
        if not ch.isalnum() and ch != " " and not (_CJK[0] <= ch <= _CJK[-1])
    )
    punctuation_penalty = max(0.3, 1.0 - punctuation / max(1, len(text)) * 1.5)
    return max(0.0, min(100.0, clean * 100.0 * length_factor * url_penalty * punctuation_penalty))


def usability(result: OCRResult | None) -> tuple[int, str]:
    """Return ``(0-100 score, best query)`` for one OCR result."""
    if result is None or result.empty:
        return 0, ""
    candidates = [clean_query(line) for line in result.lines if clean_query(line)] or [
        clean_query(result.text)
    ]
    best_line, best_score = "", 0.0
    width = max(1, result.width)
    height = max(1, result.height)
    for index, line in enumerate(candidates):
        score = line_score(line)
        # Prefer what is in the middle of the frame: the top/bottom strips are
        # usually chrome (search boxes, tabs, counters).
        if index < len(result.boxes):
            x, y, w, h = result.boxes[index]
            cx = x + w / 2.0
            cy = y + h / 2.0
            distance = math.hypot(
                (cx - width / 2.0) / (width / 2.0),
                (cy - height / 2.0) / (height / 2.0),
            )
            score *= max(0.55, 1.30 - 0.55 * min(distance, 1.0))
        if score > best_score:
            best_line, best_score = line, score
    # A single line is weak evidence; many readable lines raise confidence.
    density = min(1.0, len([l for l in candidates if line_score(l) >= 45]) / 3.0)
    score = int(round(min(100.0, best_score * (0.7 + 0.3 * density))))
    return score, best_line
