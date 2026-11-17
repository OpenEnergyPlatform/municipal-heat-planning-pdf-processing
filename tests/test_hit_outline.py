"""
A search request lists the tables and figures around its hits (owner decision
2026-11-17, from the literature on reading long documents: the model sees
what else stands in the section of a hit and may fetch it with `item`).

The promises, each with a case that breaks it by construction:

1. The outline names the tables and figures of the sections the hits stand in
   that the request does not show, AND not the shown ones, AND not those of
   other sections, AND each as its placeholder and title line, under the
   heading of its section, AND as many as the rule `hit_outline` says,
   headings not counted, AND none at 0.
2. The payload carries "outline" only where the rule is above 0 AND the
   answer may fetch an item (rule `fetches` has "item", the step may fetch).
3. The search preset shows it after the hits, and every prompt of a search
   has a part for it.
"""
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import presets, shows
from docpipe.extraction.pipeline import Source
from docpipe.extraction.units import Shown

from test_addressed import plan_of

SECTION = Source("section", 2, "Ein Satz des Kapitels. Noch einer.",
                 {"document_id": 7, "page": 2, "section_title": "Bilanz"})
ELSEWHERE = Source("section", 4, "Ein anderes Kapitel.",
                   {"document_id": 7, "page": 5, "section_title": "Ziele"})


def table(owner, block, parent, title):
    return Source("table", owner,
                  f"{title}\n| a | b |\n| --- | --- |\n| 1 | 2 |",
                  {"document_id": 7, "page": 3, "parent_section": parent,
                   "block_id": block})


SHOWN = table(3, "p3_tbl0", 2, "Tabelle 1: Gezeigt")
FIRST = table(5, "p3_tbl1", 2, "Tabelle 2: Erste ungezeigte")
SECOND = table(6, "p4_tbl0", 2, "Tabelle 3: Zweite ungezeigte")
FIGURE = Source("figure", 8, "Abbildung 1: Eine Abbildung\nText.",
                {"document_id": 7, "page": 4, "parent_section": 2,
                 "block_id": "p4_img0"})
OTHER = table(9, "p9_tbl0", 4, "Tabelle 9: Anderer Abschnitt")


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def request_of(plan, hit_owner, fetch=True):
    """A request that shows the pieces of *hit_owner* as its hit."""
    from docpipe.extraction.engine import Scope
    ask = SimpleNamespace(plan=plan, reader=None, scope=Scope(None, True),
                          fetch=fetch,
                          number=lambda key: 0)
    req = shows.Request(ask)
    hits = [c for c in plan.pieces(False) if c.owner == hit_owner]
    req.batch = hits
    req.letter_blocks(hits)
    return req


def outline(plan, hit_owner, **over):
    req = request_of(plan, hit_owner, **over)
    return shows._hit_outline(req, None, {})


def ids(got):
    return [[item["id"] for item in entry["items"]] for entry in got]


def plan():
    return plan_of(SECTION, SHOWN, FIRST, SECOND, FIGURE, ELSEWHERE, OTHER,
                   chunk_units=8)


def test_it_names_the_unshown_items_of_the_hits_section():
    got = outline(plan(), ("table", 3))
    assert ids(got) == [["p3_tbl1", "p4_tbl0", "p4_img0"]]
    assert got[0]["heading"] == "Bilanz"
    assert got[0]["items"][0]["title"] == "Tabelle 2: Erste ungezeigte"
    assert got[0]["items"][2]["title"] == "Abbildung 1: Eine Abbildung"
    # Not the shown table, not another section's table (breaks if either
    # leaks into the outline).
    flat = [i for group in ids(got) for i in group]
    assert "p3_tbl0" not in flat and "p9_tbl0" not in flat


def test_a_hit_that_is_a_section_has_its_items_and_other_sections_theirs():
    got = outline(plan(), ("section", 4))
    assert ids(got) == [["p9_tbl0"]]
    assert got[0]["heading"] == "Ziele"
    assert ids(outline(plan(), ("section", 2))) == [
        ["p3_tbl0", "p3_tbl1", "p4_tbl0", "p4_img0"]]


def test_a_hit_in_another_table_leaves_that_table_out():
    got = outline(plan(), ("table", 5))
    assert ids(got) == [["p3_tbl0", "p4_tbl0", "p4_img0"]]


def test_the_rule_cuts_the_items_and_zero_gives_none():
    with rules.overlaid(hit_outline=2):
        assert ids(outline(plan(), ("table", 3))) == [["p3_tbl1", "p4_tbl0"]]
    with rules.overlaid(hit_outline=0):
        assert outline(plan(), ("table", 3)) is shows.OMIT


def test_an_item_shown_by_another_block_is_not_listed():
    p = plan()
    req = request_of(p, ("table", 3))
    other = next(c for c in p.pieces(False) if c.owner == ("table", 5))
    req.letter_blocks([other])
    got = shows._hit_outline(req, None, {})
    assert ids(got) == [["p4_tbl0", "p4_img0"]]


def test_no_outline_where_no_item_may_be_fetched():
    assert outline(plan(), ("table", 3), fetch=False) is shows.OMIT
    with rules.overlaid(fetches=["next", "search"]):
        assert outline(plan(), ("table", 3)) is shows.OMIT


def test_the_payload_carries_outline_only_above_zero():
    inputs = [spec for spec in presets.PRESETS["search"].inputs
              if spec["key"] == "outline"]
    assert inputs and inputs[0]["show"] == "hit_outline"
    keys = [spec["key"] for spec in presets.PRESETS["search"].inputs]
    assert keys.index("outline") > keys.index("passages")
    p = plan()
    req = request_of(p, ("table", 3))
    assert "outline" in shows.build(req, inputs)
    with rules.overlaid(hit_outline=0):
        req = request_of(p, ("table", 3))
        assert "outline" not in shows.build(req, inputs)


@pytest.mark.parametrize("path", [
    "docpipe/builtin/default", "profiles/kwp", "profiles/scenarios"])
def test_every_search_prompt_has_a_part_for_it(path):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    text = (root / path / "prompts/extraction/search.md").read_text(
        encoding="utf-8")
    assert "<!-- with: outline -->" in text
    assert Shown is not None
