"""pip — one clip full-frame, the other as a rounded corner inset.

The rounded corner and its border are built from two `geq`-generated masks
rather than screenshots out of a headless browser:

    inset picture  -> rounded at radius R
    border plate   -> rounded at radius R + stroke, filled with the border colour
    picture is laid over the plate, inset by `stroke` on every side

so what remains visible of the plate is an even band that follows the curve.
Rounding the picture and the border together with a single mask does NOT work:
towards a corner the mask cuts in by about 0.29*(R+stroke), far deeper than the
border is thick, so the band is sliced away on the arcs and the picture's own
square corner is exposed.

Both masks use a signed-distance edge rather than a hard threshold, so the
corners are anti-aliased.
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
    encode_args,
    even,
    ffmpeg_head,
    freeze_pads,
    geometry,
    resolve_fps,
    scale_chain,
    write_label_files,
)
from ..probe import ClipInfo

CORNERS = ("tl", "tr", "bl", "br")
INSET_CHOICES = ("a", "b")


@dataclass
class Options(Common):
    inset: str = "a"           # which clip becomes the small corner window
    corner: str = "tr"
    inset_scale: float = 0.30  # fraction of the main clip's width
    margin: float = 0.025      # fraction of the main clip's width
    radius: int = 22           # 1080-normalised px
    stroke: int = 3            # 1080-normalised px, 0 disables the border
    border: str = "white"
    panel: int = 0             # 0 keeps the main clip's own resolution
    length: str = "shortest"


def main_size(main: ClipInfo, panel: int) -> tuple[int, int]:
    if panel <= 0:
        return even(main.width), even(main.height)
    if main.width < main.height:
        return even(panel), even(round(panel * main.height / main.width))
    return even(round(panel * main.width / main.height)), even(panel)


def rounded_mask_expression(width: int, height: int, radius: int) -> str:
    """Anti-aliased rounded-rect alpha, as a distance to the corner arc.

    Outside the corner boxes dx and dy are both 0, so the distance is 0 and the
    pixel is fully opaque; inside them it falls off across one pixel.
    """
    radius = max(min(radius, width // 2, height // 2), 0)
    dx = f"max(0,max({radius}-X,X-({width - 1}-{radius})))"
    dy = f"max(0,max({radius}-Y,Y-({height - 1}-{radius})))"
    distance = f"sqrt(pow({dx},2)+pow({dy},2))"
    return f"clip(255*({radius}-{distance}+0.5),0,255)"


def mask_command(path: Path, width: int, height: int, radius: int) -> list[str]:
    expression = rounded_mask_expression(width, height, radius)
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=1",
        "-vf", f"format=gray,geq=lum='{expression}'",
        "-frames:v", "1", str(path),
    ]


def _corner_position(
    corner: str, main_w: int, main_h: int, box_w: int, box_h: int, margin: int
) -> tuple[int, int]:
    x = margin if corner in ("tl", "bl") else main_w - margin - box_w
    y = margin if corner in ("tl", "tr") else main_h - margin - box_h
    # Keep the whole box on the canvas even when the margin is small.
    return max(0, min(x, main_w - box_w)), max(0, min(y, main_h - box_h))


def build(a: ClipInfo, b: ClipInfo, opts: Options, label_dir: Path | None = None) -> Plan:
    inset_is_a = opts.inset == "a"
    main = b if inset_is_a else a
    main_stream, inset_stream = ("1:v", "0:v") if inset_is_a else ("0:v", "1:v")

    out_w, out_h = main_size(main, opts.panel)
    fps, fps_value = resolve_fps(a, b, opts.fps)

    scale_factor = out_h / 1080
    inset_w = even(max(round(opts.inset_scale * out_w), 16))
    inset_h = even(max(round(opts.inset_scale * out_h), 16))
    # stroke 0 means "no border at all" — do not round it up to a hairline.
    stroke = 0 if opts.stroke <= 0 else max(round(opts.stroke * scale_factor), 1)
    radius = max(round(opts.radius * scale_factor), 0)
    margin = round(opts.margin * out_w)

    box_w, box_h = inset_w + 2 * stroke, inset_h + 2 * stroke
    box_x, box_y = _corner_position(opts.corner, out_w, out_h, box_w, box_h, margin)

    if opts.length == "longest":
        pad_a, pad_b = freeze_pads(a, b)
        # freeze_pads is keyed by clip, not by role — map it onto whichever
        # stream is actually the main frame and whichever is the inset.
        pad_main, pad_inset = (pad_b, pad_a) if inset_is_a else (pad_a, pad_b)
        shortest = 0
    else:
        pad_main = pad_inset = ""
        shortest = 1

    main_chain = scale_chain(opts.fit, out_w, out_h, fps)
    inset_chain = (
        f"fps={fps},{geometry(opts.fit, inset_w, inset_h)},setsar=1,format=yuva420p"
    )

    steps = [
        f"[{main_stream}]{main_chain}{pad_main}[vmain]",
        f"[{inset_stream}]{inset_chain}{pad_inset}[vins]",
    ]

    # The masks come in via -loop 1 and never end, so every alphamerge that
    # touches one needs shortest=1 — otherwise the inset stream inherits the
    # mask's infinite length and the overlay below loses its end condition.
    steps.append("[vins][2:v]alphamerge=shortest=1[vinsr]")

    mask_paths = [("inner", inset_w, inset_h, radius)]
    if stroke > 0:
        mask_paths.append(("outer", box_w, box_h, radius + stroke))
        steps += [
            f"color=c={opts.border}:s={box_w}x{box_h}:r={fps}[plate]",
            "[plate][3:v]alphamerge=shortest=1[platei]",
            # The picture sits `stroke` in from every edge, so the band of
            # plate left showing is the border, curve included.
            f"[platei][vinsr]overlay={stroke}:{stroke}:shortest=1[insbox]",
        ]
        inset_label = "insbox"
    else:
        inset_label = "vinsr"

    steps.append(f"[vmain][{inset_label}]overlay={box_x}:{box_y}:shortest={shortest}[ov]")
    last = "ov"

    if opts.labels and label_dir is not None:
        assert opts.fonts is not None
        file_a, file_b = write_label_files(opts.labels, label_dir)
        main_metrics = LabelMetrics.for_reference(min(out_w, out_h))
        # Size the inset's label off the inset, or it swamps the little window.
        inset_metrics = LabelMetrics.for_reference(min(inset_w, inset_h))

        main_x: str | int = main_metrics.inset + main_metrics.pad_h
        # The main label lives top-left; when the inset is parked there too,
        # drop it to the bottom rather than letting the two collide.
        if opts.corner == "tl":
            main_y: str | int = f"h-th-{main_metrics.inset + main_metrics.pad_v}"
        else:
            main_y = main_metrics.inset + main_metrics.pad_v
        inset_x = box_x + stroke + inset_metrics.inset + inset_metrics.pad_h
        inset_y = box_y + stroke + inset_metrics.inset + inset_metrics.pad_v

        main_label = (file_b, opts.fonts[1], opts.color_b) if inset_is_a else (
            file_a, opts.fonts[0], opts.color_a
        )
        small_label = (file_a, opts.fonts[0], opts.color_a) if inset_is_a else (
            file_b, opts.fonts[1], opts.color_b
        )
        drawn = [
            drawtext(main_label[0], main_label[1], main_metrics, main_label[2],
                     opts.label_bg, main_x, main_y),
            drawtext(small_label[0], small_label[1], inset_metrics, small_label[2],
                     opts.label_bg, inset_x, inset_y),
        ]
        steps.append(f"[{last}]{','.join(drawn)}[lv]")
        last = "lv"

    audio = audio_plan(a, b, opts.audio)
    if audio == "both":
        steps.append("[0:a][1:a]amix=inputs=2:duration=shortest[aout]")
    steps.append(f"[{last}]null[v]")

    work_dir = label_dir or Path(".")
    inputs: list = [str(a.path), str(b.path)]
    pre_commands = []
    for name, width, height, mask_radius in mask_paths:
        path = work_dir / f"pip-mask-{name}.png"
        inputs.append((["-loop", "1"], str(path)))
        pre_commands.append(mask_command(path, width, height, mask_radius))

    cmd = ffmpeg_head(inputs, ";".join(steps))
    cmd += audio_args(audio) + encode_args(opts)
    if opts.length == "shortest":
        cmd += ["-shortest"]
    cmd += [str(opts.out)]

    return Plan(
        mode="pip",
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        fps_value=fps_value,
        audio=audio,
        detail=(
            f"inset={opts.inset} @{opts.corner}, {inset_w}x{inset_h}, "
            f"radius={radius}px, stroke={stroke}px"
        ),
        command=cmd,
        pre_commands=pre_commands,
    )
