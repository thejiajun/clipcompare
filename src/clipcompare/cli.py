"""Command line entry point: `clipcompare <mode> <a> <b>`."""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path

from . import __version__, fonts
from .filters import AUDIO_CHOICES, FITS, LENGTHS, Plan
from .modes import pip as pip_mode
from .modes import sidebyside, wipe as wipe_mode
from .probe import ClipInfo, ProbeError, probe, require_binaries

FONT_NAME = "TikTokSans-Medium.ttf"
MODES = ("side", "wipe", "pip")
MODE_ALIASES = {"sbs": "side", "render": "side", "pict": "pip"}


def _bundled_font(stack: contextlib.ExitStack) -> Path:
    ref = resources.files("clipcompare").joinpath("assets", FONT_NAME)
    return Path(stack.enter_context(resources.as_file(ref)))


def _label_from_path(path: Path) -> str:
    return re.sub(r"[\s_-]+", " ", path.stem).strip().upper()[:24]


def _labels(args: argparse.Namespace) -> tuple[str, str] | None:
    if args.no_labels:
        return None
    if args.labels:
        parts = args.labels.split(",")
        if len(parts) != 2:
            raise SystemExit(
                'clipcompare: --labels needs two comma-separated values, e.g. "BEFORE,AFTER"'
            )
        return parts[0].strip(), parts[1].strip()
    if args.label_a or args.label_b:
        return (
            args.label_a or _label_from_path(args.clip_a),
            args.label_b or _label_from_path(args.clip_b),
        )
    return _label_from_path(args.clip_a), _label_from_path(args.clip_b)


def _default_out(mode: str, a: Path, b: Path) -> Path:
    slug = lambda p: re.sub(r"[^A-Za-z0-9._-]", "-", p.stem)  # noqa: E731
    suffix = "" if mode == "side" else f"-{mode}"
    return Path(f"{slug(a)}-vs-{slug(b)}{suffix}.mp4")


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
    names.add_argument("--font", type=Path, help="label font (default: bundled TikTok Sans Medium)")
    names.add_argument("--color-a", default="#ffffff", metavar="HEX", help="first label colour")
    names.add_argument("--color-b", default="#cfc3ff", metavar="HEX", help="second label colour")

    common = parser.add_argument_group("common")
    common.add_argument(
        "--fit", choices=FITS, default="cover",
        help="cover (default, crop to fill) or contain (letterbox, keeps the whole frame)",
    )
    common.add_argument(
        "--audio", choices=AUDIO_CHOICES, default="b",
        help="which clip's audio to keep, default b",
    )
    common.add_argument("--fps", metavar="N", help="force output frame rate")
    common.add_argument("--crf", type=int, default=18, help="x264 quality, default 18")
    common.add_argument("--preset", default="medium", help="x264 preset, default medium")
    common.add_argument(
        "-n", "--dry-run", action="store_true",
        help="print the ffmpeg command instead of running it",
    )
    common.add_argument("--open", action="store_true", help="open the result when done (macOS)")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipcompare",
        description="Comparison videos from two clips, powered by ffmpeg.",
        epilog=(
            "examples:\n"
            "  clipcompare side input.mp4 output.mp4\n"
            '  clipcompare side a.mp4 b.mp4 -l "ORIGINAL,EDITED" --panel 2160\n'
            "  clipcompare wipe before.mp4 after.mp4 --direction lr --pace early\n"
            "  clipcompare pip  before.mp4 after.mp4 --corner tr\n"
            "\n`sbs` is a shorter alias for this command, and `sbs` also works\n"
            "in place of the `side` mode."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"clipcompare {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="MODE")

    side = subparsers.add_parser(
        "side", aliases=["sbs", "render"],
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
        "--panel", type=int, default=1080, metavar="PX",
        help="short edge of each panel, default 1080 (use 2160 for 4K)",
    )
    group.add_argument(
        "--length", choices=LENGTHS, default="shortest",
        help="shortest (default) or longest (freezes the shorter clip's last frame)",
    )
    group.add_argument(
        "--divider", type=int, default=4, metavar="PX",
        help="separator line thickness, default 4, 0 to disable",
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
        "--pace", choices=wipe_mode.PACES, default="early",
        help="where the sweep fires, as a fraction of the clip, default early",
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
    }


def _make_plan(mode: str, args, a, b, out, label_fonts, label_dir) -> Plan:
    shared = _shared_kwargs(args, out, label_fonts)
    if mode == "side":
        opts = sidebyside.Options(
            **shared, layout=args.layout, panel=args.panel,
            length=args.length, divider=args.divider,
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


def _summary(plan: Plan, a: ClipInfo, b: ClipInfo) -> str:
    return (
        f"[{plan.mode}] {a.width}x{a.height} + {b.width}x{b.height}"
        f"  ->  {plan.out_w}x{plan.out_h} @ {plan.fps_value:.2f}fps"
        f"  ({plan.detail}, audio={plan.audio})"
    )


def _run(mode: str, args: argparse.Namespace) -> int:
    require_binaries()
    for clip in (args.clip_a, args.clip_b):
        if not clip.is_file():
            raise SystemExit(f"clipcompare: clip not found: {clip}")
    if getattr(args, "panel", 0) and args.panel < 16:
        raise SystemExit("clipcompare: --panel must be at least 16")
    if getattr(args, "divider", 0) < 0:
        raise SystemExit("clipcompare: --divider cannot be negative")

    a = probe(args.clip_a)
    b = probe(args.clip_b)

    out = args.out or _default_out(mode, args.clip_a, args.clip_b)
    out.parent.mkdir(parents=True, exist_ok=True)
    args._labels = _labels(args)

    with contextlib.ExitStack() as stack:
        if args.font is not None:
            if not args.font.is_file():
                raise SystemExit(f"clipcompare: font not found: {args.font}")
            label_fonts = (args.font, args.font)
        elif args._labels is None:
            label_fonts = None
        else:
            # The bundled font has no CJK glyphs — a Chinese label (which a
            # Chinese filename gives you by default) needs a system face.
            label_fonts, unserved = fonts.resolve(args._labels, _bundled_font(stack))
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

        plan = _make_plan(mode, args, a, b, out, label_fonts, work_dir)

        if args.dry_run:
            for command in [*plan.pre_commands, plan.command]:
                print(shlex.join(command))
            print(f"# working files kept at {work_dir}", file=sys.stderr)
            return 0

        print(_summary(plan, a, b))
        for command in plan.pre_commands:
            result = subprocess.run(command)
            if result.returncode != 0:
                return result.returncode
        result = subprocess.run(plan.command)
        if result.returncode != 0:
            return result.returncode

    written = probe(out)
    size_mb = out.stat().st_size / 1_000_000
    print(f"[{plan.mode}] done: {out}  ({written.duration:.1f}s, {size_mb:.1f} MB)")
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out)], check=False)
    return 0


def _remove_dir(path: Path) -> None:
    for child in path.glob("*"):
        with contextlib.suppress(OSError):
            child.unlink()
    with contextlib.suppress(OSError):
        os.rmdir(path)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # `clipcompare a.mp4 b.mp4` is the shape people reach for first — point at a
    # mode rather than letting argparse say "invalid choice".
    known = set(MODES) | set(MODE_ALIASES)
    if argv and argv[0] not in known and not argv[0].startswith("-"):
        if Path(argv[0]).is_file():
            hint = shlex.join(["clipcompare", "side", *argv])
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
