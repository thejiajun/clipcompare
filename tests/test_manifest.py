"""--manifest / --captions parsing, path and URL resolution, and the web page."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from clipcompare import cli, manifest, media, page, prompts

from helpers import sound


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_manifest_reads_clips_labels_prompts_titles_and_group_size(tmp_path):
    touch(tmp_path / "set" / "a.mp3")
    touch(tmp_path / "set" / "b.mp3")
    spec = manifest.read(write(tmp_path / "set" / "clips.json", {
        "titles": ["Kali", "Alia"], "out": "compare.mp4",
        "clips": [
            {"file": "a.mp3", "label": "v3", "prompt": "plain", "baseline": True},
            {"file": "b.mp3", "label": "v4", "prompt": "[warm] plain",
             "segments": [{"text": "[warm] plain", "start": 0, "end": 2, "estimated": True}]},
        ] * 2,
    }))
    assert spec.group == 2 and spec.titles == ("Kali", "Alia")
    assert spec.labels == ("v3", "v4", "v3", "v4")
    assert spec.captions[1] == "[warm] plain"
    assert spec.baselines == (True, False, True, False)
    assert spec.segments[0] is None and spec.segments[1][0]["estimated"] is True
    assert spec.out == tmp_path / "set" / "compare.mp4"
    assert spec.sequential is True


def test_paths_resolve_next_to_the_manifest_then_one_folder_up_then_here(tmp_path, monkeypatch):
    here = tmp_path / "here"
    near = touch(tmp_path / "root" / "set" / "near.mp3")
    up = touch(tmp_path / "root" / "set" / "up.mp3").rename(tmp_path / "root" / "up.mp3")
    cwd = touch(here / "cwd.mp3")
    monkeypatch.chdir(here)
    spec = manifest.read(write(tmp_path / "root" / "set" / "clips.json", {"clips": [
        {"file": "near.mp3"}, {"file": "set/near.mp3"}, {"file": "up.mp3"}, {"file": "cwd.mp3"},
    ]}))
    assert [Path(p).resolve() for p in spec.clips] == [near.resolve(), near.resolve(), up.resolve(), cwd.resolve()]


def test_uneven_groups_and_missing_files_are_reported(tmp_path):
    with pytest.raises(manifest.ManifestError, match="split evenly"):
        manifest.read(write(tmp_path / "m.json", {"titles": ["a", "b"], "clips": [{"file": "x"}] * 3}))
    with pytest.raises(manifest.ManifestError, match='no "file"'):
        manifest.read(write(tmp_path / "m.json", {"clips": [{"label": "x"}]}))


def test_captions_file_is_a_list_of_strings_one_per_clip(tmp_path):
    assert manifest.read_captions(write(tmp_path / "c.json", ["[warm] a", None]), 2) == ("[warm] a", None)
    with pytest.raises(manifest.ManifestError, match="2 captions for 3 clips"):
        manifest.read_captions(write(tmp_path / "c.json", ["a", "b"]), 3)


# --- URLs -------------------------------------------------------------------

class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_web(monkeypatch):
    """urlopen answering from a dict, recording each request's headers."""
    pages: dict[str, bytes] = {}
    seen: list = []

    def urlopen(request, timeout=None):
        seen.append(request)
        if request.full_url not in pages:
            raise OSError("404")
        return _Response(pages[request.full_url])

    monkeypatch.setattr(media.urllib.request, "urlopen", urlopen)
    return pages, seen


def test_url_entries_are_kept_and_relative_ones_join_a_manifest_url(fake_web):
    pages, seen = fake_web
    pages["https://api.example/v1/sets/7/manifest.json"] = json.dumps({"clips": [
        {"file": "https://cdn.example/a.mp3"}, {"file": "media/b.mp3"}, {"file": "/abs/c.mp3"},
    ], "out": "../../evil/x.mp4"}).encode()
    spec = manifest.read("https://api.example/v1/sets/7/manifest.json", {"Authorization": "Bearer k"})
    assert spec.clips == (
        "https://cdn.example/a.mp3", "https://api.example/v1/sets/7/media/b.mp3", "https://api.example/abs/c.mp3",
    )
    assert spec.out == Path.cwd() / "x.mp4"            # a remote manifest names the file only
    assert seen[0].get_header("Authorization") == "Bearer k"
    assert seen[0].get_header("User-agent").startswith("curl/")


