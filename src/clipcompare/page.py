"""`grid --html OUT.html`: a self-contained comparison page.

Per group, one shared player: a button per version (keys 1-9) switches to it
at the same point in the script — mapped segment to segment when both
versions have segment timing, by share of the duration otherwise. The prompt
is shown with the same marks as the video (prompts.py) and the segment being
spoken is highlighted as it plays. Each version shows its duration and words
per minute (spoken words, tags excluded).

Audio is referenced by relative path, never copied; CSS and JS are inline,
with no CDN, so the page works offline from file://.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

from .probe import ClipInfo
from .prompts import ClipPrompt, word_count

TITLE = "Prompt comparison"


def _version(clip: ClipInfo, label: str, prompt: ClipPrompt | None, src: str) -> dict:
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
        "duration": round(duration, 3),
        "wpm": round(words / duration * 60) if duration and words else None,
        "summary": prompt.summary if prompt else "",
        "baseline": bool(prompt and prompt.is_baseline),
        "segments": segments,
    }


def build(
    clips: list[ClipInfo], labels: tuple[str, ...], prompts: tuple[ClipPrompt | None, ...],
    titles: tuple[str | None, ...], group: int, out: Path, heading: str | None = None,
    sources: list[str] | None = None,
) -> str:
    """`sources` are what each player loads (URLs, or paths relative to the
    page); by default each clip's path relative to `out`."""
    size = group or len(clips)
    sources = sources or [
        Path(os.path.relpath(clip.path.resolve(), out.parent.resolve())).as_posix() for clip in clips
    ]
    groups = []
    for number, start in enumerate(range(0, len(clips), size)):
        span = range(start, min(start + size, len(clips)))
        groups.append({
            "title": (titles[number] if number < len(titles) else None) or f"Group {number + 1}",
            "versions": [
                _version(clips[i], labels[i], prompts[i] if prompts else None, sources[i]) for i in span
            ],
        })
    data = json.dumps({"groups": groups}, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(heading or TITLE)
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
  --ds-font-sans: "Telka", "TikTok Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --ds-font-display: "Telka Extended", "Telka", ui-sans-serif, system-ui, sans-serif;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: #0b0b0b; color: var(--ds-text-primary);
  font: 400 16px/1.35 var(--ds-font-sans); letter-spacing: .02em;
}
main { max-width: 1080px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font: 500 28px/1.2 var(--ds-font-display); margin: 0 0 6px; }
.lede { color: var(--ds-text-secondary); margin: 0 0 28px; font-size: 14px; }
.key { display: inline-flex; gap: 14px; flex-wrap: wrap; }
.key span { white-space: nowrap; }
section.group {
  background: var(--ds-black); border: 1px solid var(--ds-primary-300);
  border-radius: 16px; padding: 20px; margin-bottom: 24px;
}
section.group.focused { border-color: rgb(207 195 255 / 45%); }
h2 { font: 500 20px/1.2 var(--ds-font-display); margin: 0 0 14px; }
.versions { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px; margin-bottom: 14px; }
.version {
  text-align: left; font: inherit; color: inherit; cursor: pointer;
  background: var(--ds-invert-600); border: 1px solid var(--ds-primary-300);
  border-radius: 12px; padding: 10px 12px; min-height: 44px;
}
.version:hover { border-color: rgb(252 250 247 / 25%); }
.version[aria-pressed="true"] { border-color: var(--ds-accent-700); box-shadow: inset 0 0 0 1px var(--ds-accent-700); }
.version .name { font-weight: 500; display: flex; gap: 8px; align-items: baseline; }
.version kbd {
  font: 500 11px/1 var(--ds-font-sans); color: var(--ds-text-secondary);
  border: 1px solid var(--ds-primary-300); border-radius: 4px; padding: 2px 5px;
}
.version .stats { color: var(--ds-text-secondary); font-size: 13px; margin-top: 4px; font-variant-numeric: tabular-nums; }
.version .diff { color: var(--ds-text-secondary); font-size: 13px; margin-top: 2px; }
audio { width: 100%; margin-bottom: 14px; }
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
.legend .tag.new, .legend .emph { color: var(--ds-text-primary); }
.legend .tag.new { color: var(--ds-accent-700); }
@media (max-width: 520px) { .prompt { font-size: 17px; } h1 { font-size: 24px; } }
</style>
</head>
<body>
<main>
  <h1>__TITLE__</h1>
  <p class="lede"><span class="key"><span>Click a version, or press 1&ndash;9, to switch at the same point in the script.</span><span>Space plays or pauses.</span></span></p>
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

