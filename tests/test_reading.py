"""What the reading shares with the steps around it (reading.py), each
promise with a case that breaks it by construction.

The compute step's tools show the next section, a table or figure by its
placeholder and a hit by its id, each once; "similar" lists the passages of
the plan nearest to the model's own sentence, the best of each kind, AND
without a ranking it finds nothing and says so; no list shows what it was
searched with, AND the gathering keeps it, so the same search is not made
twice.

The two ends of a range a passage prints are linked on both rows, AND only
where every other coordinate and the quote agree. A correction names the ways
of answering that pass in its request.
"""
import json
from pathlib import Path

from docpipe.extraction import fields, reading
from docpipe.extraction.pipeline import Row, Source, merge_field
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.wording import say

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
EMISSION = SPEC.by_uri["emission"]
SLOTS = {slot.name: slot for slot in reading.slots_of(SPEC, EMISSION)}

BARE = Source("section", 6, "Bilanz\nEs fielen rund 300 t CO2 an.",
              {"document_id": 7, "section_title": "Bilanz"})
FIGURE = Source("figure", 30, "Abbildung 4\nBalken der Emissionen 2030",
                {"document_id": 7, "block_id": "p3_img1"})
AFTER = Source("section", 8, "Ausblick\nDie Werte gelten für das Jahr 2030.",
               {"document_id": 7, "section_title": "Ausblick"})
PLAN = {("section", 6): BARE, ("figure", 30): FIGURE, ("section", 8): AFTER}
ORDER = list(PLAN.values())
PROBE = "Die Emissionen gelten für das Bilanzjahr 2022."
NEAREST = [Source("section", 100 + i, f"S{i}\nText {i}", {})
           for i in range(20)]


def tools():
    """The tools of a compute request on BARE."""
    return reading.Gathered(seen={("section", 6)},
                            cursor={"next": ("section", 6),
                                    "previous": ("section", 6)})


def ranking(found):
    """A ranking of the plan that returns *found* without what it excludes,
    and the calls it got."""
    calls = []

    def rank(probes, exclude):
        calls.append((list(probes), set(exclude)))
        return [s for s in found if (s.owner_kind, s.owner_id) not in exclude]
    return rank, calls


def test_the_next_section_asked_for_is_shown_once_and_then_the_end():
    gathered = tools()
    assert gathered.fetch([{"get": "next"}], ORDER, PLAN, None)
    assert [m["text"] for m in gathered.context()["more"]] == [AFTER.text]
    # the failure by construction: past the last section there is none
    assert not gathered.fetch([{"get": "next"}], ORDER, PLAN, None)
    assert gathered.missed == [{"get": "next", "why": reading.END}]


def test_a_table_or_figure_named_by_its_placeholder_is_shown_and_none_else():
    gathered = tools()
    assert gathered.fetch([{"get": "item", "id": "[p3_img1: Abbildung 4]"},
                           {"get": "item", "id": "p9_img9"}], ORDER, PLAN,
                          None)
    assert [m["kind"] for m in gathered.context()["more"]] == ["figure"]
    assert gathered.missed == [{"get": "item", "id": "p9_img9",
                                "why": reading.UNKNOWN}]


def test_a_search_lists_its_hits_and_a_hit_asked_for_is_shown():
    gathered = tools()
    assert gathered.fetch([{"get": "search", "pattern": r"Jahr 20\d\d"}],
                          ORDER, PLAN, None)
    (listed,) = gathered.context()["hits"]
    assert listed["total"] == 1 and listed["hits"][0]["id"] == "H1"
    # Its hits, not its pattern (owner decision 2026-11-06).
    assert set(listed) == {"total", "hits"}
    assert gathered.hits[0]["pattern"] == r"Jahr 20\d\d"
    assert "more" not in gathered.context()
    assert gathered.fetch([{"get": "hit", "id": "H1"}], ORDER, PLAN, None)
    assert [m["text"] for m in gathered.context()["more"]] == [AFTER.text]
    # the failure by construction: a hit no list named is unknown
    assert not gathered.fetch([{"get": "hit", "id": "H9"}], ORDER, PLAN, None)
    assert gathered.missed[-1]["why"] == reading.UNKNOWN


