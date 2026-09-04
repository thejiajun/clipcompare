"""pip mode — inset geometry and the ffmpeg-generated rounded mask."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipcompare.modes.pip import (
    Options,
    build,
    main_size,
    mask_command,
    rounded_mask_expression,
)

from helpers import clip, graph


def opts(**kwargs) -> Options:
    return Options(out=Path("out.mp4"), **kwargs)


def _placement(body: str) -> tuple[int, int]:
    """Where the inset box lands on the main frame — the last overlay."""
    step = [s for s in body.split(";") if s.startswith("[vmain]")][0]
    x, y = step.split("overlay=")[1].split(":shortest")[0].split(":")
    return int(x), int(y)


def test_main_clip_is_the_one_not_inset():
    # inset=a means clip B is full frame, so the output takes B's size.
    plan = build(clip(1080, 1920), clip(1920, 1080), opts(inset="a"))
    assert (plan.out_w, plan.out_h) == (1920, 1080)
    plan = build(clip(1080, 1920), clip(1920, 1080), opts(inset="b"))
    assert (plan.out_w, plan.out_h) == (1080, 1920)


def test_main_size_keeps_resolution_by_default_and_rescales_on_panel():
    assert main_size(clip(3840, 2160), 0) == (3840, 2160)
    assert main_size(clip(3840, 2160), 1080) == (1920, 1080)


def test_inset_stream_is_the_chosen_clip():
    body = graph(build(clip(), clip(), opts(inset="a")).command)
    assert body.startswith("[1:v]")   # main is B
    body = graph(build(clip(), clip(), opts(inset="b")).command)
    assert body.startswith("[0:v]")   # main is A


@pytest.mark.parametrize(
    "corner,expect_left,expect_top",
    [("tl", True, True), ("tr", False, True), ("bl", True, False), ("br", False, False)],
)
def test_corner_placement(corner, expect_left, expect_top):
    plan = build(clip(1920, 1080), clip(1920, 1080), opts(corner=corner))
    x, y = _placement(graph(plan.command))
    assert (x < 1920 / 2) is expect_left
    assert (y < 1080 / 2) is expect_top


def test_inset_box_stays_on_canvas_with_a_zero_margin():
    plan = build(clip(1920, 1080), clip(1920, 1080), opts(corner="br", margin=0.0))
    x, y = _placement(graph(plan.command))
    assert x >= 0 and y >= 0
    assert x + round(0.30 * 1920) <= 1920




def test_mask_is_looped_because_it_is_a_still():
    cmd = build(clip(), clip(), opts()).command
    assert "-loop" in cmd
    assert cmd[cmd.index("-loop") + 1] == "1"


def test_mask_expression_is_opaque_in_the_middle_and_falls_off_at_corners():
    expression = rounded_mask_expression(200, 100, 20)
    # Distance is 0 away from the corner boxes, so 255*(r+0.5) clips to opaque.
    assert "clip(" in expression
    assert "sqrt(" in expression
    assert "max(0,max(20-X" in expression


def test_mask_radius_never_exceeds_half_the_box():
    expression = rounded_mask_expression(40, 40, 999)
    assert "max(0,max(20-X" in expression  # clamped to half of 40


def test_mask_command_renders_a_single_grayscale_frame(tmp_path):
    cmd = mask_command(tmp_path / "m.png", 120, 80, 12)
    assert cmd[cmd.index("-frames:v") + 1] == "1"
    assert "format=gray" in cmd[cmd.index("-vf") + 1]
    assert "color=c=black:s=120x80" in " ".join(cmd)


def test_radius_and_stroke_scale_with_output_height():
    small = build(clip(1920, 1080), clip(1920, 1080), opts(radius=22, stroke=3))
    assert "radius=22px" in small.detail and "stroke=3px" in small.detail
    large = build(clip(3840, 2160), clip(3840, 2160), opts(radius=22, stroke=3))
    assert "radius=44px" in large.detail and "stroke=6px" in large.detail


def test_inset_label_is_sized_off_the_inset_not_the_main_frame(tmp_path):
    font = (Path("/f/Mono.ttf"), Path("/f/Mono.ttf"))
    plan = build(
        clip(1920, 1080), clip(1920, 1080),
        opts(labels=("SMALL", "BIG"), fonts=font, inset="a"),
        tmp_path,
    )
    body = graph(plan.command)
    sizes = [int(part.split("=")[1]) for part in body.split(":") if part.startswith("fontsize=")]
    assert len(sizes) == 2
    assert min(sizes) < max(sizes)  # the inset's label is the smaller one


def test_labels_follow_which_clip_is_inset(tmp_path):
    font = (Path("/f/Mono.ttf"), Path("/f/Mono.ttf"))
    for inset in ("a", "b"):
        plan = build(
            clip(1920, 1080), clip(1920, 1080),
            opts(labels=("AAA", "BBB"), fonts=font, inset=inset),
            tmp_path,
        )
        assert (tmp_path / "a.txt").read_text() == "AAA"
        assert (tmp_path / "b.txt").read_text() == "BBB"
        assert "drawtext" in graph(plan.command)


# --- regressions found by real-video testing -------------------------------

def test_stroke_zero_means_no_border_not_a_hairline():
    # It used to be clamped to a minimum of 1, leaving an asymmetric 1px edge.
    plan = build(clip(1920, 1080), clip(1920, 1080), opts(stroke=0))
    assert "stroke=0px" in plan.detail
    body = graph(plan.command)
    assert "[plate]" not in body          # no border plate at all
    assert len(plan.pre_commands) == 1    # only the picture mask


def test_border_uses_two_masks_so_the_band_survives_the_corners():
    # One shared mask cuts ~0.29*(R+stroke) into a corner, far deeper than the
    # border is thick, which sliced the band off the arcs entirely.
    plan = build(clip(1920, 1080), clip(1920, 1080), opts(radius=22, stroke=3))
    assert len(plan.pre_commands) == 2
    joined = [" ".join(c) for c in plan.pre_commands]
    inner = [c for c in joined if "pip-mask-inner" in c][0]
    outer = [c for c in joined if "pip-mask-outer" in c][0]
    # The outer mask is rounded one stroke wider than the picture's own radius.
    assert "max(0,max(22-X" in inner
    assert "max(0,max(25-X" in outer


def test_picture_is_inset_by_the_stroke_so_the_plate_shows_as_the_border():
    body = graph(build(clip(1920, 1080), clip(1920, 1080), opts(stroke=3)).command)
    assert "[platei][vinsr]overlay=3:3:shortest=1" in body


def test_every_mask_alphamerge_is_shortest_because_masks_never_end():
    # -loop 1 masks are infinite; without shortest the inset stream inherits
    # that and the final overlay loses its end condition (renders forever).
    body = graph(build(clip(), clip(), opts()).command)
    assert "alphamerge" in body
    assert body.count("alphamerge=shortest=1") == body.count("alphamerge")


def test_freeze_padding_lands_on_the_shorter_stream_for_either_inset_choice():
    short, long_ = clip(duration=5.0), clip(duration=15.0)
    # inset=a -> main is b (the long one), so the pad belongs to the inset.
    body = graph(build(short, long_, opts(inset="a", length="longest")).command)
    assert "tpad" in body.split("[vins]")[0].split("[vmain]")[1]
    # inset=b -> main is a (the short one), so the pad belongs to the main.
    body = graph(build(short, long_, opts(inset="b", length="longest")).command)
    assert "tpad" in body.split("[vmain]")[0]


def test_shortest_still_passes_the_output_flag():
    assert "-shortest" in build(clip(), clip(), opts(length="shortest")).command
    assert "-shortest" not in build(clip(), clip(), opts(length="longest")).command


def test_main_label_moves_down_when_the_inset_takes_the_top_left(tmp_path):
    font = (Path("/f/M.ttf"), Path("/f/M.ttf"))
    body = graph(build(
        clip(1920, 1080), clip(1920, 1080),
        opts(labels=("A", "B"), fonts=font, corner="tl"), tmp_path,
    ).command)
    assert "y=h-th-" in body            # pushed to the bottom
    body = graph(build(
        clip(1920, 1080), clip(1920, 1080),
        opts(labels=("A", "B"), fonts=font, corner="tr"), tmp_path,
    ).command)
    assert "y=h-th-" not in body        # stays top-left
