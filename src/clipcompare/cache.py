"""The render cache under ~/.cache/clipcompare/ (or $XDG_CACHE_HOME).

A second render with the same inputs and settings reuses the work that does
not depend on the final output: probe results, lead-in scans and baseline
metrics (JSON), and the intermediate pictures — prompt and info PNGs, pip
masks, waveform panels. Each piece is keyed by a hash of what it was made
from: an input file by its identity (resolved path, size, mtime — a
downloaded URL clip is a file in the media cache, so it is keyed the same
way), a text file by its content, and every parameter in the command. The
final output itself is never cached. `--no-cache` turns all of it off.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

enabled = True
# Intermediate pictures a pre-command can make, which are cached; anything
# else (a --group part, the output) is always rendered.
PICTURES = (".png", ".mkv")


def root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "clipcompare"


def identity(path: Path | str) -> str:
    """A file as the cache sees it: changing, replacing or touching it misses."""
    path = Path(path)
    stat = path.stat()
    return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


def key(*parts) -> str:
    # The version is part of every key: a new release never reads an old shape.
    from . import __version__

    return hashlib.sha256(json.dumps([__version__, *parts], sort_keys=True, default=str).encode()).hexdigest()


def _file(kind: str, digest: str, suffix: str) -> Path:
    return root() / kind / digest[:2] / f"{digest}{suffix}"


def _write(target: Path, write) -> None:
    """Write to a temporary name first, so an interrupted run never leaves
    a cache entry that looks complete."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, partial = tempfile.mkstemp(dir=target.parent, prefix=".part-")
    os.close(handle)
    try:
        write(Path(partial))
        os.replace(partial, target)
    finally:
        Path(partial).unlink(missing_ok=True)


def remember(kind: str, parts: tuple, compute):
    """compute(), or the value it returned last time for the same parts."""
    if not enabled:
        return compute()
    target = _file(kind, key(kind, *parts), ".json")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    value = compute()
    try:
        _write(target, lambda path: path.write_text(json.dumps(value), encoding="utf-8"))
    except OSError:
        pass
    return value


_TEXT = re.compile(r"textfile=([^:]+?\.txt)")
_FONT = re.compile(r"fontfile=([^:]+)")


def command_key(command: list[str], work_dir: Path) -> str | None:
    """The key for a pre-command making an intermediate picture: its argv,
    with the working folder taken out, every text file it draws replaced by
    its content and every input and font by its identity. None when the
    command makes something that is not cached."""
    out = command[-1]
    if not out.endswith(PICTURES):
        return None
    folder = str(work_dir)
    parts = []
    for index, arg in enumerate(command[:-1]):
        if index and command[index - 1] == "-i" and Path(arg).is_file():
            parts.append(identity(arg))
            continue
        arg = _TEXT.sub(lambda m: "text:" + _read(m.group(1)), arg)
        arg = _FONT.sub(lambda m: "font:" + (identity(m.group(1)) if Path(m.group(1)).is_file() else m.group(1)), arg)
        parts.append(arg.replace(folder, "<work>"))
    return key("picture", parts, Path(out).suffix)


def _read(path: str) -> str:
    try:
        return Path(path.replace("\\:", ":").replace("\\'", "'").replace("\\\\", "\\")).read_text(encoding="utf-8")
    except OSError:
        return path


def fetch_picture(command: list[str], work_dir: Path) -> tuple[bool, str | None]:
    """(hit, key): on a hit the cached picture is copied to the command's output."""
    if not enabled:
        return False, None
    digest = command_key(command, work_dir)
    if digest is None:
        return False, None
    cached = _file("pictures", digest, Path(command[-1]).suffix)
    if cached.is_file():
        Path(command[-1]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, command[-1])
        return True, digest
    return False, digest


def keep_picture(command: list[str], digest: str | None) -> None:
    if not (enabled and digest) or not Path(command[-1]).is_file():
        return
    try:
        _write(_file("pictures", digest, Path(command[-1]).suffix), lambda path: shutil.copyfile(command[-1], path))
    except OSError:
        pass
