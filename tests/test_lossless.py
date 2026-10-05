"""--lossless: clip pixels reach the output unchanged, in a .mov QuickTime plays."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from clipcompare import cli
from clipcompare.filters import lossless_pix_fmt, native_geometry
from clipcompare.modes import grid, pip, sidebyside, wipe

from helpers import clip, graph, image, sound


def video(width=720, height=1280, pix_fmt="yuv420p", **kwargs):
    return replace(clip(width, height, **kwargs), pix_fmt=pix_fmt)


@pytest.mark.parametrize(
    "formats,codec,expected",
    [
        (["yuv420p", "yuv420p"], "hevc", "yuv420p"),
        (["yuv420p", "yuv420p10le"], "hevc", "yuv420p10le"),
        (["yuv420p", "yuv444p"], "hevc", "yuv444p"),
        (["yuv422p10le", "yuv420p"], "hevc", "yuv444p10le"),
        (["yuv420p", "yuv420p"], "prores", "yuv444p10le"),
    ],
)
def test_the_output_keeps_the_widest_chroma_and_depth(formats, codec, expected):
    assert lossless_pix_fmt([video(pix_fmt=f) for f in formats], codec) == expected


def test_an_image_among_videos_needs_full_chroma():
    assert lossless_pix_fmt([video(), image()], "hevc") == "yuv444p"
    assert lossless_pix_fmt([video(), sound()], "hevc") == "yuv420p"


def test_a_clip_that_fits_is_placed_as_is_or_padded_never_scaled():
    assert native_geometry(video(), "cover", 720, 1280) == ("", False)
    place, scaled = native_geometry(video(640, 1000), "cover", 720, 1280)
    assert not scaled and place == "pad=720:1280:40:140:color=black" and "scale" not in place
    # Odd sizes lose a pixel to the even panel by cropping, not by scaling.
    place, scaled = native_geometry(video(721, 1281), "cover", 720, 1280)
    assert not scaled and place == "crop=720:1280:0:0"


def test_pad_offsets_stay_even_for_420_chroma():
    place, _ = native_geometry(video(700, 1270), "contain", 720, 1280)
    assert place.endswith(":10:4:color=black")


def test_a_larger_clip_is_scaled_with_lanczos_and_says_so():
    place, scaled = native_geometry(video(1080, 1920), "cover", 720, 1280)
    assert scaled and "flags=lanczos" in place
    plan = sidebyside.build(video(), video(1080, 1920), sidebyside.Options(out=Path("o.mov"), lossless="hevc"))
    assert len(plan.notes) == 1 and "clip 2 (1080x1920)" in plan.notes[0] and "lanczos" in plan.notes[0]


def test_side_keeps_the_first_clips_own_size_and_encodes_lossless_hevc():
    plan = sidebyside.build(
        video(), video(), sidebyside.Options(out=Path("o.mov"), lossless="hevc", audio="b"),
    )
    cmd = plan.command
    assert (plan.out_w, plan.out_h) == (1440, 1280)
    assert "scale=" not in graph(cmd) and "format=yuv420p" in graph(cmd)
    assert cmd[cmd.index("-c:v") + 1] == "libx265" and "lossless=1:log-level=error" in cmd
    assert cmd[cmd.index("-tag:v") + 1] == "hvc1"
    assert "-crf" not in cmd and plan.notes == []


def test_prores_is_4444():
    cmd = sidebyside.build(video(), video(), sidebyside.Options(out=Path("o.mov"), lossless="prores")).command
    assert cmd[cmd.index("-c:v") + 1] == "prores_ks" and cmd[cmd.index("-profile:v") + 1] == "4444"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv444p10le"


def test_sound_is_pcm_instead_of_aac():
    a, b = video(audio=True), video(audio=True)
    cmd = sidebyside.build(a, b, sidebyside.Options(out=Path("o.mov"), lossless="hevc")).command
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s24le" and "aac" not in cmd
    seq = grid.build([a, b], grid.Options(out=Path("o.mov"), lossless="hevc", sequential=True, holds=(0.0, 0.0)))
    assert "pcm_s24le" in seq.command


def test_grid_tiles_are_native_however_large_the_canvas():
    plan = grid.build([video(1080, 1920)] * 6, grid.Options(out=Path("o.mov"), lossless="hevc", gap=0))
    assert (plan.out_w, plan.out_h) == (3 * 1080, 2 * 1920)
    assert "scale=" not in graph(plan.command)


def test_grid_groups_join_mov_parts(tmp_path):
    opts = grid.Options(out=tmp_path / "o.mov", lossless="hevc")
    plan = grid.build_groups([[video(), video()], [video(), video()]], opts, (None, None), tmp_path)
    assert all(command[-1].endswith("part.mov") for command in plan.pre_commands)


def test_wipe_paints_a_white_stroke_at_ten_bits():
    plan = wipe.build(video(pix_fmt="yuv420p10le"), video(), wipe.Options(out=Path("o.mov"), lossless="hevc"))
    assert "1023" in graph(plan.command) and "yuv420p10le" in plan.command


def test_pip_scales_only_the_inset_and_keeps_its_chroma():
    plan = pip.build(video(), video(), pip.Options(out=Path("o.mov"), lossless="hevc"))
    body = graph(plan.command)
    assert "flags=lanczos" in body and "format=yuva420p" in body and "format=auto" in body
    assert any("inset" in note for note in plan.notes)


def test_images_alone_stay_a_png():
    plan = grid.build([image(), image()], grid.Options(out=Path("o.png"), lossless="hevc"))
    assert "libx265" not in plan.command and "-frames:v" in plan.command


def _args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**{"group": 0, "html": None, "lossless": "hevc", **kwargs})


def test_lossless_must_be_written_as_a_mov():
    with pytest.raises(SystemExit, match="name it out.mov"):
        cli._check_images("side", _args(), [video(), video()], Path("out.mp4"))
    assert cli._default_out("side", [Path("a.mp4"), Path("b.mp4")], lossless="hevc") == Path("a-vs-b.mov")


def test_bare_lossless_does_not_swallow_the_next_clip(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_run", lambda mode, args: seen.update(mode=mode, args=args) or 0)
    assert cli.main(["grid", "--lossless", "a.mp4", "b.mp4"]) == 0
    assert seen["args"].lossless == "hevc" and seen["args"].clips == ["a.mp4", "b.mp4"]
    assert cli.main(["side", "a.mp4", "b.mp4", "--lossless", "prores"]) == 0
    assert seen["args"].lossless == "prores"


def _encoders() -> str:
    if shutil.which("ffmpeg") is None:
        return ""
    return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout


def _psnr(out: Path, source: Path, x: int, frames: int) -> float:
    """PSNR of the output's tile at `x` against `source`, over `frames` frames."""
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(out), "-i", str(source), "-filter_complex",
         f"[0:v]trim=end_frame={frames},crop=320:240:{x}:0,format=yuv420p[o];"
         f"[1:v]trim=end_frame={frames},format=yuv420p[s];[o][s]psnr", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr
    value = log.rsplit("average:", 1)[1].split()[0]
    return float("inf") if value == "inf" else float(value)


