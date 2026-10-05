"""Prompt text inside a grid tile: the segment being spoken at full
brightness, its neighbours dimmed, marked against the baseline (prompts.py).

drawtext paints one colour per call and cannot underline, so the text is laid
out here with advance widths read straight from the font files (metrics.py —
no Pillow or other dependency), cut into runs of one style, and each run drawn
at its measured x; underlines are drawboxes under the measured runs. Each
(clip, segment) view is painted once into a PNG by a pre-command, and the main
render overlays the right one while that segment plays.

All sizes are px at 1080p; callers pass `scale` (their canvas against 1080p).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import metrics
from .filters import escape
from .prompts import Token
from .tokens import DS_ACCENT_700, DS_EGGSHELL, DS_TEXT_SECONDARY_DARK

LEADING = 1.3         # --ds-type-copy-20/24-leading, a touch looser for long reads
SIZE = 30             # largest prompt size
FLOOR = 15            # smallest; past this a segment is cut with an ellipsis
CONTEXT = 1           # lines of the previous segment kept (dimmed) above the current one
DIM = 0.4             # opacity of the segments not being spoken
NOTE = "timing estimated"
NOTE_SIZE = 20        # against SIZE: the note keeps this share of the prompt size
ELLIPSIS = "…"


@dataclass(frozen=True)
class Fonts:
    body: Path   # plain words: Telka Regular, the design system's copy weight
    tag: Path    # [tags]: Telka Medium


@dataclass(frozen=True)
class Run:
    x: float
    text: str
    style: str
    width: float


Line = list[Run]


class _Measure:
    def __init__(self, fonts: Fonts, size: float):
        self.body = metrics.load(fonts.body)
        self.tag = metrics.load(fonts.tag)
        self.size = size

    def font(self, style: str) -> metrics.FontMetrics:
        return self.tag if style in ("tag", "shared") else self.body

    def __call__(self, text: str, style: str) -> float:
        return self.font(style).width(text, self.size)


def _words(marked: list[Token]) -> list[list[Token]]:
    """Unbreakable words: tokens with no space between them stay together
    ("honestly?[laughs]")."""
    words: list[list[Token]] = []
    for token in marked:
        if token.space or not words:
            words.append([token])
        else:
            words[-1].append(token)
    return words


def line_height(size: int) -> int:
    return max(round(size * LEADING), size + 1)


def wrap(marked: list[Token], width: float, size: int, fonts: Fonts) -> list[Line]:
    """Lines of runs. Neighbouring plain or tag tokens merge into one run with
    their spaces; an underlined word stays a run of its own."""
    measure = _Measure(fonts, size)
    space = measure(" ", "plain")
    lines: list[Line] = []
    line: Line = []
    x = 0.0
    for word in _words(marked):
        span = sum(measure(token.text, token.style) for token in word)
        lead = space if line else 0.0
        if line and x + lead + span > width:
            lines.append(line)
            line, x, lead = [], 0.0, 0.0
        x += lead
        for position, token in enumerate(word):
            w = measure(token.text, token.style)
            last = line[-1] if line else None
            joins = (
                last is not None and last.style == token.style and token.style != "emph"
                and (position > 0 or lead)
            )
            if joins:
                gap = "" if position > 0 else " "
                line[-1] = Run(last.x, last.text + gap + token.text, last.style, x + w - last.x)
            else:
                line.append(Run(x, token.text, token.style, w))
            x += w
    if line:
        lines.append(line)
    return lines


def _ellipsize(line: Line, width: float, size: int, fonts: Fonts) -> Line:
    measure = _Measure(fonts, size)
    mark = measure(ELLIPSIS, "plain")
    line = list(line)
    while line and line[-1].x + line[-1].width + mark > width:
        line.pop()
    end = line[-1].x + line[-1].width if line else 0.0
    return [*line, Run(end, ELLIPSIS, "plain", mark)]


def fit(segments: list[list[Token]], width: float, height: int, fonts: Fonts, scale: float) -> int:
    """The largest size at which the longest segment (plus the context line
    above it) fits width x height. Fitting to segments rather than whole
    prompts is what keeps a long walkthrough readable."""
    start, floor = max(round(SIZE * scale), 6), max(round(FLOOR * scale), 6)
    for size in range(start, floor - 1, -1):
        lh = line_height(size)
        if all((len(wrap(seg, width, size, fonts)) + CONTEXT) * lh <= height for seg in segments if seg):
            return size
    return floor


@dataclass(frozen=True)
class View:
    """What one tile shows while segment `active` plays: (line, dimmed) rows."""

    size: int
    rows: list[tuple[Line, bool]]
    note: bool


def view(
    segments: list[list[Token]], active: int, width: float, height: int, size: int, fonts: Fonts,
    note: bool = False,
) -> View:
    """The current segment from the top (after CONTEXT dimmed lines of the
    one before), then the following ones dimmed, cut at `height`; a current
    segment too long even at this size ends in an ellipsis."""
    lh = line_height(size)
    budget = max((height - (line_height(round(size * NOTE_SIZE / SIZE)) if note else 0)) // lh, 1)
    laid = [wrap(seg, width, size, fonts) for seg in segments]
    rows: list[tuple[Line, bool]] = []
    if active > 0 and CONTEXT:
        rows += [(line, True) for line in laid[active - 1][-CONTEXT:]]
    current = laid[active]
    room = budget - len(rows)
    if len(current) > room:
        current = current[:room]
        current[-1] = _ellipsize(current[-1], width, size, fonts)
    rows += [(line, False) for line in current]
    for later in laid[active + 1:]:
        rows += [(line, True) for line in later]
    return View(size, rows[:budget], note)


def render_command(
    shown: View, fonts: Fonts, out: Path, text_dir: Path, width: int, height: int,
    background: str = "black@0", pad: int = 0,
) -> list[str]:
    """The pre-command painting `shown` into a PNG (transparent, or on a
    `background` chip `pad` px larger on each side): one drawtext per run,
    underlines as drawboxes on the measured baseline."""
    measure = _Measure(fonts, shown.size)
    lh = line_height(shown.size)
    thickness = max(round(shown.size / 14), 1)
    steps = []
    for row, (line, dimmed) in enumerate(shown.rows):
        y = pad + row * lh + (lh - shown.size) // 2
        alpha = f"@{DIM}" if dimmed else ""
        for column, run in enumerate(line):
            text_file = text_dir / f"{out.stem}-{row}-{column}.txt"
            text_file.write_text(run.text, encoding="utf-8")
            color = DS_ACCENT_700 if run.style == "tag" else DS_EGGSHELL
            steps.append(_text(
                text_file, fonts.tag if run.style in ("tag", "shared") else fonts.body,
                shown.size, color + alpha, pad + round(run.x), y,
            ))
            if run.style == "emph":
                under = y + round(measure.font(run.style).baseline(shown.size) + shown.size * 0.12)
                steps.append(
                    f"drawbox=x={pad + round(run.x)}:y={under}:w={max(round(run.width), 1)}:h={thickness}"
                    f":color={DS_ACCENT_700}{alpha}:t=fill:replace=1"
                )
    if shown.note:
        note_size = max(round(shown.size * NOTE_SIZE / SIZE), 6)
        note_file = text_dir / f"{out.stem}-note.txt"
        note_file.write_text(NOTE, encoding="utf-8")
        steps.append(_text(note_file, fonts.body, note_size, DS_TEXT_SECONDARY_DARK, pad, pad + height - note_size - 2))
    chain = ",".join(steps) if steps else "null"
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={background}:s={width + 2 * pad}x{height + 2 * pad},format=rgba",
        "-vf", chain, "-frames:v", "1", str(out),
    ]


def _text(text_file: Path, font: Path, size: int, color: str, x: int, y: int) -> str:
    return ":".join([
        f"drawtext=textfile={escape(str(text_file))}",
        f"fontfile={escape(str(font))}",
        f"fontsize={size}",
        "expansion=none",
        # Every run on a line shares one baseline, whatever its glyphs.
        "y_align=font",
        f"fontcolor={color}",
        f"x={x}",
        f"y={y}",
    ])


def ellipsize_text(text: str, width: float, size: int, font: Path) -> str:
    """One line of `text` cut with an ellipsis to fit `width`."""
    face = metrics.load(font)
    if face.width(text, size) <= width:
        return text
    while text and face.width(text + ELLIPSIS, size) > width:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS
