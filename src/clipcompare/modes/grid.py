"""grid — any number of clips tiled N x M, all playing at once or one at a time.

Tiles fill in reading order (left to right, then down) and share the first
clip's aspect. The auto shape aims the whole canvas at a 16:9 screen, then
drops trailing empty columns; the auto tile size keeps the output within 4K.

--sequential plays one tile at a time: a waiting tile shows its first lit frame
(read from a second, one-second input of that clip, so its own stream is never
buffered while others play), a finished tile holds its last frame, the playing
tile is outlined, and the sound follows it. --pause holds everything still and
silent for a moment between turns.

Audio-only clips become waveform panels. With nothing but audio there is no
aspect to follow, so up to four sit in one row and the tiles fill a 1920x1080
canvas; in a sequence each line moves only during its own turn.

--title puts a header strip above the tiles (it never crosses a tile).

Still images (png, jpg, webp) among the clips hold still for the video's
length. When every clip is an image the result is one picture instead: up to
four in a row, at their own size, in full-colour RGB, with each prompt drawn
whole and static.

Prompts (--captions, or a --manifest's "prompt"s) are drawn inside the tiles,
marked against the run's baseline clip (see prompts.py): every tile shows its
label and a one-line summary of how it differs, and the playing tile also
shows its prompt, large, one segment at a time in step with the sound, the
segment being spoken at full brightness and its neighbours dimmed (see
captions.py). On an audio tile the waveform keeps to a band along the bottom,
under the text.

--group N cuts the clips into runs of N, renders each run as its own grid with
its own --title, and joins the runs end to end.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from .. import captions as captions_mod
from .. import prompts as prompts_mod
from ..filters import (
    LENGTH_EPSILON,
    Common,
    Input,
    LabelMetrics,
    Plan,
    audio_args,
    clamp_head,
    clip_input,
    drawtext,
    encode_args,
    escape,
    even,
    ffmpeg_head,
    frame_chain,
    hold_images,
    lossless_pix_fmt,
    native_panel,
    picture,
    resolve_fps,
    scale_notes,
    still_args,
    still_chain,
    wave_band,
)
from ..probe import ClipInfo, ProbeError
from ..tokens import DS_BLACK, DS_TEXT_SECONDARY_DARK
from .sidebyside import panel_size

MAX_CANVAS = 3840        # auto tile size keeps the output's long edge within 4K
MAX_TILE = 1080          # ...and never grows a tile past 1080 on its short edge
TARGET_ASPECT = 16 / 9   # the auto shape aims the whole canvas at a landscape screen
AUDIO_CANVAS = (1920, 1080)  # what auto tiles fill when every clip is audio only
AUDIO_ROW = 4                # ...and up to this many of them sit in one row
IMAGE_ROW = 4                # images too: up to this many sit side by side in one row
AUDIO_MODES = ("auto", "none", "mix")
HEADER = 0.1             # --title strip height, as a share of the canvas's short edge
SUMMARY = 0.8            # diff summary size, as a share of the label's


@dataclass
class Options(Common):
    audio: str = "auto"        # auto | none | mix | a 1-based clip number
    cols: int = 0              # 0 = auto
    rows: int = 0              # 0 = auto
    panel: int = 0             # short edge of each tile; 0 = auto
    gap: int = 4               # 1080-normalised px between tiles, 0 disables
    length: str = "shortest"
    sequential: bool = False
    holds: tuple[float, ...] = ()  # --sequential: per clip, where its picture starts
    pause: float = 0.0         # --sequential: seconds of stillness between turns
    tail: float = 0.0          # --sequential: ...and after the last one (between --group runs)
    title: str | None = None   # drawn in a header strip above the tiles
    title_font: Path | None = None
    prompts: tuple[prompts_mod.ClipPrompt | None, ...] = ()   # per clip, see prompts.prepare
    caption_fonts: captions_mod.Fonts | None = None
    caption_size: int = 0      # prompt text size; 0 fits it to these clips' longest segment


def grid_shape(count: int, tile_aspect: float, cols: int = 0, rows: int = 0) -> tuple[int, int]:
    if cols and rows:
        return cols, rows
    if cols:
        return cols, math.ceil(count / cols)
    if rows:
        return math.ceil(count / rows), rows
    cols = max(1, min(count, round(math.sqrt(count * TARGET_ASPECT / tile_aspect))))
    rows = math.ceil(count / cols)
    return math.ceil(count / rows), rows


def header_px(short: int) -> int:
    return even(round(short * HEADER))


def audio_tiles(cols: int, rows: int, gap: int, header: bool = False) -> tuple[int, int, int, int]:
    """tile_size for clips that are all audio: share AUDIO_CANVAS between them,
    less the --title header strip, so the whole video stays 1920x1080."""
    canvas_w, canvas_h = AUDIO_CANVAS
    spacing = gap_px(gap, canvas_h)
    if header:
        canvas_h -= header_px(canvas_h)
    width = even((canvas_w - (cols - 1) * spacing) // cols)
    height = even((canvas_h - (rows - 1) * spacing) // rows)
    return width, height, min(width, height), spacing


def gap_px(gap: int, short: int) -> int:
    return max(even(round(gap * short / 1080)), 2) if gap > 0 else 0


def tile_size(
    first: ClipInfo, cols: int, rows: int, panel: int, gap: int = 0, max_tile: int = MAX_TILE,
) -> tuple[int, int, int, int]:
    """(tile width, tile height, tile short edge, gap in px). The auto size
    shrinks until tiles and gaps together fit MAX_CANVAS."""
    auto = panel == 0
    if auto:
        unit_w, unit_h = panel_size(first, 1000)
        long_units = max(cols * unit_w, rows * unit_h) / 1000
        panel = min(max_tile, int(MAX_CANVAS / long_units))
    while True:
        width, height = panel_size(first, panel)
        short = min(width, height)
        spacing = gap_px(gap, short)
        canvas = max(cols * width + (cols - 1) * spacing, rows * height + (rows - 1) * spacing)
        if not auto or canvas <= MAX_CANVAS or panel <= 16:
            return width, height, short, spacing
        panel -= 2


def grid_fps(clips: list[ClipInfo], override: str | None) -> tuple[str, float]:
    if override:
        return resolve_fps(clips[0], clips[0], override)
    fastest = max(clips, key=lambda clip: clip.fps_value)
    return fastest.fps, fastest.fps_value


def together_tiles(
    clips: list[ClipInfo], chains: list[str], length: str, size: tuple[int, int], fps: str,
) -> list[str]:
    longest = max(clip.duration for clip in clips)
    steps = []
    for index, (clip, chain) in enumerate(zip(clips, chains)):
        if clip.is_audio:
            # A waveform runs flat to the end rather than freezing mid-swing.
            wave, head = picture(index, clip, *size, fps, total=longest if length == "longest" else 0.0)
            steps += [*wave, f"{head}{chain}[t{index}]"]
            continue
        pad = ""
        if length == "longest" and clip.duration and longest - clip.duration > LENGTH_EPSILON:
            pad = f",tpad=stop_mode=clone:stop_duration={longest - clip.duration:.3f}"
        steps.append(f"[{index}:v]{chain}{pad}[t{index}]")
    return steps


def turn_starts(clips: list[ClipInfo], holds: tuple[float, ...], pause: float, tail: float) -> tuple[list[float], list[float], float]:
    """--sequential timing: each clip's turn length, where it starts, and the
    whole sequence's length, with `pause` between turns and `tail` after them."""
    lengths = [clip.duration - hold for clip, hold in zip(clips, holds)]
    starts = [sum(lengths[:index]) + index * pause for index in range(len(clips))]
    return lengths, starts, starts[-1] + lengths[-1] + tail


