"""Command line entry point: `clipcompare <mode> <a> <b>`, or `clipcompare grid <clip>...`."""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path

from . import __version__, fonts, manifest, media, page
from . import prompts as prompts_mod
from .captions import Fonts as CaptionFonts
from .filters import AUDIO_CHOICES, FITS, IMAGE_EXTENSIONS, LENGTHS, Plan
from .tokens import DS_ACCENT_700, DS_EGGSHELL, DS_FONT_BODY, DS_FONT_DISPLAY, DS_FONT_SANS
from .modes import grid as grid_mode
from .modes import pip as pip_mode
from .modes import sidebyside, wipe as wipe_mode
from .probe import ClipInfo, ProbeError, lead_in_black, probe, require_binaries

FONT_NAME = "TikTokSans-Medium.ttf"
MODES = ("side", "wipe", "pip", "grid")
MODE_ALIASES = {"pict": "pip", "mosaic": "grid"}


def _bundled_font(stack: contextlib.ExitStack) -> Path:
    ref = resources.files("clipcompare").joinpath("assets", FONT_NAME)
    return Path(stack.enter_context(resources.as_file(ref)))


def _default_fonts(stack: contextlib.ExitStack) -> tuple[Path, Path]:
    """(label font, title font): the design system's Telka and Telka Extended
    when installed, else the bundled TikTok Sans for both."""
    sans = fonts.find_installed(DS_FONT_SANS)
    display = fonts.find_installed(DS_FONT_DISPLAY)
    label = sans or _bundled_font(stack)
    return label, display or label


def _caption_fonts(stack: contextlib.ExitStack, label_font: Path, captions) -> CaptionFonts | None:
    """Prompts: body text in Telka Regular (the design system's copy weight)
    when installed, [tags] in the label font. A caption with CJK uses the
    system CJK face for both."""
    texts = [text for text in captions if text]
    if not texts:
        return None
    (cjk,), _ = fonts.resolve([" ".join(texts)], label_font)
    if cjk != label_font:
        return CaptionFonts(body=cjk, tag=cjk)
    return CaptionFonts(body=fonts.find_installed(DS_FONT_BODY) or label_font, tag=label_font)


def _label_from_path(path: Path | str) -> str:
    return re.sub(r"[\s_-]+", " ", Path(path).stem).strip().upper()[:24]


def _labels(args: argparse.Namespace, paths: list[Path]) -> tuple[str, ...] | None:
    if args.no_labels:
        return None
    if not args.labels and getattr(args, "_manifest_labels", None):
        return args._manifest_labels
    if args.labels:
        parts = [part.strip() for part in args.labels.split(",")]
        group = getattr(args, "group", 0)
        if group and len(parts) == group:
            parts *= len(paths) // group  # the same labels for every --group run
        if len(parts) != len(paths):
            raise SystemExit(
                f"clipcompare: --labels needs {len(paths)} comma-separated values, one per clip, "
                'e.g. "BEFORE,AFTER"'
            )
        return tuple(parts)
    label_a, label_b = getattr(args, "label_a", None), getattr(args, "label_b", None)
    if label_a or label_b:
        return (
            label_a or _label_from_path(paths[0]),
            label_b or _label_from_path(paths[1]),
        )
    return tuple(_label_from_path(path) for path in paths)


def _default_out(mode: str, paths: list[Path], still: bool = False) -> Path:
    slug = lambda p: re.sub(r"[^A-Za-z0-9._-]", "-", p.stem)  # noqa: E731
    ext = ".png" if still else ".mp4"
    if mode == "grid":
        return Path(f"{slug(paths[0])}-grid{len(paths)}{ext}")
    suffix = "" if mode == "side" else f"-{mode}"
    return Path(f"{slug(paths[0])}-vs-{slug(paths[1])}{suffix}{ext}")


