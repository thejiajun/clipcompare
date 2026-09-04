"""wipe mode — the xfade custom expression and its timing."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipcompare.modes.wipe import (
    DEFAULT_WIPE_DUR,
    Options,
    build,
    output_size,
    resolve_start,
    wipe_expression,
)

from helpers import clip, graph


def opts(**kwargs) -> Options:
    return Options(out=Path("out.mp4"), **kwargs)


def test_output_keeps_the_first_clip_size_by_default():
    assert output_size(clip(1920, 1080), 0) == (1920, 1080)
    assert output_size(clip(3840, 2160), 0) == (3840, 2160)


def test_panel_rescales_by_short_edge():
    assert output_size(clip(3840, 2160), 1080) == (1920, 1080)
    assert output_size(clip(1080, 1920), 540) == (540, 960)


def test_output_dimensions_are_even():
    width, height = output_size(clip(1001, 1999), 641)
    assert width % 2 == 0 and height % 2 == 0


@pytest.mark.parametrize(
    "pace,duration,expected",
    [
        ("early", 3.0, 0.66),      # 22% of 3s, inside the clamp
        ("early", 10.0, 0.9),      # clamped at the top
        ("early", 1.0, 0.4),       # clamped at the bottom
        ("balanced", 3.0, 0.9),
        ("late", 3.0, 1.35),
    ],
)
def test_pace_presets_place_the_sweep(pace, duration, expected):
    assert resolve_start(duration, pace, None) == pytest.approx(expected, abs=0.01)


def test_snappy_is_an_alias_of_early():
    assert resolve_start(3.0, "snappy", None) == resolve_start(3.0, "early", None)


def test_explicit_start_accepts_seconds_and_percent():
    assert resolve_start(10.0, "early", "0.9") == pytest.approx(0.9)
    assert resolve_start(10.0, "early", "30%") == pytest.approx(3.0)


def test_easing_is_inlined_because_st_ld_races_across_xfade_threads():
    # xfade evaluates slices on threads that share the expression registers, so
    # st()/ld() there produces white-pixel speckle. The easing must be repeated
    # inline instead.
    body = graph(build(clip(), clip(), opts()).command)
    assert "st(" not in body
    assert "ld(" not in body


def test_easing_is_driven_off_one_minus_p_not_p():
    # xfade's custom-expr P runs 1 -> 0, so easing on raw P inverts the sweep.
    expression = wipe_expression("lr", 1.5)
    assert "1-P" in expression
    assert "pow(2*P" not in expression


@pytest.mark.parametrize(
    "direction,axis,comparison",
    [("lr", "X", "lt"), ("rl", "X", "gt"), ("tb", "Y", "lt"), ("bt", "Y", "gt")],
)
def test_each_direction_picks_the_right_axis_and_side(direction, axis, comparison):
    expression = wipe_expression(direction, 1.5)
    assert f"abs({axis}-" in expression
    assert f"{comparison}({axis}," in expression


def test_stroke_is_painted_white_across_luma_and_chroma():
    assert "if(eq(PLANE,0),255,128)" in wipe_expression("lr", 1.5)


def test_second_clip_is_pretrimmed_so_the_sweep_stays_time_synced():
    body = graph(build(clip(duration=4.0), clip(duration=4.0), opts(pace="early")).command)
    start = resolve_start(4.0, "early", None)
    assert f"trim=start={start:.3f}" in body
    assert "setpts=PTS-STARTPTS" in body


def test_sweep_offset_matches_the_trim_point():
    plan = build(clip(duration=4.0), clip(duration=4.0), opts())
    body = graph(plan.command)
    start = resolve_start(4.0, "early", None)
    assert f"offset={start:.3f}" in body
    assert f"trim=start={start:.3f}" in body


def test_sweep_is_pulled_back_so_it_fits_inside_the_clip():
    plan = build(clip(duration=0.5), clip(duration=0.5), opts(wipe_dur=0.35))
    assert "offset=0.150" in graph(plan.command)


def test_stroke_scales_with_output_height():
    thin = build(clip(1920, 1080), clip(1920, 1080), opts(stroke=3))
    assert "stroke=3px" in thin.detail
    thick = build(clip(3840, 2160), clip(3840, 2160), opts(stroke=3))
    assert "stroke=6px" in thick.detail


def test_labels_swap_in_place_around_the_sweep(tmp_path):
    font = (Path("/f/Mono.ttf"), Path("/f/Mono.ttf"))
    plan = build(
        clip(duration=4.0), clip(duration=4.0),
        opts(labels=("BEFORE", "AFTER"), fonts=font),
        tmp_path,
    )
    body = graph(plan.command)
    start = resolve_start(4.0, "early", None)
    assert f"enable='lt(t,{start:.3f})'" in body
    assert f"enable='gte(t,{start + DEFAULT_WIPE_DUR:.3f})'" in body
    assert (tmp_path / "a.txt").read_text() == "BEFORE"


def test_trim_to_caps_the_output():
    cmd = build(clip(), clip(), opts(trim_to=2.5)).command
    assert cmd[cmd.index("-t") + 1] == "2.500"


def test_no_trim_flag_without_trim_to():
    assert "-t" not in build(clip(), clip(), opts()).command


def test_snappy_renders_identically_to_early_because_it_is_an_alias():
    # Listed in --pace for muscle memory only; it must not drift into being a
    # fourth setting that silently differs from early.
    early = build(clip(duration=5.0), clip(duration=5.0), opts(pace="early")).command
    snappy = build(clip(duration=5.0), clip(duration=5.0), opts(pace="snappy")).command
    assert early == snappy
