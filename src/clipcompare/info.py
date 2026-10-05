"""The technical info layer: what each clip was meant to be (its recipe) and
what actually came out (measured), laid out by one rule — what is the same
for every clip of a run is said once, in the title bar; only what differs is
said in each tile.

A tile then reads in three text levels under its name:

- recipe (secondary): model, preset, params (any keys, diffed one by one),
  cost, seed — a field that differs from the baseline in --ds-accent-700,
  the same rule as the prompt marks;
- measured (tertiary, --ds-text-secondary): resolution, bitrate, rate,
  length, codecs, size, with neutral deltas against the baseline (bitrate
  −61%), and the baseline similarity (SSIM, PSNR, SNR) — the only numbers
  with a better/worse direction, so the only ones given a good/bad colour.

The display model is plain data (shared by the video, the web page and the
sidecar JSON); painting a line into a PNG lives here too, since the video
draws each tile's lines once and overlays them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import metrics
from .filters import escape
from .tokens import DS_ACCENT_700, DS_ALERT, DS_EGGSHELL, DS_NEON_GREEN, DS_TEXT_SECONDARY_DARK

RECIPE_KEYS = ("model", "preset", "params", "cost", "seed")
MINUS = "−"
TIMES = "×"
SEPARATOR = " · "

# Where a similarity number turns good or bad (against the baseline).
GOOD_BAD = {"ssim": (0.98, 0.90), "psnr": (40.0, 30.0), "snr": (30.0, 15.0)}


@dataclass(frozen=True)
class Item:
    key: str
    text: str
    accent: bool = False   # recipe: differs from the baseline
    tone: str = ""         # similarity: "good", "bad" or "" (neutral)


@dataclass(frozen=True)
class Tile:
    recipe: tuple[Item, ...] = ()
    measured: tuple[Item, ...] = ()      # only what differs between clips, with deltas
    similarity: tuple[Item, ...] = ()    # vs the baseline; ("baseline",) on the baseline itself
    is_baseline: bool = False
    differences: int | None = None       # fields differing from the baseline; None without one


@dataclass(frozen=True)
class Run:
    shared: tuple[Item, ...] = ()        # said once, in the title bar
    tiles: tuple[Tile, ...] = ()

    @property
    def shared_text(self) -> str:
        return SEPARATOR.join(item.text for item in self.shared)


# --- recipe ---------------------------------------------------------------

def recipe(entry: dict) -> dict:
    """The recipe fields a manifest clip carries; params stay one object."""
    out = {key: entry[key] for key in RECIPE_KEYS if entry.get(key) is not None}
    if "params" in out and not isinstance(out["params"], dict):
        raise ValueError('"params" must be an object of any keys')
    return out


def _value(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _recipe_fields(spec: dict | None) -> list[tuple[str, str, object]]:
    """(key, display text, value to compare) for each recipe field, params
    key by key — clipcompare knows no vendor's keys."""
    if not spec:
        return []
    out = []
    for key in RECIPE_KEYS:
        if key not in spec:
            continue
        value = spec[key]
        if key == "params":
            out += [(f"params.{name}", f"{name} {_value(item)}", item) for name, item in value.items()]
        elif key == "cost":
            text = f"${value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else _value(value)
            out.append(("cost", text, value))
        elif key == "seed":
            out.append(("seed", f"seed {_value(value)}", value))
        else:
            out.append((key, _value(value), value))
    return out


# --- measured -------------------------------------------------------------

def _rate_text(fps: float) -> str:
    return f"{fps:.0f} fps" if abs(fps - round(fps)) < 0.005 else f"{fps:.2f} fps"


def _bits(bps: float) -> str:
    return f"{bps / 1e6:.1f} Mbps" if bps >= 1e6 else f"{bps / 1e3:.0f} kbps"


def _bytes(size: float) -> str:
    return f"{size / 1e6:.1f} MB" if size >= 1e5 else f"{size / 1e3:.0f} KB"


def _measured_fields(m: dict | None) -> list[tuple[str, str, float | None]]:
    """(key, display text, number a delta is taken of) in reading order."""
    if not m:
        return []
    kind = m.get("kind")
    out: list[tuple[str, str, float | None]] = []
    if kind in ("video", "image") and m.get("width"):
        out.append(("resolution", f"{m['width']}{TIMES}{m['height']}", None))
    if kind == "video" and m.get("video_bitrate"):
        out.append(("bitrate", _bits(m["video_bitrate"]), m["video_bitrate"]))
    if kind == "audio" and m.get("audio_bitrate"):
        out.append(("bitrate", _bits(m["audio_bitrate"]), m["audio_bitrate"]))
    if kind == "video" and m.get("fps"):
        out.append(("fps", _rate_text(m["fps"]), None))
    if m.get("duration"):
        out.append(("duration", f"{m['duration']:.2f} s", m["duration"]))
    if kind == "video":
        out.append(("video", f"{m.get('video_codec')} {m.get('pix_fmt')}", None))
    if kind == "image":
        out.append(("format", f"{m.get('format')} {m.get('pix_fmt')}", None))
    if kind in ("video", "audio"):
        if m.get("audio_codec"):
            rate = f" {m['sample_rate'] / 1000:g} kHz" if m.get("sample_rate") else ""
            out.append(("audio", f"{m['audio_codec']}{rate}", None))
        else:
            out.append(("audio", "no audio", None))
    out.append(("size", _bytes(m["size"]), m["size"]))
    return out


