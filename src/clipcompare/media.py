"""Clips and manifests given as http(s) URLs.

A media URL is downloaded once into a cache folder and rendered from there:
the grid reads each clip more than once (probe, lead-in scan, a second still
input), and a local file makes every one of those reads cheap and identical,
where streaming the URL each time could fail or differ halfway through.

Downloads send a curl-like User-Agent, because some media hosts refuse
Python's default one with 403.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "curl/8.7.1"
TIMEOUT = 120


class MediaError(OSError):
    """A URL could not be fetched."""


def is_url(value: str | os.PathLike) -> bool:
    return isinstance(value, str) and re.match(r"^https?://", value, re.IGNORECASE) is not None


def cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(root) / "clipcompare" / "media"


def _request(url: str, headers: dict[str, str] | None = None) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})


def fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    try:
        with urllib.request.urlopen(_request(url, headers), timeout=TIMEOUT) as response:
            return response.read()
    except (OSError, ValueError) as exc:
        raise MediaError(f"could not fetch {url}: {exc}") from exc


def filename(url: str) -> str:
    """A cache name that is unique per URL and keeps its extension, so ffmpeg
    and a browser still see what kind of file it is."""
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name or "media"
    name = re.sub(r"[^\w.-]+", "-", name)[-80:]
    return f"{hashlib.sha256(url.encode()).hexdigest()[:12]}-{name}"


def download(url: str, folder: Path | None = None) -> Path:
    """The URL as a local file in `folder` (default: the cache), fetched only
    if it is not there yet; written to a temporary name first, so a broken
    download never leaves a file that looks complete."""
    folder = folder or cache_dir()
    target = folder / filename(url)
    if target.is_file() and target.stat().st_size:
        return target
    folder.mkdir(parents=True, exist_ok=True)
    handle, partial = tempfile.mkstemp(dir=folder, prefix=".part-")
    try:
        with os.fdopen(handle, "wb") as sink, urllib.request.urlopen(_request(url), timeout=TIMEOUT) as response:
            shutil.copyfileobj(response, sink)
        os.replace(partial, target)
    except (OSError, ValueError) as exc:
        Path(partial).unlink(missing_ok=True)
        raise MediaError(f"could not download {url}: {exc}") from exc
    return target


def join(base: str, reference: str) -> str:
    """`reference` read relative to the URL `base` (an absolute one is kept)."""
    return urllib.parse.urljoin(base, reference)


def parse_header(text: str) -> tuple[str, str]:
    """--header "Name: value"."""
    name, sep, value = text.partition(":")
    if not sep or not name.strip():
        raise ValueError(f'a header looks like "Name: value", not {text!r}')
    return name.strip(), value.strip()
