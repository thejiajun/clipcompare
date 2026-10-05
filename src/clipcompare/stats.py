"""What actually came out: each clip probed with ffprobe, and measured against
its run's baseline with ffmpeg's ssim / psnr (video, images) and asdr (sound).

Everything here is plain JSON-ready dicts, so the same numbers feed the tiles,
the web page and the `<out>.stats.json` sidecar that agents read.
"""

from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path

from .probe import IMAGE_FORMATS, ProbeError, is_image_format

# A sound is compared sample by sample only when it is the same take: two
# lengths this close (seconds, or share of the longer one). Different takes
# of a voice line never line up, and an SNR between them means nothing.
SNR_SLACK = 0.1
SNR_SHARE = 0.01


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _rate(value: str | None) -> float | None:
    try:
        rate = float(Fraction(value or ""))
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def measure(path: Path) -> dict:
    """Resolution, rate, length, codecs, bitrate and size of one clip."""
    from . import cache

    return cache.remember("measure", (cache.identity(path),), lambda: _measure(path))


def _measure(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ProbeError(f"cannot read {path}")
    return parse(json.loads(result.stdout or "{}"), Path(path).stat().st_size)


def parse(data: dict, size: int) -> dict:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    image = video is not None and is_image_format(data)
    kind = "image" if image else "video" if video is not None else "audio"
    duration = None if image else _number(fmt.get("duration")) or _number((video or audio or {}).get("duration"))
    out: dict = {"kind": kind, "size": size, "duration": duration}
    if video is not None:
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        for side in video.get("side_data_list") or []:
            if str(side.get("rotation", "0")).lstrip("-") in ("90", "270"):
                width, height = height, width
        out.update(width=width, height=height, video_codec=video.get("codec_name"), pix_fmt=video.get("pix_fmt"))
        if not image:
            out["fps"] = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
            bitrate = _number(video.get("bit_rate"))
            if bitrate is None and duration:
                # mkv / webm keep no per-stream rate: the whole file's, less the sound.
                total = _number(fmt.get("bit_rate")) or size * 8 / duration
                bitrate = max(total - (_number((audio or {}).get("bit_rate")) or 0), 0) or None
            out["video_bitrate"] = round(bitrate) if bitrate else None
    if audio is not None:
        out.update(
            audio_codec=audio.get("codec_name"),
            sample_rate=int(_number(audio.get("sample_rate")) or 0) or None,
            channels=audio.get("channels"),
        )
        bitrate = _number(audio.get("bit_rate"))
        if bitrate is None and kind == "audio" and duration:
            bitrate = _number(fmt.get("bit_rate")) or size * 8 / duration
        out["audio_bitrate"] = round(bitrate) if bitrate else None
    elif kind == "video":
        out["audio_codec"] = None
    if image:
        names = str(fmt.get("format_name") or "").split(",")
        out["format"] = next((n.removesuffix("_pipe") for n in names if n not in IMAGE_FORMATS), video.get("codec_name"))
    return out


_SSIM = re.compile(r"SSIM .*All:([0-9.]+)")
_PSNR = re.compile(r"PSNR .*average:([0-9.]+|inf)")
_SDR = re.compile(r"SDR ch0:\s*(-?[0-9.]+|inf)")


def _db(text: str) -> float:
    return float("inf") if text == "inf" else round(float(text), 2)


def compare(path: Path, measured: dict, baseline: Path, reference: dict) -> dict:
    """compare_uncached, cached by both files' identities."""
    from . import cache

    value = cache.remember(
        "compare", (cache.identity(path), cache.identity(baseline)),
        lambda: _json_safe(compare_uncached(path, measured, baseline, reference)),
    )
    return {key: float("inf") if item == "inf" else item for key, item in value.items()}


def _json_safe(value: dict) -> dict:
    return {key: "inf" if item == float("inf") else item for key, item in value.items()}


def compare_uncached(path: Path, measured: dict, baseline: Path, reference: dict) -> dict:
    """SSIM and PSNR of a clip's picture against the baseline's (scaled to the
    baseline's size when they differ, and `scaled_to` says so), and the SNR of
    its sound when both are the same take. Keys are left out when they do not
    apply; inf PSNR means the pictures are identical."""
    out: dict = {}
    pictures = measured.get("kind") in ("video", "image") and reference.get("kind") in ("video", "image")
    if pictures:
        size = (reference["width"], reference["height"])
        full = "444" in str(measured.get("pix_fmt")) + str(reference.get("pix_fmt")) or measured["kind"] == "image"
        fmt = "yuv444p" if full else "yuv420p"
        scale = ""
        if (measured["width"], measured["height"]) != size:
            scale = f"scale={size[0]}:{size[1]}:flags=lanczos,"
            out["scaled_to"] = f"{size[0]}x{size[1]}"
        log = _ffmpeg([
            "-i", str(path), "-i", str(baseline), "-filter_complex",
            f"[0:v]{scale}setsar=1,format={fmt},split[a1][a2];[1:v]setsar=1,format={fmt},split[b1][b2];"
            "[a1][b1]ssim=shortest=1[o1];[a2][b2]psnr=shortest=1[o2]",
            "-map", "[o1]", "-f", "null", "-", "-map", "[o2]", "-f", "null", "-",
        ])
        ssim, psnr = _SSIM.search(log), _PSNR.search(log)
        if ssim:
            out["ssim"] = round(float(ssim.group(1)), 4)
        if psnr:
            out["psnr"] = _db(psnr.group(1))
    if same_take(measured, reference):
        log = _ffmpeg([
            "-i", str(path), "-i", str(baseline), "-filter_complex",
            "[1:a]aresample=48000,aformat=channel_layouts=mono[r];"
            "[0:a]aresample=48000,aformat=channel_layouts=mono[c];[r][c]asdr",
            "-f", "null", "-",
        ])
        sdr = _SDR.search(log)
        if sdr:
            out["snr"] = _db(sdr.group(1))
    return out


def same_take(measured: dict, reference: dict) -> bool:
    """Both have sound of (nearly) the same length — the case where a
    sample-by-sample SNR is meaningful."""
    if not (measured.get("audio_codec") and reference.get("audio_codec")):
        return False
    a, b = measured.get("duration") or 0, reference.get("duration") or 0
    return bool(a and b) and abs(a - b) <= max(SNR_SLACK, SNR_SHARE * max(a, b))


def _ffmpeg(args: list[str]) -> str:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True)
    return result.stderr
