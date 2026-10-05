"""Prompt marking against a baseline, segment timing, and in-tile layout."""

from __future__ import annotations

from pathlib import Path

from clipcompare import captions, prompts
from clipcompare.modes.grid import Options, build, build_groups
from clipcompare.prompts import Segment, Token

from helpers import graph, sound, renders

BUNDLED = Path(__file__).resolve().parents[1] / "src" / "clipcompare" / "assets" / "TikTokSans-Medium.ttf"
FONTS = captions.Fonts(body=BUNDLED, tag=BUNDLED)

BASE = "Okay so — I tried this for a week, and honestly? I did not expect it."
TAGGED = "[casual] Okay so — I tried this for a week... and honestly? [soft laugh] I did NOT expect it."


def styles(marked):
    return [(t.text, t.style) for t in marked if t.style != "plain"]


def test_tokens_split_tags_from_words_and_keep_glued_ones_glued():
    found = prompts.tokens("[warm] Hi there,honestly?[laughs] ok")
    assert [t.text for t in found] == ["[warm]", "Hi", "there,honestly?", "[laughs]", "ok"]
    assert [t.space for t in found] == [False, True, True, False, True]


def test_new_tags_are_lilac_and_case_or_punctuation_changes_are_underlined():
    assert styles(prompts.mark(TAGGED, BASE)) == [
        ("[casual]", "tag"), ("week...", "emph"), ("[soft laugh]", "tag"), ("NOT", "emph"),
    ]


def test_a_tag_the_baseline_has_is_shared_and_an_extra_direction_makes_it_new():
    base = "[speaking quickly, energetic] Hello there."
    assert styles(prompts.mark("[energetic, speaking quickly] Hello there.", base)) == [
        ("[energetic, speaking quickly]", "shared"),
    ]
    assert styles(prompts.mark("[speaking quickly, warm] Hello there.", base)) == [
        ("[speaking quickly, warm]", "tag"),
    ]


def test_inserted_punctuation_is_underlined_but_new_words_stay_plain():
    marked = prompts.mark("So — I'm gonna go now", "So I'm going now")
    assert styles(marked) == [("—", "emph")]


def test_without_a_baseline_every_tag_is_new():
    assert styles(prompts.mark("[warm] hi", None)) == [("[warm]", "tag")]
    assert prompts.summary("[warm] hi", None) == ""


def test_summary_counts_new_directions_emphasis_and_dropped_directions():
    base = "[speaking quickly, energetic] You have ten videos saved and zero dollars."
    text = "[speaking quickly, warm] You have TEN videos saved... and zero dollars. [soft laugh]"
    assert prompts.summary(text, base) == "+2 tags · 2 emphasis · no 'energetic'"
    assert prompts.summary(base, base) == "baseline"


def test_word_count_skips_tags_and_bare_punctuation():
    assert prompts.word_count("[warm] Okay so — I tried it... [laughs]") == 5


def test_prepare_marks_each_run_against_its_own_baseline_and_splits_segments():
    captions_ = ("plain a", "[x] plain a", "plain b", "[y] plain B")
    raw = [{"text": "[y] plain", "start": 0, "end": 1}, {"text": "B", "start": 1, "end": 2, "estimated": True}]
    ready = prompts.prepare(captions_, (True, False, True, False), (None, None, None, raw), group=2)
    assert ready[0].summary == "baseline" and ready[0].is_baseline
    assert ready[1].summary == "+1 tag"
    assert ready[3].summary == "+1 tag · 1 emphasis"
    assert [[t.text for t in seg] for seg in ready[3].marked] == [["[y]", "plain"], ["B"]]
    assert ready[3].marked[1][0].style == "emph" and ready[3].segments[1].estimated


def test_windows_follow_segment_timing_and_cover_the_whole_turn():
    prompt = prompts.prepare(("one two",), (), ([{"text": "one", "start": 0.4, "end": 2}, {"text": "two", "start": 2, "end": 5}],))[0]
    assert prompts.windows(prompt, 10.0, 15.0) == [(10.0, 12.0), (12.0, 15.0)]


def test_untimed_segments_split_the_turn_by_text_length():
    prompt = prompts.prepare(("aaa b",), (), ([{"text": "aaa"}, {"text": "b"}],))[0]
    assert prompts.windows(prompt, 0.0, 4.0) == [(0.0, 3.0), (3.0, 4.0)]