def delta(value: float, base: float) -> str:
    """A neutral change against the baseline: "−61%", "+1%", "+0.6%"."""
    change = (value - base) / base * 100
    text = f"{abs(change):.0f}" if abs(change) >= 1 else f"{abs(change):.1f}"
    return f"{'+' if change >= 0 else MINUS}{text}%"


def tone(key: str, value: float) -> str:
    good, bad = GOOD_BAD[key]
    return "good" if value >= good else "bad" if value < bad else ""


def _similarity(comparison: dict | None) -> list[Item]:
    if not comparison:
        return []
    out = []
    if "ssim" in comparison:
        out.append(Item("ssim", f"SSIM {comparison['ssim']:.3f}", tone=tone("ssim", comparison["ssim"])))
    if "psnr" in comparison:
        psnr = comparison["psnr"]
        text = "PSNR identical" if psnr == float("inf") else f"PSNR {psnr:.1f} dB"
        out.append(Item("psnr", text, tone=tone("psnr", psnr)))
    if "snr" in comparison:
        snr = comparison["snr"]
        text = "SNR identical" if snr == float("inf") else f"SNR {snr:.1f} dB"
        out.append(Item("snr", text, tone=tone("snr", snr)))
    if comparison.get("scaled_to"):
        out.append(Item("scaled_to", f"at {comparison['scaled_to'].replace('x', TIMES)}"))
    return out


# --- the run --------------------------------------------------------------

def describe(
    recipes: list[dict | None], measures: list[dict | None], comparisons: list[dict | None],
    baseline: int | None,
) -> Run:
    """Split a run's recipe and measured fields into what every clip shares
    (said once) and what each tile says, marked against `baseline` (an index
    into the run, or None)."""
    count = len(recipes)
    recipe_rows = [_recipe_fields(spec) for spec in recipes]
    measured_rows = [_measured_fields(m) for m in measures]

    def shared_keys(rows) -> set[str]:
        texts = [{key: text for key, text, _ in row} for row in rows]
        keys = set(texts[0]) if texts else set()
        return {key for key in keys if all(t.get(key) == texts[0][key] for t in texts)} if count > 1 else set()

    recipe_shared = shared_keys(recipe_rows)
    measured_shared = shared_keys(measured_rows) if any(measures) else set()

    shared: list[Item] = []
    for key, text, _ in (recipe_rows[0] if recipe_rows else []):
        if key in recipe_shared:
            shared.append(Item(key, text))
    for key, text, _ in (measured_rows[0] if measured_rows else []):
        if key in measured_shared:
            shared.append(Item(key, text))

    base_recipe = {key: value for key, _, value in recipe_rows[baseline]} if baseline is not None else {}
    base_measured = {key: (text, number) for key, text, number in measured_rows[baseline]} if baseline is not None else {}
    tiles = []
    for index in range(count):
        is_base = baseline == index
        compared = baseline is not None and not is_base
        recipe_items = tuple(
            Item(key, text, accent=compared and (key not in base_recipe or base_recipe[key] != value))
            for key, text, value in recipe_rows[index] if key not in recipe_shared
        )
        measured_items = []
        changed = 0
        for key, text, number in measured_rows[index]:
            if key in measured_shared:
                continue
            base = base_measured.get(key)
            if compared and base and base[0] != text:
                changed += 1
                if number is not None and base[1]:
                    text = f"{text} {delta(number, base[1])}"
            measured_items.append(Item(key, text))
        similarity: list[Item] = [Item("baseline", "baseline")] if is_base and any(measures) else []
        if compared:
            similarity += _similarity(comparisons[index])
        missing = {key for key in base_recipe if key not in {k for k, _, _ in recipe_rows[index]}}
        tiles.append(Tile(
            recipe=recipe_items,
            measured=tuple(measured_items),
            similarity=tuple(similarity),
            is_baseline=is_base,
            differences=(
                None if baseline is None
                else 0 if is_base
                else sum(item.accent for item in recipe_items) + len(missing) + changed
            ),
        ))
    return Run(tuple(shared), tuple(tiles))


def as_json(run: Run) -> dict:
    return {"shared": [asdict(item) for item in run.shared], "tiles": [asdict(tile) for tile in run.tiles]}