def sequence_tiles(
    clips: list[ClipInfo], chains: list[str], opts: Options, holds: tuple[float, ...], fps_value: float,
    size: tuple[int, int], fps: str,
) -> tuple[list[str], list[Input], list[tuple[float, float]]]:
    """Per-tile video for --sequential, the extra still inputs it reads, and each
    clip's turn as (start, end) on the output timeline."""
    if not all(clip.duration for clip in clips):
        raise ProbeError("--sequential needs every clip's duration, and ffprobe reported none for one")
    frame = 1 / fps_value if fps_value > 0 else 0.0
    lengths, starts, total = turn_starts(clips, holds, opts.pause, opts.tail)

    steps: list[str] = []
    stills: list[Input] = []
    for index, (clip, hold, chain) in enumerate(zip(clips, holds, chains)):
        if clip.is_audio:
            # No still needed: the line is flat before and after its own turn.
            wave, head = picture(index, clip, *size, fps, delay=starts[index], total=total)
            steps += [*wave, f"{head}{chain}[t{index}]"]
            continue
        after = total - starts[index] - lengths[index]
        tail = f",tpad=stop_mode=clone:stop_duration={after:.3f}" if after > LENGTH_EPSILON else ""
        play = f"[{index}:v]{chain},trim=start={hold:.3f},setpts=PTS-STARTPTS{tail}"
        if index == 0:
            steps.append(f"{play}[t0]")
            continue
        still = len(clips) + len(stills)
        stills.append((["-ss", f"{hold:.3f}", "-t", "1"], str(clip.path)))
        wait = max(starts[index] - frame, 0.0)
        steps += [
            f"[{still}:v]{chain},trim=end_frame=1,tpad=stop_mode=clone:stop_duration={wait:.3f}[w{index}]",
            f"{play}[p{index}]",
            f"[w{index}][p{index}]concat=n=2:v=1:a=0[t{index}]",
        ]
    turns = [(start, start + length) for start, length in zip(starts, lengths)]
    return steps, stills, turns


