"""A clip's prompt, marked up against its group's baseline prompt.

The point of a comparison is what changed, so a prompt is split into tokens
and each one gets a style:

- "tag":   a [bracket tag] carrying a direction the baseline does not have
           (drawn in --ds-accent-700)
- "shared": a [tag] the baseline also has (plain text, tag weight)
- "emph":  a word that matches the baseline's except for case or punctuation
           ("TEN" for "ten", "saved..." for "saved"), or punctuation the
           baseline lacks ("—") — underlined in the accent colour
- "plain": everything else

Words are aligned with difflib on a key that ignores case and punctuation,
after the tags are taken out, so an inserted tag never shifts the alignment.
The same marks feed the video and the web page.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"\[[^\[\]\n]*\]|[^\s\[]+")
_KEY = re.compile(r"[^\w']+")

STYLES = ("plain", "tag", "shared", "emph")


@dataclass(frozen=True)
class Token:
    text: str
    style: str = "plain"
    space: bool = True       # whitespace before it (False glues it to the previous token)

    @property
    def is_tag(self) -> bool:
        return self.text.startswith("[")


@dataclass(frozen=True)
class Segment:
    text: str
    start: float | None = None  # seconds into the clip; None when the timing is unknown
    end: float | None = None
    estimated: bool = False


def tokens(text: str) -> list[Token]:
    found = []
    at = 0
    for match in _TOKEN.finditer(text):
        found.append(Token(match.group(), space=bool(found) and match.start() > at))
        at = match.end()
    return found


def key(word: str) -> str:
    """What two words must share to count as the same word."""
    return _KEY.sub("", word).lower()


def directions(tag: str) -> list[str]:
    """The comma-separated directions inside a tag: "[soft laugh, warm]" ->
    ["soft laugh", "warm"]."""
    return [part.strip().lower() for part in tag.strip("[]").split(",") if part.strip()]


def _baseline_directions(baseline: str) -> set[str]:
    return {d for token in tokens(baseline) if token.is_tag for d in directions(token.text)}


def mark(text: str, baseline: str | None) -> list[Token]:
    """`text` as styled tokens. With no baseline (or for the baseline itself)
    every tag is new and nothing is emphasised."""
    found = tokens(text)
    if baseline is None:
        return [Token(t.text, "tag" if t.is_tag else "plain", t.space) for t in found]
    if text == baseline:
        return [Token(t.text, "shared" if t.is_tag else "plain", t.space) for t in found]
    known = _baseline_directions(baseline)
    words = [index for index, token in enumerate(found) if not token.is_tag]
    base = [token.text for token in tokens(baseline) if not token.is_tag]
    ours = [found[index].text for index in words]

    def keys(items: list[str]) -> list[str]:
        # Pure punctuation ("—", "...") keeps itself as its key.
        return [key(word) or word for word in items]

    styles = ["plain"] * len(found)
    matcher = difflib.SequenceMatcher(None, keys(base), keys(ours), autojunk=False)
    for op, b0, _b1, o0, o1 in matcher.get_opcodes():
        for offset, position in enumerate(range(o0, o1)):
            word = ours[position]
            if op == "equal":
                if word != base[b0 + offset]:
                    styles[words[position]] = "emph"
            elif not key(word):
                styles[words[position]] = "emph"   # punctuation the baseline does not have
    for index, token in enumerate(found):
        if token.is_tag:
            new = any(d not in known for d in directions(token.text)) or not directions(token.text)
            styles[index] = "tag" if new else "shared"
    return [Token(t.text, style, t.space) for t, style in zip(found, styles)]


def summary(text: str, baseline: str | None) -> str:
    """One line on how `text` differs from the baseline, for a waiting tile:
    "+3 tags · 2 emphasis · no 'speaking quickly'"."""
    if baseline is None:
        return ""
    if text == baseline:
        return "baseline"
    marked = mark(text, baseline)
    added = sum(
        sum(1 for d in directions(t.text) if d not in _baseline_directions(baseline))
        for t in marked if t.style == "tag"
    )
    emphasis = sum(1 for t in marked if t.style == "emph")
    ours = {d for t in marked if t.is_tag for d in directions(t.text)}
    missing = sorted(_baseline_directions(baseline) - ours)
    parts = []
    if added:
        parts.append(f"+{added} tag{'s' if added != 1 else ''}")
    if emphasis:
        parts.append(f"{emphasis} emphasis")
    if missing:
        parts.append("no " + ", ".join(f"'{direction}'" for direction in missing))
    return " · ".join(parts) or "same words"


def word_count(text: str) -> int:
    """Spoken words: tags and bare punctuation do not count."""
    return sum(1 for token in tokens(text) if not token.is_tag and key(token.text))


def split_marked(marked: list[Token], segments: list[Segment]) -> list[list[Token]]:
    """Cut a whole prompt's marked tokens into its segments, by token count
    (a segment's text is a run of the prompt's text)."""
    out = []
    at = 0
    for segment in segments:
        count = len(tokens(segment.text))
        piece = list(marked[at:at + count])
        if piece:
            piece[0] = Token(piece[0].text, piece[0].style, False)
        out.append(piece)
        at += count
    if at < len(marked) and out:
        out[-1].extend(marked[at:])
    return out


def segments_of(prompt: str, raw: list[dict] | None) -> list[Segment]:
    """The manifest's segments, or the whole prompt as one untimed segment."""
    if not raw:
        return [Segment(prompt)]
    return [
        Segment(
            str(item.get("text", "")),
            float(item["start"]) if item.get("start") is not None else None,
            float(item["end"]) if item.get("end") is not None else None,
            bool(item.get("estimated")),
        )
        for item in raw
    ]


