"""Font selection — the bundled face is Latin-only, so labels get matched
to a font one by one."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipcompare import fonts
from clipcompare.modes.sidebyside import Options, build

from helpers import clip, graph

BUNDLED = Path("/bundled/TikTokSans-Medium.ttf")
SYSTEM_CJK = Path("/system/STHeiti Medium.ttc")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ORIGINAL", False),
        ("PIKA VFX 2", False),
        ("WEIRD %{n} NAME", False),
        ("原始素材", True),
        ("MIXED 中文 LABEL", True),
        ("カタカナ", True),
        ("한글", True),
        ("ＦＵＬＬＷＩＤＴＨ", True),
    ],
)
def test_needs_cjk(text, expected):
    assert fonts.needs_cjk(text) is expected


def test_latin_labels_both_keep_the_bundled_font(monkeypatch):
    monkeypatch.setattr(fonts, "find_cjk_font", lambda: SYSTEM_CJK)
    chosen, unserved = fonts.resolve(("ORIGINAL", "EDITED"), BUNDLED)
    assert chosen == (BUNDLED, BUNDLED)
    assert unserved is False


def test_only_the_cjk_label_switches_font(monkeypatch):
    monkeypatch.setattr(fonts, "find_cjk_font", lambda: SYSTEM_CJK)
    chosen, unserved = fonts.resolve(("原始", "EDITED"), BUNDLED)
    assert chosen == (SYSTEM_CJK, BUNDLED)
    assert unserved is False


def test_missing_system_font_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(fonts, "find_cjk_font", lambda: None)
    chosen, unserved = fonts.resolve(("原始", "EDITED"), BUNDLED)
    assert chosen == (BUNDLED, BUNDLED)
    assert unserved is True


def test_system_font_is_looked_up_once_for_two_cjk_labels(monkeypatch):
    calls = []

    def counted():
        calls.append(1)
        return SYSTEM_CJK

    monkeypatch.setattr(fonts, "find_cjk_font", counted)
    fonts.resolve(("原始", "成片"), BUNDLED)
    assert len(calls) == 1


def test_per_label_fonts_reach_the_filtergraph(tmp_path):
    plan = build(
        clip(), clip(),
        Options(
            out=Path("out.mp4"),
            labels=("原始", "EDITED"),
            fonts=(SYSTEM_CJK, BUNDLED),
        ),
        tmp_path,
    )
    body = graph(plan.command)
    assert str(SYSTEM_CJK) in body
    assert str(BUNDLED) in body
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "原始"
