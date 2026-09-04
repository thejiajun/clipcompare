"""Pieces every mode shares: escaping, scaling, labels, audio, encode flags."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .probe import ClipInfo

FITS = ("cover", "contain")
LENGTHS = ("shortest", "longest")
AUDIO_CHOICES = ("a", "b", "both", "none")

# Below this the two clips count as the same length and no padding is added.
LENGTH_EPSILON = 0.04


@dataclass
class Common:
    """Options every mode accepts."""

    out: Path
    labels: tuple[str, str] | None = None   # None means draw nothing
    fonts: tuple[Path, Path] | None = None  # one per label; see fonts.resolve
    audio: str = "b"
    fit: str = "cover"
    color_a: str = "#ffffff"
    color_b: str = "#cfc3ff"
    label_bg: str = "black@0.55"
    fps: str | None = None                  # None means match the faster clip
    crf: int = 18
    preset: str = "medium"


@dataclass
class Plan:
    """What a mode decided, for the one-line summary the CLI prints."""

    mode: str
    out_w: int
    out_h: int
    fps: str
    fps_value: float
    audio: str = "none"
    detail: str = ""
    command: list[str] = field(default_factory=list)
    # Commands that must run before `command` (pip renders its mask first).
    pre_commands: list[list[str]] = field(default_factory=list)


def escape(value: str) -> str:
    """Escape a value going into a filtergraph option (paths, mainly)."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def even(value: int) -> int:
    return value - (value % 2)


def resolve_fps(a: ClipInfo, b: ClipInfo, override: str | None) -> tuple[str, float]:
    if override:
        try:
            from fractions import Fraction

            return override, float(Fraction(override))
        except (ValueError, ZeroDivisionError):
            return override, 0.0
    # Stacked and cross-faded video runs the two sides in lockstep — mismatched
    # rates desync them.
    return (a.fps, a.fps_value) if a.fps_value >= b.fps_value else (b.fps, b.fps_value)


def geometry(fit: str, width: int, height: int) -> str:
    if fit == "cover":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def scale_chain(fit: str, width: int, height: int, fps: str) -> str:
    return f"fps={fps},{geometry(fit, width, height)},setsar=1,format=yuv420p"


def freeze_pads(a: ClipInfo, b: ClipInfo) -> tuple[str, str]:
    """--length longest: hold the shorter clip's last frame for the difference."""
    if not (a.duration and b.duration):
        return "", ""
    gap = abs(a.duration - b.duration)
    if gap <= LENGTH_EPSILON:
        return "", ""
    pad = f",tpad=stop_mode=clone:stop_duration={gap:.3f}"
    return (pad, "") if a.duration < b.duration else ("", pad)


@dataclass(frozen=True)
class LabelMetrics:
    """Label sizing, all derived from a 1080-normalised reference edge."""

    inset: int
    size: int
    pad_v: int
    pad_h: int

    @classmethod
    def for_reference(cls, reference: int) -> LabelMetrics:
        size = max(round(reference * 37 / 1000), 10)
        return cls(
            inset=max(round(reference * 44 / 1000), 8),
            size=size,
            pad_v=round(size * 42 / 100),
            pad_h=round(size * 72 / 100),
        )


def write_label_files(labels: tuple[str, str], label_dir: Path) -> tuple[Path, Path]:
    file_a = label_dir / "a.txt"
    file_b = label_dir / "b.txt"
    file_a.write_text(labels[0], encoding="utf-8")
    file_b.write_text(labels[1], encoding="utf-8")
    return file_a, file_b


def drawtext(
    text_file: Path,
    font: Path,
    metrics: LabelMetrics,
    color: str,
    background: str,
    x: str | int,
    y: str | int,
    enable: str | None = None,
) -> str:
    """One label. textfile= sidesteps filtergraph quoting entirely; expansion=none
    keeps a filename-derived label containing %{...} literal."""
    parts = [
        f"drawtext=textfile={escape(str(text_file))}",
        f"fontfile={escape(str(font))}",
        f"fontsize={metrics.size}",
        "expansion=none",
        "box=1",
        f"boxcolor={background}",
        f"boxborderw={metrics.pad_v}|{metrics.pad_h}|{metrics.pad_v}|{metrics.pad_h}",
        f"fontcolor={color}",
        f"x={x}",
        f"y={y}",
    ]
    if enable is not None:
        parts.append(f"enable='{enable}'")
    return ":".join(parts)


def audio_plan(a: ClipInfo, b: ClipInfo, requested: str) -> str:
    """Resolve to what we can actually map: 'a', 'b', 'both' or 'none'."""
    if requested == "a":
        return "a" if a.has_audio else "none"
    if requested == "b":
        return "b" if b.has_audio else "none"
    if requested == "both":
        if a.has_audio and b.has_audio:
            return "both"
        if b.has_audio:
            return "b"
        return "a" if a.has_audio else "none"
    return "none"


def audio_args(audio: str, index_a: int = 0, index_b: int = 1) -> list[str]:
    if audio == "both":
        return ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    if audio in ("a", "b"):
        stream = f"{index_a if audio == 'a' else index_b}:a"
        return ["-map", stream, "-c:a", "aac", "-b:a", "192k"]
    return ["-an"]


def encode_args(common: Common) -> list[str]:
    return [
        "-c:v", "libx264", "-crf", str(common.crf), "-preset", common.preset,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]


# An input is either a path, or per-input flags plus a path (e.g. -loop 1).
Input = str | tuple[list[str], str]


def ffmpeg_head(inputs: list[Input], filtergraph: str) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y"]
    for source in inputs:
        if isinstance(source, tuple):
            flags, path = source
            cmd += [*flags, "-i", path]
        else:
            cmd += ["-i", source]
    cmd += ["-filter_complex", filtergraph, "-map", "[v]"]
    return cmd