@dataclass(frozen=True)
class ClipPrompt:
    """Everything a tile (or the web page) shows of one clip's prompt."""

    text: str
    segments: tuple[Segment, ...]
    marked: tuple[tuple[Token, ...], ...]   # per segment
    summary: str                            # vs the baseline; "" when there is none
    is_baseline: bool = False


def prepare(
    captions: tuple[str | None, ...], baselines: tuple[bool, ...] = (), segments: tuple = (), group: int = 0,
) -> tuple[ClipPrompt | None, ...]:
    """Mark every clip's prompt against the baseline of its run (its --group,
    or all clips). A run with no baseline marks every tag as new and has no
    summaries."""
    count = len(captions)
    size = group or count
    baselines = baselines or (False,) * count
    segments = segments or (None,) * count
    out: list[ClipPrompt | None] = []
    for start in range(0, count, size):
        run = range(start, min(start + size, count))
        reference = next((captions[i] for i in run if baselines[i] and captions[i]), None)
        for index in run:
            text = captions[index]
            if not text:
                out.append(None)
                continue
            parts = segments_of(text, segments[index])
            marked = split_marked(mark(" ".join(p.text for p in parts) if segments[index] else text, reference), parts)
            out.append(ClipPrompt(
                text, tuple(parts), tuple(tuple(m) for m in marked), summary(text, reference),
                is_baseline=bool(baselines[index]) and reference is not None,
            ))
    return tuple(out)


def windows(prompt: ClipPrompt, start: float, end: float, hold: float = 0.0) -> list[tuple[float, float]]:
    """Each segment's span on the output timeline, for a clip playing from
    `start` to `end` with its first `hold` seconds cut. Segments without
    timing split the turn by text length. Spans are contiguous and cover the
    whole turn."""
    parts = prompt.segments
    length = end - start
    if all(p.start is not None for p in parts):
        cuts = [start + max(p.start - hold, 0.0) for p in parts]
    else:
        sizes = [max(len(p.text), 1) for p in parts]
        total = sum(sizes)
        cuts = [start + length * sum(sizes[:i]) / total for i in range(len(parts))]
    cuts[0] = start
    cuts = [min(max(cut, start), end) for cut in cuts] + [end]
    return [(cuts[i], cuts[i + 1]) for i in range(len(parts))]
