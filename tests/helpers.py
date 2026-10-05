"""Shared test helpers: fake clips and filtergraph extraction."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from clipcompare.probe import AUDIO_PANEL, ClipInfo


def clip(width=1080, height=1920, fps="30/1", duration=3.0, audio=False, name="clip.mp4"):
    return ClipInfo(
        path=Path(name),
        width=width,
        height=height,
        fps=fps,
        fps_value=float(Fraction(fps)),
        duration=duration,
        has_audio=audio,
    )


def sound(duration=3.0, name="voice.mp3"):
    """An audio-only clip, shaped the way probe reports one."""
    return ClipInfo(
        path=Path(name),
        width=AUDIO_PANEL,
        height=AUDIO_PANEL,
        fps="30",
        fps_value=30.0,
        duration=duration,
        has_audio=True,
        has_video=False,
    )


def graph(command: list[str]) -> str:
    return command[command.index("-filter_complex") + 1]


def waves(plan) -> list[str]:
    """The filtergraphs of the pre-commands that render waveform panels, in order."""
    return [graph(command) for command in plan.pre_commands if command[-1].endswith(".mkv")]


def renders(plan) -> list[list[str]]:
    """Pre-commands other than waveform panels."""
    return [command for command in plan.pre_commands if not command[-1].endswith(".mkv")]


def image(width=720, height=720, name="still.png"):
    """A still image, shaped the way probe reports one."""
    return ClipInfo(
        path=Path(name),
        width=width,
        height=height,
        fps="30",
        fps_value=30.0,
        duration=0.0,
        has_audio=False,
        still=True,
    )
