"""Filtergraph tests for grid — pure `build()` output, no ffmpeg involved."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipcompare.modes.grid import Options, build, build_groups, grid_shape, tile_size
from clipcompare.probe import ProbeError

from helpers import clip, graph, sound


def opts(**kwargs) -> Options:
    return Options(out=Path("out.mp4"), **kwargs)


def clips(count, **kwargs):
    return [clip(name=f"c{index}.mp4", **kwargs) for index in range(count)]


def inputs(cmd: list[str]) -> list[str]:
    return [cmd[index + 1] for index, arg in enumerate(cmd) if arg == "-i"]


@pytest.mark.parametrize(
    "count,aspect,expected",
    [
        (19, 1080 / 1920, (7, 3)),  # portrait tiles: wide rows, no empty column left over
        (4, 1920 / 1080, (2, 2)),
        (2, 1080 / 1920, (2, 1)),
        (9, 1.0, (3, 3)),  # 4 columns would leave one empty; 3x3 fills every cell
    ],
)
def test_auto_shape_aims_the_canvas_at_16_by_9(count, aspect, expected):
    assert grid_shape(count, aspect) == expected


def test_one_fixed_dimension_derives_the_other():
    assert grid_shape(19, 0.5625, cols=5) == (5, 4)
    assert grid_shape(19, 0.5625, rows=2) == (10, 2)
    assert grid_shape(4, 1.0, cols=3, rows=3) == (3, 3)


def test_auto_tile_keeps_tiles_and_gaps_within_4k_and_even():
    width, height, short, gap = tile_size(clip(), 7, 3, 0, 4)
    assert 7 * width + 6 * gap <= 3840
    assert 3 * height + 2 * gap <= 3840
    assert width % 2 == 0 and height % 2 == 0 and gap % 2 == 0
    assert short == width


def test_auto_tile_never_grows_past_1080():
    assert tile_size(clip(), 2, 1, 0)[2] == 1080


def test_a_given_panel_is_kept_even_if_the_canvas_runs_past_4k():
    assert tile_size(clip(), 7, 3, 1080, 4)[0] == 1080


def test_tiles_are_laid_out_in_reading_order_with_gaps():
    plan = build(clips(3), opts(cols=2, panel=540, gap=4))
    body = graph(plan.command)
    # panel 540 -> 540x960 tiles, a 4 px gap at 1080p becomes 2 px here
    assert "xstack=inputs=3:layout=0_0|542_0|0_962:fill=black:shortest=1[st]" in body
    assert (plan.out_w, plan.out_h) == (540 * 2 + 2, 960 * 2 + 2)
    assert "2x2" in plan.detail


def test_gap_zero_butts_tiles_together():
    body = graph(build(clips(2), opts(panel=540, gap=0)).command)
    assert "layout=0_0|540_0" in body


def test_longest_freezes_every_shorter_clip():
    body = graph(build(
        [clip(duration=3.0), clip(duration=5.0), clip(duration=4.0)], opts(length="longest"),
    ).command)
    assert "[0:v]" in body and "stop_duration=2.000[t0]" in body
    assert "stop_duration=1.000[t2]" in body
    assert body.count("tpad") == 2
    assert "shortest=0" in body


def test_sequential_plays_one_tile_at_a_time_from_a_still():
    plan = build(
        [clip(duration=3.0, name="a.mp4"), clip(duration=4.0, name="b.mp4"), clip(duration=2.0, name="c.mp4")],
        opts(sequential=True, holds=(0.0, 0.1, 0.2)),
    )
    body, cmd = graph(plan.command), plan.command
    assert inputs(cmd) == ["a.mp4", "b.mp4", "c.mp4", "b.mp4", "c.mp4"]
    assert cmd[cmd.index("b.mp4", cmd.index("c.mp4")) - 5 : cmd.index("b.mp4", cmd.index("c.mp4"))] == [
        "-ss", "0.100", "-t", "1", "-i",
    ]
    # turns: a 0-3, b 3-6.9, c 6.9-8.7 of 8.7 s
    assert "[0:v]" in body and "trim=start=0.000,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=5.700[t0]" in body
    assert "[3:v]" in body and "stop_duration=2.967[w1]" in body
    assert "[w1][p1]concat=n=2:v=1:a=0[t1]" in body
    assert "[4:v]" in body and "stop_duration=6.867[w2]" in body
    assert "enable='between(t,3.000,6.900)'" in body
    assert "-shortest" not in cmd


def test_sequential_sound_follows_the_playing_tile():
    plan = build(
        [clip(duration=3.0, audio=True), clip(duration=4.0, audio=False)],
        opts(sequential=True, holds=(0.0, 0.5)),
    )
    body = graph(plan.command)
    assert plan.audio == "follow"
    assert "[0:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0.000:3.000" in body
    assert "anullsrc=r=48000:cl=stereo,atrim=0.500:4.000" in body
    assert "[s0][s1]concat=n=2:v=0:a=1[aout]" in body


def test_sequential_needs_every_duration():
    with pytest.raises(ProbeError):
        build([clip(), clip(duration=0.0)], opts(sequential=True))


def test_auto_audio_at_once_is_the_first_clip_with_sound():
    plan = build([clip(audio=False), clip(audio=True), clip(audio=True)], opts())
    assert plan.audio == "2"
    assert plan.command[plan.command.index("1:a") - 1] == "-map"


def test_audio_mix_and_numbered_and_none():
    three = [clip(audio=True), clip(audio=False), clip(audio=True)]
    mixed = build(three, opts(audio="mix"))
    assert "[0:a][2:a]amix=inputs=2:duration=shortest[aout]" in graph(mixed.command)
    assert build(three, opts(audio="3")).audio == "3"
    assert build(three, opts(audio="2")).audio == "none"
    assert "-an" in build(three, opts(audio="none")).command


def test_head_cuts_every_input_and_every_turn():
    plan = build(
        [clip(duration=10.0, audio=True, name="a.mp4"), clip(duration=3.0, audio=True, name="b.mp4")],
        opts(sequential=True, head=5.0),
    )
    cmd, body = plan.command, graph(plan.command)
    assert cmd[cmd.index("a.mp4") - 3 : cmd.index("a.mp4")] == ["-t", "5.000", "-i"]
    assert cmd[cmd.index("b.mp4") - 3 : cmd.index("b.mp4")] == ["-t", "5.000", "-i"]
    assert "atrim=0.000:5.000" in body  # a cut to 5 s
    assert "atrim=0.000:3.000" in body  # b already shorter
    assert "enable='between(t,5.000,8.000)'" in body


def test_one_label_per_tile(tmp_path):
    plan = build(
        clips(3),
        opts(labels=("ZH", "JA", "ES"), fonts=(Path("/fonts/Mono.ttf"),) * 3, panel=540),
        tmp_path,
    )
    body = graph(plan.command)
    assert body.count("drawtext=") == 3
    assert [(tmp_path / f"label-{index}.txt").read_text() for index in range(3)] == ["ZH", "JA", "ES"]


def test_filtergraph_is_one_connected_chain():
    body = graph(build(clips(4), opts()).command)
    assert body.endswith("[v]")
    assert body.count("[st]") == 2


def test_audio_clips_become_waveform_tiles_filling_a_1080p_row():
    plan = build([sound(name="v3.mp3"), sound(name="v4.mp3")], opts())
    body = graph(plan.command)
    assert (plan.out_w, plan.out_h) == (1920, 1080)
    # the waveform is a band along the bottom, leaving the top for label and prompt
    assert "[0:a]aresample=48000,aformat=channel_layouts=mono,showwaves=s=958x324" in body
    assert "overlay=0:713:shortest=1" in body
    assert "[1:a]" in body and "[0:v]" not in body and "[1:v]" not in body
    assert "[wave0]fps=30,scale=958:1080" in body


def test_four_audio_clips_share_one_row_and_five_wrap():
    assert "4x1" in build([sound()] * 4, opts()).detail
    assert "3x2" in build([sound()] * 5, opts()).detail


def test_sequential_audio_lines_move_only_in_their_turn_with_a_pause_between():
    plan = build(
        [sound(duration=3.0, name="a.mp3"), sound(duration=4.0, name="b.mp3")],
        opts(sequential=True, pause=0.5),
    )
    body, cmd = graph(plan.command), plan.command
    assert inputs(cmd) == ["a.mp3", "b.mp3"]  # no still reads for a waveform
    # a 0-3, pause, b 3.5-7.5
    assert "[0:a]aresample=48000,aformat=channel_layouts=mono,apad=whole_dur=7.500,showwaves" in body
    assert "[1:a]aresample=48000,aformat=channel_layouts=mono,adelay=delays=3500:all=1,apad=whole_dur=7.500" in body
    assert "enable='between(t,3.500,7.500)'" in body
    # the sound carries the pause as silence after a's turn, none after the last
    assert "apad,atrim=0.000:3.500,asetpts" in body
    assert "apad,atrim=0.000:4.000,asetpts" in body


def test_mixed_audio_and_video_tiles_follow_the_video_shape():
    plan = build([clip(audio=True), sound()], opts(sequential=True))
    body = graph(plan.command)
    assert "[0:v]" in body and "showwaves=s=1080x" in body
    assert "adelay=delays=3000" in body


def test_title_sits_in_a_header_strip_above_the_tiles(tmp_path):
    plan = build(
        [sound(), sound()], opts(title="Kali", title_font=Path("/fonts/Mono.ttf")), tmp_path,
    )
    body = graph(plan.command)
    assert (tmp_path / "title.txt").read_text() == "Kali"
    assert (plan.out_w, plan.out_h) == (1920, 1080)
    assert "pad=1920:1080:0:108:color=0x111111" in body   # tiles start under the header
    assert "x=(w-tw)/2:y=28" in body


def test_groups_render_each_run_then_join_them_by_copy(tmp_path):
    runs = [[sound(name=f"{name}-v3.mp3"), sound(name=f"{name}-v4.mp3")] for name in ("kali", "alia")]
    font = Path("/fonts/Mono.ttf")
    plan = build_groups(
        runs,
        opts(
            sequential=True, pause=0.5, labels=("V3", "V4") * 2, fonts=(font,) * 4, title_font=font,
        ),
        ("Kali", "Alia"),
        tmp_path,
    )
    assert len(plan.pre_commands) == 2
    assert "kali-v3.mp3" in plan.pre_commands[0] and "alia-v3.mp3" in plan.pre_commands[1]
    assert (tmp_path / "group-1" / "title.txt").read_text() == "Kali"
    assert (tmp_path / "group-2" / "title.txt").read_text() == "Alia"
    first, second = (graph(command) for command in plan.pre_commands)
    # a pause after the first run's last turn, none after the final run's
    assert "apad,atrim=0.000:3.500,asetpts=N/SR/TB[s1]" in first
    assert "apad,atrim=0.000:3.000,asetpts=N/SR/TB[s1]" in second
    cmd = plan.command
    assert cmd[cmd.index("-f") + 1] == "concat" and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "out.mp4"
    assert (tmp_path / "groups.txt").read_text().splitlines() == [
        f"file '{tmp_path / f'group-{number}' / 'part.mp4'}'" for number in (1, 2)
    ]
