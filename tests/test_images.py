"""Image mode: stills make one picture; among videos they hold for the video's length."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from clipcompare import cli, prompts
from clipcompare.captions import Fonts
from clipcompare.modes import grid, sidebyside

from helpers import clip, graph, image, sound

FONT = Path(__file__).resolve().parents[1] / "src" / "clipcompare" / "assets" / "TikTokSans-Medium.ttf"


def grid_opts(**kwargs) -> grid.Options:
    return grid.Options(out=kwargs.pop("out", Path("out.png")), **kwargs)


def images(count, **kwargs):
    return [image(name=f"c{index}.png", **kwargs) for index in range(count)]


@pytest.mark.parametrize("count", [2, 3, 4])
def test_up_to_four_images_sit_in_one_row(count):
    plan = grid.build(images(count), grid_opts())
    assert f"{count}x1" in plan.detail
    assert plan.out_h == 720


def test_five_images_fall_back_to_the_auto_shape():
    assert "3x2" in grid.build(images(5), grid_opts()).detail


def test_cols_and_rows_still_win_for_images():
    assert "2x2" in grid.build(images(3), grid_opts(cols=2)).detail
    assert "1x3" in grid.build(images(3), grid_opts(rows=3)).detail


def test_an_all_image_grid_writes_one_full_colour_picture():
    plan = grid.build(images(3), grid_opts())
    cmd = plan.command
    body = graph(cmd)
    assert ["-frames:v", "1"] == cmd[cmd.index("-frames:v"):cmd.index("-frames:v") + 2]
    assert "-an" in cmd and "libx264" not in cmd and "-shortest" not in cmd
    assert "format=rgb24" in body and "yuv420p" not in body and "fps=" not in body
    assert "-loop" not in cmd
    assert plan.detail.endswith("image")


def test_images_are_not_scaled_up_by_the_auto_size():
    plan = grid.build(images(3), grid_opts(gap=0))
    assert (plan.out_w, plan.out_h) == (3 * 720, 720)
    assert grid.build(images(3), grid_opts(gap=0, panel=1080)).out_h == 1080


@pytest.mark.parametrize("name,flags", [("out.jpg", ["-q:v", "2"]), ("out.webp", ["-lossless", "1"])])
def test_the_output_extension_picks_the_image_format(name, flags):
    cmd = grid.build(images(2), grid_opts(out=Path(name))).command
    assert all(flag in cmd for flag in flags) and cmd[-1] == name


def test_sequential_is_ignored_for_images():
    plan = grid.build(images(3), grid_opts(sequential=True, pause=0.5))
    assert "drawbox" not in graph(plan.command) and "image" in plan.detail


def test_title_and_labels_are_drawn_on_the_picture(tmp_path):
    plan = grid.build(
        images(3),
        grid_opts(labels=("A", "B", "C"), fonts=(FONT,) * 3, title="Title", title_font=FONT),
        tmp_path,
    )
    body = graph(plan.command)
    assert body.count("box=1") == 3
    assert "title.txt" in body
    assert plan.out_h == 720 + grid.header_px(720)


def test_a_mixed_grid_holds_each_image_for_the_videos_length():
    plan = grid.build([clip(duration=4.0), image(width=1080, height=1920), sound(duration=5.0)], grid_opts(out=Path("out.mp4")))
    cmd = plan.command
    at = cmd.index("still.png")
    assert cmd[at - 5:at] == ["-loop", "1", "-t", "5.000", "-i"]
    assert "libx264" in cmd and "-frames:v" not in cmd


def test_a_mixed_sequential_grid_gives_the_image_a_turn():
    plan = grid.build(
        [clip(duration=4.0), image(width=1080, height=1920)],
        grid_opts(out=Path("out.mp4"), sequential=True, holds=(0.0, 0.0)),
    )
    assert "between(t,4.000,8.000)" in graph(plan.command)


def test_prompts_on_images_are_static_whole_prompts(tmp_path):
    captions = ("one two three", "one [laughs] two three")
    segments = ([{"text": "one two", "start": 0}, {"text": "three", "start": 1}], None)
    plan = grid.build(
        images(2),
        grid_opts(
            prompts=prompts.prepare(captions, (True, False), segments),
            caption_fonts=Fonts(body=FONT, tag=FONT),
        ),
        tmp_path,
    )
    body = graph(plan.command)
    # One picture per tile (not per segment), always shown, no timing.
    assert len(plan.pre_commands) == 2
    assert "enable=" not in body
    assert "summary-1.txt" in body


def test_two_images_side_by_side_make_one_picture_at_their_own_size():
    plan = sidebyside.build(image(), image(), sidebyside.Options(out=Path("out.png")))
    cmd = plan.command
    assert (plan.out_w, plan.out_h) == (1440, 720)
    assert "-frames:v" in cmd and "libx264" not in cmd and "-shortest" not in cmd
    assert "format=rgb24" in graph(cmd)


def test_side_holds_an_image_against_a_video():
    plan = sidebyside.build(clip(duration=3.0), image(1080, 1920), sidebyside.Options(out=Path("out.mp4")))
    cmd = plan.command
    assert "-loop" in cmd and "3.000" in cmd and "libx264" in cmd


def _args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**{"group": 0, "html": None, **kwargs})


def test_all_images_default_to_a_png_name():
    assert cli._default_out("grid", [Path("c1.png")] * 3, still=True) == Path("c1-grid3.png")
    assert cli._default_out("side", [Path("a.png"), Path("b.png")], still=True) == Path("a-vs-b.png")


def test_images_cannot_be_written_as_a_video():
    with pytest.raises(SystemExit, match="name it out.png"):
        cli._check_images("grid", _args(), [image(), image()], Path("out.mp4"))


def test_video_cannot_be_written_as_an_image():
    with pytest.raises(SystemExit, match="use .mp4"):
        cli._check_images("grid", _args(), [image(), clip()], Path("out.png"))


@pytest.mark.parametrize("mode", ["wipe", "pip"])
def test_wipe_and_pip_refuse_images(mode):
    with pytest.raises(SystemExit, match="use side or grid"):
        cli._check_images(mode, _args(), [image(), clip()], None)


def test_group_and_html_refuse_all_images():
    with pytest.raises(SystemExit, match="--group"):
        cli._check_images("grid", _args(group=2), images(4), None)
    with pytest.raises(SystemExit, match="--html"):
        cli._check_images("grid", _args(html=Path("x.html")), images(2), None)


def test_images_end_to_end(tmp_path):
    """A real ffmpeg render of two generated stills."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    for name, color in (("a.png", "red"), ("b.png", "blue")):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=320x240", "-frames:v", "1",
             str(tmp_path / name)],
            check=True,
        )
    out = tmp_path / "out.png"
    assert cli.main(["grid", str(tmp_path / "a.png"), str(tmp_path / "b.png"), "--title", "T", "-o", str(out)]) == 0
    from clipcompare.probe import probe

    info = probe(out)
    assert info.is_image and info.width > info.height
