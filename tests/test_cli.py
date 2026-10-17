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


@pytest.mark.parametrize("name", ["sbs", "render", "pict", "mosaic"])
def test_every_mode_has_one_name(name):
    assert cli.MODES == ("side", "wipe", "pip", "grid")
    with pytest.raises(SystemExit):
        cli._parser().parse_args([name, "a.mp4", "b.mp4"])


def test_three_bare_clips_suggest_grid(tmp_path, capsys, monkeypatch):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"")
    monkeypatch.setattr(sys, "argv", ["clipcompare"])
    assert cli.main([str(clip), str(clip), str(clip)]) == 2
    assert "clipcompare grid" in capsys.readouterr().err


def test_grid_labels_must_match_the_clip_count():
    args = cli._parser().parse_args(["grid", "a.mp4", "b.mp4", "c.mp4", "-l", "A,B"])
    with pytest.raises(SystemExit, match="3 comma-separated values"):
        cli._labels(args, list(args.clips))


def test_grid_default_labels_come_from_every_filename():
    args = cli._parser().parse_args(["grid", "zh_cn.mp4", "ja-jp.mp4", "es.mp4"])
    assert cli._labels(args, list(args.clips)) == ("ZH CN", "JA JP", "ES")


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--cols", "2", "--rows", "1"], "holds 2 clips, not 3"),
        (["--audio", "4"], "clip number 1-3"),
        (["--audio", "loud"], "clip number 1-3"),
    ],
)
def test_grid_rejects_impossible_settings(extra, message):
    args = cli._parser().parse_args(["grid", "a.mp4", "b.mp4", "c.mp4", *extra])
    with pytest.raises(SystemExit, match=message):
        cli._check_grid(args, 3)


def test_no_arguments_prints_help(capsys):
    assert cli.main([]) == 0
    assert "MODE" in capsys.readouterr().out


def test_grid_group_reuses_one_run_of_labels_and_takes_a_title_per_run():
    args = cli._parser().parse_args(
        ["grid", "a.mp3", "b.mp3", "c.mp3", "d.mp3", "--group", "2", "-l", "V3,V4", "--title", "Kali,Alia"]
    )
    assert cli._labels(args, list(args.clips)) == ("V3", "V4", "V3", "V4")
    assert cli._titles(args, 4) == ("Kali", "Alia")
    assert args.pause == 0.5


def test_grid_title_count_must_match_the_runs():
    args = cli._parser().parse_args(["grid", "a.mp3", "b.mp3", "c.mp3", "d.mp3", "--group", "2", "--title", "Kali"])
    with pytest.raises(SystemExit, match="2 comma-separated values"):
        cli._titles(args, 4)


def test_a_single_grid_title_keeps_its_commas():
    args = cli._parser().parse_args(["grid", "a.mp3", "b.mp3", "--title", "Kali, take 2"])
    assert cli._titles(args, 2) == ("Kali, take 2",)


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--group", "3"], "do not split into runs of 3"),
        (["--group", "4"], "do not split into runs of 4"),
        (["--group", "1"], "runs of two or more"),
        (["--pause", "-1"], "--pause cannot be negative"),
    ],
)
def test_grid_rejects_impossible_groups(extra, message):
    args = cli._parser().parse_args(["grid", "a.mp3", "b.mp3", "c.mp3", "d.mp3", *extra])
    with pytest.raises(SystemExit, match=message):
        cli._check_grid(args, 4)


@pytest.mark.parametrize("value", ["F2EEE8", "#F2EEE8", "0xf2eee8"])
def test_background_takes_any_hex_spelling(value):
    from clipcompare.filters import hex_color

    assert hex_color(value) == "0xf2eee8"


def test_background_rejects_anything_but_six_hex_digits():
    from clipcompare.filters import hex_color

    for value in ("white", "#fff", "F2EEE8FF"):
        with pytest.raises(ValueError):
            hex_color(value)


def test_side_divider_is_unset_unless_given_so_padding_can_drop_it():
    args = cli._parser().parse_args(["side", "a.mp4", "b.mp4", "--padding", "60", "--background", "F2EEE8"])
    assert args.divider is None and args.padding == 60 and args.background == "F2EEE8"
    assert cli._parser().parse_args(["side", "a.mp4", "b.mp4", "--divider", "4"]).divider == 4
