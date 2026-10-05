"""Font selection.

Labels default to the design system's Telka when it is installed (see
tokens.py), the bundled TikTok Sans otherwise. Both cover Latin only, so a label carrying CJK — which is
what you get for free from a Chinese filename — would render as tofu boxes.
Labels are therefore matched to a font one by one, falling back to a system
CJK face only for the labels that actually need it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# Ranges worth switching fonts for: CJK ideographs (plus the common extension
# and compatibility blocks), kana, and Hangul.
_CJK_RANGES = (
    (0x2E80, 0x2FDF),    # radicals
    (0x3040, 0x30FF),    # kana
    (0x3400, 0x4DBF),    # ideographs extension A
    (0x4E00, 0x9FFF),    # ideographs
    (0xAC00, 0xD7AF),    # hangul syllables
    (0xF900, 0xFAFF),    # compatibility ideographs
    (0xFF00, 0xFF60),    # fullwidth forms
    (0x20000, 0x2FA1F),  # extensions B-F
)

# Verified against ffmpeg's drawtext, best first. fontconfig lookups by family
# name are deliberately not used — "PingFang SC" resolves to a face that
# renders tofu, while these files render correctly.
_CJK_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
)


# Where an installed font file can live; the first match wins.
_FONT_DIRS = (
    Path.home() / "Library" / "Fonts",
    Path("/Library/Fonts"),
    Path.home() / ".local" / "share" / "fonts",
    Path.home() / ".fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
)


def find_installed(filename: str, dirs: Sequence[Path] = _FONT_DIRS) -> Path | None:
    """An installed font file by name, searched one folder deep (Linux font
    folders are usually split per family)."""
    for folder in dirs:
        for candidate in (folder / filename, *folder.glob(f"*/{filename}")):
            if candidate.is_file():
                return candidate
    return None


def needs_cjk(text: str) -> bool:
    return any(
        any(low <= ord(char) <= high for low, high in _CJK_RANGES)
        for char in text
    )


def find_cjk_font() -> Path | None:
    for candidate in _CJK_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def resolve(labels: Sequence[str], default: Path) -> tuple[tuple[Path, ...], bool]:
    """Pick a font per label. Returns one font per label, in order, plus whether
    CJK text went unserved."""
    cjk_font = None
    unserved = False
    chosen = []
    for label in labels:
        if not needs_cjk(label):
            chosen.append(default)
            continue
        if cjk_font is None:
            cjk_font = find_cjk_font()
        if cjk_font is None:
            unserved = True
            chosen.append(default)
        else:
            chosen.append(cjk_font)
    return tuple(chosen), unserved