def test_wrap_keeps_lines_within_width_and_merges_runs_of_one_style():
    marked = prompts.mark("[warm] one two three four five six seven eight nine ten", None)
    lines = captions.wrap(marked, 200, 20, FONTS)
    assert len(lines) > 1
    for line in lines:
        assert line[-1].x + line[-1].width <= 200 + 0.5
    assert lines[0][0] == captions.Run(0.0, "[warm]", "tag", lines[0][0].width)
    assert lines[0][1].text.startswith("one two")


def test_an_underlined_word_is_a_run_of_its_own():
    marked = [Token("I"), Token("did"), Token("NOT", "emph"), Token("go")]
    runs = captions.wrap(marked, 1000, 20, FONTS)[0]
    assert [run.text for run in runs] == ["I did", "NOT", "go"]


def test_fit_sizes_to_the_longest_segment_not_the_whole_prompt():
    long = [Token(word) for word in ("word " * 120).split()]
    short = [Token("hi")]
    small = captions.fit([long, short], 400, 500, FONTS, 1.0)
    assert captions.fit([short], 400, 500, FONTS, 1.0) == captions.SIZE
    assert captions.FLOOR <= small < captions.SIZE
    lines = captions.wrap(long, 400, small, FONTS)
    assert (len(lines) + captions.CONTEXT) * captions.line_height(small) <= 500


def test_view_dims_neighbours_and_cuts_an_overlong_segment_with_an_ellipsis():
    segs = [[Token("before")], [Token(w) for w in ("now " * 200).split()], [Token("after")]]
    shown = captions.view(segs, 1, 300, 200, 20, FONTS)
    assert shown.rows[0][1] is True                     # the previous segment, dimmed
    assert not any(dimmed for _, dimmed in shown.rows[1:])
    assert shown.rows[-1][0][-1].text == captions.ELLIPSIS
    assert len(shown.rows) * captions.line_height(20) <= 200


def test_render_paints_tags_lilac_and_underlines_in_lilac(tmp_path):
    marked = [Token("[warm]", "tag"), Token("TEN", "emph"), Token("ok")]
    shown = captions.view([marked], 0, 400, 100, 20, FONTS, note=True)
    body = " ".join(captions.render_command(shown, FONTS, tmp_path / "p.png", tmp_path, 400, 100))
    assert "fontcolor=0xcfc3ff:" in body                 # the tag
    assert "drawbox=" in body and "color=0xcfc3ff:t=fill:replace=1" in body   # the underline
    assert "fontcolor=0xfcfaf7@0.7" in body             # the "timing estimated" note
    texts = sorted(path.read_text() for path in tmp_path.glob("p-*.txt"))
    assert "[warm]" in texts and "TEN" in texts and captions.NOTE in texts


def _grid_prompts(**kwargs):
    raw = [{"text": "[warm] one", "start": 0, "end": 1}, {"text": "two", "start": 1, "end": 3}]
    return prompts.prepare(("one two", "[warm] one two"), (True, False), (None, raw), **kwargs)


def test_the_playing_tile_shows_each_segment_in_its_span_and_every_tile_its_summary(tmp_path):
    plan = build(
        [sound(duration=3.0, name="a.mp3"), sound(duration=3.0, name="b.mp3")],
        Options(out=Path("o.mp4"), sequential=True, pause=0.5, prompts=_grid_prompts(), caption_fonts=FONTS),
        tmp_path,
    )
    body = graph(plan.command)
    # b plays 3.5-6.5; its segments at 0-1 s and 1-3 s of the clip
    assert "enable='between(t,3.500,4.500)'" in body and "enable='between(t,4.500,6.500)'" in body
    assert "enable='between(t,0.000,3.000)'" in body    # a: one untimed segment, its whole turn
    assert (tmp_path / "summary-0.txt").read_text() == "baseline"
    assert (tmp_path / "summary-1.txt").read_text() == "+1 tag"
    assert len(renders(plan)) == 3 and plan.caption_size


def test_groups_share_one_prompt_size(tmp_path):
    long = " ".join(["word"] * 400)
    ready = prompts.prepare(("hi", "hi there", long, long + " x"), (True, False, True, False), group=2)
    font = BUNDLED
    plan = build_groups(
        [[sound(), sound()], [sound(), sound()]],
        Options(out=Path("o.mp4"), sequential=True, prompts=ready, caption_fonts=FONTS, title_font=font),
        (None, None), tmp_path,
    )
    sizes = {command[command.index("-vf") + 1].split("fontsize=")[1].split(":")[0]
             for command in plan.pre_commands if "-vf" in command}
    assert len(sizes) == 1

