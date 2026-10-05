"""Thin ffprobe wrappers — one probe call per clip, everything derived from it."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

# Display Matrix rotations that swap the stored width and height.
_QUARTER_TURNS = {90, -90, 270, -270}

# An audio-only clip has no frame of its own: it is drawn as a square waveform
# panel at this size, at this rate, until a mode sizes it like its neighbours.
AUDIO_PANEL = 1080
AUDIO_FPS = "30"

# ffprobe reads a still image (png, jpg, webp, ...) through one of these
# demuxers; such a file is one picture with no duration of its own.
IMAGE_FORMATS = {"image2"}


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
    has_video: bool = True  # False: audio only (mp3, wav, ...), drawn as a waveform
    still: bool = False     # True: a still image, held for as long as its neighbours play
    pix_fmt: str = ""       # the picture's pixel format as ffprobe names it, e.g. "yuv420p"

    @property
    def is_audio(self) -> bool:
        return not self.has_video

    @property
    def is_image(self) -> bool:
        return self.still

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


_BLACK = re.compile(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)")
# A clip's first frame often sits a few ms after zero (an edit list, a B-frame
# delay), so black that starts within this much of the top is its lead-in.
LEAD_IN_SLACK = 0.25


def parse_lead_in_black(log: str) -> float:
    match = _BLACK.search(log)
    if match is None or float(match.group(1)) > LEAD_IN_SLACK:
        return 0.0
    return float(match.group(2))


def lead_in_black(path: Path, window: float = 3.0) -> float:
    """Seconds of black at the very start of a clip — AI renders (lipsync in
    particular) often open on a few black frames. 0.0 when it opens on picture."""
    from . import cache

    return cache.remember("lead-in", (cache.identity(path), window), lambda: _lead_in_black(path, window))


def _lead_in_black(path: Path, window: float) -> float:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-t", f"{window}", "-i", str(path),
            "-vf", "scale=270:-2,blackdetect=d=0:pix_th=0.10",
            "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    return parse_lead_in_black(result.stderr)


def probe(path: Path) -> ClipInfo:
    """The clip as the modes see it; cached by the file's identity."""
    from . import cache

    if not Path(path).is_file():
        return _probe(path)
    stored = cache.remember("probe", (cache.identity(path),), lambda: {**asdict(_probe(path)), "path": str(path)})
    return ClipInfo(**{**stored, "path": Path(path)})


def _probe(path: Path) -> ClipInfo:
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
    # Cover art in an mp3 or m4a shows up as a one-frame video stream; it is
    # not a picture to compare, so such a file counts as audio only.
    video = next(
        (
            s for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if video is None:
        if not has_audio:
            raise ProbeError(f"no video or audio stream in {path}")
        return ClipInfo(
            path=path,
            width=AUDIO_PANEL,
            height=AUDIO_PANEL,
            fps=AUDIO_FPS,
            fps_value=float(AUDIO_FPS),
            duration=_duration(data, streams),
            has_audio=True,
            has_video=False,
        )

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ProbeError(f"no usable frame size in {path}")
    # ffmpeg auto-rotates on decode, so only our layout maths needs the swap.
    if _rotation(video) in _QUARTER_TURNS:
        width, height = height, width

    fps, fps_value = _rational(video.get("r_frame_rate"))
    if is_image_format(data):
        # A still's 25/1 "rate" is the demuxer's default, not the picture's.
        return ClipInfo(
            path=path, width=width, height=height, fps=AUDIO_FPS, fps_value=float(AUDIO_FPS),
            duration=0.0, has_audio=False, still=True, pix_fmt=str(video.get("pix_fmt") or ""),
        )

    return ClipInfo(
        path=path,
        width=width,
        height=height,
        fps=fps,
        fps_value=fps_value,
        duration=_duration(data, [video, *(s for s in streams if s.get("codec_type") == "audio")]),
        has_audio=has_audio,
        pix_fmt=str(video.get("pix_fmt") or ""),
    )


def is_image_format(data: dict) -> bool:
    names = str((data.get("format") or {}).get("format_name") or "").split(",")
    return any(name in IMAGE_FORMATS or name.endswith("_pipe") for name in names)


def _duration(data: dict, streams: list[dict]) -> float:
    """The clip lasts as long as its longest stream: a dub that runs past the
    picture must be heard to the end (the picture holds its last frame)."""
    lengths = []
    for candidate in (
        (data.get("format") or {}).get("duration"),
        *(s.get("duration") for s in streams),
    ):
        try:
            lengths.append(float(candidate))
        except (TypeError, ValueError):
            continue
    return max((length for length in lengths if length > 0), default=0.0)
