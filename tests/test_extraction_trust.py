"""How much of a value the run can stand behind, as a level a reader can act on.

Every accepted tuple is verified, and that is a floor rather than a grade: a
value read out of the document's own text and one read out of a picture, with
a coordinate the run gave up on, both clear it.

What these tests hold is that the cut is where the measurement puts it. Image
origin alone separates nothing on this corpus (527 of Kassel's 559 tuples came
out of a table or figure), so it is not a warning. Where a coordinate's passage
stands is no reason either: the harvest takes any shown passage that carries
the answer, and a second check here would be one it does not make.

No model, no GPU.
"""
import importlib
from pathlib import Path

import pytest

from docpipe.extraction import fields
from docpipe.extraction.trust import (LEVEL_A, LEVEL_B, LEVEL_C, MARKS,
                                      check_prose, document_summary, marks,
                                      render, trust)
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL


def _row(**overrides):
    """A value with everything read, every passage in its own table."""
    row = {
        "parameter": "energy_consumption", "value": 241.0,
        "value_target": 241.0, "tier": TIER_TEXT, "flags": [],
        "provenance": {"document_id": 857, "owner_kind": "table",
                       "owner_id": 87457, "parent_section": 349525,
                       "page": 86},
    }
    for name in ("quantity", "carrier", "sector", "year", "scenario",
                 "spatial_scope"):
        row[f"{name}_state"] = fields.READ
        row[f"{name}_source"] = ["table", 87457]
    row["aggregation_state"] = fields.DERIVED
    row.update(overrides)
    return row


def test_a_value_read_off_its_own_table_in_the_plans_text_is_an_a():
    verdict = trust(_row())
    assert verdict == {"level": LEVEL_A, "reasons": [], "image_origin": False,
                       "corroborated": False}


def test_a_reading_out_of_a_picture_is_a_b_and_not_a_warning():
    """527 of Kassel's 559 tuples came out of a table or figure image. A
    signal that fires on 94 percent of the corpus separates nothing, so it
    lowers the level and adds no reason for anyone to chase."""
    verdict = trust(_row(tier=TIER_VISUAL))
    assert verdict["level"] == LEVEL_B
    assert verdict["reasons"] == []
    assert verdict["image_origin"] is True


def test_the_same_value_from_a_transcribed_plan_never_reaches_a():
    """Eleven plans of the corpus have no PDF text layer: a model read their
    pages and everything downstream ran unchanged, so the section text a
    quote is verified against is itself a reading."""
    assert trust(_row())["level"] == LEVEL_A
    capped = trust(_row(), transcribed=True)
    assert capped["level"] == LEVEL_B
    assert capped["reasons"] == ["page_transcribed"]
    # And it caps rather than condemns: on its own it is not a C.
    assert trust(_row(tier=TIER_VISUAL), transcribed=True)["level"] == LEVEL_B


def test_where_a_coordinates_passage_stands_is_not_a_reason():
    """The harvest takes a reading whose quote stands in a shown passage and
    carries the answer, wherever the passage stands. A year cited from
    another table's caption is such a reading, and grading it down here
    would be a check the harvest does not make."""
    assert trust(_row(year_source=["table", 87517])) == {
        "level": LEVEL_A, "reasons": [], "image_origin": False,
        "corroborated": False}
    assert trust(_row(carrier_source=["section", 1]))["level"] == LEVEL_A


@pytest.mark.parametrize("field,expected", [
    ({"year_state": fields.EXHAUSTED}, "exhausted:year"),
    ({"sector_state": fields.UNBACKED}, "unbacked:sector"),
    ({"flags": ["quote_repaired"]}, "repaired"),
    ({"flags": ["computed"]}, "computed"),
    ({"flags": ["not_located"]}, "not_located"),
])
def test_every_doubt_the_harvest_records_lowers_the_level(field, expected):
    verdict = trust(_row(**field))
    assert verdict["level"] == LEVEL_C
    assert expected in verdict["reasons"]


def test_a_contested_identity_is_a_c_even_with_everything_else_right():
    verdict = trust(_row(), conflict=True)
    assert verdict["level"] == LEVEL_C
    assert verdict["reasons"] == ["conflict"]


