"""`grid --html OUT.html`: a self-contained comparison page that plays the
ORIGINAL files — local ones by path relative to the page, URLs as they are
(or copied next to it with --copy-media) — never a re-encoded copy.

Per group, the versions play in sync. A group of video or images gets a
large view (keys 1-9 or a click switch it, on the same frame: the others
follow the shown one, mapped segment to segment when both are timed and by
share of the duration otherwise), frame steps (, and .), a wipe between any
two versions (CSS clip-path over two synced elements, no rendered video), and
a synced loupe (2x / 4x, pixelated at 4x) showing the same region of every
version side by side, on playing or paused video and on images. Each version
has an info card: recipe, measured (with % against the baseline) and its
prompt, with the same marks as the video. A group of audio clips keeps one
player whose prompt is highlighted segment by segment as it is spoken.

What every version of a group shares is said once in the group's header.
CSS and JS are inline, with no CDN, so the page works offline from file://.
"""

from __future__ import annotations

import html
import json
import os
from dataclasses import asdict
from pathlib import Path

from .info import Run
from .probe import ClipInfo
from .prompts import ClipPrompt, word_count

TITLE = "Clip comparison"


def _kind(clip: ClipInfo) -> str:
    return "audio" if clip.is_audio else "image" if clip.is_image else "video"


def _version(clip: ClipInfo, label: str, prompt: ClipPrompt | None, src: str, tile) -> dict:
    duration = clip.duration or 0.0
    text = prompt.text if prompt else ""
    words = word_count(text)
    segments = []
    if prompt:
        for segment, marked in zip(prompt.segments, prompt.marked):
            segments.append({
                "start": segment.start,
                "end": segment.end,
                "estimated": segment.estimated,
                "chars": len(segment.text),
                "tokens": [[token.text, token.style, token.space] for token in marked],
            })
    return {
        "label": label,
        "src": src,
        "kind": _kind(clip),
        "width": clip.width,
        "height": clip.height,
        "fps": clip.fps_value,
        "duration": round(duration, 3),
        "wpm": round(words / duration * 60) if duration and words else None,
        "summary": prompt.summary if prompt else "",
        "baseline": bool(prompt and prompt.is_baseline) or bool(tile and tile.is_baseline),
        "segments": segments,
        "info": asdict(tile) if tile else None,
    }


