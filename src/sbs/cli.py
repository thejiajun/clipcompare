"""Command line entry point: `sbs render <a> <b>`."""

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

from . import __version__
from .probe import ClipInfo, ProbeError, probe, require_binaries
from .render import AUDIO_CHOICES, FITS, LAYOUTS, LENGTHS, Options, build

FONT_NAME = "SpaceMono-Regular.ttf"
SUBCOMMANDS = ("render",)


def _bundled_font(stack: contextlib.ExitStack) -> Path:
    ref = resources.files("sbs").joinpath("assets", FONT_NAME)
    return Path(stack.enter_context(resources.as_file(ref)))


def _label_from_path(path: Path) -> str:
    label = re.sub(r"[\s_-]+", " ", path.stem).strip().upper()
    return label[:24]


def _labels(args: argparse.Namespace, a: Path, b: Path) -> tuple[str, str] | None:
    if args.no_labels:
        return None
    if args.labels:
        parts = args.labels.split(",")
        if len(parts) != 2:
            raise SystemExit('sbs: --labels needs two comma-separated values, e.g. "BEFORE,AFTER"')
        return parts[0].strip(), parts[1].strip()
    return _label_from_path(a), _label_from_path(b)


def _default_out(a: Path, b: Path) -> Path:
    slug = lambda p: re.sub(r"[^A-Za-z0-9._-]", "-", p.stem)  # noqa: E731
    return Path(f"{slug(a)}-vs-{slug(b)}.mp4")


def _add_render_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("clip_a", metavar="CLIP-A", type=Path, help="first clip (left / top)")
    parser.add_argument("clip_b", metavar="CLIP-B", type=Path, help="second clip (right / bottom)")
    parser.add_argument("-o", "--out", type=Path, help="output file (default: <a>-vs-<b>.mp4)")
    parser.add_argument(
        "-l", "--labels", metavar='"A,B"',
        help="label text pair (default: the two filenames, uppercased)",
    )
    parser.add_argument("--no-labels", action="store_true", help="draw no labels")
    parser.add_argument(
        "--layout", choices=LAYOUTS, default="auto",
        help="auto (default: portrait/square -> lr, landscape -> tb), lr, or tb",
    )
    parser.add_argument(
        "--panel", type=int, default=1080, metavar="PX",
        help="short edge of each panel, default 1080 (use 2160 for 4K)",
    )
    parser.add_argument(
        "--fit", choices=FITS, default="cover",
        help="cover (default, crop to fill) or contain (letterbox, keeps the whole frame)",
    )
    parser.add_argument(
        "--length", choices=LENGTHS, default="shortest",
        help="shortest (default) or longest (freezes the shorter clip's last frame)",
    )
    parser.add_argument(
        "--audio", choices=AUDIO_CHOICES, default="b",
        help="which clip's audio to keep, default b",
    )
    parser.add_argument(
        "--divider", type=int, default=4, metavar="PX",
        help="separator line thickness, default 4, 0 to disable",
    )
    parser.add_argument("--font", type=Path, help="label font (default: bundled Space Mono)")
    parser.add_argument("--color-a", default="#ffffff", metavar="HEX", help="left/top label colour")
    parser.add_argument(
        "--color-b", default="#cfc3ff", metavar="HEX", help="right/bottom label colour"
    )
    parser.add_argument("--fps", metavar="N", help="force output frame rate")
    parser.add_argument("--crf", type=int, default=18, help="x264 quality, default 18")
    parser.add_argument("--preset", default="medium", help="x264 preset, default medium")
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="print the ffmpeg command instead of running it",
    )
    parser.add_argument("--open", action="store_true", help="open the result when done (macOS)")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sbs",
        description="Side-by-side comparison videos, powered by ffmpeg.",
        epilog=(
            "examples:\n"
            "  sbs render input.mp4 output.mp4\n"
            '  sbs render orig.mp4 vfx.mp4 -l "ORIGINAL,EDITED" --panel 2160 --audio both\n'
            "  sbs render a.mov b.mov --fit contain --length longest -o cmp.mp4"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"sbs {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    render = subparsers.add_parser(
        "render",
        help="stack two clips into one comparison video",
        description="Stack two clips into one comparison video.",
    )
    _add_render_arguments(render)
    return parser


def _summary(plan, a: ClipInfo, b: ClipInfo, opts: Options) -> str:
    return (
        f"[sbs] {plan.layout}  {a.width}x{a.height} + {b.width}x{b.height}"
        f"  ->  {plan.out_w}x{plan.out_h} @ {plan.fps_value:.2f}fps"
        f"  ({opts.fit}, {opts.length}, audio={plan.audio})"
    )


def _run_render(args: argparse.Namespace) -> int:
    require_binaries()
    for clip in (args.clip_a, args.clip_b):
        if not clip.is_file():
            raise SystemExit(f"sbs: clip not found: {clip}")
    if args.panel < 16:
        raise SystemExit("sbs: --panel must be at least 16")
    if args.divider < 0:
        raise SystemExit("sbs: --divider cannot be negative")

    a = probe(args.clip_a)
    b = probe(args.clip_b)

    out = args.out or _default_out(args.clip_a, args.clip_b)
    out.parent.mkdir(parents=True, exist_ok=True)

    with contextlib.ExitStack() as stack:
        font = args.font
        if font is None:
            font = _bundled_font(stack)
        elif not font.is_file():
            raise SystemExit(f"sbs: font not found: {font}")

        opts = Options(
            out=out,
            labels=_labels(args, args.clip_a, args.clip_b),
            layout=args.layout,
            panel=args.panel,
            fit=args.fit,
            length=args.length,
            audio=args.audio,
            divider=args.divider,
            font=font,
            color_a=args.color_a,
            color_b=args.color_b,
            fps=args.fps,
            crf=args.crf,
            preset=args.preset,
        )

        # --dry-run prints a command pointing at the label files, so it keeps
        # them; a normal run cleans them up once ffmpeg is done.
        label_dir = Path(tempfile.mkdtemp(prefix="sbs-"))
        if not args.dry_run:
            stack.callback(lambda: _remove_dir(label_dir))

        plan = build(a, b, opts, label_dir)

        if args.dry_run:
            print(shlex.join(plan.command))
            if opts.labels:
                print(f"# label files kept at {label_dir}", file=sys.stderr)
            return 0

        print(_summary(plan, a, b, opts))
        result = subprocess.run(plan.command)
        if result.returncode != 0:
            return result.returncode

    written = probe(out)
    size_mb = out.stat().st_size / 1_000_000
    print(f"[sbs] done: {out}  ({written.duration:.1f}s, {size_mb:.1f} MB)")
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

    # `sbs a.mp4 b.mp4` is the shape people reach for first — point at `render`
    # rather than letting argparse say "invalid choice".
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        if Path(argv[0]).is_file():
            hint = shlex.join(["sbs", "render", *argv])
            print(f"sbs: did you mean:\n  {hint}", file=sys.stderr)
            return 2

    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        return _run_render(args)
    except ProbeError as exc:
        raise SystemExit(f"sbs: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