def test_a_coordinate_the_plan_does_not_state_is_not_a_doubt():
    """"The plan does not say it" is a finding about the plan, and "never
    asked, the row left at the gate" is one about this run's scope. Neither
    is a reason to distrust the number that was read."""
    for state in (fields.SAID_UNSTATED, fields.OUT_OF_SLICE,
                  fields.DERIVED, fields.UNANSWERED):
        # The source key is left pointing at a foreign table on purpose. A
        # coordinate that is not read has no evidence to judge, so whatever
        # a previous window left behind must not be judged as if it had.
        verdict = trust(_row(sector_state=state,
                             sector_source=["table", 87517]))
        assert verdict["level"] == LEVEL_A, state
        assert verdict["reasons"] == [], state


def test_the_line_says_what_to_do_about_it():
    """The core no longer writes the words, so this is asked through a
    profile's table. kwp's, because kwp's line is the published wording."""
    from profiles.kwp.kg import TRUST_JOIN, TRUST_PROSE
    line = render(trust(_row(tier=TIER_VISUAL,
                             year_state=fields.EXHAUSTED)),
                  TRUST_PROSE, join=TRUST_JOIN, row=_row(tier=TIER_VISUAL))
    assert line.startswith("Trust: C")
    assert "exhausted:year" in line
    assert "review recommended" in line
    # An A says its level and nothing else: there is nothing to act on.
    assert render(trust(_row()), TRUST_PROSE, join=TRUST_JOIN) == "Trust: A"


# ---------------------------------------------------------------------------
# The seam: the marks are the core's, the words are the profile's
# ---------------------------------------------------------------------------

# Enough verdicts to make the core produce every mark it has, each isolating
# as few as it can. Not a sample of what a run writes: a matrix of what a line
# CAN say, which is what a profile has to be able to word.
_VERDICTS = [
    ({"level": LEVEL_A, "reasons": [], "image_origin": False,
      "corroborated": False}, {}),                            # level alone
    ({"level": LEVEL_B, "reasons": [], "image_origin": True,
      "corroborated": False}, {"provenance": {}}),            # + unnamed image
    ({"level": LEVEL_B, "reasons": [], "image_origin": True,
      "corroborated": False},
     {"provenance": {"image": "kassel_t_12.png"}}),           # + named image
    ({"level": LEVEL_B, "reasons": [], "image_origin": False,
      "corroborated": True}, {}),                             # + second source
    ({"level": LEVEL_B, "reasons": ["repaired"], "image_origin": False,
      "corroborated": False}, {}),                            # + one reason
    ({"level": LEVEL_C, "reasons": [], "image_origin": False,
      "corroborated": False}, {}),                            # + review, alone
    ({"level": LEVEL_C, "reasons": ["exhausted:carrier", "repaired"],
      "image_origin": False, "corroborated": False}, {}),     # two reasons
]


def _profiles():
    """Every profile that serializes a graph, found rather than listed."""
    root = Path(__file__).resolve().parent.parent / "profiles"
    return sorted(p.parent.name for p in root.glob("*/kg.py"))


def test_the_cases_below_produce_every_mark_the_core_has():
    """A mark no case produces is a mark the profile test never asks about,
    so the matrix is held against the vocabulary instead of eyeballed. This is
    the direction a key-set check cannot see: a mark added to MARKS whose
    branch in `marks()` was forgotten."""
    seen = {mark for verdict, row in _VERDICTS
            for mark, _ in marks(verdict, row)}
    assert seen == set(MARKS), sorted(set(MARKS) ^ seen)


def test_every_mark_is_reached_by_a_case_that_isolates_it():
    """Each mark has a case where it is the only thing said beside the level.
    Without that, deleting one branch of `marks()` can hide behind another
    mark that flipped in the same case."""
    alone = set()
    for verdict, row in _VERDICTS:
        pairs = marks(verdict, row)
        if len(pairs) == 2:
            alone.add(pairs[1][0])
    assert alone == set(MARKS) - {"level"}, sorted(alone)


@pytest.mark.parametrize("name", _profiles())
def test_every_profile_words_every_mark_the_core_can_produce(name):
    """The promise of the split: the marks come from the core. That is only a
    promise if a profile cannot quietly stop saying one of them."""
    kg = importlib.import_module("profiles.%s.kg" % name)
    assert set(kg.TRUST_PROSE) == set(MARKS), (
        "profiles/%s/kg.py TRUST_PROSE against trust.MARKS" % name)
    for verdict, row in _VERDICTS:
        for mark, args in marks(verdict, row):
            # Wording a mark as the empty string is not a way to silence it.
            assert kg.TRUST_PROSE[mark].format(**args).strip(), (
                "profiles/%s/kg.py words %r as nothing" % (name, mark))
        line = render(verdict, kg.TRUST_PROSE, join=kg.TRUST_JOIN, row=row)
        assert line.strip()
        assert all(part.strip() for part in line.split(kg.TRUST_JOIN))


