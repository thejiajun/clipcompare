"""Filtergraph tests — pure `build()` output, no ffmpeg involved."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipcompare.modes.sidebyside import Options, build, panel_size, resolve_layout

from helpers import clip, graph




def opts(**kwargs) -> Options:
    return Options(out=Path("out.mp4"), **kwargs)


def test_portrait_pair_stacks_left_right_at_skill_dimensions():
    plan = build(clip(), clip(), opts())
    assert resolve_layout(clip(), "auto") == "lr"
    assert panel_size(clip(), 1080) == (1080, 1920)
    assert (plan.out_w, plan.out_h) == (2160, 1920)
    assert "hstack=inputs=2:shortest=1" in graph(plan.command)


def test_landscape_pair_stacks_top_bottom():
    plan = build(clip(1920, 1080), clip(1920, 1080), opts())
    assert resolve_layout(clip(1920, 1080), "auto") == "tb"
    assert (plan.out_w, plan.out_h) == (1920, 2160)
    assert "vstack=inputs=2:shortest=1" in graph(plan.command)


def test_panel_is_the_short_edge():
    plan = build(clip(720, 1280), clip(720, 1280), opts(panel=2160))
    assert panel_size(clip(720, 1280), 2160) == (2160, 3840)
    assert (plan.out_w, plan.out_h) == (4320, 3840)


def test_square_clips_go_side_by_side():
    plan = build(clip(1080, 1080), clip(1080, 1080), opts())
    assert resolve_layout(clip(1080, 1080), "auto") == "lr"
    assert (plan.out_w, plan.out_h) == (2160, 1080)


def test_layout_override_wins_over_orientation():
    plan = build(clip(1920, 1080), clip(1920, 1080), opts(layout="lr"))
    assert "lr" in plan.detail
    assert (plan.out_w, plan.out_h) == (3840, 1080)


def test_odd_derived_panel_size_is_rounded_even():
    build(clip(1001, 1999), clip(1001, 1999), opts(panel=641))
    width, height = panel_size(clip(1001, 1999), 641)
    assert width % 2 == 0
    assert height % 2 == 0


def test_cover_crops_and_contain_pads():
    assert "crop=1080:1920" in graph(build(clip(), clip(), opts(fit="cover")).command)
    padded = graph(build(clip(), clip(), opts(fit="contain")).command)
    assert "pad=1080:1920" in padded
    assert "force_original_aspect_ratio=decrease" in padded


def test_output_frame_rate_follows_the_faster_clip_as_an_exact_rational():
    plan = build(clip(fps="24/1"), clip(fps="30000/1001"), opts())
    assert plan.fps == "30000/1001"
    assert "fps=30000/1001" in graph(plan.command)


def test_explicit_fps_overrides_both_clips():
    plan = build(clip(fps="24/1"), clip(fps="60/1"), opts(fps="25"))
    assert "fps=25," in graph(plan.command)


def test_shortest_trims_and_adds_no_padding():
    cmd = build(clip(duration=3.0), clip(duration=4.0), opts(length="shortest")).command
    assert "tpad" not in graph(cmd)
    assert "-shortest" in cmd


def test_longest_freezes_the_shorter_clip_only():
    cmd = build(clip(duration=3.0), clip(duration=4.0), opts(length="longest")).command
    body = graph(cmd)
    assert "tpad=stop_mode=clone:stop_duration=1.000" in body
    assert body.count("tpad") == 1
    assert body.split("[va]")[0].count("tpad") == 1  # padding landed on clip A
    assert "shortest=0" in body
    assert "-shortest" not in cmd


def test_near_equal_durations_are_not_padded():
    cmd = build(clip(duration=3.00), clip(duration=3.02), opts(length="longest")).command
    assert "tpad" not in graph(cmd)


def test_audio_both_falls_back_when_only_one_clip_has_sound():
    plan = build(clip(audio=False), clip(audio=True), opts(audio="both"))
    assert plan.audio == "b"
    assert "amix" not in graph(plan.command)
    assert plan.command[plan.command.index("-map", plan.command.index("-map") + 1) + 1] == "1:a"


def test_audio_both_mixes_when_both_have_sound():
    plan = build(clip(audio=True), clip(audio=True), opts(audio="both"))
    assert plan.audio == "both"
    assert "amix=inputs=2:duration=shortest[aout]" in graph(plan.command)


def test_audio_request_for_a_silent_clip_becomes_none():
    plan = build(clip(audio=False), clip(audio=False), opts(audio="a"))
    assert plan.audio == "none"
    assert "-an" in plan.command


def test_divider_is_drawn_between_panels_and_can_be_disabled():
    body = graph(build(clip(), clip(), opts(divider=4)).command)
    assert "drawbox=x=1078:y=0:w=4:h=ih" in body
    assert "drawbox" not in graph(build(clip(), clip(), opts(divider=0)).command)


def test_divider_scales_with_panel_size():
    body = graph(build(clip(), clip(), opts(panel=2160, divider=4)).command)
    assert "w=8:h=ih" in body


def test_no_labels_leaves_drawtext_out(tmp_path):
    body = graph(build(clip(), clip(), opts(labels=None), tmp_path).command)
    assert "drawtext" not in body


def test_labels_are_written_to_files_and_never_inlined(tmp_path):
    plan = build(
        clip(), clip(),
        opts(labels=("ORIGINAL", "EDITED"), fonts=(Path("/fonts/Mono.ttf"), Path("/fonts/Mono.ttf"))),
        tmp_path,
    )
    body = graph(plan.command)
    assert "textfile=" in body
    assert "text=ORIGINAL" not in body
    assert (tmp_path / "a.txt").read_text() == "ORIGINAL"
    assert (tmp_path / "b.txt").read_text() == "EDITED"
    assert "expansion=none" in body


def test_label_text_with_ffmpeg_expansion_syntax_stays_literal(tmp_path):
    build(
        clip(), clip(),
        opts(labels=("WEIRD %{n} NAME", "B"), fonts=(Path("/fonts/Mono.ttf"), Path("/fonts/Mono.ttf"))),
        tmp_path,
    )
    assert (tmp_path / "a.txt").read_text() == "WEIRD %{n} NAME"


def test_second_label_is_right_aligned_side_by_side_and_left_aligned_stacked(tmp_path):
    font = (Path("/fonts/Mono.ttf"), Path("/fonts/Mono.ttf"))
    lr = graph(build(clip(), clip(), opts(labels=("A", "B"), fonts=font), tmp_path).command)
    assert "x=w-tw-" in lr
    tb = graph(
        build(
            clip(1920, 1080), clip(1920, 1080),
            opts(labels=("A", "B"), fonts=font), tmp_path,
        ).command
    )
    assert "x=w-tw-" not in tb
    assert "y=1145" in tb  # panel height 1080 + inset 48 + box padding 17


def test_font_path_with_filtergraph_metacharacters_is_escaped(tmp_path):
    plan = build(
        clip(), clip(),
        opts(labels=("A", "B"), fonts=(Path("/od d:fonts/Mono.ttf"),) * 2),
        tmp_path,
    )
    assert "/od d\\:fonts/Mono.ttf" in graph(plan.command)


@pytest.mark.parametrize("crf,preset", [(18, "medium"), (23, "veryfast")])
def test_encode_settings_are_passed_through(crf, preset):
    cmd = build(clip(), clip(), opts(crf=crf, preset=preset)).command
    assert cmd[cmd.index("-crf") + 1] == str(crf)
    assert cmd[cmd.index("-preset") + 1] == preset


def test_filtergraph_labels_form_one_connected_chain():
    body = graph(build(clip(), clip(), opts()).command)
    assert body.endswith("[v]")
    assert body.count("[st]") == 2  # produced once, consumed once