def _check_images(mode: str, args: argparse.Namespace, clips: list[ClipInfo], out: Path | None) -> bool:
    """Whether the result is a still picture (every clip an image), after
    checking the output extension and mode can make what was asked for."""
    images = [clip for clip in clips if clip.is_image]
    if images and getattr(args, "html", None) is not None:
        raise SystemExit("clipcompare: --html plays videos and audio; images are not supported there")
    if images and mode in ("wipe", "pip"):
        raise SystemExit(f"clipcompare: {mode} needs two videos; use side or grid for images")
    still = len(images) == len(clips)
    image_out = out is not None and out.suffix.lower() in IMAGE_EXTENSIONS
    if still and out is not None and not image_out:
        raise SystemExit(
            f"clipcompare: every clip is an image, so the result is a picture: "
            f"name it {out.with_suffix('.png').name} (or .jpg / .webp)"
        )
    if image_out and not still:
        raise SystemExit(f"clipcompare: {out.name} is an image, but some clips are video or audio; use .mp4")
    if still and getattr(args, "group", 0):
        raise SystemExit("clipcompare: --group joins videos; run once per group to compare images")
    return still


def _add_render_arguments(common: argparse._ArgumentGroup) -> None:
    common.add_argument(
        "--fit", choices=FITS, default="cover",
        help="cover (default, crop to fill) or contain (letterbox, keeps the whole frame)",
    )
    common.add_argument("--fps", metavar="N", help="force output frame rate")
    common.add_argument("--crf", type=int, default=18, help="x264 quality, default 18")
    common.add_argument("--preset", default="medium", help="x264 preset, default medium")
    common.add_argument(
        "-n", "--dry-run", action="store_true",
        help="print the ffmpeg command instead of running it",
    )
    common.add_argument("--open", action="store_true", help="open the result when done (macOS)")


def _add_shared_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("clip_a", metavar="CLIP-A", type=Path, help="first clip")
    parser.add_argument("clip_b", metavar="CLIP-B", type=Path, help="second clip")
    parser.add_argument("-o", "--out", type=Path, help="output file")

    names = parser.add_argument_group("labels")
    names.add_argument(
        "-l", "--labels", metavar='"A,B"',
        help="both labels at once (default: the two filenames, uppercased)",
    )
    names.add_argument("-A", "--label-a", metavar="TEXT", help="label for the first clip")
    names.add_argument("-B", "--label-b", metavar="TEXT", help="label for the second clip")
    names.add_argument("--no-labels", action="store_true", help="draw no labels")
    names.add_argument("--font", type=Path, help="label and title font (default: Telka from the design system if installed, else bundled TikTok Sans)")
    names.add_argument("--color-a", default=DS_EGGSHELL, metavar="HEX", help="first label colour (default: --ds-eggshell)")
    names.add_argument("--color-b", default=DS_ACCENT_700, metavar="HEX", help="second label colour (default: --ds-accent-700)")

    common = parser.add_argument_group("common")
    common.add_argument(
        "--audio", choices=AUDIO_CHOICES, default="b",
        help="which clip's audio to keep, default b",
    )
    _add_render_arguments(common)