def build(
    clips: list[ClipInfo], labels: tuple[str, ...], prompts: tuple[ClipPrompt | None, ...],
    titles: tuple[str | None, ...], group: int, out: Path, heading: str | None = None,
    sources: list[str] | None = None, infos: tuple[Run | None, ...] = (),
) -> str:
    """`sources` are what each version loads (URLs, or paths relative to the
    page); by default each clip's path relative to `out`. `infos` holds one
    info.Run per group."""
    size = group or len(clips)
    sources = sources or [
        Path(os.path.relpath(clip.path.resolve(), out.parent.resolve())).as_posix() for clip in clips
    ]
    groups = []
    for number, start in enumerate(range(0, len(clips), size)):
        span = range(start, min(start + size, len(clips)))
        run = infos[number] if number < len(infos) else None
        versions = [
            _version(
                clips[i], labels[i], prompts[i] if prompts else None, sources[i],
                run.tiles[i - start] if run else None,
            )
            for i in span
        ]
        groups.append({
            "title": (titles[number] if number < len(titles) else None) or f"Group {number + 1}",
            "kind": "audio" if all(v["kind"] == "audio" for v in versions) else "visual",
            "shared": [asdict(item) for item in run.shared] if run else [],
            "versions": versions,
        })
    data = json.dumps({"groups": groups}, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(heading or (titles[0] if len(groups) == 1 and titles and titles[0] else TITLE))
    return _TEMPLATE.replace("__TITLE__", title).replace("__DATA__", data)


def write(out: Path, page: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
/* Tokens from @mellis-labs/design-system (dark theme), see tokens.py. */
:root {
  --ds-black: #111111;
  --ds-eggshell: #fcfaf7;
  --ds-accent-700: #cfc3ff;
  --ds-text-primary: #fcfaf7;
  --ds-text-secondary: #fcfaf7b3;
  --ds-text-disabled: #fcfaf759;
  --ds-invert-600: rgb(34 34 34 / 60%);
  --ds-primary-300: rgb(252 250 247 / 10%);
  --ds-neon-green: #15cb74;
  --ds-alert: #de0000;
  --ds-font-sans: "Telka", "TikTok Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --ds-font-display: "Telka Extended", "Telka", ui-sans-serif, system-ui, sans-serif;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: #0b0b0b; color: var(--ds-text-primary);
  font: 400 16px/1.35 var(--ds-font-sans); letter-spacing: .02em;
}
main { max-width: 1280px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font: 500 28px/1.2 var(--ds-font-display); margin: 0 0 6px; }
.lede { color: var(--ds-text-secondary); margin: 0 0 28px; font-size: 14px; }
.key { display: inline-flex; gap: 14px; flex-wrap: wrap; }
.key span { overflow-wrap: anywhere; }
kbd {
  font: 500 11px/1 var(--ds-font-sans); color: var(--ds-text-secondary);
  border: 1px solid var(--ds-primary-300); border-radius: 4px; padding: 2px 5px;
}
section.group {
  background: var(--ds-black); border: 1px solid var(--ds-primary-300);
  border-radius: 16px; padding: 20px; margin-bottom: 24px; min-width: 0;
}
section.group.focused { border-color: rgb(207 195 255 / 45%); }
h2 { font: 500 20px/1.2 var(--ds-font-display); margin: 0 0 4px; }
.shared { color: var(--ds-text-secondary); font-size: 14px; margin: 0 0 14px; font-variant-numeric: tabular-nums; }
.shared:empty { display: none; }
.num { font-variant-numeric: tabular-nums; }

/* --- audio groups --- */
.versions { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px; margin: 10px 0 14px; }
.version {
  text-align: left; font: inherit; color: inherit; cursor: pointer;
  background: var(--ds-invert-600); border: 1px solid var(--ds-primary-300);
  border-radius: 12px; padding: 10px 12px; min-height: 44px;
}
.version:hover { border-color: rgb(252 250 247 / 25%); }
.version[aria-pressed="true"] { border-color: var(--ds-accent-700); box-shadow: inset 0 0 0 1px var(--ds-accent-700); }
.version .name { font-weight: 500; display: flex; gap: 8px; align-items: baseline; }
.version .stats { color: var(--ds-text-secondary); font-size: 13px; margin-top: 4px; font-variant-numeric: tabular-nums; }
.version .diff { color: var(--ds-text-secondary); font-size: 13px; margin-top: 2px; }
audio.player { width: 100%; margin-bottom: 14px; }
.prompt {
  position: relative; max-height: 340px; overflow-y: auto; scroll-behavior: smooth;
  font-size: 19px; line-height: 1.5; padding-right: 6px;
}
.seg { display: block; color: var(--ds-text-disabled); transition: color .2s; margin: 0 0 .7em; }
.seg.now { color: var(--ds-text-primary); }
.seg .note { display: block; font-size: 12px; color: var(--ds-text-secondary); margin-top: 2px; }
.seg:not(.now) .note { display: none; }
.tag { font-weight: 500; }
.tag.new { color: var(--ds-accent-700); }
.seg:not(.now) .tag.new { color: rgb(207 195 255 / 45%); }
.emph { text-decoration: underline; text-decoration-color: var(--ds-accent-700); text-underline-offset: 3px; text-decoration-thickness: 2px; }
.legend { color: var(--ds-text-secondary); font-size: 13px; margin-top: 10px; }
.legend .tag.new { color: var(--ds-accent-700); }

/* --- video and image groups --- */
.toolbar { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin: 10px 0 12px; }
.toolbar .cluster { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.btn, select {
  font: 500 13px/1 var(--ds-font-sans); color: var(--ds-text-primary); cursor: pointer;
  background: var(--ds-invert-600); border: 1px solid var(--ds-primary-300); border-radius: 8px;
  padding: 8px 10px; min-height: 34px;
}
.btn[aria-pressed="true"] { border-color: var(--ds-accent-700); color: var(--ds-accent-700); }
.btn:disabled { opacity: .4; cursor: default; }
.toolbar .label { color: var(--ds-text-secondary); font-size: 13px; }
.time { font: 400 13px/1 var(--ds-font-sans); color: var(--ds-text-secondary); font-variant-numeric: tabular-nums; min-width: 92px; }
input[type=range] { accent-color: var(--ds-accent-700); flex: 1 1 160px; min-width: 120px; }
.scrub { display: flex; gap: 10px; align-items: center; flex: 1 1 260px; min-width: 0; }
.stage {
  position: relative; margin: 0 auto; background: #000; border-radius: 10px; overflow: hidden;
  max-width: 100%; touch-action: none; user-select: none;
}
.stage .layer { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; opacity: 0; pointer-events: none; }
.stage .layer.on { opacity: 1; }
.stage .audio-layer { display: flex; align-items: center; justify-content: center; color: var(--ds-text-secondary); background: var(--ds-black); }
.stage .chip {
  position: absolute; top: 10px; background: var(--ds-invert-600); color: var(--ds-text-primary);
  font-size: 13px; font-weight: 500; padding: 5px 9px; border-radius: 6px; pointer-events: none; max-width: 45%;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.stage .chip.a { left: 10px; } .stage .chip.b { right: 10px; color: var(--ds-accent-700); }
.stage .chip, .handle, .lens { z-index: 3; }
.handle { position: absolute; top: 0; bottom: 0; width: 28px; margin-left: -14px; cursor: ew-resize; display: none; }
.handle::before { content: ""; position: absolute; left: 13px; top: 0; bottom: 0; width: 2px; background: var(--ds-eggshell); box-shadow: 0 0 0 1px rgb(0 0 0 / 35%); }
.handle::after {
  content: ""; position: absolute; left: 4px; top: 50%; width: 20px; height: 20px; margin-top: -10px;
  border-radius: 50%; background: var(--ds-eggshell);
}
.wipe .handle { display: block; }
.lens { position: absolute; border: 1px solid var(--ds-accent-700); pointer-events: none; display: none; }
.loupe { display: none; grid-template-columns: repeat(auto-fit, minmax(140px, 240px)); justify-content: center; gap: 8px; margin: 12px 0 0; }
.loupe.on { display: grid; }
.loupe figure { margin: 0; min-width: 0; }
.loupe canvas { width: 100%; aspect-ratio: 1; display: block; background: #000; border-radius: 8px; }
.loupe canvas.pixelated { image-rendering: pixelated; }
.loupe figcaption { font-size: 12px; color: var(--ds-text-secondary); margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 16px; }
.card { min-width: 0; }
.thumb {
  position: relative; display: block; width: 100%; padding: 0; border: 1px solid var(--ds-primary-300);
  border-radius: 10px; overflow: hidden; background: #000; cursor: pointer; color: inherit; font: inherit;
}
.thumb[aria-pressed="true"] { border-color: var(--ds-accent-700); box-shadow: 0 0 0 1px var(--ds-accent-700); }
.thumb canvas { display: block; width: auto; max-width: 100%; height: auto; max-height: 260px; margin: 0 auto; }
.thumb .audio-thumb { aspect-ratio: 16 / 9; display: flex; align-items: center; justify-content: center; color: var(--ds-text-secondary); font-size: 13px; }
.badge {
  position: absolute; right: 8px; bottom: 8px; background: var(--ds-invert-600); color: var(--ds-accent-700);
  font-size: 12px; font-weight: 500; padding: 4px 8px; border-radius: 6px;
}
.badge.base { color: var(--ds-text-primary); }
.thumb kbd { position: absolute; left: 8px; top: 8px; background: var(--ds-invert-600); }
.card .name { font-weight: 500; margin: 8px 0 2px; overflow-wrap: anywhere; }
.info { font-size: 13px; }
.info h4 { font: 500 11px/1 var(--ds-font-sans); text-transform: uppercase; letter-spacing: .08em; color: var(--ds-text-secondary); margin: 12px 0 6px; }
.info table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.info td, .info th { padding: 3px 0; vertical-align: top; text-align: left; font-weight: 400; }
.info th { color: var(--ds-text-secondary); padding-right: 10px; width: 40%; overflow-wrap: anywhere; }
.info td { overflow-wrap: anywhere; }
.info td.delta { text-align: right; color: var(--ds-text-secondary); white-space: nowrap; padding-left: 8px; width: 1%; }
.info .accent { color: var(--ds-accent-700); }
.info td.nowrap { white-space: nowrap; }
.info .good { color: var(--ds-neon-green); }
.info .bad { color: var(--ds-alert); }
.info details { margin-top: 12px; }
.info summary { cursor: pointer; color: var(--ds-text-secondary); font: 500 11px/1.4 var(--ds-font-sans); text-transform: uppercase; letter-spacing: .08em; }
.info summary .sum { text-transform: none; letter-spacing: 0; margin-left: 6px; font-weight: 400; }
.info .text { font-size: 14px; line-height: 1.5; margin-top: 6px; }
.info .text .seg { color: var(--ds-text-primary); margin: 0 0 .5em; }
.compact .info h4 { margin-top: 8px; }
@media (max-width: 520px) {
  .prompt { font-size: 17px; } h1 { font-size: 24px; } section.group { padding: 14px; }
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
</head>
<body>
<main>
  <h1>__TITLE__</h1>
  <p class="lede"><span class="key">
    <span>Click a version or press <kbd>1</kbd>&ndash;<kbd>9</kbd> to switch at the same moment.</span>
    <span><kbd>Space</kbd> plays or pauses.</span>
    <span><kbd>,</kbd> <kbd>.</kbd> step a frame.</span>
    <span><kbd>W</kbd> wipe, <kbd>Z</kbd> loupe.</span>
  </span></p>
  <div id="groups"></div>
</main>
<script>
const DATA = __DATA__;

// Segment spans in seconds for a version: its own timing when every segment
// has one, else the duration split by text length (as the video does).
function spans(version, duration) {
  const segs = version.segments;
  if (!segs.length) return [[0, duration]];
  if (segs.every(s => s.start != null)) {
    return segs.map((s, i) => [s.start, i + 1 < segs.length ? segs[i + 1].start : Math.max(duration, s.end || 0)]);
  }
  const total = segs.reduce((n, s) => n + Math.max(s.chars, 1), 0);
  let at = 0;
  return segs.map(s => { const a = at; at += duration * Math.max(s.chars, 1) / total; return [a, at]; });
}
function timed(version) { return version.segments.length > 1 && version.segments.every(s => s.start != null); }

// The same point in `to` as `t` is in `from`: the same share of the same
// segment when both are timed, the same share of the duration otherwise.
function mapTime(from, to, t, fromDur, toDur) {
  if (timed(from) && timed(to) && from.segments.length === to.segments.length) {
    const a = spans(from, fromDur), b = spans(to, toDur);
    let k = a.findIndex(([s, e]) => t >= s && t < e);
    if (k < 0) k = t < a[0][0] ? 0 : a.length - 1;
    const [s, e] = a[k], share = e > s ? Math.min(Math.max((t - s) / (e - s), 0), 1) : 0;
    return b[k][0] + share * (b[k][1] - b[k][0]);
  }
  return fromDur ? t / fromDur * toDur : 0;
}

// One frame on from `t` at `fps` (direction +1 or -1), landing mid-frame so
// the decoder never rounds onto the neighbour.
function stepTime(t, fps, direction, duration) {
  const frame = Math.floor(t * fps + 1e-3) + direction;
  const last = Math.max(Math.floor(duration * fps) - 1, 0);
  return (Math.min(Math.max(frame, 0), last) + 0.5) / fps;
}

// Where a natW x natH picture lands inside a boxW x boxH box (object-fit: contain).
function fitRect(boxW, boxH, natW, natH) {
  const scale = Math.min(boxW / natW, boxH / natH);
  const w = natW * scale, h = natH * scale;
  return { x: (boxW - w) / 2, y: (boxH - h) / 2, w, h, scale };
}

// The loupe's source rectangle in a natW x natH picture: centred on (u, v)
// (shares of the frame), as large as `view` CSS px shows of the reference
// picture (refW x refH) at `zoom` — the same piece of the scene in every
// version, whatever its resolution — and kept inside the frame.
function loupeRegion(u, v, view, zoom, refW, refH, natW, natH) {
  const fw = Math.min(view / zoom / refW, 1), fh = Math.min(view / zoom / refH, 1);
  const cu = Math.min(Math.max(u, fw / 2), 1 - fw / 2), cv = Math.min(Math.max(v, fh / 2), 1 - fh / 2);
  return { sx: (cu - fw / 2) * natW, sy: (cv - fh / 2) * natH, sw: fw * natW, sh: fh * natH, cu, cv, fw, fh };
}

function fmt(sec) {
  const whole = Math.round(sec), m = Math.floor(whole / 60), s = whole % 60;
  return m + ":" + String(s).padStart(2, "0");
}
function fmtFine(sec) {
  const m = Math.floor(sec / 60), s = sec - m * 60;
  return m + ":" + s.toFixed(2).padStart(5, "0");
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function renderPrompt(box, version) {
  box.textContent = "";
  version.segments.forEach((seg, i) => {
    const node = el("span", "seg");
    node.dataset.index = i;
    seg.tokens.forEach(([text, style, space], j) => {
      if (j && space) node.append(" ");
      if (style === "plain") { node.append(text); return; }
      node.append(el("span", style === "emph" ? "emph" : style === "tag" ? "tag new" : "tag", text));
    });
    if (seg.estimated) node.append(el("span", "note", "timing estimated"));
    box.append(node);
  });
}

// A version's info card: recipe, measured (% against the baseline), prompt.
function infoCard(version, withPrompt) {
  const card = el("div", "info");
  const info = version.info;
  if (info && info.recipe.length) {
    card.append(el("h4", "", "Recipe"));
    const table = el("table");
    info.recipe.forEach(item => {
      const row = table.insertRow();
      row.append(el("th", "", item.label));
      row.append(el("td", item.accent ? "accent" : "", item.value));
    });
    card.append(table);
  }
  if (info && (info.measured.length || info.similarity.length)) {
    card.append(el("h4", "", "Measured"));
    const table = el("table");
    [...info.measured, ...info.similarity].forEach(item => {
      const row = table.insertRow();
      row.append(el("th", "", item.label));
      const value = el("td", (item.tone || "") + " nowrap", item.value);
      row.append(value);
      row.append(el("td", "delta", item.delta || ""));
    });
    card.append(table);
  }
  if (withPrompt && version.segments.length) {
    const details = el("details");
    const summary = el("summary", "", "Prompt");
    if (version.summary) summary.append(el("span", "sum", version.summary));
    const text = el("div", "text");
    renderPrompt(text, version);
    details.append(summary, text);
    card.append(details);
  }
  return card;
}

function legend(group) {
  if (!group.versions.some(v => v.segments.some(s => s.tokens.some(([, st]) => st !== "plain")))) return null;
  const node = el("div", "legend");
  node.innerHTML = '<span class="tag new">[lilac]</span> a tag the baseline does not have &middot; <span class="emph">underlined</span> a change only in case or punctuation';
  return node;
}

function header(section, group) {
  // A lone group titled like the page needs no second heading.
  if (!(DATA.groups.length === 1 && group.title === document.querySelector("h1").textContent)) {
    section.append(el("h2", "", group.title));
  }
  section.append(el("p", "shared", group.shared.map(item => item.text).join(" \\u00b7 ")));
}

const players = [];
let focused = null;
function focus(state) {
  focused = state;
  players.forEach(p => p.section.classList.toggle("focused", p === state));
}

// --- audio groups: one player, the prompt followed as it is spoken ---------

function audioGroup(group) {
  const section = el("section", "group");
  header(section, group);
  const row = el("div", "versions");
  row.setAttribute("role", "group");
  const audio = el("audio", "player");
  audio.controls = true;
  audio.preload = "metadata";
  const box = el("div", "prompt");
  section.append(row, audio, box);
  const state = { kind: "audio", group, audio, box, section, current: -1, buttons: [], lastSeg: -1 };

  group.versions.forEach((v, i) => {
    const b = el("button", "version compact");
    b.type = "button";
    b.setAttribute("aria-pressed", "false");
    const name = el("div", "name");
    name.append(el("kbd", "", String(i + 1)), el("span", "", v.label));
    const stats = [fmt(v.duration), v.wpm ? v.wpm + " wpm" : null].filter(Boolean).join(" \\u00b7 ");
    b.append(name, el("div", "stats", stats), el("div", "diff", v.summary));
    if (v.info) b.append(infoCard(v, false));
    b.addEventListener("click", () => { focus(state); select(state, i, true); });
    row.append(b);
    state.buttons.push(b);
  });
  const key = legend(group);
  if (key) section.append(key);
  audio.addEventListener("timeupdate", () => highlight(state));
  audio.addEventListener("play", () => {
    focus(state);
    players.forEach(p => { if (p !== state) pauseGroup(p); });
  });
  section.addEventListener("pointerdown", () => focus(state));
  select(state, 0, false);
  return state;
}

function audioDuration(state, i) {
  const v = state.group.versions[i];
  return (i === state.current && isFinite(state.audio.duration) && state.audio.duration) || v.duration;
}

function selectAudio(state, i, keepPlace) {
  if (i === state.current || i >= state.group.versions.length) return;
  const audio = state.audio;
  const from = state.current >= 0 ? state.group.versions[state.current] : null;
  const to = state.group.versions[i];
  const wasPlaying = !audio.paused;
  const at = from && keepPlace ? mapTime(from, to, audio.currentTime, audioDuration(state, state.current), to.duration) : 0;
  state.current = i;
  state.lastSeg = -1;
  state.buttons.forEach((b, j) => b.setAttribute("aria-pressed", String(j === i)));
  renderPrompt(state.box, to);
  audio.src = to.src;
  const seek = () => {
    audio.currentTime = Math.min(at, (audio.duration || to.duration) - 0.05);
    highlight(state);
    if (wasPlaying) audio.play();
  };
  if (audio.readyState >= 1) seek(); else audio.addEventListener("loadedmetadata", seek, { once: true });
  highlight(state);
}

function highlight(state) {
  const v = state.group.versions[state.current];
  const t = state.audio.currentTime;
  const s = spans(v, audioDuration(state, state.current));
  let k = s.findIndex(([a, b]) => t >= a && t < b);
  if (k < 0) k = t >= (s[s.length - 1] || [0, 0])[1] ? s.length - 1 : 0;
  if (k === state.lastSeg) return;
  state.lastSeg = k;
  const segs = state.box.querySelectorAll(".seg");
  segs.forEach((node, j) => node.classList.toggle("now", j === k));
  const now = segs[k];
  if (now) state.box.scrollTop = now.offsetTop;   // the spoken segment at the top
}

// --- video and image groups: a large view, a wipe, a loupe ----------------

const ZOOMS = [0, 2, 4];

function visualGroup(group) {
  const section = el("section", "group");
  header(section, group);
  const versions = group.versions;
  const timedGroup = versions.some(v => v.kind !== "image");

  const toolbar = el("div", "toolbar");
  const transport = el("div", "cluster scrub");
  const play = el("button", "btn", "Play");
  const back = el("button", "btn", "\\u2039 Frame");
  const next = el("button", "btn", "Frame \\u203a");
  const time = el("span", "time", "0:00.00");
  const range = el("input");
  range.type = "range"; range.min = 0; range.max = 1000; range.value = 0;
  range.setAttribute("aria-label", "Position");
  range.addEventListener("pointerdown", () => { state.scrubbing = true; });
  range.addEventListener("pointerup", () => { state.scrubbing = false; });
  transport.append(play, back, next, time, range);
  const view = el("div", "cluster");
  const single = el("button", "btn", "Single");
  const wipe = el("button", "btn", "Wipe");
  const pickA = el("select"), pickB = el("select");
  pickA.setAttribute("aria-label", "Wipe left (A)"); pickB.setAttribute("aria-label", "Wipe right (B)");
  versions.forEach((v, i) => { pickA.append(new Option("A: " + v.label, i)); pickB.append(new Option("B: " + v.label, i)); });
  view.append(single, wipe, pickA, pickB);
  const lensTools = el("div", "cluster");
  lensTools.append(el("span", "label", "Loupe"));
  const zoomButtons = ZOOMS.map(z => el("button", "btn", z ? z + "\\u00d7" : "Off"));
  lensTools.append(...zoomButtons);
  [play, back, next].forEach(b => { b.type = "button"; b.disabled = !timedGroup; });
  [single, wipe, ...zoomButtons].forEach(b => { b.type = "button"; });
  if (timedGroup) toolbar.append(transport);
  toolbar.append(view, lensTools);

  const stage = el("div", "stage");
  const layers = versions.map(v => {
    let node;
    if (v.kind === "image") { node = el("img", "layer"); node.alt = v.label; node.decoding = "async"; }
    else if (v.kind === "video") { node = el("video", "layer"); node.playsInline = true; node.preload = "auto"; node.muted = true; }
    else {
      node = el("div", "layer audio-layer", v.label + " \\u00b7 audio");
      const sound = el("audio"); sound.preload = "auto"; sound.muted = true; sound.src = v.src;
      node.media = sound; node.append(sound);
    }
    if (v.kind !== "audio") node.src = v.src;
    stage.append(node);
    return node;
  });
  const chipA = el("div", "chip a"), chipB = el("div", "chip b");
  const handle = el("div", "handle");
  handle.setAttribute("role", "slider"); handle.setAttribute("aria-label", "Wipe position");
  const lens = el("div", "lens");
  stage.append(chipA, chipB, handle, lens);

  const loupe = el("div", "loupe");
  const loupeCanvases = versions.map(v => {
    const figure = el("figure");
    const canvas = el("canvas");
    figure.append(canvas, el("figcaption", "", v.label));
    loupe.append(figure);
    return canvas;
  });

  const cards = el("div", "cards");
  const thumbs = [];
  const thumbCanvases = versions.map((v, i) => {
    const card = el("div", "card");
    const thumb = el("button", "thumb");
    thumb.type = "button";
    let canvas = null;
    if (v.kind === "audio") thumb.append(el("div", "audio-thumb", "audio"));
    else {
      // A fixed backing size: CSS scales it, so a thumbnail never depends on layout.
      canvas = el("canvas");
      const scale = Math.min(480 / v.width, 480 / v.height, 1);
      canvas.width = Math.max(Math.round(v.width * scale), 1); canvas.height = Math.max(Math.round(v.height * scale), 1);
      thumb.append(canvas);
    }
    thumb.append(el("kbd", "", String(i + 1)));
    const differences = v.info ? v.info.differences : null;
    if (v.baseline) thumb.append(el("span", "badge base", "baseline"));
    else if (differences) thumb.append(el("span", "badge", "+" + differences + " difference" + (differences === 1 ? "" : "s")));
    card.append(thumb, el("div", "name", v.label), infoCard(v, true));
    cards.append(card);
    thumbs.push(thumb);
    return canvas;
  });
  section.append(toolbar, stage, loupe, cards);
  const key = legend(group);
  if (key) section.append(key);

  const state = {
    kind: "visual", group, section, stage, layers, loupe, loupeCanvases, thumbCanvases, thumbs, lens,
    current: 0, view: "single", a: 0, b: Math.min(1, versions.length - 1), wipeAt: 0.5, zoom: 0, point: null,
    playing: false, play, time, range, single, wipe, pickA, pickB, zoomButtons, chipA, chipB, scrubbing: false,
  };
  pickB.value = state.b;

  play.addEventListener("click", () => { focus(state); togglePlay(state); });
  back.addEventListener("click", () => { focus(state); step(state, -1); });
  next.addEventListener("click", () => { focus(state); step(state, 1); });
  range.addEventListener("input", () => {
    const m = media(state, master(state));
    if (!m) return;
    m.currentTime = range.value / 1000 * duration(state, master(state));
    follow(state, true);
  });
  single.addEventListener("click", () => setView(state, "single"));
  wipe.addEventListener("click", () => setView(state, "wipe"));
  pickA.addEventListener("change", () => { state.a = Number(pickA.value); setView(state, "wipe"); });
  pickB.addEventListener("change", () => { state.b = Number(pickB.value); setView(state, "wipe"); });
  zoomButtons.forEach((b, i) => b.addEventListener("click", () => setZoom(state, ZOOMS[i])));
  thumbs.forEach((t, i) => t.addEventListener("click", () => { focus(state); select(state, i); }));

  // The loupe follows the pointer over the large view or any thumbnail; a
  // drag on the large view (outside the loupe) moves the wipe line.
  let dragging = false;
  const pointAt = (event, target, version) => {
    const box = target.getBoundingClientRect();
    const v = versions[version];
    const r = target === stage ? fitRect(box.width, box.height, v.width, v.height) : { x: 0, y: 0, w: box.width, h: box.height };
    return { u: (event.clientX - box.left - r.x) / r.w, v: (event.clientY - box.top - r.y) / r.h };
  };
  stage.addEventListener("pointerdown", e => {
    focus(state);
    if (state.view === "wipe" && (e.target === handle || !state.zoom)) {
      dragging = true; stage.setPointerCapture(e.pointerId); moveWipe(state, e);
    }
  });
  stage.addEventListener("pointermove", e => {
    if (dragging) { moveWipe(state, e); return; }
    if (state.zoom) { state.point = pointAt(e, stage, master(state)); paint(state); }
  });
  stage.addEventListener("pointerup", () => { dragging = false; });
  thumbCanvases.forEach((canvas, i) => {
    if (!canvas) return;
    canvas.addEventListener("pointermove", e => {
      if (state.zoom) { state.point = pointAt(e, canvas, i); paint(state); }
    });
  });

  layers.forEach((node, i) => {
    const m = node.media || (node.tagName === "IMG" ? null : node);
    const repaint = () => paint(state);
    if (!m) { node.addEventListener("load", () => { layout(state); repaint(); }); return; }
    m.addEventListener("loadeddata", () => { layout(state); follow(state, true); repaint(); });
    m.addEventListener("seeked", repaint);
    m.addEventListener("ended", () => {
      if (i !== master(state)) return;
      // Loop, all together, so a comparison can be watched again and again.
      timeline(state).forEach(x => { x.currentTime = 0; });
      if (state.playing) timeline(state).forEach(x => x.play().catch(() => {}));
    });
  });
  section.addEventListener("pointerdown", () => focus(state));
  window.addEventListener("resize", () => { layout(state); paint(state); });
  select(state, 0);
  setZoom(state, 0);
  return state;
}

function media(state, i) {
  const node = state.layers[i];
  return node.media || (node.tagName === "IMG" ? null : node);
}
function timeline(state) { return state.layers.map((_, i) => media(state, i)).filter(Boolean); }
function duration(state, i) {
  const m = media(state, i), v = state.group.versions[i];
  return (m && isFinite(m.duration) && m.duration) || v.duration || 0;
}
// The version every other one follows: the one shown (A in a wipe), or, if
// that is a still image, the first that plays.
function master(state) {
  const shown = state.view === "wipe" ? state.a : state.current;
  if (media(state, shown)) return shown;
  const any = state.layers.findIndex((_, i) => media(state, i));
  return any < 0 ? shown : any;
}

// Every other version to the master's moment: exactly (`force`, when paused
// or after a seek), or only past a small drift while playing; proportional
// pairs also play at their length ratio, so they stay in step on their own.
function follow(state, force) {
  const lead = master(state), m = media(state, lead);
  if (!m) return;
  const versions = state.group.versions, from = versions[lead], fromDur = duration(state, lead);
  state.layers.forEach((_, i) => {
    const x = media(state, i);
    if (!x || i === lead) return;
    const to = versions[i], toDur = duration(state, i);
    const want = Math.min(mapTime(from, to, m.currentTime, fromDur, toDur), Math.max(toDur - 0.001, 0));
    const proportional = !(timed(from) && timed(to));
    x.playbackRate = proportional && fromDur && toDur ? toDur / fromDur : 1;
    if (force || Math.abs(x.currentTime - want) > 0.12) x.currentTime = want;
  });
  m.playbackRate = 1;
  const d = duration(state, lead);
  state.time.textContent = fmtFine(m.currentTime);
  if (!state.scrubbing && d) state.range.value = Math.round(m.currentTime / d * 1000);
}

function togglePlay(state) {
  if (state.playing) pauseGroup(state);
  else {
    players.forEach(p => { if (p !== state) pauseGroup(p); });
    state.playing = true;
    follow(state, true);
    timeline(state).forEach(x => x.play().catch(() => {}));
    state.play.textContent = "Pause";
    tick(state);
  }
}

function pauseGroup(state) {
  if (state.kind === "audio") { state.audio.pause(); return; }
  state.playing = false;
  timeline(state).forEach(x => x.pause());
  follow(state, true);
  state.play.textContent = "Play";
  paint(state);
}

function tick(state) {
  if (!state.playing) return;
  follow(state, false);
  paint(state);
  requestAnimationFrame(() => tick(state));
}

function step(state, direction) {
  if (state.playing) pauseGroup(state);
  const lead = master(state), m = media(state, lead);
  if (!m) return;
  const fps = state.group.versions[lead].fps || 30;
  m.currentTime = stepTime(m.currentTime, fps, direction, duration(state, lead));
  follow(state, true);
}

function select(state, i) {
  if (state.kind === "audio") { selectAudio(state, i, true); return; }
  if (i >= state.group.versions.length) return;
  state.current = i;
  state.view = "single";
  update(state);
}

function setView(state, view) {
  if (state.group.versions.length < 2) view = "single";
  state.view = view;
  if (view === "wipe" && state.a === state.b) state.b = (state.a + 1) % state.group.versions.length;
  update(state);
}

function setZoom(state, zoom) {
  state.zoom = zoom;
  state.zoomButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(ZOOMS[i] === zoom)));
  state.loupe.classList.toggle("on", zoom > 0);
  state.loupeCanvases.forEach(c => c.classList.toggle("pixelated", zoom >= 4));
  if (zoom && !state.point) state.point = { u: 0.5, v: 0.5 };
  paint(state);
}

function moveWipe(state, event) {
  const box = state.stage.getBoundingClientRect();
  state.wipeAt = Math.min(Math.max((event.clientX - box.left) / box.width, 0), 1);
  update(state);
}

// Shown layers, chips, sound and the stage's shape for the current view.
function update(state) {
  const versions = state.group.versions;
  const wiping = state.view === "wipe";
  state.pickA.value = state.a; state.pickB.value = state.b;
  state.layers.forEach((node, i) => {
    const on = wiping ? i === state.a || i === state.b : i === state.current;
    node.classList.toggle("on", on);
    node.style.clipPath = wiping && i === state.b ? "inset(0 0 0 " + (state.wipeAt * 100).toFixed(2) + "%)" : "";
    node.style.zIndex = wiping && i === state.b ? 2 : on ? 1 : 0;
  });
  const lead = master(state);
  // Only the version in front is heard.
  timeline(state).forEach(x => { x.muted = true; });
  const heard = media(state, wiping ? state.a : state.current);
  if (heard) heard.muted = false;
  state.stage.classList.toggle("wipe", wiping);
  state.stage.querySelector(".handle").style.left = (state.wipeAt * 100) + "%";
  state.chipA.textContent = wiping ? "A \\u00b7 " + versions[state.a].label : versions[state.current].label;
  state.chipB.textContent = wiping ? "B \\u00b7 " + versions[state.b].label : "";
  state.chipB.style.display = wiping ? "" : "none";
  state.single.setAttribute("aria-pressed", String(!wiping));
  state.wipe.setAttribute("aria-pressed", String(wiping));
  state.thumbs.forEach((t, i) => t.setAttribute("aria-pressed", String(wiping ? i === state.a || i === state.b : i === state.current)));
  layout(state);
  follow(state, !state.playing);
  if (state.playing) timeline(state).forEach(x => x.play().catch(() => {}));
  paint(state);
  void lead;
}

// The stage takes the shown version's shape, within the window's height.
function layout(state) {
  const v = state.group.versions[state.view === "wipe" ? state.a : state.current];
  const width = state.section.clientWidth - 2 * parseFloat(getComputedStyle(state.section).paddingLeft || 0);
  const maxH = Math.max(window.innerHeight * 0.7, 240);
  const w = Math.min(width, maxH * v.width / v.height);
  state.stage.style.width = Math.round(w) + "px";
  state.stage.style.height = Math.round(w * v.height / v.width) + "px";
}

function drawable(state, i) {
  const node = state.layers[i];
  if (node.tagName === "IMG") return node.complete && node.naturalWidth ? node : null;
  if (node.tagName === "VIDEO") return node.readyState >= 2 ? node : null;
  return null;
}

function sizeCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const w = Math.max(Math.round(canvas.clientWidth * ratio), 1), h = Math.max(Math.round(canvas.clientHeight * ratio), 1);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
}

// Thumbnails and the loupe are painted from the large view's own elements,
// so every picture on the page is the same decoded frame.
function paint(state) {
  const versions = state.group.versions;
  state.thumbCanvases.forEach((canvas, i) => {
    const source = canvas && drawable(state, i);
    if (!source) return;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  });
  const lens = state.lens;
  if (!state.zoom || !state.point) { lens.style.display = "none"; return; }
  const lead = state.view === "wipe" ? state.a : state.current;
  const ref = versions[lead];
  const first = state.loupeCanvases[0];
  const view = first.clientWidth || 200;
  let region = null;
  state.loupeCanvases.forEach((canvas, i) => {
    const v = versions[i];
    sizeCanvas(canvas);
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = state.zoom < 4;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const source = drawable(state, i);
    if (!source || v.kind === "audio") return;
    const r = loupeRegion(state.point.u, state.point.v, view, state.zoom, ref.width, ref.height, v.width, v.height);
    if (i === lead) region = r;
    // Natural size from the element: a scaled picture still maps by share.
    const natW = source.videoWidth || source.naturalWidth || v.width, natH = source.videoHeight || source.naturalHeight || v.height;
    ctx.drawImage(source, r.sx * natW / v.width, r.sy * natH / v.height, r.sw * natW / v.width, r.sh * natH / v.height, 0, 0, canvas.width, canvas.height);
  });
  if (!region) region = loupeRegion(state.point.u, state.point.v, view, state.zoom, ref.width, ref.height, ref.width, ref.height);
  // Outline the magnified piece on the large view.
  const box = state.stage.getBoundingClientRect();
  const fit = fitRect(box.width, box.height, ref.width, ref.height);
  lens.style.display = "block";
  lens.style.left = (fit.x + (region.cu - region.fw / 2) * fit.w) + "px";
  lens.style.top = (fit.y + (region.cv - region.fh / 2) * fit.h) + "px";
  lens.style.width = (region.fw * fit.w) + "px";
  lens.style.height = (region.fh * fit.h) + "px";
}

DATA.groups.forEach(group => {
  const state = group.kind === "audio" ? audioGroup(group) : visualGroup(group);
  players.push(state);
  document.getElementById("groups").append(state.section);
  if (state.kind === "visual") { layout(state); update(state); }
});

document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey || !focused) return;
  if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
  const state = focused;
  if (/^[1-9]$/.test(e.key)) { select(state, Number(e.key) - 1); e.preventDefault(); return; }
  if (e.key === " ") {
    if (state.kind === "audio") state.audio.paused ? state.audio.play() : state.audio.pause();
    else togglePlay(state);
    e.preventDefault();
    return;
  }
  if (state.kind !== "visual") return;
  if (e.key === "," || e.key === ".") { step(state, e.key === "," ? -1 : 1); e.preventDefault(); }
  else if (e.key === "w" || e.key === "W") setView(state, state.view === "wipe" ? "single" : "wipe");
  else if (e.key === "z" || e.key === "Z") setZoom(state, ZOOMS[(ZOOMS.indexOf(state.zoom) + 1) % ZOOMS.length]);
});
if (players.length) focus(players[0]);

// For tests: the state of each player and the pure helpers.
window.__compare = { players, mapTime, spans, select, stepTime, fitRect, loupeRegion };
</script>
</body>
</html>
"""