def test_a_table_that_words_a_mark_that_is_not_one_is_refused():
    """And the other direction, at import rather than at the first C of a
    corpus run: one missing piece of one comment line in one document out of a
    thousand is not something anybody reads."""
    complete = {mark: "x" for mark in MARKS}
    assert check_prose(dict(complete), "here") == complete
    for broken in (dict(complete, extra="x"),
                   {k: v for k, v in complete.items() if k != "review"}):
        with pytest.raises(LookupError):
            check_prose(broken, "here")


def _sentence_before_sc3(verdict, row=None):
    """`trust.sentence` as it stood before the marks were split out.

    Frozen on purpose, in its order and its joins. The words are English
    since 2026-09-10 (the owner: the graph's language is English), so the
    copy was reworded and nothing else, and the claim is still checked here.
    """
    parts = ["Trust: %s" % verdict["level"]]
    if verdict.get("image_origin"):
        image = ((row or {}).get("provenance") or {}).get("image")
        parts.append("from an image" + (" (%s)" % image if image else ""))
    if verdict.get("corroborated"):
        parts.append("confirmed by a second reading")
    if verdict["reasons"]:
        parts.append(", ".join(verdict["reasons"]))
    if verdict["level"] == LEVEL_C:
        parts.append("review recommended")
    return " · ".join(parts)


def test_the_kwp_line_is_the_one_that_stood_there_before():
    """Every combination, not the seven of the matrix: the order of the marks
    and the two joins are as easy to get wrong as the words, and only one of
    the three shows up in a spot check."""
    from profiles.kwp.kg import TRUST_JOIN, TRUST_PROSE
    checked = 0
    for level in (LEVEL_A, LEVEL_B, LEVEL_C):
        for image_origin in (False, True):
            for corroborated in (False, True):
                for why in ([], ["repaired"], ["exhausted:carrier", "repaired"]):
                    for image in (None, "kassel_t_12.png"):
                        verdict = {"level": level, "reasons": list(why),
                                   "image_origin": image_origin,
                                   "corroborated": corroborated}
                        row = {"provenance":
                               {"image": image} if image else {}}
                        assert render(verdict, TRUST_PROSE, join=TRUST_JOIN,
                                      row=row) == _sentence_before_sc3(
                                          verdict, row), verdict
                        checked += 1
    assert checked == 72


# ---------------------------------------------------------------------------
# One line per document
# ---------------------------------------------------------------------------
def test_the_summary_counts_every_value_once_and_names_why():
    """A corpus of 1.082 plans is not read tuple by tuple. What a reader
    wants -- how much of this plan is usable -- has to be one line."""
    rows = [_row(),                                     # A
            _row(tier=TIER_VISUAL),                     # B
            _row(year_state=fields.EXHAUSTED),          # C, gave up on it
            _row(flags=["computed"])]                   # C, computed
    got = document_summary(857, rows, [{"reason": "x"}, {"reason": "y"}])
    assert got == {"document_id": 857, "tuples": 4, "refusals": 2,
                   "levels": {LEVEL_A: 1, LEVEL_B: 1, LEVEL_C: 2},
                   "reasons": {"computed": 1, "exhausted:year": 1},
                   "image_origin": 1}
    assert sum(got["levels"].values()) == got["tuples"], "every value, once"


def test_the_summary_says_nothing_about_a_conflict_it_cannot_see():
    """A contested identity is the serializer's finding, and a second reading
    is a later pass. Both would have to be guessed here, and a guessed C is
    worse than an honest floor: the graph side recomputes the level with
    them, and a value that is a C already never becomes an A."""
    got = document_summary(857, [_row()], [])
    assert got["levels"] == {LEVEL_A: 1, LEVEL_B: 0, LEVEL_C: 0}
    assert got["reasons"] == {}
    # The same value, once the serializer knows the identity is contested.
    assert trust(_row(), conflict=True)["level"] == LEVEL_C


def test_a_document_with_nothing_in_it_still_has_a_summary():
    """A plan the run found no value in is a finding about the plan. An
    absent line reads as a plan that was never harvested."""
    got = document_summary(1082, [], [])
    assert got["tuples"] == 0 and got["refusals"] == 0
    assert got["levels"] == {LEVEL_A: 0, LEVEL_B: 0, LEVEL_C: 0}


