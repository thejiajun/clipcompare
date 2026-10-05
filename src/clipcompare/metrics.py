"""Advance widths straight from a font file, so captions can be wrapped and
coloured run by run without a text-layout dependency.

Reads only what width needs from an OpenType / TrueType file (or the first
face of a collection): unitsPerEm from `head`, the advances from `hhea` and
`hmtx`, and the character map from `cmap` formats 4 and 12. Kerning is
ignored, which leaves a line a few pixels off at most — wrapping keeps slack.
"""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path


class FontMetrics:
    def __init__(self, data: bytes):
        offset = 0
        if data[:4] == b"ttcf":  # a collection: measure its first face
            offset = struct.unpack_from(">I", data, 12)[0]
        count = struct.unpack_from(">H", data, offset + 4)[0]
        tables = {}
        for index in range(count):
            tag, _, start, length = struct.unpack_from(">4sIII", data, offset + 12 + 16 * index)
            tables[tag.decode("latin-1")] = (start, length)

        self.units = struct.unpack_from(">H", data, tables["head"][0] + 18)[0]
        # hhea's ascender is what FreeType (and so drawtext's y_align=font)
        # puts the baseline under.
        self.ascent = struct.unpack_from(">h", data, tables["hhea"][0] + 4)[0]
        metric_count = struct.unpack_from(">H", data, tables["hhea"][0] + 34)[0]
        hmtx = tables["hmtx"][0]
        self.advances = [struct.unpack_from(">H", data, hmtx + 4 * index)[0] for index in range(metric_count)]
        self.glyphs = _cmap(data, tables["cmap"][0])
        # A character the font lacks is drawn by drawtext as its .notdef box,
        # which is glyph 0's width.
        self.missing = self.advances[0] if self.advances else self.units // 2

    def has(self, char: str) -> bool:
        return ord(char) in self.glyphs

    def baseline(self, size: float) -> float:
        """How far below a drawtext y (with y_align=font) the baseline sits."""
        return self.ascent * size / self.units

    def width(self, text: str, size: float) -> float:
        last = len(self.advances) - 1
        total = 0
        for char in text:
            glyph = self.glyphs.get(ord(char))
            total += self.missing if glyph is None else self.advances[min(glyph, last)]
        return total * size / self.units


def _cmap(data: bytes, base: int) -> dict[int, int]:
    """Character -> glyph from the best Unicode subtable: format 12 (full
    Unicode) when there is one, else format 4 (the Basic Multilingual Plane)."""
    count = struct.unpack_from(">H", data, base + 2)[0]
    best: tuple[int, int] | None = None
    for index in range(count):
        platform, encoding, offset = struct.unpack_from(">HHI", data, base + 4 + 8 * index)
        if (platform, encoding) not in ((3, 1), (3, 10), (0, 3), (0, 4), (0, 6)):
            continue
        fmt = struct.unpack_from(">H", data, base + offset)[0]
        if fmt in (4, 12) and (best is None or fmt > best[0]):
            best = (fmt, base + offset)
    if best is None:
        return {}
    fmt, table = best
    glyphs: dict[int, int] = {}
    if fmt == 12:
        groups = struct.unpack_from(">I", data, table + 12)[0]
        for index in range(groups):
            start, end, first = struct.unpack_from(">III", data, table + 16 + 12 * index)
            for code in range(start, min(end, 0x10FFFF) + 1):
                glyphs[code] = first + code - start
        return glyphs
    segments = struct.unpack_from(">H", data, table + 6)[0] // 2
    ends = table + 14
    starts = ends + 2 * segments + 2
    deltas = starts + 2 * segments
    ranges = deltas + 2 * segments
    for index in range(segments):
        end = struct.unpack_from(">H", data, ends + 2 * index)[0]
        start = struct.unpack_from(">H", data, starts + 2 * index)[0]
        delta = struct.unpack_from(">h", data, deltas + 2 * index)[0]
        range_offset = struct.unpack_from(">H", data, ranges + 2 * index)[0]
        for code in range(start, end + 1):
            if code == 0xFFFF:
                continue
            if range_offset == 0:
                glyph = (code + delta) & 0xFFFF
            else:
                at = ranges + 2 * index + range_offset + 2 * (code - start)
                glyph = struct.unpack_from(">H", data, at)[0]
                glyph = (glyph + delta) & 0xFFFF if glyph else 0
            if glyph:
                glyphs[code] = glyph
    return glyphs


@lru_cache(maxsize=16)
def load(path: Path) -> FontMetrics:
    return FontMetrics(Path(path).read_bytes())
