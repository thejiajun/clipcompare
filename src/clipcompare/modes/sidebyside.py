"""side — both clips on screen at once, left-right or top-bottom."""

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
    ffmpeg_head,
    encode_args,
    freeze_pads,
    resolve_fps,
    scale_chain,
    write_label_files,
)
from ..probe import ClipInfo

LAYOUTS = ("auto", "lr", "tb")


@dataclass
class Options(Common):
    layout: str = "auto"
    panel: int = 1080      # short edge of each panel
    length: str = "shortest"
    divider: int = 4       # 1080-normalised px, 0 disables


def resolve_layout(a: ClipInfo, requested: str) -> str:
    if requested != "auto":
        return requested
    return "lr" if a.is_portrait else "tb"


def panel_size(a: ClipInfo, panel: int) -> tuple[int, int]:
    """`panel` is the SHORT edge; the panel aspect comes from the first clip."""
    if a.width < a.height:
        width, height = panel, round(panel * a.height / a.width)
    else:
        width, height = round(panel * a.width / a.height), panel
    return even(width), even(height)


def build(a: ClipInfo, b: ClipInfo, opts: Options, label_dir: Path | None = None) -> Plan:
    layout = resolve_layout(a, opts.layout)
    panel_w, panel_h = panel_size(a, opts.panel)
    if layout == "lr":
        out_w, out_h, stack = panel_w * 2, panel_h, "hstack"
    else:
        out_w, out_h, stack = panel_w, panel_h * 2, "vstack"

    fps, fps_value = resolve_fps(a, b, opts.fps)
    chain = scale_chain(opts.fit, panel_w, panel_h, fps)

    if opts.length == "longest":
        pad_a, pad_b = freeze_pads(a, b)
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
        assert opts.fonts is not None
        metrics = LabelMetrics.for_reference(opts.panel)
        file_a, file_b = write_label_files(opts.labels, label_dir)
        x_a, y_a = metrics.inset + metrics.pad_h, metrics.inset + metrics.pad_v
        if layout == "lr":
            x_b, y_b = f"w-tw-{metrics.inset + metrics.pad_h}", y_a
        else:
            x_b, y_b = x_a, panel_h + metrics.inset + metrics.pad_v
        labels = ",".join([
            drawtext(file_a, opts.fonts[0], metrics, opts.color_a, opts.label_bg, x_a, y_a),
            drawtext(file_b, opts.fonts[1], metrics, opts.color_b, opts.label_bg, x_b, y_b),
        ])
        steps.append(f"[{last}]{labels}[lv]")
        last = "lv"

    audio = audio_plan(a, b, opts.audio)
    if audio == "both":
        steps.append("[0:a][1:a]amix=inputs=2:duration=shortest[aout]")
    steps.append(f"[{last}]null[v]")

    cmd = ffmpeg_head([str(a.path), str(b.path)], ";".join(steps))
    cmd += audio_args(audio) + encode_args(opts)
    if opts.length == "shortest":
        cmd += ["-shortest"]
    cmd += [str(opts.out)]

    return Plan(
        mode="side",
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        fps_value=fps_value,
        audio=audio,
        detail=f"{layout}, {opts.fit}, {opts.length}",
        command=cmd,
    )
