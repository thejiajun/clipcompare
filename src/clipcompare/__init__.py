"""clipcompare — comparison videos from two clips, powered by ffmpeg."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("clipcompare")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
