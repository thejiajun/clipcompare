"""Drawing the info layer (info.py) onto a video or picture, for every mode
that has panels — grid's tiles and side's two halves alike:

- a recipe chip under each panel's label, and a measured strip along its
  bottom, each painted once into a PNG (a pre-command, so the render cache
  keeps it) and overlaid;
- the shared line in the title bar: what every panel has in common, once.
"""

from __future__ import annotations

from pathlib import Path

from . import captions as captions_mod
from . import info as info_mod
from .filters import Input, LabelMetrics, escape, even
from .tokens import DS_TEXT_SECONDARY_DARK

RECIPE = 0.8      # recipe text size, as a share of the label's
MEASURED = 0.7    # measured strip text size, as a share of the label's
SHARED = 0.05     # shared-line band height, as a share of the canvas's short edge

Painted = tuple[info_mod.Painted | None, info_mod.Painted | None]


def shared_px(short: int) -> int:
    return even(round(short * SHARED))


def pictures(
    run: info_mod.Run, font: Path, background: str, folder: Path, panel_w: int, metrics: LabelMetrics,
) -> list[Painted]:
    """Per panel, the recipe chip and the measured strip (either may be None)."""
    recipe_size = max(round(metrics.size * RECIPE), 8)
    measured_size = max(round(metrics.size * MEASURED), 8)
    pad_v, pad_h = max(metrics.pad_v // 2, 2), max(metrics.pad_h // 2, 4)
    out: list[Painted] = []
    for index, tile in enumerate(run.tiles):
        top = bottom = None
        spans = info_mod.recipe_spans(tile)
        if spans:
            line = info_mod.fit_line(spans, panel_w - 2 * metrics.inset - 2 * pad_h, font, recipe_size)
            top = info_mod.paint(
                [line], font, recipe_size, folder / f"recipe-{index}.png", folder,
                background=background, pad_v=pad_v, pad_h=pad_h,
            )
        lines = [
            info_mod.fit_line(line, panel_w - 2 * metrics.inset, font, measured_size)
            for line in info_mod.measured_lines(tile)
        ]
        if lines:
            bottom = info_mod.paint(
                lines, font, measured_size, folder / f"measured-{index}.png", folder,
                width=panel_w, background=background, pad_v=pad_v, pad_h=metrics.inset,
            )
        out.append((top, bottom))
    return out


def overlay(
    painted: list[Painted], spots: list[tuple[int, int]], panel_h: int, metrics: LabelMetrics,
    steps: list[str], inputs: list[Input], pre_commands: list[list[str]], last: str,
    still: bool, fps: str, lossless: str | None = None,
) -> str:
    """Overlay each panel's pictures at its spot (top-left corner); returns
    the new last label. A still keeps RGB; --lossless keeps its chroma."""
    label_bottom = metrics.inset + metrics.size + 2 * metrics.pad_v
    for index, ((top, bottom), (x, y)) in enumerate(zip(painted, spots)):
        for name, picture, at in (
            ("r", top, (x + metrics.inset, y + label_bottom + metrics.inset // 2)),
            ("m", bottom, (x, y + panel_h - (bottom.height if bottom else 0))),
        ):
            if picture is None:
                continue
            pre_commands.append(picture.command)
            source = len(inputs)
            image = picture.command[-1]
            if still:
                inputs.append(image)
                steps.append(f"[{last}][{source}:v]overlay={at[0]}:{at[1]}:format=rgb[i{name}{index}]")
            else:
                inputs.append((["-loop", "1", "-framerate", fps], image))
                steps.append(
                    f"[{last}][{source}:v]overlay={at[0]}:{at[1]}:shortest=1"
                    f"{':format=auto' if lossless else ''}[i{name}{index}]"
                )
            last = f"i{name}{index}"
    return last


def shared_line(
    last: str, text: str, font: Path, band: int, top: int, width: int, folder: Path, margin: int,
) -> tuple[str, str]:
    """(step, new last label) drawing `text` centred in a band `band` px tall
    starting at `top`, cut with an ellipsis to fit `width` less `margin`s."""
    size = max(round(band * 0.45), 8)
    shared_file = folder / "shared.txt"
    shared_file.write_text(captions_mod.ellipsize_text(text, width - 2 * margin, size, font), encoding="utf-8")
    step = (
        f"[{last}]drawtext=textfile={escape(str(shared_file))}:fontfile={escape(str(font))}"
        f":fontsize={size}:expansion=none:fontcolor={DS_TEXT_SECONDARY_DARK}"
        f":y_align=font:x=(w-tw)/2:y={top + (band - size) // 2}[sh]"
    )
    return step, "sh"