def grid_audio(
    clips: list[ClipInfo], opts: Options, holds: tuple[float, ...],
) -> tuple[str, list[str], list[str]]:
    """(summary label, filter steps, output mapping)."""
    with_sound = [index for index, clip in enumerate(clips) if clip.has_audio]
    choice = opts.audio
    if choice == "none" or not with_sound:
        return "none", [], audio_args("none")
    lossless = opts.lossless

    if opts.sequential and choice == "auto":
        steps = []
        for index, (clip, hold) in enumerate(zip(clips, holds)):
            source = (
                f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
                if clip.has_audio
                else "anullsrc=r=48000:cl=stereo,"
            )
            # Each turn runs on into silence for the pause after it.
            gap = opts.tail if index == len(clips) - 1 else opts.pause
            steps.append(f"{source}atrim={hold:.3f}:{clip.duration + gap:.3f},asetpts=N/SR/TB[s{index}]")
        turns = "".join(f"[s{index}]" for index in range(len(clips)))
        steps.append(f"{turns}concat=n={len(clips)}:v=0:a=1[aout]")
        return "follow", steps, audio_args("both", lossless=lossless)

    if choice == "mix" and len(with_sound) > 1:
        sources = "".join(f"[{index}:a]" for index in with_sound)
        duration = "longest" if opts.length == "longest" or opts.sequential else "shortest"
        steps = [f"{sources}amix=inputs={len(with_sound)}:duration={duration}[aout]"]
        return "mix", steps, audio_args("both", lossless=lossless)

    if choice in ("auto", "mix"):
        index = with_sound[0]
    else:
        index = int(choice) - 1
        if index not in with_sound:
            return "none", [], audio_args("none")
    return str(index + 1), [], audio_args("a", index_a=index, lossless=lossless)


