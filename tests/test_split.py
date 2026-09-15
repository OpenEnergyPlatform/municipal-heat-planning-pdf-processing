"""Cutting an oversized section: the LLM says where, the code does it."""
import json
import re
import threading

import pytest

from docpipe.refinement import split


def _text(words, page=1):
    return {"page": page, "kind": "text", "text": " ".join(f"w{i}" for i in range(words))}


def _media(ref, kind="table", page=1):
    return {"page": page, "kind": kind, "ref": ref}


def _section(segments, title="Bestandsanalyse"):
    sec = {
        "title": title,
        "segments": segments,
        "page_number": segments[0]["page"] if segments else 1,
        "tables": [{"id": s["ref"], "path": f"images/{s['ref']}.png", "caption": "T"}
                   for s in segments if s.get("kind") == "table"],
        "figures": [{"id": s["ref"], "path": f"images/{s['ref']}.png", "caption": "F"}
                    for s in segments if s.get("kind") == "figure"],
    }
    sec["content"] = split.content_from_segments(segments)
    sec["pages"] = sorted({s["page"] for s in segments})
    return sec


# ---------------------------------------------------------------------------
# what counts as oversized
# ---------------------------------------------------------------------------
def test_a_normal_section_is_left_alone():
    assert not split.needs_split(_section([_text(300)]))


def test_a_literature_section_is_never_split():
    """Its content is a list of BibTeX strings, not prose."""
    sec = {"title": "[LITERATURE]", "content": ["@book{a}", "@book{b}"], "segments": []}
    assert not split.needs_split(sec)


def test_oversized_is_measured_in_words():
    assert split.needs_split(_section([_text(1200)]))


# ---------------------------------------------------------------------------
# the cut itself
# ---------------------------------------------------------------------------
def test_the_parts_together_are_the_original_text():
    """Nothing may be rephrased, dropped or duplicated."""
    segments = [_text(200), _text(200), _text(200), _text(200)]
    sec = _section(segments)
    parts = split.apply_cuts(sec, [{"at": 2, "title": "Zweiter Teil"}])
    assert len(parts) == 2
    assert " ".join(p["content"] for p in parts) == sec["content"]


def test_each_part_keeps_only_its_own_media_and_pages():
    segments = [_text(150, page=1), _media("p1_tbl0", "table", 1),
                _text(150, page=4), _media("p4_img0", "figure", 4)]
    sec = _section(segments)
    a, b = split.apply_cuts(sec, [{"at": 2, "title": "Potenziale"}])
    assert [t["id"] for t in a["tables"]] == ["p1_tbl0"] and a["figures"] == []
    assert [f["id"] for f in b["figures"]] == ["p4_img0"] and b["tables"] == []
    assert a["pages"] == [1] and b["pages"] == [4]
    assert a["page_number"] == 1 and b["page_number"] == 4


def test_the_placeholder_survives_in_the_part_that_holds_it():
    sec = _section([_text(150), _media("p1_tbl0"), _text(150)])
    parts = split.apply_cuts(sec, [{"at": 2, "title": "B"}])
    assert "[p1_tbl0]" in parts[0]["content"]
    assert "[p1_tbl0]" not in parts[1]["content"]


def test_titles_come_from_the_model_first_part_may_keep_its_own():
    sec = _section([_text(200), _text(200)])
    parts = split.apply_cuts(sec, [{"at": 1, "title": "Potenzialanalyse"}],
                             first_title="Bestandsanalyse")
    assert [p["title"] for p in parts] == ["Bestandsanalyse", "Potenzialanalyse"]


def test_a_part_without_a_title_still_gets_one():
    sec = _section([_text(200), _text(200)])
    parts = split.apply_cuts(sec, [{"at": 1, "title": None}])
    assert all(p["title"] for p in parts)


# ---------------------------------------------------------------------------
# what the model is allowed to propose
# ---------------------------------------------------------------------------
def test_cuts_outside_the_section_are_dropped():
    sec = _section([_text(300), _text(300), _text(300)])
    kept = split._sanitize([{"at": 0}, {"at": 99}, {"at": -1}, {"at": 2}], 3, sec)
    assert [c["at"] for c in kept] == [2]


def test_a_cut_that_would_leave_a_sliver_is_dropped():
    """Below ~100 words a part is not a chunk, it is debris.

    Both cuts are proposed, which would make the 20-word block a part of its
    own. The second is dropped, so that block joins the part after it.
    """
    sec = _section([_text(300), _text(20), _text(300)])
    assert split._sanitize([{"at": 1}, {"at": 2}], 3, sec) == [{"at": 1, "title": None}]


def test_a_trailing_sliver_does_not_get_its_own_part():
    sec = _section([_text(300), _text(20)])
    assert split._sanitize([{"at": 1}], 2, sec) == []


def test_duplicate_cuts_collapse():
    sec = _section([_text(300), _text(300)])
    assert len(split._sanitize([{"at": 1}, {"at": 1}], 2, sec)) == 1


