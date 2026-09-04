"""Thin ffprobe wrappers — one probe call per clip, everything derived from it."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

# Display Matrix rotations that swap the stored width and height.
_QUARTER_TURNS = {90, -90, 270, -270}


class ProbeError(RuntimeError):
    """ffprobe is missing, or a clip has nothing we can work with."""


def require_binaries() -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise ProbeError(f"{binary} not found on PATH")


@dataclass(frozen=True)
class ClipInfo:
    path: Path
    width: int          # display width — rotation metadata already applied
    height: int
    fps: str            # exact rational as ffprobe reports it, e.g. "30000/1001"
    fps_value: float
    duration: float     # seconds; 0.0 when the container does not say
    has_audio: bool

    @property
    def is_portrait(self) -> bool:
        return self.width <= self.height


def _rotation(stream: dict) -> int:
    for side_data in stream.get("side_data_list") or []:
        if "rotation" in side_data:
            try:
                return int(float(side_data["rotation"]))
            except (TypeError, ValueError):
                pass
    tag = (stream.get("tags") or {}).get("rotate")
    try:
        return int(float(tag))
    except (TypeError, ValueError):
        return 0


def _rational(value: str | None) -> tuple[str, float]:
    """Keep the exact rational (29.97 is 30000/1001, not 29.97) alongside a float."""
    if not value or value in ("0/0", "N/A"):
        return "30", 30.0
    try:
        as_float = float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return "30", 30.0
    if as_float <= 0:
        return "30", 30.0
    return value, as_float


def probe(path: Path) -> ClipInfo:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise ProbeError(f"cannot read {path}: {detail[-1] if detail else 'ffprobe failed'}")

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError(f"no video stream in {path}")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ProbeError(f"no usable frame size in {path}")
    # ffmpeg auto-rotates on decode, so only our layout maths needs the swap.
    if _rotation(video) in _QUARTER_TURNS:
        width, height = height, width

    fps, fps_value = _rational(video.get("r_frame_rate"))

    duration = 0.0
    for candidate in (video.get("duration"), (data.get("format") or {}).get("duration")):
        try:
            duration = float(candidate)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            break

    return ClipInfo(
        path=path,
        width=width,
        height=height,
        fps=fps,
        fps_value=fps_value,
        duration=max(duration, 0.0),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )
