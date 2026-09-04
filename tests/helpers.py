"""Shared test helpers: fake clips and filtergraph extraction."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from clipcompare.probe import ClipInfo


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


def graph(command: list[str]) -> str:
    return command[command.index("-filter_complex") + 1]
