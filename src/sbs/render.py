"""Build the side-by-side ffmpeg command.

Everything here is pure: `build()` takes two probed clips plus options and
returns the argv list, so the filtergraph can be tested without touching ffmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .probe import ClipInfo

LAYOUTS = ("auto", "lr", "tb")
FITS = ("cover", "contain")
LENGTHS = ("shortest", "longest")
AUDIO_CHOICES = ("a", "b", "both", "none")

# Below this the two clips count as the same length and no padding is added.
_LENGTH_EPSILON = 0.04


@dataclass
class Options:
    out: Path
    labels: tuple[str, str] | None = None   # None means draw nothing
    layout: str = "auto"
    panel: int = 1080                       # short edge of each panel
    fit: str = "cover"
    length: str = "shortest"
    audio: str = "b"
    divider: int = 4                        # 1080-normalised px, 0 disables
    fonts: tuple[Path, Path] | None = None  # one per label; see fonts.resolve
    color_a: str = "#ffffff"
    color_b: str = "#cfc3ff"
    label_bg: str = "black@0.55"
    fps: str | None = None                  # None means match the faster clip
    crf: int = 18
    preset: str = "medium"


@dataclass
class Plan:
    """What build() decided, for the one-line summary the CLI prints."""

    layout: str
    panel_w: int
    panel_h: int
    out_w: int
    out_h: int
    fps: str
    fps_value: float
    audio: str = "none"
    command: list[str] = field(default_factory=list)


def _escape(value: str) -> str:
    """Escape a value going into a filtergraph option (paths, mainly)."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _even(value: int) -> int:
    return value - (value % 2)


def _resolve_fps(a: ClipInfo, b: ClipInfo, override: str | None) -> tuple[str, float]:
    if override:
        try:
            from fractions import Fraction

            return override, float(Fraction(override))
        except (ValueError, ZeroDivisionError):
            return override, 0.0
    # hstack/vstack run the two sides in lockstep — mismatched rates desync them.
    return (a.fps, a.fps_value) if a.fps_value >= b.fps_value else (b.fps, b.fps_value)


def _resolve_layout(a: ClipInfo, requested: str) -> str:
    if requested != "auto":
        return requested
    return "lr" if a.is_portrait else "tb"


def _panel_size(a: ClipInfo, panel: int) -> tuple[int, int]:
    """`panel` is the SHORT edge; the panel aspect comes from the first clip."""
    if a.width < a.height:
        width, height = panel, round(panel * a.height / a.width)
    else:
        width, height = round(panel * a.width / a.height), panel
    return _even(width), _even(height)