# ProRes 4444 is visually lossless: about 56 dB on camera footage, near 40 on
# these hard-edged test patterns. HEVC lossless is bit-exact.
@pytest.mark.parametrize("codec,floor", [("hevc", float("inf")), ("prores", 38.0)])
def test_lossless_end_to_end_keeps_the_tile_pixels(tmp_path, codec, floor):
    """Compose two real clips, then measure each tile against its source."""
    encoders = _encoders()
    if "libx264" not in encoders or ("libx265" if codec == "hevc" else "prores_ks") not in encoders:
        pytest.skip("needs ffmpeg with libx264 and the codec under test")
    sources = []
    for name, pattern in (("a.mp4", "testsrc2"), ("b.mp4", "rgbtestsrc")):
        path = tmp_path / name
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{pattern}=s=320x240:r=30:d=1",
             "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(path)],
            check=True,
        )
        sources.append(path)
    out = tmp_path / "out.mov"
    assert cli.main([
        "side", str(sources[0]), str(sources[1]), "--lossless", codec, "--no-labels", "--divider", "0",
        "--layout", "lr", "--audio", "both", "-o", str(out),
    ]) == 0
    assert _psnr(out, sources[0], 0, 30) >= floor
    assert _psnr(out, sources[1], 320, 30) >= floor
    audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert audio == "pcm_s24le"
