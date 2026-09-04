"""wipe — an eased line sweeps across, revealing clip B over clip A in place.

Single `xfade=transition=custom` pass. Two traps, both of which cost real
debugging time in the shell script this grew out of:

1. xfade's custom-expr `P` runs 1 -> 0 across the transition, not 0 -> 1. Drive
   the easing off `q = 1-P` or the wipe inverts — it jumps to B, sweeps
   backwards, then snaps back.
2. The easing MUST be inlined — no `st()`/`ld()` registers. xfade evaluates
   slices across threads that share the expression register array, so st/ld
   races produce scattered white-pixel speckle on the passthrough side.
   Repeating the inline expression is race-free and just as fast, because the
   expr only evaluates on the handful of transition frames.

Clip B is pre-trimmed to the wipe start so both sides show the SAME timestamp
during the sweep — motion stays continuous across the line, which a plain wipe
transition would desync.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..filters import (
    Common,
    LabelMetrics,
    Plan,
    audio_args,
    audio_plan,
    drawtext,
    even,
    encode_args,
    ffmpeg_head,
    resolve_fps,
    scale_chain,
    write_label_files,
)
from ..probe import ClipInfo

DIRECTIONS = ("lr", "rl", "tb", "bt")
PACES = ("early", "balanced", "late", "snappy")

# Measured off the launch reference cuts: a short hold, a quick wipe, then a
# long hold on the result. 0.35s is the house wipe duration everywhere.
_PACE_PRESETS = {
    "early": (0.22, 0.4, 0.9),
    "balanced": (0.30, 0.6, 1.1),
    "late": (0.45, 0.9, 1.8),
}
# `snappy` is not a fourth setting — it is the old name for `early`, kept so
# existing muscle memory and scripts keep working. It renders byte-identical
# output, which the CLI help says out loud rather than listing it as a peer.
_PACE_PRESETS["snappy"] = _PACE_PRESETS["early"]
DEFAULT_WIPE_DUR = 0.35

# ease-in-out circ, inlined, driven off q = 1-P (see the module docstring).
_EASED = (
    "if(lt(1-P,0.5),(1-sqrt(1-pow(2*(1-P),2)))/2,(sqrt(1-pow(2-2*(1-P),2))+1)/2)"
)
# White across the luma and chroma planes.
_WHITE = "if(eq(PLANE,0),255,128)"


@dataclass
class Options(Common):
    direction: str = "lr"
    pace: str = "early"
    panel: int = 0            # 0 keeps clip A's own resolution
    wipe_start: str | None = None   # seconds ("0.9") or percent ("30%")
    wipe_dur: float = DEFAULT_WIPE_DUR
    stroke: int = 3           # 1080-normalised px
    trim_to: float | None = None


def output_size(a: ClipInfo, panel: int) -> tuple[int, int]:
    if panel <= 0:
        return even(a.width), even(a.height)
    if a.width < a.height:
        return even(panel), even(round(panel * a.height / a.width))
    return even(round(panel * a.width / a.height)), even(panel)


def resolve_start(duration: float, pace: str, override: str | None) -> float:
    if override:
        text = override.strip()
        if text.endswith("%"):
            return max(float(text[:-1]) / 100.0 * duration, 0.0)
        return max(float(text), 0.0)
    fraction, low, high = _PACE_PRESETS[pace]
    return min(max(fraction * duration, low), high)


def wipe_expression(direction: str, half_stroke: float) -> str:
    """Paint the stroke within +/- half its width of the boundary, then pick a
    side. `A` is the first xfade input, `B` the second."""
    if direction == "lr":
        edge, axis, revealed = f"({_EASED})*W", "X", "lt"
    elif direction == "rl":
        edge, axis, revealed = f"(W-({_EASED})*W)", "X", "gt"
    elif direction == "tb":
        edge, axis, revealed = f"({_EASED})*H", "Y", "lt"
    else:  # bt
        edge, axis, revealed = f"(H-({_EASED})*H)", "Y", "gt"
    return (
        f"if(lt(abs({axis}-{edge}),{half_stroke:.2f}),{_WHITE},"
        f"if({revealed}({axis},{edge}),B,A))"
    )


def build(a: ClipInfo, b: ClipInfo, opts: Options, label_dir: Path | None = None) -> Plan:
    out_w, out_h = output_size(a, opts.panel)
    fps, fps_value = resolve_fps(a, b, opts.fps)
    chain = scale_chain(opts.fit, out_w, out_h, fps)

    duration = a.duration or b.duration or 3.0
    start = resolve_start(duration, opts.pace, opts.wipe_start)
    # Leave room for the sweep itself inside clip A.
    start = min(start, max(duration - opts.wipe_dur, 0.0))

    stroke_px = max(round(opts.stroke * out_h / 1080), 1)
    expr = wipe_expression(opts.direction, stroke_px / 2.0)

    steps = [
        f"[0:v]{chain}[va]",
        # Pre-trim B so the two sides show the same timestamp during the sweep.
        f"[1:v]{chain},trim=start={start:.3f},setpts=PTS-STARTPTS[vb]",
        f"[va][vb]xfade=transition=custom:duration={opts.wipe_dur:.3f}"
        f":offset={start:.3f}:expr='{expr}'[xf]",
    ]
    last = "xf"

    if opts.labels and label_dir is not None:
        assert opts.fonts is not None
        metrics = LabelMetrics.for_reference(min(out_w, out_h))
        file_a, file_b = write_label_files(opts.labels, label_dir)
        x, y = metrics.inset + metrics.pad_h, metrics.inset + metrics.pad_v
        # The label swaps in place: A before the sweep, B after it, neither
        # during — so nothing fights the moving line for attention.
        end = start + opts.wipe_dur
        labels = ",".join([
            drawtext(
                file_a, opts.fonts[0], metrics, opts.color_a, opts.label_bg, x, y,
                enable=f"lt(t,{start:.3f})",
            ),
            drawtext(
                file_b, opts.fonts[1], metrics, opts.color_b, opts.label_bg, x, y,
                enable=f"gte(t,{end:.3f})",
            ),
        ])
        steps.append(f"[{last}]{labels}[lv]")
        last = "lv"

    audio = audio_plan(a, b, opts.audio)
    if audio == "both":
        steps.append("[0:a][1:a]amix=inputs=2:duration=shortest[aout]")
    steps.append(f"[{last}]null[v]")

    cmd = ffmpeg_head([str(a.path), str(b.path)], ";".join(steps))
    cmd += audio_args(audio) + encode_args(opts)
    if opts.trim_to:
        cmd += ["-t", f"{opts.trim_to:.3f}"]
    cmd += [str(opts.out)]

    return Plan(
        mode="wipe",
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        fps_value=fps_value,
        audio=audio,
        detail=(
            f"{opts.direction}, start={start:.2f}s, "
            f"wipe={opts.wipe_dur:.2f}s, stroke={stroke_px}px"
        ),
        command=cmd,
    )
