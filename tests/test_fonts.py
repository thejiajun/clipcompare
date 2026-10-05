"""Font selection — the bundled face is Latin-only, so labels get matched
to a font one by one."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from clipcompare import cli, fonts
from clipcompare.tokens import DS_FONT_DISPLAY, DS_FONT_SANS
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


def test_an_installed_font_is_found_by_file_name_one_folder_deep(tmp_path):
    flat, nested = tmp_path / "flat", tmp_path / "nested"
    (nested / "telka").mkdir(parents=True)
    flat.mkdir()
    (nested / "telka" / "Telka-Medium.otf").write_bytes(b"")
    assert fonts.find_installed("Telka-Medium.otf", [flat, nested]) == nested / "telka" / "Telka-Medium.otf"
    assert fonts.find_installed("Missing.otf", [flat, nested]) is None


def test_labels_use_telka_and_titles_telka_extended_when_installed(monkeypatch, tmp_path):
    found = {DS_FONT_SANS: tmp_path / DS_FONT_SANS, DS_FONT_DISPLAY: tmp_path / DS_FONT_DISPLAY}
    monkeypatch.setattr(fonts, "find_installed", found.get)
    with contextlib.ExitStack() as stack:
        assert cli._default_fonts(stack) == (found[DS_FONT_SANS], found[DS_FONT_DISPLAY])


def test_without_telka_both_fall_back_to_the_bundled_font(monkeypatch):
    monkeypatch.setattr(fonts, "find_installed", lambda name: None)
    with contextlib.ExitStack() as stack:
        label, title = cli._default_fonts(stack)
    assert label.name == cli.FONT_NAME and title == label


def test_default_colours_are_design_system_tokens():
    from clipcompare.filters import Common, WAVE_BACKGROUND, WAVE_BASELINE, WAVE_COLOR

    common = Common(out=Path("out.mp4"))
    assert (common.color_a, common.color_b, common.label_bg) == ("0xfcfaf7", "0xcfc3ff", "0x222222@0.6")
    assert (WAVE_BACKGROUND, WAVE_COLOR, WAVE_BASELINE) == ("0x111111", "0xcfc3ff", "0xfcfaf7@0.1")
    args = cli._parser().parse_args(["grid", "a.mp3", "b.mp3"])
    assert (args.color_a, args.color_b) == ("0xfcfaf7", "0xcfc3ff")
