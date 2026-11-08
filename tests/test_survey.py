"""The spec puts every coordinate in exactly one group, read in the reading;
and every passage of a plan is read for every parameter, each parameter's
passages best first by its own search, the rest after them in the plan's
order, the order kept on disk under its own key (owner decisions
2026-11-08).

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import survey
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import SpecError, load as load_spec

RAW = json.loads((Path(__file__).resolve().parent.parent / "profiles" / "kwp"
                  / "extraction_spec.json").read_text(encoding="utf-8"))
SPEC = load_spec(RAW)


def with_groups(change) -> dict:
    raw = copy.deepcopy(RAW)
    change(raw["groups"])
    return raw


def passage(kind, number, text, page=1):
    return Source(kind, number, text, {"document_id": 7, "page": page,
                                       "section_title": "Bilanz"})


# -- the groups of the spec ----------------------------------------------------

def test_every_coordinate_of_the_spec_is_in_exactly_one_group():
    grouped = [c for group in SPEC.groups.values() for c in group.coordinates]
    assert len(grouped) == len(set(grouped))
    # Every group is read in the reading (owner decision 2026-11-07: each
    # value is asked its own scenario and year).
    assert {group.read_in for group in SPEC.groups.values()} == {"reading"}


def test_a_coordinate_in_no_group_is_refused():
    raw = with_groups(lambda g: g["context"]["coordinates"].remove("whole"))
    with pytest.raises(SpecError, match="whole"):
        load_spec(raw)


def test_a_coordinate_in_two_groups_is_refused():
    raw = with_groups(lambda g: g["number"]["coordinates"].append("year"))
    with pytest.raises(SpecError, match="already in group"):
        load_spec(raw)


def test_a_name_that_is_no_coordinate_is_refused():
    raw = with_groups(lambda g: g["context"]["coordinates"].append("colour"))
    with pytest.raises(SpecError, match="no coordinate"):
        load_spec(raw)


def test_a_group_read_by_no_step_is_refused():
    raw = with_groups(lambda g: g["frame"].update(read_in="search"))
    with pytest.raises(SpecError, match="read_in"):
        load_spec(raw)


def test_a_group_read_in_the_survey_is_refused():
    # Owner decisions 2026-11-08: the survey is gone, so a group it was to
    # read would be read by no step.
    raw = with_groups(lambda g: g["frame"].update(read_in="survey"))
    with pytest.raises(SpecError, match="read_in"):
        load_spec(raw)


def test_what_only_a_value_s_own_passage_or_number_says_is_of_its_group():
    # Owner decision 2026-11-06: what a number counts and how it is
    # aggregated only its own passage says, a word like "ca." only the
    # number itself; the combing does not look for them elsewhere.
    number, context = SPEC.groups["number"], SPEC.groups["context"]
    # And its unit, what the number is, and the beginning of a period it is
    # a mean over: read again beside it, never searched elsewhere (owner
    # decisions 2026-11-07).
    assert (number.own_passage, number.own_value) == (
        ("unit", "what", "subject"), ("qualifier",))
    # Which body made the plan, the municipality itself or another, only the
    # passage that names it says (owner decision 2026-11-07).
    assert context.own_passage == ("aggregation", "role")
    assert SPEC.groups["frame"].own_passage == ()
    raw = with_groups(lambda g: g["number"].update(own_passage=["year"]))
    with pytest.raises(SpecError, match="group's coordinates"):
        load_spec(raw)
    raw = with_groups(lambda g: g["number"].update(own_value=["subject"]))
    with pytest.raises(SpecError, match="not both"):
        load_spec(raw)


# -- pieces and pages ----------------------------------------------------------

def test_a_text_longer_than_its_room_goes_in_pieces_that_keep_it():
    long = "Zeile mit Text\n" * 100
    cut = survey.pieces(long, 300)
    assert len(cut) > 1 and all(len(piece) <= 300 for piece in cut)
    assert "".join(cut) == long


def test_two_pages_are_twice_the_plans_text_per_page_without_figures():
    passages = [passage("section", 1, "a" * 4000),
                passage("figure", 2, "b" * 9000)]
    assert survey.budget_of(passages, 4) == 2000
    assert survey.budget_of(passages, 4, 1) == 1000


# -- the order every passage is read in ----------------------------------------
# Promise (owner decisions 2026-11-08): every passage of the plan is read for
# every parameter, AND each parameter's passages come best first by its own
# search, AND a passage the search did not return comes after them in the
# plan's order, AND no passage is left out or named twice.

PLAN = [passage("section", 1, "Einleitung"), passage("table", 2, "Tabelle"),
        passage("figure", 3, "Abbildung"), passage("section", 4, "Ausblick")]
EMISSION, ENERGY = SPEC.by_uri["emission"], SPEC.by_uri["energy_consumption"]


def ranked_by(order_of: dict):
    """A search that returns, for a parameter's sentence, the passages
    *order_of* lists for it, best first; the sentences it was asked."""
    asked = []

    def rank(document_id, sentences, exclude):
        asked.append(list(sentences))
        return [next(p for p in PLAN if p.owner_id == number)
                for number in order_of.get(sentences[0], ())]
    return rank, asked


def test_every_passage_is_read_for_every_parameter():
    found = survey.Ranking(None, lambda d: PLAN, [EMISSION, ENERGY])(7)
    owners = [(p.owner_kind, p.owner_id) for p in PLAN]
    for parameter in (EMISSION, ENERGY):
        assert found.passages_of(parameter.uri) == owners
    # The failure by construction: a parameter the order was not made for
    # is read nowhere.
    assert found.passages_of("heat_load") == []


def test_each_parameter_reads_its_own_best_first_and_the_rest_after():
    rank, asked = ranked_by({EMISSION.label: [3, 2],
                             ENERGY.label: [4]})
    found = survey.Ranking(rank, lambda d: PLAN, [EMISSION, ENERGY])(7)
    assert asked == [[EMISSION.label], [ENERGY.label]]
    assert found.passages_of(EMISSION.uri) == [
        ("figure", 3), ("table", 2), ("section", 1), ("section", 4)]
    assert found.passages_of(ENERGY.uri) == [
        ("section", 4), ("section", 1), ("table", 2), ("figure", 3)]


def test_a_hit_outside_the_plan_and_a_hit_named_twice_are_no_passages():
    ranked = [SimpleNamespace(owner_kind="table", owner_id=99), PLAN[1],
              PLAN[1]]
    assert survey.ranked_owners(ranked, PLAN) == [
        ("table", 2), ("section", 1), ("figure", 3), ("section", 4)]


def test_a_search_that_fails_reads_in_the_plans_order():
    def rank(document_id, sentences, exclude):
        raise RuntimeError("the index is gone")
    found = survey.Ranking(rank, lambda d: PLAN, [EMISSION])(7)
    assert found.passages_of(EMISSION.uri) == [
        (p.owner_kind, p.owner_id) for p in PLAN]


def test_an_order_is_kept_and_read_again_while_its_parameters_and_passages_stay(
        tmp_path):
    rank, asked = ranked_by({EMISSION.label: [3]})
    survey.Ranking(rank, lambda d: PLAN, [EMISSION], store=tmp_path)(7)
    again = survey.Ranking(rank, lambda d: PLAN, [EMISSION],
                           store=tmp_path)(7)
    assert len(asked) == 1
    assert again.passages_of(EMISSION.uri)[0] == ("figure", 3)
    # The failure by construction: other passages, or other parameters, and
    # it is made anew.
    survey.Ranking(rank, lambda d: PLAN[:3], [EMISSION], store=tmp_path)(7)
    survey.Ranking(rank, lambda d: PLAN, [EMISSION, ENERGY],
                   store=tmp_path)(7)
    assert len(asked) == 4


def test_an_order_of_part_of_a_plan_is_kept_beside_the_whole_ones(tmp_path):
    survey.Ranking(None, lambda d: PLAN, [EMISSION], store=tmp_path)(7)
    survey.Ranking(None, lambda d: PLAN, [EMISSION], store=tmp_path,
                   scope="found")(7, PLAN[:2])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["7.found.json",
                                                          "7.json"]
    kept = json.loads((tmp_path / "7.found.json").read_text(encoding="utf-8"))
    assert [a["owner"] for a in kept["answers"]] == [["section", 1],
                                                    ["table", 2]]


def test_the_reading_reads_each_parameter_s_passages_in_their_order():
    from docpipe.extraction import reading
    rank, _asked = ranked_by({EMISSION.label: [4, 2]})
    found = survey.Ranking(rank, lambda d: PLAN, [EMISSION])(7)
    read = []

    def ask_values(source, parameter, context, done, thread, follow=None,
                   drawn=False):
        read.append((source.owner_kind, source.owner_id))
        return {"values": [], "incomplete": False}
    reader = reading.Reader(SPEC, ask_values, lambda *a, **k: {})
    reader(7, found, {(p.owner_kind, p.owner_id): p for p in PLAN})
    assert read == [("section", 4), ("table", 2), ("section", 1),
                    ("figure", 3)]
