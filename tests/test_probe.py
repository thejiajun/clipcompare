"""blackdetect log parsing — no ffmpeg involved."""

from __future__ import annotations

import json
import subprocess

import pytest

from clipcompare.probe import AUDIO_PANEL, ProbeError, parse_lead_in_black, probe


def test_black_at_the_start_reports_where_picture_begins():
    log = "[blackdetect @ 0x1] black_start:0 black_end:0.112029 black_duration:0.112029\n"
    assert parse_lead_in_black(log) == 0.112029


def test_black_from_a_first_frame_just_after_zero_is_a_lead_in():
    log = "[blackdetect @ 0x1] black_start:0.0433333 black_end:0.0645 black_duration:0.021\n"
    assert parse_lead_in_black(log) == 0.0645


def test_black_later_in_the_clip_is_not_a_lead_in():
    log = "[blackdetect @ 0x1] black_start:1.5 black_end:2 black_duration:0.5\n"
    assert parse_lead_in_black(log) == 0.0


def test_no_black_at_all_is_zero():
    assert parse_lead_in_black("frame=  80 fps=0.0 q=-0.0 size=N/A\n") == 0.0


def _ffprobe_says(monkeypatch, streams, duration="5.0"):
    payload = json.dumps({"streams": streams, "format": {"duration": duration}})
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=payload, stderr=""),
    )


def test_a_file_with_only_sound_is_an_audio_clip(monkeypatch, tmp_path):
    _ffprobe_says(monkeypatch, [{"codec_type": "audio", "duration": "6.01"}], duration="6.0")
    info = probe(tmp_path / "voice.mp3")
    assert info.is_audio and info.has_audio
    assert (info.width, info.height) == (AUDIO_PANEL, AUDIO_PANEL)
    assert info.duration == 6.01


def test_cover_art_does_not_make_an_mp3_a_video(monkeypatch, tmp_path):
    _ffprobe_says(monkeypatch, [
        {"codec_type": "audio"},
        {"codec_type": "video", "width": 600, "height": 600, "disposition": {"attached_pic": 1}},
    ])
    assert probe(tmp_path / "song.mp3").is_audio


def test_a_real_video_stream_is_still_a_video(monkeypatch, tmp_path):
    _ffprobe_says(monkeypatch, [
        {"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
        {"codec_type": "audio"},
    ])
    info = probe(tmp_path / "clip.mp4")
    assert not info.is_audio and (info.width, info.height) == (1080, 1920)


def test_nothing_to_show_or_hear_is_an_error(monkeypatch, tmp_path):
    _ffprobe_says(monkeypatch, [{"codec_type": "data"}])
    with pytest.raises(ProbeError, match="no video or audio"):
        probe(tmp_path / "empty.bin")