def _geometry(fit: str, panel_w: int, panel_h: int) -> str:
    if fit == "cover":
        return (
            f"scale={panel_w}:{panel_h}:force_original_aspect_ratio=increase,"
            f"crop={panel_w}:{panel_h}"
        )
    return (
        f"scale={panel_w}:{panel_h}:force_original_aspect_ratio=decrease,"
        f"pad={panel_w}:{panel_h}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def _freeze_pads(a: ClipInfo, b: ClipInfo) -> tuple[str, str]:
    """--length longest: hold the shorter clip's last frame for the difference."""
    if not (a.duration and b.duration):
        return "", ""
    gap = abs(a.duration - b.duration)
    if gap <= _LENGTH_EPSILON:
        return "", ""
    pad = f",tpad=stop_mode=clone:stop_duration={gap:.3f}"
    return (pad, "") if a.duration < b.duration else ("", pad)


def _label_filters(
    opts: Options,
    layout: str,
    panel: int,
    panel_h: int,
    label_dir: Path,
    fonts: tuple[Path, Path],
) -> str:
    inset = max(round(panel * 44 / 1000), 8)
    size = max(round(panel * 37 / 1000), 10)
    pad_v = round(size * 42 / 100)
    pad_h = round(size * 72 / 100)

    assert opts.labels is not None
    text_a, text_b = opts.labels
    file_a = label_dir / "a.txt"
    file_b = label_dir / "b.txt"
    file_a.write_text(text_a, encoding="utf-8")
    file_b.write_text(text_b, encoding="utf-8")

    # textfile= sidesteps filtergraph quoting entirely; expansion=none keeps a
    # filename-derived label containing %{...} literal.
    def common(font: Path) -> str:
        return (
            f"fontfile={_escape(str(font))}:fontsize={size}:expansion=none:"
            f"box=1:boxcolor={opts.label_bg}:"
            f"boxborderw={pad_v}|{pad_h}|{pad_v}|{pad_h}"
        )

    x_a, y_a = inset + pad_h, inset + pad_v
    if layout == "lr":
        x_b, y_b = f"w-tw-{inset + pad_h}", y_a
    else:
        x_b, y_b = x_a, panel_h + inset + pad_v

    return (
        f"drawtext=textfile={_escape(str(file_a))}:{common(fonts[0])}:"
        f"fontcolor={opts.color_a}:x={x_a}:y={y_a},"
        f"drawtext=textfile={_escape(str(file_b))}:{common(fonts[1])}:"
        f"fontcolor={opts.color_b}:x={x_b}:y={y_b}"
    )


def _audio_plan(a: ClipInfo, b: ClipInfo, requested: str) -> str:
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


def build(a: ClipInfo, b: ClipInfo, opts: Options, label_dir: Path | None = None) -> Plan:
    layout = _resolve_layout(a, opts.layout)
    panel_w, panel_h = _panel_size(a, opts.panel)
    if layout == "lr":
        out_w, out_h, stack = panel_w * 2, panel_h, "hstack"
    else:
        out_w, out_h, stack = panel_w, panel_h * 2, "vstack"

    fps, fps_value = _resolve_fps(a, b, opts.fps)
    chain = f"fps={fps},{_geometry(opts.fit, panel_w, panel_h)},setsar=1,format=yuv420p"

    if opts.length == "longest":
        pad_a, pad_b = _freeze_pads(a, b)
        shortest = 0
    else:
        pad_a = pad_b = ""
        shortest = 1

    steps = [
        f"[0:v]{chain}{pad_a}[va]",
        f"[1:v]{chain}{pad_b}[vb]",
        f"[va][vb]{stack}=inputs=2:shortest={shortest}[st]",
    ]
    last = "st"

    if opts.divider > 0:
        thickness = max(round(opts.divider * opts.panel / 1080), 1)
        if layout == "lr":
            box = (
                f"drawbox=x={panel_w - thickness // 2}:y=0:w={thickness}:h=ih"
                ":color=white@0.85:t=fill"
            )
        else:
            box = (
                f"drawbox=x=0:y={panel_h - thickness // 2}:w=iw:h={thickness}"
                ":color=white@0.85:t=fill"
            )
        steps.append(f"[{last}]{box}[dv]")
        last = "dv"

    if opts.labels and label_dir is not None:
        fonts = opts.fonts
        assert fonts is not None
        steps.append(
            f"[{last}]{_label_filters(opts, layout, opts.panel, panel_h, label_dir, fonts)}[lv]"
        )
        last = "lv"

    audio = _audio_plan(a, b, opts.audio)
    if audio == "both":
        steps.append("[0:a][1:a]amix=inputs=2:duration=shortest[aout]")

    steps.append(f"[{last}]null[v]")

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y",
        "-i", str(a.path), "-i", str(b.path),
        "-filter_complex", ";".join(steps),
        "-map", "[v]",
    ]
    if audio == "both":
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    elif audio in ("a", "b"):
        cmd += ["-map", "0:a" if audio == "a" else "1:a", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", "libx264", "-crf", str(opts.crf), "-preset", opts.preset,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]
    if opts.length == "shortest":
        cmd += ["-shortest"]
    cmd += [str(opts.out)]

    return Plan(
        layout=layout,
        panel_w=panel_w,
        panel_h=panel_h,
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        fps_value=fps_value,
        audio=audio,
        command=cmd,
    )
