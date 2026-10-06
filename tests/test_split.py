"""Cutting an oversized section: the LLM says where, the code does it."""
import re
import threading

import pytest

from docpipe.reading import Hole
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


def _cuts(*at, first=None):
    """What a read cut reply is: the one object, as `ask` hands it over."""
    return {"first_title": first,
            "cuts": [{"at": n, "title": f"Teil {n}"} for n in at]}


def test_a_good_answer_is_followed():
    sec = _section([_text(400), _text(400), _text(400)])
    seen = {}

    def ask(system, user, again=False):
        seen["system"], seen["user"] = system, user
        return {"first_title": "Erstes", "cuts": [{"at": 2, "title": "Zweites"}]}

    holes: list = []
    parts = split.split_section(sec, ask, holes=holes)
    assert [p["title"] for p in parts] == ["Erstes", "Zweites"]
    assert "OUTLINE:" in seen["user"] and "600 words" in seen["system"]
    assert holes == [], "an answer that was followed is no hole"


@pytest.mark.parametrize("cause", ["no_object", "syntax", "outside_text",
                                   "missing_key", "refused", "cut_off",
                                   "empty", "error"])
def test_a_hole_is_cut_mechanically_and_named_with_its_cause(cause):
    """The section still gets cut (the model only decides how well) and the
    report says which sections the model did not cut and why."""
    sec = _section([_text(400) for _ in range(6)], "Lang")
    holes: list = []
    parts = split.split_section(sec, lambda s, u, again=False: Hole(cause),
                                holes=holes)
    assert len(parts) > 1
    assert " ".join(p["content"] for p in parts) == sec["content"]
    assert holes == [{"title": "Lang", "why": cause}]


def test_an_answer_of_no_cuts_is_an_answer_and_no_hole():
    """The prompt allows `{"cuts": []}`. The section is cut mechanically all
    the same, because it is far over the limit, but nobody failed."""
    sec = _section([_text(400) for _ in range(6)])
    holes: list = []
    parts = split.split_section(sec, lambda s, u, again=False: {"cuts": []},
                                holes=holes)
    assert len(parts) > 1
    assert holes == []


def test_without_a_model_the_section_is_cut_mechanically_and_no_hole_is_named():
    """Nobody was asked, so nobody failed."""
    sec = _section([_text(400) for _ in range(6)])
    holes: list = []
    assert len(split.split_section(sec, None, holes=holes)) > 1
    assert holes == []


def test_a_call_that_breaks_in_our_own_code_is_not_hidden():
    """The old fallback caught every exception and cut mechanically with one
    log line. A request nobody answered is NotServed; anything else is a
    defect that must be seen."""
    sec = _section([_text(400) for _ in range(6)])

    def ask(system, user, again=False):
        raise RuntimeError("a bug")

    with pytest.raises(RuntimeError):
        split.split_section(sec, ask)


def test_a_section_whose_segments_do_not_match_its_content_is_not_touched():
    """Cutting along provenance that no longer describes the text would lose it."""
    sec = _section([_text(600), _text(600)])
    sec["content"] = "etwas ganz anderes"
    assert split.split_section(sec, lambda s, u, again=False: _cuts(1)) == [sec]


def test_split_oversized_leaves_the_short_ones_in_place():
    short, long = _section([_text(100)], "Kurz"), _section([_text(700), _text(700)], "Lang")
    out = split.split_oversized([short, long], ask=lambda s, u, again=False: _cuts(1))
    assert len(out) == 3
    assert out[0] is short


@pytest.mark.parametrize("at", [float("inf"), float("-inf"), float("nan"),
                                "x", None, [2], {"n": 2}])
def test_a_cut_position_that_is_no_number_is_dropped_and_ends_nothing(at):
    """No `except Exception` stands around the cut any more, so a position that
    a strict JSON read lets through must not raise: Infinity and NaN are valid
    to Python's reader, and an infinity is no integer. The case built to break
    it is the infinity, which used to be cut mechanically by that catch-all."""
    from docpipe import reading

    assert reading.loads_object('{"cuts": [{"at": Infinity}]}') == {
        "cuts": [{"at": float("inf")}]}, "the reader does let it through"
    sec = _section([_text(400), _text(400), _text(400)])
    parts = split.split_section(sec, lambda s, u, again=False: {
        "cuts": [{"at": at, "title": "Nichts"}, {"at": 2, "title": "Zwei"}]})
    assert [p["title"] for p in parts] == ["Bestandsanalyse", "Zwei"]


def test_a_title_that_is_no_text_is_no_title():
    """Element handling of an answer that was read exactly: a number where the
    grammar asks for a string must not end the document."""
    sec = _section([_text(400), _text(400), _text(400)])
    parts = split.split_section(sec, lambda s, u, again=False: {
        "first_title": 7, "cuts": [{"at": 2, "title": 5}]})
    assert [p["title"] for p in parts] == ["Bestandsanalyse",
                                           "Bestandsanalyse"]


