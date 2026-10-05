"""The info layer: recipe and measured fields, said once when shared, per tile when not."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from clipcompare import cli, info, manifest, stats
from clipcompare.modes import grid

from helpers import clip, graph

FONT = Path(__file__).resolve().parents[1] / "src" / "clipcompare" / "assets" / "TikTokSans-Medium.ttf"


def measured(bitrate=13_000_000, duration=5.6, size=9_100_000, width=720):
    return {
        "kind": "video", "width": width, "height": 1280, "fps": 30.0, "duration": duration,
        "video_codec": "h264", "pix_fmt": "yuv420p", "video_bitrate": bitrate, "audio_codec": None, "size": size,
    }


def test_shared_fields_go_to_the_title_bar_and_differences_to_the_tiles():
    run = info.describe(
        [{"model": "kling", "params": {"fit": "none", "cfg": 0.5}}, {"model": "kling", "params": {"fit": "crf", "cfg": 0.5}}],
        [measured(), measured(bitrate=5_100_000, size=3_600_000)],
        [None, {"ssim": 0.987, "psnr": 45.4}],
        baseline=0,
    )
    assert [item.text for item in run.shared] == ["kling", "cfg 0.5", "720×1280", "30 fps", "5.60 s", "h264 yuv420p", "no audio"]
    base, other = run.tiles
    assert [item.text for item in other.recipe] == ["fit crf"] and other.recipe[0].accent
    assert not base.recipe[0].accent
    assert [item.text for item in other.measured] == ["5.1 Mbps −61%", "3.6 MB −60%"]
    assert [item.text for item in base.similarity] == ["baseline"]
    assert [(item.text, item.tone) for item in other.similarity] == [("SSIM 0.987", "good"), ("PSNR 45.4 dB", "good")]
    assert other.differences == 3 and base.differences == 0


def test_params_are_diffed_key_by_key_whatever_the_keys():
    run = info.describe([{"params": {"a": 1}}, {"params": {"b": 1}}], [None, None], [None, None], baseline=0)
    assert [(i.text, i.accent) for i in run.tiles[1].recipe] == [("b 1", True)]
    assert run.tiles[1].differences == 2   # b is new, a is missing


def test_without_a_baseline_nothing_is_marked_or_compared():
    run = info.describe([{"seed": 1}, {"seed": 2}], [measured(), measured(bitrate=1)], [None, None], baseline=None)
    assert all(not item.accent for tile in run.tiles for item in tile.recipe)
    assert "−" not in run.tiles[1].measured[0].text   # no delta without a baseline
    assert run.tiles[0].differences is None


@pytest.mark.parametrize("key,value,expected", [("ssim", 0.99, "good"), ("ssim", 0.93, ""), ("psnr", 25, "bad"), ("snr", 31, "good")])
def test_only_similarity_gets_a_good_or_bad_colour(key, value, expected):
    assert info.tone(key, value) == expected


def test_identical_and_scaled_comparisons_say_so():
    run = info.describe([None, None], [measured(), measured(width=1080)], [None, {"psnr": float("inf"), "scaled_to": "720x1280"}], 0)
    texts = [item.text for item in run.tiles[1].similarity]
    assert texts == ["PSNR identical", "at 720×1280"]


def test_cost_and_seed_read_like_a_recipe():
    fields = info._recipe_fields({"cost": 0.42, "seed": 7, "preset": "pro"})
    assert [text for _, text, _ in fields] == ["pro", "$0.42", "seed 7"]


def test_manifest_reads_recipes_and_stats(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"stats": True, "clips": [
        {"file": "a.mp4", "model": "m", "params": {"x": True}, "cost": 1},
        {"file": "a.mp4"},
    ]}))
    spec = manifest.read(path)
    assert spec.stats and spec.recipes == ({"model": "m", "params": {"x": True}, "cost": 1}, None)
    path.write_text(json.dumps({"clips": [{"file": "a.mp4", "params": [1]}]}))
    with pytest.raises(manifest.ManifestError, match="params"):
        manifest.read(path)


def test_probe_numbers_come_from_ffprobe_json():
    data = {"format": {"duration": "5.6", "bit_rate": "13000000", "format_name": "mov,mp4"}, "streams": [
        {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 720, "height": 1280,
         "avg_frame_rate": "30/1", "bit_rate": "13025055"},
    ]}
    out = stats.parse(data, 9_119_652)
    assert out["kind"] == "video" and out["video_bitrate"] == 13025055 and out["fps"] == 30.0 and out["audio_codec"] is None
    image = stats.parse({"format": {"format_name": "png_pipe"}, "streams": [
        {"codec_type": "video", "codec_name": "png", "pix_fmt": "rgb24", "width": 10, "height": 10}]}, 100)
    assert image["kind"] == "image" and image["format"] == "png" and "fps" not in image


def test_same_take_only_when_lengths_match():
    a = {"audio_codec": "aac", "duration": 10.0}
    assert stats.same_take(a, {"audio_codec": "mp3", "duration": 10.05})
    assert not stats.same_take(a, {"audio_codec": "mp3", "duration": 11.0})
    assert not stats.same_take(a, {"audio_codec": None, "duration": 10.0})


def test_grid_paints_recipe_and_measured_strips_and_a_shared_line(tmp_path):
    run = info.describe([{"model": "m", "seed": 1}, {"model": "m", "seed": 2}], [measured(), measured(bitrate=1_000_000)],
                        [None, {"ssim": 0.5}], 0)
    plain = grid.build([clip(), clip()], grid.Options(out=tmp_path / "o.mp4"), tmp_path)
    plan = grid.build([clip(), clip()], grid.Options(out=tmp_path / "o.mp4", info=run, info_font=FONT), tmp_path)
    body = graph(plan.command)
    assert "shared.txt" in body and (tmp_path / "shared.txt").read_text().startswith("m · ")
    assert sum(cmd[-1].endswith(("recipe-0.png", "recipe-1.png", "measured-0.png", "measured-1.png")) for cmd in plan.pre_commands) == 4
    assert plan.out_h == plain.out_h + grid.shared_px(min(plain.out_w, plain.out_h))


def test_tabular_digits_share_one_advance():
    layout = info._Layout(FONT, 20)
    one = layout.width([info.Span("1111", "white", tabular=True)])
    eight = layout.width([info.Span("8888", "white", tabular=True)])
    assert one == eight


def test_stats_end_to_end_writes_the_sidecar(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    for name, crf in (("a.mp4", 10), ("b.mp4", 40)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1",
                        "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", str(tmp_path / name)], check=True)
    out = tmp_path / "o.mp4"
    assert cli.main(["grid", str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4"), "--stats", "--baseline", "1", "-o", str(out)]) == 0
    report = json.loads((tmp_path / "o.mp4.stats.json").read_text())
    group = report["groups"][0]
    assert group["baseline"] == 0 and "320×240" in group["shared"]
    other = group["clips"][1]
    assert other["measured"]["video_bitrate"] < group["clips"][0]["measured"]["video_bitrate"]
    assert 0 < other["vs_baseline"]["ssim"] < 1 and other["vs_baseline"]["psnr"] > 10
    assert other["tile"]["similarity"][0]["key"] == "ssim"
