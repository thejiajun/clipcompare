"""CLI-level behaviour that does not need ffmpeg."""

from __future__ import annotations

import sys

import pytest

from clipcompare import cli


def test_missing_mode_suggests_a_pasteable_line(tmp_path, capsys, monkeypatch):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"")
    monkeypatch.setattr(sys, "argv", ["clipcompare"])
    assert cli.main([str(clip), str(clip)]) == 2
    assert "clipcompare side" in capsys.readouterr().err


def test_suggestion_echoes_the_name_actually_typed(tmp_path, capsys, monkeypatch):
    # Invoked as `sbs`, the hint must say `sbs`, not the canonical name.
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/sbs"])
    assert cli.main([str(clip), str(clip)]) == 2
    err = capsys.readouterr().err
    assert "sbs side" in err
    assert "clipcompare side" not in err


@pytest.mark.parametrize("alias,expected", [("sbs", "side"), ("render", "side"), ("pict", "pip")])
def test_mode_aliases_resolve(alias, expected):
    assert cli.MODE_ALIASES[alias] == expected


def test_no_arguments_prints_help(capsys):
    assert cli.main([]) == 0
    assert "MODE" in capsys.readouterr().out