# --- painting -------------------------------------------------------------

TONES = {"good": DS_NEON_GREEN, "bad": DS_ALERT}
DIGITS = "0123456789"


@dataclass(frozen=True)
class Span:
    text: str
    color: str
    tabular: bool = False   # digits on a fixed advance, so numbers line up tile to tile


@dataclass
class Painted:
    command: list[str]
    width: int
    height: int
    lines: list[list[Span]] = field(default_factory=list)


def recipe_spans(tile: Tile) -> list[Span]:
    spans: list[Span] = []
    for item in tile.recipe:
        if spans:
            spans.append(Span(SEPARATOR, DS_TEXT_SECONDARY_DARK))
        spans.append(Span(item.text, DS_ACCENT_700 if item.accent else DS_EGGSHELL))
    return spans


def measured_lines(tile: Tile) -> list[list[Span]]:
    """Up to two lines: the differing measured values, then the similarity."""
    lines = []
    for items in (tile.measured, tile.similarity):
        spans: list[Span] = []
        for item in items:
            if spans:
                spans.append(Span(SEPARATOR, DS_TEXT_SECONDARY_DARK))
            spans.append(Span(item.text, TONES.get(item.tone, DS_TEXT_SECONDARY_DARK), tabular=True))
        if spans:
            lines.append(spans)
    return lines


class _Layout:
    def __init__(self, font: Path, size: int):
        self.face = metrics.load(font)
        self.size = size
        self.digit = max(self.face.width(d, size) for d in DIGITS)

    def pieces(self, span: Span) -> list[tuple[str, float]]:
        """(text, advance) pieces: a tabular span draws each digit alone, on
        a cell as wide as the widest digit."""
        if not span.tabular:
            return [(span.text, self.face.width(span.text, self.size))]
        out: list[tuple[str, float]] = []
        run = ""
        for char in span.text:
            if char in DIGITS:
                if run:
                    out.append((run, self.face.width(run, self.size)))
                    run = ""
                out.append((char, self.digit))
            else:
                run += char
        if run:
            out.append((run, self.face.width(run, self.size)))
        return out

    def width(self, spans: list[Span]) -> float:
        return sum(advance for span in spans for _, advance in self.pieces(span))


def fit_line(spans: list[Span], width: float, font: Path, size: int) -> list[Span]:
    """Drop trailing spans (then ellipsize the last) until the line fits."""
    layout = _Layout(font, size)
    spans = list(spans)
    while spans and layout.width(spans) > width:
        last = spans.pop()
        while spans and spans[-1].text == SEPARATOR:
            spans.pop()
        if not spans:
            text = last.text
            while text and layout.width([Span(text + "…", last.color, last.tabular)]) > width:
                text = text[:-1]
            spans = [Span(text + "…", last.color, last.tabular)] if text else []
            break
        if layout.width(spans + [Span(" …", DS_TEXT_SECONDARY_DARK)]) <= width:
            spans.append(Span(" …", DS_TEXT_SECONDARY_DARK))
            break
    return spans


def line_height(size: int) -> int:
    return max(round(size * 1.35), size + 1)   # --ds-type-caption-12-leading


def paint(
    lines: list[list[Span]], font: Path, size: int, out: Path, text_dir: Path,
    width: int | None = None, background: str = "black@0", pad_v: int = 0, pad_h: int = 0,
) -> Painted:
    """The pre-command painting `lines` into a PNG: on a `background` chip
    hugging the text (or `width` wide), pad_v / pad_h around it."""
    layout = _Layout(font, size)
    lh = line_height(size)
    inner = max((layout.width(line) for line in lines), default=0.0)
    chip_w = width or round(inner) + 2 * pad_h
    chip_h = len(lines) * lh + 2 * pad_v
    steps = []
    for row, line in enumerate(lines):
        x = float(pad_h)
        y = pad_v + row * lh + (lh - size) // 2
        for column, span in enumerate(line):
            for piece, (text, advance) in enumerate(layout.pieces(span)):
                left = x + (advance - layout.face.width(text, size)) / 2 if span.tabular and text in DIGITS else x
                if text.strip():
                    text_file = text_dir / f"{out.stem}-{row}-{column}-{piece}.txt"
                    text_file.write_text(text, encoding="utf-8")
                    steps.append(":".join([
                        f"drawtext=textfile={escape(str(text_file))}", f"fontfile={escape(str(font))}",
                        f"fontsize={size}", "expansion=none", "y_align=font",
                        f"fontcolor={span.color}", f"x={round(left)}", f"y={y}",
                    ]))
                x += advance
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={background}:s={max(chip_w, 2)}x{max(chip_h, 2)},format=rgba",
        "-vf", ",".join(steps) or "null", "-frames:v", "1", str(out),
    ]
    return Painted(command, max(chip_w, 2), max(chip_h, 2), lines)
