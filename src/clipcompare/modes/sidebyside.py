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
    clamp_head,
    clip_input,
    drawtext,
    even,
    ffmpeg_head,
    encode_args,
    freeze_pads,
    picture,
    resolve_fps,
    scale_chain,
    write_label_files,
)
from ..probe import ClipInfo, ProbeError

LAYOUTS = ("auto", "lr", "tb")


@dataclass
class Options(Common):
    layout: str = "auto"
    panel: int = 1080      # short edge of each panel
    length: str = "shortest"
    divider: int = 4       # 1080-normalised px, 0 disables
    sequential: bool = False  # A plays through, then B; the idle side holds its frame
    hold_b_at: float = 0.0    # --sequential: the moment of B shown while A plays


def sequence_video(
    a: ClipInfo, b: ClipInfo, chain: str, hold_b_at: float, fps_value: float,
    size: tuple[int, int], fps: str,
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
    steps: list[str] = []
    if a.is_audio:
        wave, head = picture(0, a, width, height, fps, total=hold + b_turn)
        steps += [*wave, f"{head}{chain}[va]"]
    else:
        steps.append(f"[0:v]{chain},tpad=stop_mode=clone:stop_duration={b_turn:.3f}[va]")
    if b.is_audio:
        wave, head = picture(1, b, width, height, fps, delay=hold)
        steps += [*wave, f"{head}{chain}[vb]"]
    else:
        steps += [
            f"[2:v]{chain},trim=end_frame=1,tpad=stop_mode=clone:stop_duration={hold:.3f}[bh]",
            f"[1:v]{chain},trim=start={hold_b_at:.3f},setpts=PTS-STARTPTS[bp]",
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
    a, b = clamp_head(a, opts.head), clamp_head(b, opts.head)
    layout = resolve_layout(a, opts.layout)
    panel_w, panel_h = panel_size(a, opts.panel)
    if layout == "lr":
        out_w, out_h, stack = panel_w * 2, panel_h, "hstack"
    else:
        out_w, out_h, stack = panel_w, panel_h * 2, "vstack"

    fps, fps_value = resolve_fps(a, b, opts.fps)
    chain = scale_chain(opts.fit, panel_w, panel_h, fps)

    inputs = [clip_input(a, opts.head), clip_input(b, opts.head)]
    if opts.sequential:
        steps = sequence_video(a, b, chain, opts.hold_b_at, fps_value, (panel_w, panel_h), fps)
        if not b.is_audio:
            inputs.append((["-ss", f"{opts.hold_b_at:.3f}"], str(b.path)))
        shortest = 0
    else:
        if opts.length == "longest":
            pad_a, pad_b = freeze_pads(a, b)
            shortest = 0
        else:
            pad_a = pad_b = ""
            shortest = 1
        # An audio side's waveform runs flat to the end instead of freezing.
        longest = max(a.duration, b.duration) if opts.length == "longest" else 0.0
        steps = []
        for index, (clip, pad, name) in enumerate(((a, pad_a, "va"), (b, pad_b, "vb"))):
            wave, head = picture(index, clip, panel_w, panel_h, fps, total=longest)
            steps += [*wave, f"{head}{chain}{'' if clip.is_audio else pad}[{name}]"]
    steps.append(f"[va][vb]{stack}=inputs=2:shortest={shortest}[st]")
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

    if opts.sequential:
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
    cmd += audio_args("both" if audio == "a→b" else audio) + encode_args(opts)
    if opts.length == "shortest" and not opts.sequential:
        cmd += ["-shortest"]
    cmd += [str(opts.out)]

    return Plan(
        mode="side",
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        fps_value=fps_value,
        audio=audio,
        detail=f"{layout}, {opts.fit}, {'sequential' if opts.sequential else opts.length}",
        command=cmd,
    )