function fmt(sec) {
  const whole = Math.round(sec), m = Math.floor(whole / 60), s = whole % 60;
  return m + ":" + String(s).padStart(2, "0");
}

function renderPrompt(box, version) {
  box.textContent = "";
  version.segments.forEach((seg, i) => {
    const el = document.createElement("span");
    el.className = "seg";
    el.dataset.index = i;
    seg.tokens.forEach(([text, style, space], j) => {
      if (j && space) el.append(" ");
      if (style === "plain") { el.append(text); return; }
      const span = document.createElement("span");
      span.textContent = text;
      span.className = style === "emph" ? "emph" : style === "tag" ? "tag new" : "tag";
      el.append(span);
    });
    if (seg.estimated) {
      const note = document.createElement("span");
      note.className = "note";
      note.textContent = "timing estimated";
      el.append(note);
    }
    box.append(el);
  });
}

const players = [];
let focused = null;

DATA.groups.forEach((group, g) => {
  const section = document.createElement("section");
  section.className = "group";
  section.innerHTML = '<h2></h2><div class="versions" role="group"></div><audio controls preload="metadata"></audio><div class="prompt" aria-live="off"></div>';
  section.querySelector("h2").textContent = group.title;
  const row = section.querySelector(".versions");
  const audio = section.querySelector("audio");
  const box = section.querySelector(".prompt");
  const state = { group, audio, box, section, current: -1, buttons: [], lastSeg: -1 };
  players.push(state);

  group.versions.forEach((v, i) => {
    const b = document.createElement("button");
    b.className = "version";
    b.type = "button";
    b.setAttribute("aria-pressed", "false");
    const stats = [fmt(v.duration), v.wpm ? v.wpm + " wpm" : null].filter(Boolean).join(" · ");
    b.innerHTML = '<div class="name"><kbd></kbd><span></span></div><div class="stats"></div><div class="diff"></div>';
    b.querySelector("kbd").textContent = i + 1;
    b.querySelector(".name span").textContent = v.label;
    b.querySelector(".stats").textContent = stats;
    b.querySelector(".diff").textContent = v.summary;
    b.addEventListener("click", () => { focus(state); select(state, i, true); });
    row.append(b);
    state.buttons.push(b);
  });
  if (group.versions.some(v => v.segments.some(s => s.tokens.some(([, st]) => st !== "plain")))) {
    const legend = document.createElement("div");
    legend.className = "legend";
    legend.innerHTML = '<span class="tag new">[lilac]</span> a tag the baseline does not have &middot; <span class="emph">underlined</span> a change only in case or punctuation';
    section.append(legend);
  }
  audio.addEventListener("timeupdate", () => highlight(state));
  audio.addEventListener("play", () => {
    focus(state);
    players.forEach(p => { if (p !== state) p.audio.pause(); });
  });
  section.addEventListener("pointerdown", () => focus(state));
  document.getElementById("groups").append(section);
  select(state, 0, false);
});

function focus(state) {
  focused = state;
  players.forEach(p => p.section.classList.toggle("focused", p === state));
}

function duration(state, i) {
  const v = state.group.versions[i];
  return (i === state.current && isFinite(state.audio.duration) && state.audio.duration) || v.duration;
}

function select(state, i, keepPlace) {
  if (i === state.current || i >= state.group.versions.length) return;
  const audio = state.audio;
  const from = state.current >= 0 ? state.group.versions[state.current] : null;
  const to = state.group.versions[i];
  const wasPlaying = !audio.paused;
  const at = from && keepPlace ? mapTime(from, to, audio.currentTime, duration(state, state.current), to.duration) : 0;
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
  const s = spans(v, duration(state, state.current));
  let k = s.findIndex(([a, b]) => t >= a && t < b);
  if (k < 0) k = t >= (s[s.length - 1] || [0, 0])[1] ? s.length - 1 : 0;
  if (k === state.lastSeg) return;
  state.lastSeg = k;
  const segs = state.box.querySelectorAll(".seg");
  segs.forEach((el, j) => el.classList.toggle("now", j === k));
  const now = segs[k];
  if (now) state.box.scrollTop = now.offsetTop;   // the spoken segment at the top
}

document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey || !focused) return;
  if (/^[1-9]$/.test(e.key)) { select(focused, Number(e.key) - 1, true); e.preventDefault(); }
  else if (e.key === " " && e.target === document.body) {
    focused.audio.paused ? focused.audio.play() : focused.audio.pause();
    e.preventDefault();
  }
});
if (players.length) focus(players[0]);

// For tests: the state of each player.
window.__compare = { players, mapTime, spans, select };
</script>
</body>
</html>
"""