def _add_grid_parser(subparsers) -> None:
    grid = subparsers.add_parser(
        "grid", aliases=["mosaic"],
        help="any number of clips tiled N x M, all at once or one at a time",
        description=(
            "Any number of clips tiled N x M in reading order (left to right, then down), "
            "all playing at once or one at a time."
        ),
    )
    grid.add_argument("clips", metavar="CLIP", nargs="*", help="two or more clips (files or http(s) URLs), in reading order")
    grid.add_argument("-o", "--out", type=Path, help="output file")
    grid.add_argument(
        "--header", action="append", default=[], metavar='"NAME: VALUE"',
        help='an HTTP header for fetching a --manifest URL, e.g. "Authorization: Bearer ..."; repeatable',
    )
    grid.add_argument(
        "--copy-media", action="store_true",
        help="with --html, download URL clips next to the page (into media/) so it works offline",
    )
    grid.add_argument(
        "--html", type=Path, metavar="OUT.html",
        help="also (or, without -o and a manifest \"out\", only) write a self-contained web page: "
             "one player per group that switches versions at the same point in the script",
    )
    grid.add_argument(
        "--manifest", metavar="FILE|URL|-",
        help='JSON naming the clips instead: {"titles": [...], "out": ..., "clips": '
             '[{"file", "label", "prompt", "baseline", "segments"}, ...]}; paths are looked up '
             "next to the file, then one folder up, then here. Implies --sequential and --group "
             "from the title count; flags given here still win",
    )

    names = grid.add_argument_group("labels")
    names.add_argument(
        "-l", "--labels", metavar='"A,B,..."',
        help="one label per clip, comma-separated (default: the filenames, uppercased)",
    )
    names.add_argument("--no-labels", action="store_true", help="draw no labels")
    names.add_argument("--font", type=Path, help="label and title font (default: Telka from the design system if installed, else bundled TikTok Sans)")
    names.add_argument("--color", dest="color_a", default=DS_EGGSHELL, metavar="HEX", help="label colour (default: --ds-eggshell)")

    common = grid.add_argument_group("common")
    common.add_argument(
        "--audio", default="auto", metavar="auto|none|mix|N",
        help="auto (default): the playing clip's sound with --sequential, otherwise clip 1's; "
             "none; mix (all at once); or a clip number",
    )
    _add_render_arguments(common)

    group = grid.add_argument_group("grid")
    group.add_argument("--cols", type=int, default=0, metavar="N", help="columns (default: auto, aiming the video at 16:9)")
    group.add_argument("--rows", type=int, default=0, metavar="M", help="rows (default: auto)")
    group.add_argument(
        "--panel", type=int, default=0, metavar="PX",
        help="short edge of each tile (default: auto, output within 3840 px, tiles at most 1080)",
    )
    group.add_argument(
        "--gap", type=int, default=4, metavar="PX",
        help="black gap between tiles at 1080p, default 4, 0 for none",
    )
    group.add_argument(
        "--length", choices=LENGTHS, default="shortest",
        help="shortest (default) or longest (shorter clips freeze on their last frame)",
    )
    group.add_argument(
        "--sequential", action="store_true",
        help="play the clips one at a time in reading order: waiting tiles hold a frame, the "
             "playing tile is outlined, and the sound follows it (--length is ignored)",
    )
    group.add_argument(
        "--pause", type=float, default=0.5, metavar="SEC",
        help="with --sequential, a still, silent moment between turns, default 0.5, 0 for none",
    )
    group.add_argument(
        "--highlight", dest="color_b", default=DS_ACCENT_700, metavar="HEX",
        help="outline colour of the playing tile with --sequential (default: --ds-accent-700)",
    )
    group.add_argument(
        "--head", type=float, metavar="SEC",
        help="use only the first SEC seconds of every clip (at once, or each turn with --sequential)",
    )
    group.add_argument(
        "--title", metavar="TEXT",
        help="a header above the tiles; with --group, one per run, comma-separated",
    )
    group.add_argument(
        "--captions", type=Path, metavar="FILE",
        help="JSON list of prompt strings, one per clip (or a --manifest file): the playing tile "
             "shows its prompt, every [tag] in the accent colour; long text shrinks, then is cut with …",
    )
    group.add_argument(
        "--group", type=int, default=0, metavar="N",
        help="cut the clips into runs of N (e.g. 2 for pairs), one grid each, played one after "
             "another; -l may then give just N labels, reused for every run",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipcompare",
        description="Comparison videos from two or more clips, powered by ffmpeg.",
        epilog=(
            "examples:\n"
            "  clipcompare side input.mp4 output.mp4\n"
            '  clipcompare side a.mp4 b.mp4 -l "ORIGINAL,EDITED" --panel 2160\n'
            "  clipcompare wipe before.mp4 after.mp4 --direction lr --pace early\n"
            "  clipcompare pip  before.mp4 after.mp4 --corner tr\n"
            "  clipcompare grid take-*.mp4 --sequential --head 8\n"
            "  clipcompare grid v3.mp3 v4.mp3 --sequential   # audio becomes a waveform"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"clipcompare {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="MODE")

    side = subparsers.add_parser(
        "side",
        help="both clips on screen at once, left-right or top-bottom",
        description="Both clips on screen at once, left-right or top-bottom.",
    )
    _add_shared_arguments(side)
    group = side.add_argument_group("side-by-side")
    group.add_argument(
        "--layout", choices=sidebyside.LAYOUTS, default="auto",
        help="auto (default: portrait/square -> lr, landscape -> tb), lr, or tb",
    )
    group.add_argument(
        "--panel", type=int, default=0, metavar="PX",
        help="short edge of each panel, default 1080 (two images: their own size, at most 1080; "
             "use 2160 for 4K)",
    )
    group.add_argument(
        "--length", choices=LENGTHS, default="shortest",
        help="shortest (default) or longest (freezes the shorter clip's last frame)",
    )
    group.add_argument(
        "--divider", type=int, default=4, metavar="PX",
        help="separator line thickness, default 4, 0 to disable",
    )
    group.add_argument(
        "--sequential", action="store_true",
        help="play A through, then B; the idle side holds its frame and the sound "
             "follows whichever side is playing (--audio none mutes it; --length is ignored)",
    )
    group.add_argument(
        "--head", type=float, metavar="SEC",
        help="use only the first SEC seconds of each clip (both at once, or each turn with --sequential)",
    )

    wipe = subparsers.add_parser(
        "wipe",
        help="an eased line sweeps across, revealing clip B over clip A in place",
        description=(
            "An eased line sweeps across, revealing clip B over clip A in place. "
            "Both clips should share framing and timing."
        ),
    )
    _add_shared_arguments(wipe)
    group = wipe.add_argument_group("wipe")
    group.add_argument(
        "--direction", choices=wipe_mode.DIRECTIONS, default="lr",
        help="sweep direction, default lr (left to right)",
    )
    group.add_argument(
        "--pace", choices=wipe_mode.PACES, default="early", metavar="PACE",
        help="where the sweep fires: early (default), balanced, late "
             "(snappy is accepted as an alias of early)",
    )
    group.add_argument(
        "--wipe-start", metavar="SEC|N%%",
        help="override the sweep start, e.g. 0.9 or 30%%",
    )
    group.add_argument(
        "--wipe-dur", type=float, default=wipe_mode.DEFAULT_WIPE_DUR, metavar="SEC",
        help=f"sweep duration, default {wipe_mode.DEFAULT_WIPE_DUR}",
    )
    group.add_argument(
        "--stroke", type=int, default=3, metavar="PX",
        help="white line thickness at 1080p, default 3",
    )
    group.add_argument(
        "--panel", type=int, default=0, metavar="PX",
        help="short edge of the output, default 0 (keep clip A's own size)",
    )
    group.add_argument("--trim-to", type=float, metavar="SEC", help="trim the output to N seconds")

    pip = subparsers.add_parser(
        "pip", aliases=["pict"],
        help="one clip full-frame, the other as a rounded corner inset",
        description="One clip full-frame, the other as a rounded corner inset.",
    )
    _add_shared_arguments(pip)
    group = pip.add_argument_group("picture-in-picture")
    group.add_argument(
        "--inset", choices=pip_mode.INSET_CHOICES, default="a",
        help="which clip becomes the small window, default a",
    )
    group.add_argument(
        "--corner", choices=pip_mode.CORNERS, default="tr",
        help="which corner the inset sits in, default tr",
    )
    group.add_argument(
        "--inset-scale", type=float, default=0.30, metavar="F",
        help="inset size as a fraction of the main clip's width, default 0.30",
    )
    group.add_argument(
        "--margin", type=float, default=0.025, metavar="F",
        help="inset distance from the edge, as a fraction of width, default 0.025",
    )
    group.add_argument(
        "--radius", type=int, default=22, metavar="PX",
        help="corner radius at 1080p, default 22",
    )
    group.add_argument(
        "--stroke", type=int, default=3, metavar="PX",
        help="border thickness at 1080p, default 3",
    )
    group.add_argument("--border", default="white", help="border colour, default white")
    group.add_argument(
        "--panel", type=int, default=0, metavar="PX",
        help="short edge of the output, default 0 (keep the main clip's own size)",
    )
    group.add_argument(
        "--length", choices=LENGTHS, default="shortest",
        help="shortest (default) or longest (freezes the shorter clip's last frame)",
    )

    _add_grid_parser(subparsers)
    return parser


def _shared_kwargs(args: argparse.Namespace, out: Path, label_fonts) -> dict:
    return {
        "out": out,
        "labels": args._labels,
        "fonts": label_fonts,
        "audio": args.audio,
        "fit": args.fit,
        "color_a": args.color_a,
        "color_b": args.color_b,
        "fps": args.fps,
        "crf": args.crf,
        "preset": args.preset,
        "head": getattr(args, "head", None),
    }


def _hold(clip: ClipInfo) -> float:
    """Where a clip's picture starts: past any black lead-in. Audio and images have none."""
    return 0.0 if clip.is_audio or clip.is_image else lead_in_black(clip.path)


def _titles(args: argparse.Namespace, count: int) -> tuple[str | None, ...]:
    """One title per --group run (or one for the whole grid); None draws none."""
    runs = count // args.group if getattr(args, "group", 0) else 1
    if not getattr(args, "title", None):
        return (None,) * runs
    parts = [part.strip() for part in args.title.split(",")] if runs > 1 else [args.title.strip()]
    if len(parts) != runs:
        raise SystemExit(f"clipcompare: --title needs {runs} comma-separated values, one per group")
    return tuple(parts)


def _make_plan(mode: str, args, clips: list[ClipInfo], out, label_fonts, label_dir) -> Plan:
    shared = _shared_kwargs(args, out, label_fonts)
    if mode == "grid":
        opts = grid_mode.Options(
            **shared, cols=args.cols, rows=args.rows, panel=args.panel, gap=args.gap,
            length=args.length, sequential=args.sequential, pause=args.pause if args.sequential else 0.0,
            holds=tuple(_hold(clip) for clip in clips) if args.sequential and not args._still else (),
            title_font=args._title_font,
            prompts=args._prompts, caption_fonts=args._caption_fonts,
        )
        if args.group:
            runs = [clips[start:start + args.group] for start in range(0, len(clips), args.group)]
            return grid_mode.build_groups(runs, opts, args._titles, label_dir)
        opts.title = args._titles[0]
        return grid_mode.build(clips, opts, label_dir)
    a, b = clips
    if mode == "side":
        opts = sidebyside.Options(
            **shared, layout=args.layout, panel=args.panel,
            length=args.length, divider=args.divider, sequential=args.sequential,
            hold_b_at=_hold(b) if args.sequential and not args._still else 0.0,
        )
        return sidebyside.build(a, b, opts, label_dir)
    if mode == "wipe":
        opts = wipe_mode.Options(
            **shared, direction=args.direction, pace=args.pace, panel=args.panel,
            wipe_start=args.wipe_start, wipe_dur=args.wipe_dur,
            stroke=args.stroke, trim_to=args.trim_to,
        )
        return wipe_mode.build(a, b, opts, label_dir)
    opts = pip_mode.Options(
        **shared, inset=args.inset, corner=args.corner,
        inset_scale=args.inset_scale, margin=args.margin, radius=args.radius,
        stroke=args.stroke, border=args.border, panel=args.panel, length=args.length,
    )
    return pip_mode.build(a, b, opts, label_dir)


def _summary(plan: Plan, clips: list[ClipInfo]) -> str:
    sources = (
        " + ".join("audio" if clip.is_audio else f"{clip.width}x{clip.height}" for clip in clips)
        if len(clips) <= 3
        else f"{len(clips)} clips"
    )
    return (
        f"[{plan.mode}] {sources}"
        f"  ->  {plan.out_w}x{plan.out_h} @ {plan.fps_value:.2f}fps"
        f"  ({plan.detail}, audio={plan.audio})"
    )


def _check_grid(args: argparse.Namespace, count: int) -> None:
    if count < 2:
        raise SystemExit("clipcompare: grid needs at least two clips")
    if args.cols < 0 or args.rows < 0:
        raise SystemExit("clipcompare: --cols and --rows cannot be negative")
    if args.cols and args.rows and args.cols * args.rows < count:
        raise SystemExit(
            f"clipcompare: a {args.cols}x{args.rows} grid holds {args.cols * args.rows} clips, not {count}"
        )
    if args.gap < 0:
        raise SystemExit("clipcompare: --gap cannot be negative")
    if args.group:
        if args.group < 2 or count % args.group or count == args.group:
            raise SystemExit(
                f"clipcompare: --group {args.group} needs at least two runs of two or more clips, "
                f"and {count} clips do not split into runs of {args.group}"
            )
    if args.pause < 0:
        raise SystemExit("clipcompare: --pause cannot be negative")
    audio = args.audio
    if audio not in grid_mode.AUDIO_MODES and not (audio.isdigit() and 1 <= int(audio) <= count):
        raise SystemExit(f"clipcompare: --audio takes auto, none, mix or a clip number 1-{count}")


def _apply_manifest(args: argparse.Namespace) -> None:
    """Fill grid arguments from --manifest (anything given on the command line
    wins) and read --captions; sets args._captions."""
    args._captions = ()
    args._baselines = ()
    args._segments = ()
    args._manifest_labels = None
    try:
        if args.manifest is not None:
            if args.clips:
                raise SystemExit("clipcompare: give clips either on the command line or in --manifest, not both")
            try:
                headers = dict(media.parse_header(header) for header in args.header)
            except ValueError as exc:
                raise SystemExit(f"clipcompare: --header: {exc}") from exc
            spec = manifest.read(args.manifest, headers)
            args.clips = list(spec.clips)
            args._manifest_labels = spec.labels
            args._captions = spec.captions if any(spec.captions) else ()
            args._baselines = spec.baselines
            args._segments = spec.segments
            args.sequential = args.sequential or spec.sequential
            if spec.titles and not args.title:
                args.title = ",".join(spec.titles) if len(spec.titles) > 1 else spec.titles[0]
            # --html alone writes just the page, unless the manifest names a video.
            args.out = args.out or spec.out
            args.group = args.group or spec.group
        if args.captions is not None:
            args._captions = manifest.read_captions(args.captions, len(args.clips))
            args._baselines = args._segments = ()
    except manifest.ManifestError as exc:
        raise SystemExit(f"clipcompare: {exc}") from exc


def _run(mode: str, args: argparse.Namespace) -> int:
    require_binaries()
    if mode == "grid":
        _apply_manifest(args)
    sources: list[Path | str] = (
        [clip if media.is_url(str(clip)) else Path(clip) for clip in args.clips]
        if mode == "grid" else [args.clip_a, args.clip_b]
    )
    # Downloaded clips keep their URL's filename for default labels.
    names = [Path(media.filename(src).split("-", 1)[1]) if isinstance(src, str) else src for src in sources]
    paths = []
    for source in sources:
        if isinstance(source, str):
            print(f"[{mode}] fetching {source}", file=sys.stderr)
            try:
                source = media.download(source)
            except media.MediaError as exc:
                raise SystemExit(f"clipcompare: {exc}") from exc
        paths.append(source)
    for clip in paths:
        if not clip.is_file():
            raise SystemExit(f"clipcompare: clip not found: {clip}")
    if getattr(args, "panel", 0) and args.panel < 16:
        raise SystemExit("clipcompare: --panel must be at least 16")
    if getattr(args, "divider", 0) < 0:
        raise SystemExit("clipcompare: --divider cannot be negative")
    if getattr(args, "head", None) is not None and args.head <= 0:
        raise SystemExit("clipcompare: --head must be a positive number of seconds")
    if mode == "grid":
        _check_grid(args, len(paths))

    clips = [probe(path) for path in paths]
    args._still = _check_images(mode, args, clips, args.out)
    if mode == "grid":
        args._prompts = (
            prompts_mod.prepare(args._captions, args._baselines, args._segments, args.group)
            if args._captions else ()
        )
        if args.html is not None:
            labels = _labels(args, names) or tuple(_label_from_path(path) for path in names)
            page.write(args.html, page.build(
                clips, labels, args._prompts, _titles(args, len(paths)), args.group, args.html,
                sources=_page_sources(sources, paths, args.html, args.copy_media),
            ))
            print(f"[grid] page: {args.html}")
            if args.out is None:
                return 0

    out = args.out or _default_out(mode, names, args._still)
    out.parent.mkdir(parents=True, exist_ok=True)
    args._labels = _labels(args, names)
    args._titles = _titles(args, len(paths))
    titled = [title for title in args._titles if title]

    with contextlib.ExitStack() as stack:
        if args.font is not None:
            if not args.font.is_file():
                raise SystemExit(f"clipcompare: font not found: {args.font}")
            label_fonts = (args.font,) * len(paths)
            args._title_font = args.font
            args._caption_fonts = CaptionFonts(body=args.font, tag=args.font)
        else:
            # The bundled font has no CJK glyphs — a Chinese label (which a
            # Chinese filename gives you by default) needs a system face.
            # Titles share one font, picked as if they were one label.
            label_font, title_font = _default_fonts(stack)
            labels = list(args._labels or ())
            label_fonts, unserved = fonts.resolve(labels, label_font) if labels else ((), False)
            label_fonts = label_fonts or None
            args._title_font = None
            if titled:
                (args._title_font,), title_unserved = fonts.resolve([" ".join(titled)], title_font)
                unserved = unserved or title_unserved
            args._caption_fonts = _caption_fonts(stack, label_font, getattr(args, "_captions", ()) or ())
            if unserved:
                print(
                    "clipcompare: no CJK font found — non-Latin labels will render as "
                    "boxes; pass --font /path/to/font.ttf",
                    file=sys.stderr,
                )

        # --dry-run prints commands pointing at the label files and the pip
        # mask, so it keeps them; a normal run cleans up once ffmpeg is done.
        work_dir = Path(tempfile.mkdtemp(prefix="clipcompare-"))
        if not args.dry_run:
            stack.callback(lambda: _remove_dir(work_dir))

        plan = _make_plan(mode, args, clips, out, label_fonts, work_dir)

        if args.dry_run:
            for command in [*plan.pre_commands, plan.command]:
                print(shlex.join(command))
            print(f"# working files kept at {work_dir}", file=sys.stderr)
            return 0

        print(_summary(plan, clips))
        for command in plan.pre_commands:
            result = subprocess.run(command)
            if result.returncode != 0:
                return result.returncode
        result = subprocess.run(plan.command)
        if result.returncode != 0:
            return result.returncode

    written = probe(out)
    size_mb = out.stat().st_size / 1_000_000
    shape = f"{written.width}x{written.height}" if args._still else f"{written.duration:.1f}s"
    print(f"[{plan.mode}] done: {out}  ({shape}, {size_mb:.1f} MB)")
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out)], check=False)
    return 0


