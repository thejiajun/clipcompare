"""sbs — side-by-side comparison videos, powered by ffmpeg."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sbs-video")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