def build(clips: list[ClipInfo], opts: Options, label_dir: Path | None = None) -> Plan:
    # Every clip a still image: the result is one picture, not a video.
    still = all(clip.is_image for clip in clips)
    if still:
        # A picture of stills is a lossless PNG already.
        opts = replace(opts, sequential=False, holds=(), pause=0.0, tail=0.0, head=None, lossless=None)
    else:
        clips = hold_images([clamp_head(clip, opts.head) for clip in clips])
    count = len(clips)
    first = clips[0]
    all_audio = all(clip.is_audio for clip in clips)
    if (all_audio and count <= AUDIO_ROW or still and count <= IMAGE_ROW) and not (opts.cols or opts.rows):
        cols, rows = count, 1
    else:
        cols, rows = grid_shape(count, first.width / first.height, opts.cols, opts.rows)
    titled = bool(opts.title and opts.title_font and label_dir is not None)
    if all_audio and not opts.panel:
        tile_w, tile_h, short, gap = audio_tiles(cols, rows, opts.gap, titled)
    else:
        # Stills keep their own pixels: the auto size never scales them up.
        cap = min(MAX_TILE, first.width, first.height) if still else MAX_TILE
        # --lossless tiles are the first clip's own size, however large the canvas.
        panel = opts.panel or (native_panel(first) if opts.lossless else 0)
        tile_w, tile_h, short, gap = tile_size(first, cols, rows, panel, opts.gap, cap)
    grid_w = cols * tile_w + (cols - 1) * gap
    grid_h = rows * tile_h + (rows - 1) * gap
    header = 0
    if titled:
        header = AUDIO_CANVAS[1] - grid_h if all_audio and not opts.panel else header_px(min(grid_w, grid_h))
    out_w, out_h = grid_w, grid_h + header
    cells = [((index % cols) * (tile_w + gap), (index // cols) * (tile_h + gap)) for index in range(count)]
    # Where each tile lands on the finished canvas, below the header.
    spots = [(x, y + header) for x, y in cells]

    fps, fps_value = grid_fps(clips, opts.fps)
    pix_fmt = lossless_pix_fmt(clips, opts.lossless) if opts.lossless else "yuv420p"
    chains = [
        still_chain(opts.fit, tile_w, tile_h) if still
        else frame_chain(clip, opts.fit, tile_w, tile_h, fps, opts.lossless, pix_fmt)
        for clip in clips
    ]
    inputs: list[Input] = [clip_input(clip, opts.head) for clip in clips]
    holds = opts.holds or (0.0,) * count

    turns: list[tuple[float, float]] = []
    if opts.sequential:
        steps, stills, turns = sequence_tiles(clips, chains, opts, holds, fps_value, (tile_w, tile_h), fps)
        inputs += stills
        shortest = 0
    else:
        steps = together_tiles(clips, chains, opts.length, (tile_w, tile_h), fps)
        shortest = 1 if opts.length == "shortest" and not still else 0

    layout = "|".join(f"{x}_{y}" for x, y in cells)
    tiles = "".join(f"[t{index}]" for index in range(count))
    steps.append(f"{tiles}xstack=inputs={count}:layout={layout}:fill=black:shortest={shortest}[st]")
    last = "st"

    if header:
        steps.append(f"[{last}]pad={out_w}:{out_h}:0:{header}:color={DS_BLACK}[hd]")
        last = "hd"

    if turns:
        thickness = max(round(short * 8 / 1080), 2)
        boxes = ",".join(
            f"drawbox=x={x}:y={y}:w={tile_w}:h={tile_h}:color={opts.color_b}:t={thickness}"
            f":enable='between(t,{start:.3f},{end:.3f})'"
            for (x, y), (start, end) in zip(spots, turns)
        )
        steps.append(f"[{last}]{boxes}[hl]")
        last = "hl"

    metrics = LabelMetrics.for_reference(short)
    pre_commands: list[list[str]] = []
    caption_size = 0
    if opts.prompts and any(opts.prompts) and opts.caption_fonts and label_dir is not None:
        last, caption_size = prompt_steps(
            clips, opts, label_dir, spots, (tile_w, tile_h), metrics,
            min(out_w, AUDIO_CANVAS[1] if all_audio else out_h) / 1080,
            turns or [(0.0, clip.duration) for clip in clips], holds, fps,
            steps, inputs, pre_commands, last, still,
        )

    if opts.labels and label_dir is not None:
        assert opts.fonts is not None
        texts = []
        for index, ((x, y), label, font) in enumerate(zip(spots, opts.labels, opts.fonts)):
            text_file = label_dir / f"label-{index}.txt"
            text_file.write_text(label, encoding="utf-8")
            texts.append(drawtext(
                text_file, font, metrics, opts.color_a, opts.label_bg,
                x + metrics.inset + metrics.pad_h, y + metrics.inset + metrics.pad_v,
            ))
        steps.append(f"[{last}]{','.join(texts)}[lv]")
        last = "lv"

    if header:
        assert opts.title and opts.title_font
        title_metrics = LabelMetrics.for_reference(round(header / HEADER * 1.3))
        title_file = label_dir / "title.txt"
        title_file.write_text(opts.title, encoding="utf-8")
        steps.append(
            f"[{last}]drawtext=textfile={escape(str(title_file))}:fontfile={escape(str(opts.title_font))}"
            f":fontsize={title_metrics.size}:expansion=none:fontcolor={opts.color_a}"
            f":y_align=font:x=(w-tw)/2:y={(header - title_metrics.size) // 2}[tv]"
        )
        last = "tv"

    if still:
        audio, audio_steps, output = "none", [], still_args(opts.out)
    else:
        audio, audio_steps, audio_map = grid_audio(clips, opts, holds)
        output = audio_map + encode_args(opts, pix_fmt)
    steps += audio_steps
    steps.append(f"[{last}]null[v]")

    cmd = ffmpeg_head(inputs, ";".join(steps)) + output
    if shortest:
        cmd += ["-shortest"]
    cmd += [str(opts.out)]

    return Plan(
        mode="grid",
        out_w=out_w,
        out_h=out_h,
        fps=fps,
        fps_value=fps_value,
        audio=audio,
        detail=f"{cols}x{rows}, {opts.fit}, "
               f"{'image' if still else 'sequential' if opts.sequential else opts.length}"
               + (f", lossless {opts.lossless} {pix_fmt}" if opts.lossless else ""),
        command=cmd,
        pre_commands=pre_commands,
        caption_size=caption_size,
        notes=scale_notes(clips, [(tile_w, tile_h)] * count, opts.fit, opts.lossless),
    )


def prompt_region(tile_w: int, tile_h: int, metrics: LabelMetrics, is_audio: bool) -> tuple[int, int, int, int, int]:
    """(left, summary y, prompt top, prompt width, prompt height) inside a
    tile: the summary line sits under the label, the prompt under that, and
    on an audio tile it stops above the waveform band."""
    label_bottom = metrics.inset + metrics.size + 2 * metrics.pad_v
    summary_y = label_bottom + metrics.inset // 2
    top = summary_y + round(metrics.size * SUMMARY) + metrics.inset
    pad = 0 if is_audio else metrics.pad_v
    bottom = wave_band(tile_h)[0] - metrics.inset // 2 if is_audio else tile_h - metrics.inset
    return metrics.inset, summary_y, top, tile_w - 2 * metrics.inset - 2 * pad, bottom - top - 2 * pad


def prompt_steps(
    clips: list[ClipInfo], opts: Options, label_dir: Path, spots: list[tuple[int, int]],
    tile: tuple[int, int], metrics: LabelMetrics, scale: float, turns: list[tuple[float, float]],
    holds: tuple[float, ...], fps: str, steps: list[str], inputs: list[Input],
    pre_commands: list[list[str]], last: str, still: bool = False,
) -> tuple[str, int]:
    """Each tile's diff summary under its label, and while it plays, one PNG
    per prompt segment (a pre-command each), shown during that segment's
    span. In a still picture each tile shows its whole prompt at once.
    Returns the new last label and the prompt size used."""
    fonts = opts.caption_fonts
    assert fonts is not None
    tile_w, tile_h = tile
    regions = [prompt_region(tile_w, tile_h, metrics, clip.is_audio) for clip in clips]
    if still:
        # One untimed segment per prompt: nothing plays, so nothing steps through.
        opts = replace(opts, prompts=tuple(
            replace(
                prompt,
                segments=(prompts_mod.Segment(prompt.text),),
                marked=(tuple(token for segment in prompt.marked for token in segment),),
            ) if prompt else None
            for prompt in opts.prompts
        ))
        turns = [(0.0, 1.0)] * len(clips)
    size = opts.caption_size or captions_mod.fit(
        [list(segment) for prompt in opts.prompts if prompt for segment in prompt.marked],
        min(region[3] for region in regions), min(region[4] for region in regions), fonts, scale,
    )
    summaries = []
    summary_size = max(round(metrics.size * SUMMARY), 6)
    for index, (clip, prompt, (x, y), (left, summary_y, top, width, height)) in enumerate(
        zip(clips, opts.prompts, spots, regions)
    ):
        if prompt is None or width < 16 or height < 8:
            continue
        if prompt.summary:
            text_file = label_dir / f"summary-{index}.txt"
            text_file.write_text(
                captions_mod.ellipsize_text(prompt.summary, tile_w - 2 * left, summary_size, fonts.body),
                encoding="utf-8",
            )
            summaries.append(
                f"drawtext=textfile={escape(str(text_file))}:fontfile={escape(str(fonts.body))}"
                f":fontsize={summary_size}:expansion=none:fontcolor={DS_TEXT_SECONDARY_DARK}"
                f":x={x + left}:y={y + summary_y}"
            )
        pad = 0 if clip.is_audio else metrics.pad_v
        spans = prompts_mod.windows(prompt, *turns[index], hold=holds[index] if opts.sequential else 0.0)
        segments = [list(segment) for segment in prompt.marked]
        for number, (segment, (start, end)) in enumerate(zip(prompt.segments, spans)):
            if end - start <= 0:
                continue
            shown = captions_mod.view(segments, number, width, height, size, fonts, note=segment.estimated)
            if still:
                # Nothing plays over a still, so the chip hugs the text and leaves the picture.
                height = min(height, len(shown.rows) * captions_mod.line_height(size))
            image = label_dir / f"prompt-{index}-{number}.png"
            pre_commands.append(captions_mod.render_command(
                shown, fonts, image, label_dir, width, height,
                background="black@0" if clip.is_audio else opts.label_bg, pad=pad,
            ))
            source = len(inputs)
            if still:
                inputs.append(str(image))
                steps.append(f"[{last}][{source}:v]overlay={x + left}:{y + top}:format=rgb[p{index}_{number}]")
            else:
                inputs.append((["-loop", "1", "-framerate", fps], str(image)))
                # format=auto keeps a --lossless 4:4:4 picture from dropping to 4:2:0.
                steps.append(
                    f"[{last}][{source}:v]overlay={x + left}:{y + top}:shortest=1"
                    f"{':format=auto' if opts.lossless else ''}"
                    f":enable='between(t,{start:.3f},{end:.3f})'[p{index}_{number}]"
                )
            last = f"p{index}_{number}"
    if summaries:
        steps.append(f"[{last}]{','.join(summaries)}[sm]")
        last = "sm"
    return last, size


def build_groups(
    groups: list[list[ClipInfo]], opts: Options, titles: tuple[str | None, ...], label_dir: Path,
) -> Plan:
    """--group: each run rendered as its own grid into the working folder, then
    joined without re-encoding. Every run has the same tile count and settings,
    so their streams match and the join is a plain copy."""
    size = len(groups[0])
    parts = _build_runs(groups, opts, titles, label_dir)
    sizes = {plan.caption_size for plan in parts if plan.caption_size}
    if len(sizes) > 1 and not opts.caption_size:
        # One prompt size for the whole video: the one the densest run needed.
        parts = _build_runs(groups, replace(opts, caption_size=min(sizes)), titles, label_dir)

    listing = label_dir / "groups.txt"
    listing.write_text("".join(f"file '{plan.command[-1]}'\n" for plan in parts), encoding="utf-8")
    first = parts[0]
    return Plan(
        mode="grid",
        out_w=first.out_w,
        out_h=first.out_h,
        fps=first.fps,
        fps_value=first.fps_value,
        audio=first.audio,
        detail=f"{len(groups)} groups of {size}, {first.detail}",
        notes=[note for plan in parts for note in plan.notes],
        command=[
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", "-movflags", "+faststart", str(opts.out),
        ],
        pre_commands=[command for plan in parts for command in (*plan.pre_commands, plan.command)],
        caption_size=first.caption_size,
    )


def _build_runs(
    groups: list[list[ClipInfo]], opts: Options, titles: tuple[str | None, ...], label_dir: Path,
) -> list[Plan]:
    size = len(groups[0])
    parts: list[Plan] = []
    for number, group in enumerate(groups):
        part_dir = label_dir / f"group-{number + 1}"
        part_dir.mkdir(parents=True, exist_ok=True)
        span = slice(number * size, (number + 1) * size)
        part = replace(
            opts,
            out=part_dir / f"part{opts.out.suffix or '.mp4'}",
            # One rate for every run, or the copied join would play them at odd speeds.
            fps=opts.fps or grid_fps([clip for run in groups for clip in run], None)[0],
            labels=opts.labels[span] if opts.labels else None,
            fonts=opts.fonts[span] if opts.fonts else None,
            holds=opts.holds[span] if opts.holds else (),
            prompts=opts.prompts[span] if opts.prompts else (),
            title=titles[number],
            tail=opts.pause if number < len(groups) - 1 else 0.0,
        )
        parts.append(build(group, part, part_dir))
    return parts
