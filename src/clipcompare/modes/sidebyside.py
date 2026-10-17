"""side — both clips on screen at once, left-right or top-bottom."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ..filters import (
    Common,
    LabelMetrics,
    Plan,
    audio_args,
    audio_plan,
    clamp_head,
    clip_input,
    drawtext,
    even,
    ffmpeg_head,
    encode_args,
    frame_chain,
    freeze_pads,
    hold_images,
    lossless_pix_fmt,
    native_panel,
    picture,
    resolve_fps,
    scaled_px,
    scale_notes,
    still_args,
    still_chain,
    text_on,
    write_label_files,
)
from .. import info as info_mod
from .. import layers
from ..probe import ClipInfo, ProbeError
from ..tokens import DS_ACCENT_700, DS_BLACK, DS_EGGSHELL, DS_TEXT_PRIMARY_LIGHT, DS_TEXT_SECONDARY_LIGHT

LAYOUTS = ("auto", "lr", "tb")


@dataclass
class Options(Common):
    layout: str = "auto"
    panel: int = 0         # short edge of each panel; 0 = 1080, or an image's own size
    length: str = "shortest"
    divider: int | None = None  # 1080-normalised px, 0 disables; None: 4, or 0 with padding
    padding: int = 0       # 1080-normalised px around and between the panels
    background: str = DS_BLACK  # the canvas: padding and the title bar
    # None: the design default, chosen for what the label sits on (label_colors).
    color_a: str | None = None
    color_b: str | None = None
    sequential: bool = False  # A plays through, then B; the idle side holds its frame
    hold_b_at: float = 0.0    # --sequential: the moment of B shown while A plays
    info: info_mod.Run | None = None   # --stats: measured strips and the shared title bar
    info_font: Path | None = None


def sequence_video(
    a: ClipInfo, b: ClipInfo, chains: tuple[str, str], hold_b_at: float, fps_value: float,
    size: tuple[int, int], fps: str, folder: Path | None = None, pre: list | None = None,
    head: float | None = None,
) -> list[str]:
    """--sequential: A holds its last frame while B plays; while A plays, B shows
    one still taken at `hold_b_at` — past any black lead-in, which a plain
    tpad start clone would freeze on — and B's turn also starts there, so the
    hand-off never flashes black. The still comes from a second read of B
    (input 2) so B's own stream is never buffered while A plays. An audio-only
    side needs none of that: its waveform is simply flat outside its turn."""
    if not (a.duration and b.duration):
        raise ProbeError("--sequential needs both clips' durations, and ffprobe reported none")
    frame = 1 / fps_value if fps_value > 0 else 0.0
    hold = max(a.duration - frame, 0.0)
    b_turn = b.duration - hold_b_at
    width, height = size
    chain_a, chain_b = chains
    steps: list[str] = []
    pre = pre if pre is not None else []
    if a.is_audio:
        wave, start, render = picture(0, a, width, height, fps, total=hold + b_turn, folder=folder, head=head)
        pre += render
        steps += [*wave, f"{start}{chain_a}[va]"]
    else:
        steps.append(f"[0:v]{chain_a},tpad=stop_mode=clone:stop_duration={b_turn:.3f}[va]")
    if b.is_audio:
        wave, start, render = picture(1, b, width, height, fps, delay=hold, folder=folder, head=head)
        pre += render
        steps += [*wave, f"{start}{chain_b}[vb]"]
    else:
        steps += [
            f"[2:v]{chain_b},trim=end_frame=1,tpad=stop_mode=clone:stop_duration={hold:.3f}[bh]",
            f"[1:v]{chain_b},trim=start={hold_b_at:.3f},setpts=PTS-STARTPTS[bp]",
            "[bh][bp]concat=n=2:v=1:a=0[vb]",
        ]
    return steps


def sequence_audio(a: ClipInfo, b: ClipInfo, b_start: float) -> list[str]:
    """A's sound for A's turn, then B's from `b_start` (where B's picture starts).
    Each turn is cut or padded to its video length so the sound switches exactly
    when the playing side does; a clip without audio gives silence for its turn."""
    steps = []
    for index, (info, start) in enumerate(((a, 0.0), (b, b_start))):
        source = (
            f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
            if info.has_audio
            else "anullsrc=r=48000:cl=stereo,"
        )
        steps.append(
            f"{source}atrim={start:.3f}:{info.duration:.3f},asetpts=N/SR/TB[s{index}]"
        )
    steps.append("[s0][s1]concat=n=2:v=0:a=1[aout]")
    return steps


def label_colors(opts: Options, outside: bool) -> tuple[str, str]:
    """The label colours: as given, else the design defaults — which on a
    light --background, once the labels sit on it rather than on their dark
    chip, give way to the light theme's text colour for both."""
    if outside and text_on(opts.background) == DS_TEXT_SECONDARY_LIGHT:
        defaults = (DS_TEXT_PRIMARY_LIGHT, DS_TEXT_PRIMARY_LIGHT)
    else:
        defaults = (DS_EGGSHELL, DS_ACCENT_700)
    return opts.color_a or defaults[0], opts.color_b or defaults[1]


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
    # Two still images make one still picture.
    still = a.is_image and b.is_image
    if still:
        opts = replace(opts, sequential=False, head=None)
    else:
        a, b = hold_images([clamp_head(a, opts.head), clamp_head(b, opts.head)])
    # Stills keep their own pixels unless --panel says otherwise; so does
    # --lossless, at the first clip's own size.
    if still:
        opts = replace(opts, lossless=None)
    panel = opts.panel or (
        min(1080, a.width, a.height) if still else native_panel(a) if opts.lossless else 1080
    )
    opts = replace(opts, panel=panel)
    layout = resolve_layout(a, opts.layout)
    panel_w, panel_h = panel_size(a, opts.panel)
    # Padding frames both panels and splits them, so the divider line is
    # redundant there unless asked for.
    space = scaled_px(opts.padding, opts.panel)
    divider = opts.divider if opts.divider is not None else (0 if space else 4)
    # Each panel's top-left corner on the canvas.
    if layout == "lr":
        out_w, out_h, stack = panel_w * 2 + space * 3, panel_h + space * 2, "hstack"
        corners = [(space, space), (space * 2 + panel_w, space)]
    else:
        out_w, out_h, stack = panel_w + space * 2, panel_h * 2 + space * 3, "vstack"
        corners = [(space, space), (space, space * 2 + panel_h)]

    fps, fps_value = resolve_fps(a, b, opts.fps)
    pix_fmt = lossless_pix_fmt([a, b], opts.lossless) if opts.lossless else "yuv420p"
    if still:
        chains = (still_chain(opts.fit, panel_w, panel_h),) * 2
    else:
        chains = tuple(frame_chain(clip, opts.fit, panel_w, panel_h, fps, opts.lossless, pix_fmt) for clip in (a, b))

    inputs = [clip_input(a, opts.head), clip_input(b, opts.head)]
    pre_commands: list[list[str]] = []
    if opts.sequential:
        steps = sequence_video(
            a, b, chains, opts.hold_b_at, fps_value, (panel_w, panel_h), fps, label_dir, pre_commands, opts.head,
        )
        if not b.is_audio:
            inputs.append((["-ss", f"{opts.hold_b_at:.3f}"], str(b.path)))
        shortest = 0
    else:
        if opts.length == "longest" or still:
            pad_a, pad_b = freeze_pads(a, b)
            shortest = 0
        else:
            pad_a = pad_b = ""
            shortest = 1
        # An audio side's waveform runs flat to the end instead of freezing.
        longest = max(a.duration, b.duration) if opts.length == "longest" else 0.0
        steps = []
        for index, (clip, freeze, name) in enumerate(((a, pad_a, "va"), (b, pad_b, "vb"))):
            wave, head, render = picture(
                index, clip, panel_w, panel_h, fps, total=longest, folder=label_dir, head=opts.head,
            )
            pre_commands += render
            steps += [*wave, f"{head}{chains[index]}{'' if clip.is_audio else freeze}[{name}]"]
    if space:
        # A takes the padding before it, B the padding on both sides of it.
        if layout == "lr":
            sizes = ((panel_w + space, panel_h + space * 2), (panel_w + space * 2, panel_h + space * 2))
        else:
            sizes = ((panel_w + space * 2, panel_h + space), (panel_w + space * 2, panel_h + space * 2))
        for name, (width, height) in zip(("a", "b"), sizes):
            steps.append(f"[v{name}]pad={width}:{height}:{space}:{space}:color={opts.background}[p{name}]")
        stacked = "[pa][pb]"
    else:
        stacked = "[va][vb]"
    steps.append(f"{stacked}{stack}=inputs=2:shortest={shortest}[st]")
    last = "st"

    # The info layer, drawn the way grid draws its tiles: a strip along each
    # panel's bottom, and what both share once in a title bar above them.
    metrics = LabelMetrics.for_reference(opts.panel)
    run_info = opts.info if opts.info and opts.info_font and label_dir is not None else None
    if run_info:
        spots = corners
        painted = layers.pictures(run_info, opts.info_font, opts.label_bg, label_dir, panel_w, metrics)
        last = layers.overlay(
            painted, spots, panel_h, metrics, steps, inputs, pre_commands, last, still, fps, opts.lossless,
        )

    if divider > 0:
        thickness = max(round(divider * opts.panel / 1080), 1)
        # Centred in the space between the panels (on the seam without padding).
        middle = space + (panel_w if layout == "lr" else panel_h) + space // 2 - thickness // 2
        if layout == "lr":
            box = f"drawbox=x={middle}:y=0:w={thickness}:h=ih:color=white@0.85:t=fill"
        else:
            box = f"drawbox=x=0:y={middle}:w=iw:h={thickness}:color=white@0.85:t=fill"

        steps.append(f"[{last}]{box}[dv]")
        last = "dv"

    if opts.labels and label_dir is not None:
        assert opts.fonts is not None
        file_a, file_b = write_label_files(opts.labels, label_dir)
        (left_a, top_a), (left_b, top_b) = corners
        x_a, y_a = left_a + metrics.inset + metrics.pad_h, top_a + metrics.inset + metrics.pad_v
        if layout == "lr":
            x_b, y_b = f"w-tw-{space + metrics.inset + metrics.pad_h}", y_a
        else:
            x_b, y_b = x_a, top_b + metrics.inset + metrics.pad_v
        chip, align = opts.label_bg, ""
        # Padding that holds a label takes it: plain text on the canvas just
        # above each panel, clear of the clip's own corners (an app's header).
        if space >= metrics.size + metrics.pad_v:
            # y is the baseline: capitals (about 0.7 em tall) centred in the space.
            baseline = space // 2 + round(metrics.size * 0.35)
            (x_a, y_a), (x_b, y_b) = ((left, top - space + baseline) for left, top in corners)
            chip, align = "black@0", ":y_align=baseline"
        color_a, color_b = label_colors(opts, outside=bool(align))
        labels = ",".join([
            drawtext(file_a, opts.fonts[0], metrics, color_a, chip, x_a, y_a) + align,
            drawtext(file_b, opts.fonts[1], metrics, color_b, chip, x_b, y_b) + align,
        ])
        steps.append(f"[{last}]{labels}[lv]")
        last = "lv"

    if run_info and run_info.shared_text:
        assert opts.info_font
        band = layers.shared_px(min(out_w, out_h))
        steps.append(f"[{last}]pad={out_w}:{out_h + band}:0:{band}:color={opts.background}[hd]")
        step, last = layers.shared_line(
            "hd", run_info.shared_text, opts.info_font, band, 0, out_w, label_dir, metrics.inset,
            color=text_on(opts.background),
        )
        steps.append(step)
        out_h += band

    if still:
        audio = "none"
    elif opts.sequential:
        silent = opts.audio == "none" or not (a.has_audio or b.has_audio)
        audio = "none" if silent else "a→b"
    else:
        audio = audio_plan(a, b, opts.audio)
    if audio == "a→b":
        steps += sequence_audio(a, b, opts.hold_b_at)
    elif audio == "both":
        steps.append("[0:a][1:a]amix=inputs=2:duration=shortest[aout]")
    steps.append(f"[{last}]null[v]")

    cmd = ffmpeg_head(inputs, ";".join(steps))
    if still:
        cmd += still_args(opts.out)
    else:
        cmd += audio_args("both" if audio == "a→b" else audio, lossless=opts.lossless) + encode_args(opts, pix_fmt)
    if opts.length == "shortest" and not opts.sequential and not still:
        cmd += ["-shortest"]
    cmd += [str(opts.out)]

    return Plan(
        mode="side",
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        fps_value=fps_value,
        audio=audio,
        detail=f"{layout}, {opts.fit}, {'image' if still else 'sequential' if opts.sequential else opts.length}"
               + (f", lossless {opts.lossless} {pix_fmt}" if opts.lossless else ""),
        command=cmd,
        pre_commands=pre_commands,
        notes=scale_notes([a, b], [(panel_w, panel_h)] * 2, opts.fit, opts.lossless),
    )