def test_a_search_after_a_list_no_search_made_is_searched_once():
    gathered = reading.Gathered()
    gathered.list_hits([(("section", 6), "Bilanz", "Es fielen rund 300 t CO2")],
                       query="Emissionen")
    ask = [{"get": "search", "pattern": r"Jahr 20\d\d"}]
    assert gathered.fetch(ask, ORDER, PLAN, None)
    assert not gathered.fetch(ask, ORDER, PLAN, None)
    # No list shows what it was searched with, whoever searched.
    assert all(set(listed) <= {"total", "hits"}
               for listed in gathered.context()["hits"])


def test_similar_lists_the_passages_nearest_to_its_sentence_best_of_each_kind():
    rank, calls = ranking(NEAREST)
    gathered = reading.Gathered(seen={("section", 6)}, rank=rank)
    ask = [{"get": "similar", "text": PROBE}]
    assert gathered.fetch(ask, ORDER, PLAN, None)
    assert calls == [([PROBE], {("section", 6)})]
    (listed,) = gathered.context()["hits"]
    # Its hits, not its sentence, which the gathering keeps (owner decision
    # 2026-11-06).
    assert set(listed) == {"hits"}
    assert PROBE not in json.dumps(gathered.context(), ensure_ascii=False)
    assert gathered.hits[0]["similar"] == PROBE
    assert [hit["title"] for hit in listed["hits"]] \
        == [f"S{i}" for i in range(reading.SHOWN["section"])]
    # The same sentence again asks nothing and brings nothing new.
    assert not gathered.fetch(ask, ORDER, PLAN, None)
    assert len(calls) == 1


def test_similar_without_a_ranking_finds_nothing_and_says_so():
    gathered = reading.Gathered()
    assert not gathered.fetch([{"get": "similar", "text": PROBE}],
                              ORDER, PLAN, None)
    assert gathered.missed == [{"get": "similar", "text": PROBE,
                                "why": reading.UNKNOWN}]


def test_the_two_ends_of_a_range_are_linked_on_both_rows():
    slots = reading.slots_of(SPEC, EMISSION)

    def end(label, value, which, quote="zwischen 60 und 100 t CO2", **more):
        return Row(label=label, item_index=0, claim={
            "value": value, "quote": quote, "qualifier": which,
            "qualifier_state": "read", **more})
    low, high = end("R1", 60, fields.RANGE_LOW), end("R2", 100,
                                                     fields.RANGE_HIGH)
    assert reading.link_ranges([low, high], slots) == 1
    assert low.claim[fields.RANGE] == high.claim[fields.RANGE] == [60, 100]
    # Another answer to a coordinate, or another quote, is another range.
    gas = end("R3", 60, fields.RANGE_LOW, carrier="Erdgas")
    oil = end("R4", 100, fields.RANGE_HIGH, carrier="Heizöl")
    elsewhere = end("R5", 100, fields.RANGE_HIGH, quote="bis 100 t CO2")
    assert reading.link_ranges([gas, oil, elsewhere], slots) == 0
    assert fields.RANGE not in gas.claim


def test_a_correction_names_the_ways_that_pass_in_its_request():
    source = [Source("section", 1, "Wärmeverbrauch Erdgas 300 MWh im Jahr", {})]
    quote = "Wärmeverbrauch Erdgas 300 MWh"
    got = merge_field([Row("R1", 0, {})], source, SLOTS["carrier"],
                      {"answers": {"R1": {"value": "Heizöl", "quote": quote}}})
    assert got["failed"][0]["reason"] == say(
        "answer_not_in_quote", answer="Heizöl") + say("or_unstated",
                                                      unstated=fields.UNSTATED)
    got = merge_field([Row("R1", 0, {})], source, SLOTS["subject"],
                      {"answers": {"R1": {"value": "Schule", "quote": quote}}})
    assert got["failed"][0]["reason"] == say(
        "answer_not_in_quote_text", answer="Schule") + say(
            "or_unstated", unstated=fields.UNSTATED)