def test_manifest_from_stdin_resolves_against_the_current_folder(tmp_path, monkeypatch):
    touch(tmp_path / "a.mp3")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"clips": [{"file": "a.mp3"}, {"file": "https://x.example/b.mp3"}]})))
    spec = manifest.read("-")
    assert Path(spec.clips[0]).resolve() == (tmp_path / "a.mp3").resolve() and spec.clips[1] == "https://x.example/b.mp3"


def test_downloads_are_cached_by_url_with_a_curl_user_agent(fake_web, tmp_path):
    pages, seen = fake_web
    pages["https://cdn.example/voice%20one.mp3?sig=1"] = b"ID3data"
    first = media.download("https://cdn.example/voice%20one.mp3?sig=1", tmp_path)
    again = media.download("https://cdn.example/voice%20one.mp3?sig=1", tmp_path)
    assert first == again and first.read_bytes() == b"ID3data"
    assert first.name.endswith("-voice-one.mp3")
    assert len(seen) == 1 and seen[0].get_header("User-agent").startswith("curl/")
    assert media.filename("https://a/x.mp3?v=1") != media.filename("https://a/x.mp3?v=2")


def test_a_failed_download_leaves_nothing_behind(fake_web, tmp_path):
    with pytest.raises(media.MediaError):
        media.download("https://cdn.example/missing.mp3", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_header_flag_parses_name_and_value():
    assert media.parse_header("Authorization: Bearer a:b") == ("Authorization", "Bearer a:b")
    with pytest.raises(ValueError):
        media.parse_header("no colon")


def test_page_references_urls_as_is_and_copy_media_puts_them_next_to_the_page(fake_web, tmp_path):
    pages, _ = fake_web
    pages["https://cdn.example/a.mp3"] = b"a"
    local = touch(tmp_path / "clips" / "b.mp3")
    html = tmp_path / "out" / "compare.html"
    sources = ["https://cdn.example/a.mp3", local]
    paths = [tmp_path / "cache-a.mp3", local]
    assert cli._page_sources(sources, paths, html, copy=False) == ["https://cdn.example/a.mp3", "../clips/b.mp3"]
    copied = cli._page_sources(sources, paths, html, copy=True)
    assert copied[0].startswith("media/") and (html.parent / copied[0]).read_bytes() == b"a"


# --- the page -----------------------------------------------------------------

def _page(tmp_path) -> str:
    ready = prompts.prepare(
        ("one two three", "[warm] one TWO three"), (True, False),
        ([{"text": "one", "start": 0, "end": 1}, {"text": "two three", "start": 1, "end": 3}],
         [{"text": "[warm] one", "start": 0, "end": 2}, {"text": "TWO three", "start": 2, "end": 6}]),
    )
    clips = [sound(duration=3.0, name=str(tmp_path / "a.mp3")), sound(duration=6.0, name=str(tmp_path / "b.mp3"))]
    return page.build(clips, ("v3", "v4"), ready, ("Kali",), 0, tmp_path / "compare.html")


def test_page_embeds_versions_with_marks_durations_and_wpm(tmp_path):
    text = _page(tmp_path)
    data = json.loads(text.split("const DATA = ")[1].split(";\n")[0])
    a, b = data["groups"][0]["versions"]
    assert data["groups"][0]["title"] == "Kali"
    assert (a["src"], b["src"]) == ("a.mp3", "b.mp3")
    assert (a["wpm"], b["wpm"]) == (60, 30)
    assert a["summary"] == "baseline" and b["summary"] == "+1 tag · 1 emphasis"
    assert ["[warm]", "tag", False] in b["segments"][0]["tokens"]
    assert ["TWO", "emph", False] in b["segments"][1]["tokens"]
    assert "<script src" not in text and "<link" not in text and "http" not in text.split("<script>")[0]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_switching_versions_maps_the_position_segment_to_segment(tmp_path):
    script = _page(tmp_path).split("<script>")[1].split("DATA.groups.forEach")[0]
    probe = script + """
const [a, b] = DATA.groups[0].versions;
console.log(JSON.stringify([
  mapTime(a, b, 0.5, 3, 6),   // half-way through segment 1 of a -> half-way through b's
  mapTime(a, b, 2.0, 3, 6),   // half-way through segment 2
  mapTime({segments: []}, {segments: []}, 1.5, 3, 6),   // untimed: by share of duration
]));
"""
    out = subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [1.0, 4.0, 3.0]