# ---------------------------------------------------------------------------
# talking to the model
# ---------------------------------------------------------------------------
def test_the_model_sees_an_outline_not_the_text():
    sec = _section([_text(40), _media("p1_tbl0"), _text(40)])
    text = split.outline(sec)
    assert "[40 words]" in text and "[TABLE] p1_tbl0" in text
    assert len(text.split()) < len(sec["content"].split())      # far smaller


def test_a_good_answer_is_followed():
    sec = _section([_text(400), _text(400), _text(400)])
    seen = {}

    def ask(system, user):
        seen["system"], seen["user"] = system, user
        return json.dumps({"first_title": "Erstes", "cuts": [{"at": 2, "title": "Zweites"}]})

    parts = split.split_section(sec, ask)
    assert [p["title"] for p in parts] == ["Erstes", "Zweites"]
    assert "OUTLINE:" in seen["user"] and "600 words" in seen["system"]


@pytest.mark.parametrize("reply", ["not json", '{"cuts": "kaputt"}', '{}', ""])
def test_an_unusable_answer_falls_back_to_a_mechanical_cut(reply):
    """The section still gets cut — the model only decides how well."""
    sec = _section([_text(400) for _ in range(6)])
    parts = split.split_section(sec, lambda s, u: reply)
    assert len(parts) > 1
    assert " ".join(p["content"] for p in parts) == sec["content"]


def test_a_failing_call_falls_back_too():
    sec = _section([_text(400) for _ in range(6)])

    def ask(system, user):
        raise RuntimeError("server down")

    assert len(split.split_section(sec, ask)) > 1


def test_a_section_whose_segments_do_not_match_its_content_is_not_touched():
    """Cutting along provenance that no longer describes the text would lose it."""
    sec = _section([_text(600), _text(600)])
    sec["content"] = "etwas ganz anderes"
    assert split.split_section(sec, lambda s, u: '{"cuts": [{"at": 1}]}') == [sec]


def test_split_oversized_leaves_the_short_ones_in_place():
    short, long = _section([_text(100)], "Kurz"), _section([_text(700), _text(700)], "Lang")
    out = split.split_oversized([short, long], ask=lambda s, u: '{"cuts": [{"at": 1}]}')
    assert len(out) == 3
    assert out[0] is short


# ---------------------------------------------------------------------------
# the split calls of a document go out together
# ---------------------------------------------------------------------------
def test_the_split_calls_go_out_together(monkeypatch):
    """Serially this phase held exactly one request in flight per document, and
    it finishes before the first refinement window is dispatched. The barrier
    only clears if the calls overlap."""
    monkeypatch.setattr(split, "LLM_NUM_PARALLEL", 4)
    sections = [_section([_text(700), _text(700)], f"Lang {i}") for i in range(4)]
    barrier = threading.Barrier(len(sections), timeout=5)

    def ask(system, user):
        barrier.wait()
        return json.dumps({"first_title": "Erstes",
                           "cuts": [{"at": 1, "title": "Zweites"}]})

    out = split.split_oversized(sections, ask=ask)

    assert not barrier.broken
    # A mechanical fallback would cut these in two as well — only the titles
    # say the model's answer was used.
    assert [p["title"] for p in out] == ["Erstes", "Zweites"] * 4


def test_the_replies_land_on_the_section_they_describe(monkeypatch):
    """Under a pool the answers come back out of order — here in reverse, on
    purpose. The cuts still have to be the serial ones, in the serial order."""
    monkeypatch.setattr(split, "LLM_NUM_PARALLEL", 4)
    sections = [_section([_text(400) for _ in range(3)], f"S{i}") for i in range(4)]
    answered = [threading.Event() for _ in sections]

    def ask(system, user):
        i = int(re.search(r"TITLE: S(\d+)", user).group(1))
        if i + 1 < len(sections):
            answered[i + 1].wait(5)     # the last section answers first
        answered[i].set()
        return json.dumps({"first_title": f"S{i}a",
                           "cuts": [{"at": 2, "title": f"S{i}b"}]})

    parallel = split.split_oversized(sections, ask=ask)
    # Every event is set by now, so the reference run answers straight away.
    serial = [p for s in sections for p in split.split_section(s, ask)]

    assert [p["title"] for p in parallel] == [f"S{i}{c}" for i in range(4)
                                              for c in ("a", "b")]
    assert [(p["title"], p["content"]) for p in parallel] \
        == [(p["title"], p["content"]) for p in serial]


def test_a_section_that_cannot_be_cut_is_not_asked_about(monkeypatch):
    """Its segments no longer rebuild its content, so no answer could be used."""
    monkeypatch.setattr(split, "LLM_NUM_PARALLEL", 4)
    sec = _section([_text(600), _text(600)])
    sec["content"] = "etwas ganz anderes"
    asked = []

    split.split_oversized([sec], ask=lambda s, u: asked.append(u) or "{}")

    assert asked == []
