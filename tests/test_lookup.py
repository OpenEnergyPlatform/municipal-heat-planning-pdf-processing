"""`following` gives the next (previous) SECTION after a passage AND skips
tables and figures AND is None at either end or for an unknown owner; `item`
gives the one table or figure a placeholder names in any form the text prints
it AND is None for an unknown or a doubly carried placeholder AND never
returns a section; `matching` gives the passages whose text matches AND each
hit names its owner, title and the matching neighbourhood AND the hits stay in
`room` while `total` counts all AND an invalid or catastrophic pattern is a
fault, not an exception."""
import json

from docpipe.extraction import lookup
from docpipe.extraction.lookup import following, item, matching
from docpipe.extraction.pipeline import Source


def sec(i, text, title=None):
    return Source("section", i, text, {"section_title": title or f"S{i}"})


def tab(i, text, block, parent=1):
    return Source("table", i, text, {"title": f"T{i}", "block_id": block,
                                     "parent_section": parent})


def fig(i, text, block, parent=1):
    return Source("figure", i, text, {"title": f"F{i}", "block_id": block,
                                      "parent_section": parent})


DOC = [sec(1, "Alpha\nbody one"), tab(10, "Cap\n| a |", "p1_tab1"),
       fig(20, "Cap\nan image", "p1_img1"), sec(2, "Beta\nbody two"),
       sec(3, "Gamma\nbody three")]


def ids(p):
    return None if p is None else (p.owner_kind, p.owner_id)


# --- following ---------------------------------------------------------

def test_following_gives_next_section_and_skips_table_and_figure():
    assert ids(following(DOC, ("section", 1))) == ("section", 2)
    assert ids(following(DOC, ("section", 2))) == ("section", 3)


def test_following_breaks_when_a_table_is_taken_for_a_section():
    # the table sits right after section 1; a version not skipping it fails
    assert following(DOC, ("section", 1)).owner_kind == "section"


def test_following_previous_section_skips_table_and_figure():
    assert ids(following(DOC, ("section", 2), -1)) == ("section", 1)
    assert ids(following(DOC, ("section", 3), -1)) == ("section", 2)


def test_following_counts_from_a_table_or_figure_own_position():
    assert ids(following(DOC, ("table", 10))) == ("section", 2)
    assert ids(following(DOC, ("figure", 20))) == ("section", 2)
    assert ids(following(DOC, ("table", 10), -1)) == ("section", 1)


def test_following_is_none_at_either_end():
    assert following(DOC, ("section", 3)) is None
    assert following(DOC, ("section", 1), -1) is None


def test_following_is_none_when_only_items_remain():
    assert following([sec(1, "A"), tab(2, "T", "b")], ("section", 1)) is None


def test_following_is_none_for_unknown_owner_and_kind_mismatch():
    assert following(DOC, ("section", 99)) is None
    assert following(DOC, ("table", 1)) is None  # id 1 is a section


def test_following_steps_over_several_sections():
    assert ids(following(DOC, ("section", 1), 2)) == ("section", 3)
    assert following(DOC, ("section", 1), 3) is None


# --- item --------------------------------------------------------------

def test_item_resolves_each_form_the_model_copies():
    for name in ("p1_tab1", "[p1_tab1]", "[p1_tab1: Tabelle 2-3 Energie]",
                 "  [p1_tab1]  "):
        assert ids(item(DOC, name)) == ("table", 10), name
    assert ids(item(DOC, "[p1_img1: Abbildung 2-3]")) == ("figure", 20)


def test_item_is_none_for_a_placeholder_no_passage_has():
    assert item(DOC, "p9_img9") is None
    assert item(DOC, "[p9_img9: x]") is None
    assert item(DOC, "") is None


def test_item_is_none_when_two_passages_carry_the_placeholder():
    twice = DOC + [fig(21, "Cap\nother", "p1_tab1")]
    assert item(twice, "p1_tab1") is None
    assert ids(item(twice, "p1_img1")) == ("figure", 20)  # others unharmed


def test_item_never_returns_a_section():
    s = Source("section", 5, "x", {"block_id": "p2_img1"})
    assert item([s], "p2_img1") is None


# --- matching ----------------------------------------------------------

def test_matching_gives_matching_passages_with_owner_title_and_line():
    r = matching(DOC, "body t", 10_000)
    assert r.fault is None
    assert [h["owner"] for h in r.hits] == [["section", 2], ["section", 3]]
    assert r.total == 2
    assert [h["title"] for h in r.hits] == ["S2", "S3"]
    assert "body two" in r.hits[0]["line"]


def test_matching_finds_nothing_when_nothing_matches():
    r = matching(DOC, "zebra", 10_000)
    assert r.hits == [] and r.total == 0 and r.fault is None


def test_matching_is_case_insensitive_and_titles_items_by_their_title():
    r = matching(DOC, "AN IMAGE", 10_000)
    assert r.hits[0]["owner"] == ["figure", 20]
    assert r.hits[0]["title"] == "F20"


def test_matching_trims_the_line_to_the_neighbourhood():
    far = "x" * 500 + " needle " + "y" * 500
    r = matching([sec(1, "H\n" + far)], "needle", 10_000)
    line = r.hits[0]["line"]
    assert "needle" in line
    assert len(line) < 2 * lookup.NEIGHBOURHOOD + 20


def test_matching_line_is_one_line_of_the_passage():
    r = matching([sec(1, "above\nthe needle here\nbelow")], "needle", 10_000)
    assert "above" not in r.hits[0]["line"]
    assert "below" not in r.hits[0]["line"]


def test_matching_cuts_the_hits_by_room_and_still_counts_all():
    many = [sec(i, f"H\nneedle {i}") for i in range(1, 21)]
    full = matching(many, "needle", 10_000)
    assert len(full.hits) == 20 and full.total == 20
    one = len(json.dumps(full.hits[0], ensure_ascii=False))
    cut = matching(many, "needle", one * 5)
    assert 0 < len(cut.hits) <= 5
    assert cut.total == 20
    assert [h["owner"] for h in cut.hits] == [h["owner"] for h in
                                              full.hits[:len(cut.hits)]]


def test_matching_with_no_room_gives_no_hits_but_counts():
    r = matching(DOC, "body", 1)
    assert r.hits == [] and r.total == 3 and r.fault is None


def test_matching_invalid_pattern_is_a_fault_not_an_exception():
    r = matching(DOC, "(unclosed", 10_000)
    assert r.fault == "invalid_pattern" and r.detail
    assert r.hits == [] and r.total == 0


def test_matching_catastrophic_pattern_times_out_as_a_fault(monkeypatch):
    monkeypatch.setattr(lookup, "PATTERN_TIMEOUT_S", 0.2)
    bomb = [sec(1, "H\n" + "a" * 60 + "b")]
    r = matching(bomb, "(a|aa)+$", 10_000)
    assert r.fault == "timeout" and r.detail
    assert r.hits == []


def test_matching_the_same_catastrophic_pattern_is_fine_when_it_can_succeed():
    ok = [sec(1, "H\n" + "a" * 60)]
    r = matching(ok, "(a|aa)+$", 10_000)
    assert r.fault is None and r.total == 1