# ---------------------------------------------------------------------------
# a cut request that was cut off is asked again for half of the outline
# ---------------------------------------------------------------------------
def _outline_numbers(user):
    """The segment numbers an outline lists, from the request."""
    return [int(n) for n in re.findall(r"^\s*(\d+) \[", user, re.M)]


def test_a_cut_off_outline_is_asked_in_halves_with_the_numbers_it_has():
    sec = _section([_text(400) for _ in range(8)])
    asked = []

    def ask(system, user, again=False):
        numbers = _outline_numbers(user)
        asked.append((numbers[0], numbers[-1], again))
        if len(numbers) == 8:
            return Hole("cut_off")
        if numbers[0] == 0:
            return {"first_title": "Anfang", "cuts": [{"at": 2, "title": "B"}]}
        return {"first_title": "Mitte", "cuts": [{"at": 6, "title": "D"}]}

    parts = split.split_section(sec, ask)
    assert asked == [(0, 7, False), (0, 3, False), (4, 7, False)], (
        "the whole outline once, never again as it stands; then each half "
        "with the numbers of the section")
    # the cuts of both halves and the cut between them, titled by the model
    # for the second half's first part
    assert [p["title"] for p in parts] == ["Anfang", "B", "Mitte", "D"]
    assert " ".join(p["content"] for p in parts) == sec["content"]


def test_the_merged_cuts_are_the_two_halves_and_the_cut_between_them():
    sec = _section([_text(400) for _ in range(8)])

    def ask(system, user, again=False):
        numbers = _outline_numbers(user)
        if len(numbers) == 8:
            return Hole("cut_off")
        if numbers[0] == 0:
            return {"first_title": "A", "cuts": [{"at": 2, "title": "B"}]}
        return {"first_title": "C", "cuts": [{"at": 6, "title": "D"}]}

    got = split._ask_cuts(sec, ask)
    assert got == {"first_title": "A",
                   "cuts": [{"at": 2, "title": "B"}, {"at": 4, "title": "C"},
                            {"at": 6, "title": "D"}]}


def test_a_half_that_is_a_hole_makes_the_whole_cut_a_hole():
    """A stretch nobody placed cuts in is not a cut. The cause is the half's."""
    sec = _section([_text(400) for _ in range(8)])

    def ask(system, user, again=False):
        numbers = _outline_numbers(user)
        if len(numbers) == 8:
            return Hole("cut_off")
        return _cuts(2) if numbers[0] == 0 else Hole("syntax")

    assert split._ask_cuts(sec, ask) == Hole("syntax")
    holes: list = []
    split.split_section(sec, ask, holes=holes)
    assert holes == [{"title": "Bestandsanalyse", "why": "syntax"}]


def test_halves_are_cut_again_until_they_fit_and_never_asked_as_they_stand():
    sec = _section([_text(400) for _ in range(8)])
    sizes = []

    def ask(system, user, again=False):
        numbers = _outline_numbers(user)
        sizes.append(len(numbers))
        return Hole("cut_off") if len(numbers) > 2 else {"cuts": []}

    split._ask_cuts(sec, ask)
    assert sizes == [8, 4, 2, 2, 4, 2, 2]


def test_an_outline_of_one_segment_gets_more_room_once_and_then_is_a_hole():
    sec = _section([_text(400)])
    marks = []

    def ask(system, user, again=False):
        marks.append(again)
        return Hole("cut_off")

    assert split._ask_cuts(sec, ask) == Hole("cut_off")
    assert marks == [False, True], "as it was, and once more marked as again"


def test_a_cut_reply_that_is_read_is_never_asked_twice():
    sec = _section([_text(400) for _ in range(4)])
    asked = []

    def ask(system, user, again=False):
        asked.append(again)
        return _cuts(2)

    split._ask_cuts(sec, ask)
    assert asked == [False]


def test_the_outline_of_a_range_keeps_the_numbers_of_the_section():
    sec = _section([_text(40), _media("p1_tbl0"), _text(40), _text(40)])
    text = split.outline(sec, start=1, stop=3)
    assert _outline_numbers(text) == [1, 2]
    assert "[TABLE] p1_tbl0" in text and "[40 words]" in text
    assert _outline_numbers(split.outline(sec)) == [0, 1, 2, 3]


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

    def ask(system, user, again=False):
        barrier.wait()
        return {"first_title": "Erstes", "cuts": [{"at": 1, "title": "Zweites"}]}

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

    def ask(system, user, again=False):
        i = int(re.search(r"TITLE: S(\d+)", user).group(1))
        if i + 1 < len(sections):
            answered[i + 1].wait(5)     # the last section answers first
        answered[i].set()
        return {"first_title": f"S{i}a",
                "cuts": [{"at": 2, "title": f"S{i}b"}]}

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

    split.split_oversized([sec], ask=lambda s, u, again=False:
                          asked.append(u) or {"cuts": []})

    assert asked == []
