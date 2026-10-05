"""The render cache: keyed by what each piece is made from, never the output."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from clipcompare import cache, cli


def test_remember_computes_once_per_key_and_not_at_all_when_off():
    calls = []
    compute = lambda: calls.append(1) or {"n": len(calls)}  # noqa: E731
    assert cache.remember("t", ("a",), compute) == {"n": 1}
    assert cache.remember("t", ("a",), compute) == {"n": 1}
    assert cache.remember("t", ("b",), compute) == {"n": 2}
    cache.enabled = False
    assert cache.remember("t", ("a",), compute) == {"n": 3}


def test_a_touched_file_is_a_different_input(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    before = cache.identity(clip)
    os.utime(clip, ns=(1, 1))
    assert cache.identity(clip) != before


def test_picture_keys_follow_text_content_and_inputs_not_the_work_folder(tmp_path):
    def command(work: Path, text: str) -> list[str]:
        work.mkdir(exist_ok=True)
        (work / "t.txt").write_text(text)
        return ["ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=10x10", "-vf",
                f"drawtext=textfile={work / 't.txt'}:fontsize=20", str(work / "p.png")]

    one, two = tmp_path / "w1", tmp_path / "w2"
    assert cache.command_key(command(one, "hi"), one) == cache.command_key(command(two, "hi"), two)
    assert cache.command_key(command(one, "hi"), one) != cache.command_key(command(two, "ho"), two)
    # A --group part (or anything else not an intermediate picture) is never cached.
    assert cache.command_key(["ffmpeg", "-i", "x", str(one / "part.mp4")], one) is None


def test_a_second_render_reuses_its_pictures_but_never_the_output(tmp_path, capsys):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    for name, freq in (("a.mp3", 440), ("b.mp3", 660)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine={freq}:d=1", str(tmp_path / name)], check=True)
    args = ["grid", str(tmp_path / "a.mp3"), str(tmp_path / "b.mp3"), "--sequential", "-o", str(tmp_path / "o.mp4")]
    assert cli.main(args) == 0
    assert "cache: reused" not in capsys.readouterr().out
    (tmp_path / "o.mp4").unlink()
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "cache: reused 2 of 2" in out and (tmp_path / "o.mp4").is_file()
    assert cli.main([*args, "--no-cache"]) == 0
    assert "cache: reused" not in capsys.readouterr().out
    assert not list((cache.root()).rglob("o.mp4"))
