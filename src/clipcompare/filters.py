"""Pieces every mode shares: escaping, scaling, labels, audio, encode flags."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .probe import ClipInfo
from .tokens import DS_ACCENT_700, DS_BLACK, DS_EGGSHELL, DS_INVERT_600_DARK, DS_PRIMARY_300_DARK

FITS = ("cover", "contain")
LENGTHS = ("shortest", "longest")
AUDIO_CHOICES = ("a", "b", "both", "none")

# Below this the two clips count as the same length and no padding is added.
LENGTH_EPSILON = 0.04

# An audio-only clip is drawn as its live waveform: a band along the bottom of
# a plain dark panel (the top is left for its label and caption), scaled by
# sqrt so quiet speech still visibly moves.
WAVE_BACKGROUND = DS_BLACK
WAVE_COLOR = DS_ACCENT_700
WAVE_BAND = 0.3          # share of the panel height the waveform band takes
WAVE_MARGIN = 0.04       # gap under the band, as a share of the panel height
WAVE_BASELINE = DS_PRIMARY_300_DARK  # a faint centre line, so a silent panel still reads as one


def wave_band(height: int) -> tuple[int, int]:
    """(top, height) of the waveform band inside a panel `height` tall."""
    band = max(even(round(height * WAVE_BAND)), 2)
    return max(height - band - round(height * WAVE_MARGIN), 0), band


@dataclass
class Common:
    """Options every mode accepts."""

    out: Path
    labels: tuple[str, str] | None = None   # None means draw nothing
    fonts: tuple[Path, Path] | None = None  # one per label; see fonts.resolve
    audio: str = "b"
    fit: str = "cover"
    color_a: str = DS_EGGSHELL
    color_b: str = DS_ACCENT_700
    label_bg: str = DS_INVERT_600_DARK
    fps: str | None = None                  # None means match the faster clip
    crf: int = 18
    preset: str = "medium"
    head: float | None = None               # use only the first SEC of every clip


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
    caption_size: int = 0   # grid: the prompt text size it settled on


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


def picture(
    index: int, clip: ClipInfo, width: int, height: int, fps: str,
    delay: float = 0.0, total: float = 0.0,
) -> tuple[list[str], str]:
    """(steps, head) for a clip's picture, where `head` starts the chain that
    scales it — `[0:v]` for a video. An audio-only clip gets a waveform panel
    built from its own sound instead, already at width x height. `delay` holds
    the line flat (silence) for that long first, and `total` keeps it flat
    after the sound ends until then — so the line moves only while it plays."""
    if not clip.is_audio:
        return [], f"[{index}:v]"
    timing = ""
    if delay > 0:
        timing += f",adelay=delays={round(delay * 1000)}:all=1"
    if total > 0:
        timing += f",apad=whole_dur={total:.3f}"
    top, band = wave_band(height)
    name = f"wave{index}"
    return [
        f"color=c={WAVE_BACKGROUND}:s={width}x{height}:r={fps},"
        f"drawbox=x=0:y={top + band // 2 - 1}:w={width}:h=2:color={WAVE_BASELINE}:t=fill[{name}bg]",
        f"[{index}:a]aresample=48000,aformat=channel_layouts=mono{timing},"
        f"showwaves=s={width}x{band}:mode=cline:scale=sqrt:rate={fps}:colors={WAVE_COLOR}:draw=full[{name}w]",
        f"[{name}bg][{name}w]overlay=0:{top}:shortest=1,format=yuv420p[{name}]",
    ], f"[{name}]"


# An input is either a path, or per-input flags plus a path (e.g. -loop 1).
Input = str | tuple[list[str], str]


def clamp_head(clip: ClipInfo, head: float | None) -> ClipInfo:
    """--head: the clip as the rest of the plan sees it once cut to its first SEC."""
    if not head:
        return clip
    return replace(clip, duration=min(clip.duration, head) if clip.duration else head)


def clip_input(clip: ClipInfo, head: float | None) -> Input:
    """The clip as an ffmpeg input; --head becomes an input -t, which cuts its
    picture and its sound alike before any filter sees them."""
    return (["-t", f"{head:.3f}"], str(clip.path)) if head else str(clip.path)


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