def _page_sources(sources: list, paths: list[Path], html: Path, copy: bool) -> list[str]:
    """What the page's players load: a URL as is (or, with --copy-media, a
    copy next to the page), a local file by its path relative to the page."""
    out = []
    for source, path in zip(sources, paths):
        if isinstance(source, str) and not copy:
            out.append(source)
            continue
        if isinstance(source, str):
            path = media.download(source, html.parent / "media")
        out.append(Path(os.path.relpath(path.resolve(), html.parent.resolve())).as_posix())
    return out


def _remove_dir(path: Path) -> None:
    # --group renders each run in a subfolder, so clear the whole tree.
    shutil.rmtree(path, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # `clipcompare a.mp4 b.mp4` is the shape people reach for first — point at a
    # mode rather than letting argparse say "invalid choice".
    known = set(MODES) | set(MODE_ALIASES)
    if argv and argv[0] not in known and not argv[0].startswith("-"):
        if Path(argv[0]).is_file():
            mode = "side" if len(argv) <= 2 or not Path(argv[2]).is_file() else "grid"
            hint = shlex.join(["clipcompare", mode, *argv])
            print(
                f"clipcompare: pick a mode ({', '.join(MODES)}). Did you mean:\n  {hint}",
                file=sys.stderr,
            )
            return 2

    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    mode = MODE_ALIASES.get(args.command, args.command)
    try:
        return _run(mode, args)
    except ProbeError as exc:
        raise SystemExit(f"clipcompare: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