def test_parameter_states_names_every_parameter_of_the_spec():
    """One line per parameter, whatever came of it, keyed on the uri the
    tuples are keyed on. Keyed on the label instead, every count reads zero
    and every parameter reads `unstated` on a run that answered."""
    import json
    from pathlib import Path

    from docpipe.extraction.spec import load as load_spec
    from docpipe.extraction.trust import parameter_states

    root = Path(__file__).resolve().parent.parent
    spec = load_spec(json.loads(
        (root / "profiles" / "kwp" / "extraction_spec.json")
        .read_text(encoding="utf-8")))

    tuples = [{"parameter": "energy_consumption", "value": 1.0},
              {"parameter": "energy_consumption", "value": 2.0}]
    refusals = [{"parameter": "emission", "reason": "no_quote"},
                # A refusal that names a parameter with a tuple does not
                # take it back: the tuple survived verification.
                {"parameter": "energy_consumption", "reason": "no_quote"}]
    got = parameter_states(spec, tuples, refusals)

    assert [g["parameter"] for g in got] == [p.uri for p in spec.parameters]
    assert {g["parameter"]: g["state"] for g in got} == {
        "energy_consumption": fields.READ,
        "emission": fields.UNBACKED,
        "planning_organisation": fields.SAID_UNSTATED,
        "heat_load": fields.SAID_UNSTATED}
    assert [(g["tuples"], g["refusals"]) for g in got] == [
        (2, 1), (0, 1), (0, 0), (0, 0)]


def _kwp_spec():
    import json
    from pathlib import Path

    from docpipe.extraction.spec import load as load_spec
    root = Path(__file__).resolve().parent.parent
    return load_spec(json.loads(
        (root / "profiles" / "kwp" / "extraction_spec.json")
        .read_text(encoding="utf-8")))


def test_a_parameter_whose_own_passages_were_read_is_unstated_not_exhausted():
    """Kassel's planning_organisation was marked exhausted because a
    table request elsewhere in the plan was cut off, while its one
    candidate passage had been read in full. Exhausted is a statement about
    the run, so it needs the run to have missed one of the parameter's own
    passages."""
    from docpipe.extraction.trust import parameter_states
    spec = _kwp_spec()
    cut = [{"parameter": None, "reason": "claim names no parameter of the spec",
            "claim": {"_harvest_failed": True, "_cut_off": True},
            "owner": ["table", 87517]}]
    sources_of = {"planning_organisation": {("section", 349407)},
                  "heat_load": {("table", 87517), ("section", 1)}}
    got = {g["parameter"]: g["state"] for g in parameter_states(
        spec, [], cut, harvested=10, answered=5, sources_of=sources_of)}
    assert got["planning_organisation"] == fields.SAID_UNSTATED
    assert got["heat_load"] == fields.EXHAUSTED
    # No sources known for a parameter: a cut anywhere still counts.
    assert got["energy_consumption"] == fields.EXHAUSTED

    # Nothing answered at all: every empty parameter is exhausted.
    got = {g["parameter"]: g["state"] for g in parameter_states(
        spec, [], [], harvested=10, answered=0, sources_of=sources_of)}
    assert got["planning_organisation"] == fields.EXHAUSTED

    # A failed request that names no source cannot be placed.
    anonymous = [{"parameter": None, "reason": "unreachable",
                  "claim": {"_harvest_failed": True, "_why": "unreachable"}}]
    got = {g["parameter"]: g["state"] for g in parameter_states(
        spec, [], anonymous, harvested=10, answered=5,
        sources_of=sources_of)}
    assert got["planning_organisation"] == fields.EXHAUSTED


def test_the_plan_keeps_which_passages_each_parameters_own_anchors_rank():
    """Planned from nothing: the fused ranking still decides what is
    read. It is what tells a cut-off before a parameter's passages from a
    reading of them that found nothing."""
    from docpipe.extraction.pipeline import Source, plan_document
    spec = _kwp_spec()
    office = Source("section", 1, "Erstellt durch ...", {})
    table = Source("table", 2, "| Erdgas | 512 |", {})

    def retrieve(probes, document_id, exclude):
        return ([office] if "office" in probes else []) + (
            [table] if "gwh" in probes else [])

    _items, report = plan_document(
        7, spec, [], retrieve=retrieve, top=50,
        extra_probes={"planning_organisation": ["office"],
                      "energy_consumption": ["gwh"]})
    assert report.sources_of == {
        "planning_organisation": {("section", 1)},
        "energy_consumption": {("table", 2)}}
