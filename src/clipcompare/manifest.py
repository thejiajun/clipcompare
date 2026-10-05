"""`grid --manifest FILE` and `grid --captions FILE`: clips, labels, prompts,
titles and the output named in one JSON file instead of on the command line.

    {
      "titles": ["Kali", "Alia"],          # optional: one per group
      "out": "compare.mp4",                # optional, written next to the manifest
      "group": 4,                          # optional: default clips / titles
      "sequential": true,                  # optional, default true
      "stats": true,                       # optional: measure every clip (like --stats)
      "clips": [
        {"file": "kali-v3.mp3", "label": "v3", "prompt": "[warm] Okay so...",
         "baseline": true,                 # the reference the others are diffed against
         "segments": [{"text": "...", "start": 0.0, "end": 9.5, "estimated": true}],
         # optional recipe: what this clip was meant to be (see info.py)
         "model": "eleven-v3", "preset": "warm", "params": {"stability": 0.5},
         "cost": 0.12, "seed": 7},
        ...
      ]
    }

A clip's caption is its "caption", or else its "prompt". A "file" may be an
http(s) URL. A relative one is looked up in the manifest's folder, then the
folder above it, then the current one — or, for a manifest read from a URL,
read relative to that URL. The manifest itself can come from a file, a URL
(`--manifest https://...`) or stdin (`--manifest -`).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import info, media


class ManifestError(ValueError):
    """The file is not a manifest or caption list this tool can use."""


@dataclass(frozen=True)
class Manifest:
    clips: tuple[Path | str, ...]   # a str is an http(s) URL
    labels: tuple[str, ...] | None
    captions: tuple[str | None, ...]
    titles: tuple[str, ...]
    out: Path | None
    group: int
    baselines: tuple[bool, ...] = ()
    segments: tuple[list[dict] | None, ...] = ()
    sequential: bool = True
    recipes: tuple[dict | None, ...] = ()
    stats: bool = False


def _load(path, headers: dict[str, str] | None = None):
    source = str(path)
    try:
        if source == "-":
            text = sys.stdin.read()
        elif media.is_url(source):
            text = media.fetch(source, headers).decode("utf-8")
        else:
            text = Path(source).expanduser().read_text(encoding="utf-8")
        return json.loads(text)
    except FileNotFoundError as exc:
        raise ManifestError(f"{path} not found") from exc
    except media.MediaError as exc:
        raise ManifestError(str(exc)) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc


def base_of(source) -> Path | str:
    """Where a manifest's relative paths start: its URL, its folder, or (from
    stdin) the current folder."""
    source = str(source)
    if media.is_url(source):
        return source
    if source == "-":
        return Path.cwd()
    return Path(source).expanduser().resolve().parent


def locate(name: str, base: Path | str) -> Path | str:
    if media.is_url(name):
        return name
    if isinstance(base, str):
        return media.join(base, name)
    path = Path(name).expanduser()
    if path.is_absolute():
        return path
    for root in (base, base.parent, Path.cwd()):
        if (root / path).is_file():
            return root / path
    return base / path  # missing everywhere; the caller reports it


def _caption(entry: dict) -> str | None:
    value = entry.get("caption", entry.get("prompt"))
    return str(value) if value else None


def _segments(entry: dict, index: int, path: Path) -> list[dict] | None:
    raw = entry.get("segments")
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, dict) and "text" in item for item in raw):
        raise ManifestError(f'clip {index + 1} in {path}: "segments" must be a list of {{"text", "start", "end"}}')
    return raw or None


def read(path, headers: dict[str, str] | None = None) -> Manifest:
    data = _load(path, headers)
    if not isinstance(data, dict) or not isinstance(data.get("clips"), list) or not data["clips"]:
        raise ManifestError(f'{path} needs a "clips" list of {{"file", "label", "prompt"}} objects')
    base = base_of(path)
    # The output goes next to a manifest file, else into the current folder.
    out_dir = base if isinstance(base, Path) else Path.cwd()
    entries = data["clips"]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("file"):
            raise ManifestError(f'clip {index + 1} in {path} has no "file"')
    labels = [entry.get("label") for entry in entries]
    recipes = []
    for index, entry in enumerate(entries):
        try:
            recipes.append(info.recipe(entry) or None)
        except ValueError as exc:
            raise ManifestError(f"clip {index + 1} in {path}: {exc}") from exc
    titles = tuple(str(title) for title in data.get("titles") or ())
    group = int(data.get("group") or 0)
    if not group and len(titles) > 1:
        if len(entries) % len(titles):
            raise ManifestError(f"{len(entries)} clips do not split evenly into {len(titles)} titled groups")
        group = len(entries) // len(titles)
    return Manifest(
        clips=tuple(locate(entry["file"], base) for entry in entries),
        labels=tuple(str(label) for label in labels) if all(labels) else None,
        captions=tuple(_caption(entry) for entry in entries),
        titles=titles,
        # A remote manifest only names the file, never where it lands.
        out=(out_dir / (data["out"] if isinstance(base, Path) else Path(data["out"]).name)) if data.get("out") else None,
        group=group,
        baselines=tuple(bool(entry.get("baseline")) for entry in entries),
        segments=tuple(_segments(entry, index, path) for index, entry in enumerate(entries)),
        sequential=bool(data.get("sequential", True)),
        recipes=tuple(recipes),
        stats=bool(data.get("stats", False)),
    )


def read_captions(path, count: int) -> tuple[str | None, ...]:
    """--captions: a JSON list of strings (null for none), or a manifest whose
    clips carry them — one per clip, in clip order."""
    data = _load(path)
    if isinstance(data, dict) and isinstance(data.get("clips"), list):
        data = [_caption(entry) if isinstance(entry, dict) else None for entry in data["clips"]]
    if not isinstance(data, list) or not all(item is None or isinstance(item, str) for item in data):
        raise ManifestError(f"{path} must be a JSON list of strings, one per clip")
    if len(data) != count:
        raise ManifestError(f"{path} has {len(data)} captions for {count} clips")
    return tuple(item or None for item in data)
