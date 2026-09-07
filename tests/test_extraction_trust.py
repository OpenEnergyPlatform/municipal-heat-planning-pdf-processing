"""How much of a value the run can stand behind, as a level a reader can act on.

Every accepted tuple is verified, and that is a floor rather than a grade: a
value with every coordinate read off its own table and a value whose year was
read off the caption of a different table three pages away both clear it, and
until now the graph showed a reader two numbers.

What these tests hold is that the cut is where the measurement puts it. Image
origin alone separates nothing on this corpus (527 of Kassel's 559 tuples came
out of a table or figure), so it is not a warning; a passage that belongs to
another row is the failure the whole repair is about, so it is.

No model, no GPU.
"""
import pytest

from docpipe.extraction import fields
from docpipe.extraction.trust import (LEVEL_A, LEVEL_B, LEVEL_C,
                                      document_summary, sentence, trust)
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


def test_a_passage_that_belongs_to_another_row_is_a_c():
    """The measured failure: 370 of Kassel's 455 year readings cited a
    passage outside the row's own table and its section, 146 of them the
    annotated placeholder of a DIFFERENT table."""
    verdict = trust(_row(year_source=["table", 87517]))
    assert verdict["level"] == LEVEL_C
    assert verdict["reasons"] == ["nonlocal:year"]

    # The section the table stands in is not "another row": that is where a
    # caption and the sentence announcing a table live.
    assert trust(_row(year_source=["section", 349525]))["level"] == LEVEL_A


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


def test_the_sentence_says_what_to_do_about_it():
    line = sentence(trust(_row(tier=TIER_VISUAL,
                               year_source=["table", 87517])),
                    _row(tier=TIER_VISUAL))
    assert line.startswith("Vertrauen: C")
    assert "nonlocal:year" in line
    assert "Prüfung empfohlen" in line
    # An A says its level and nothing else: there is nothing to act on.
    assert sentence(trust(_row())) == "Vertrauen: A"


# ---------------------------------------------------------------------------
# One line per document
# ---------------------------------------------------------------------------
def test_the_summary_counts_every_value_once_and_names_why():
    """A corpus of 1.082 plans is not read tuple by tuple. What a reader
    wants -- how much of this plan is usable -- has to be one line."""
    rows = [_row(),                                     # A
            _row(tier=TIER_VISUAL),                     # B
            _row(year_source=["table", 87517]),         # C, foreign year
            _row(flags=["computed"])]                   # C, computed
    got = document_summary(857, rows, [{"reason": "x"}, {"reason": "y"}])
    assert got == {"document_id": 857, "tuples": 4, "refusals": 2,
                   "levels": {LEVEL_A: 1, LEVEL_B: 1, LEVEL_C: 2},
                   "reasons": {"computed": 1, "nonlocal:year": 1},
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


# ---------------------------------------------------------------------------
# Which axes may be held to the row's own source
# ---------------------------------------------------------------------------
OWN = frozenset({("energy_consumption", "carrier"),
                 ("energy_consumption", "sector")})


def test_an_axis_the_spec_lets_read_a_page_away_is_not_a_doubt():
    """The rule is per axis. A row label is read off its own table, a
    scenario is often named a page earlier, a class is argued in a methods
    chapter. The harvest enforces each one and writes `unbacked` when it is
    broken, so a foreign passage on a `local` or `any` axis is the rule
    working -- reporting it here would fire on the whole corpus and separate
    nothing, which is why image origin is not a reason either."""
    foreign = _row(year_source=["table", 87517])
    assert trust(foreign)["level"] == LEVEL_C, "no rule known: judge it"
    assert trust(foreign, own=OWN) == {"level": LEVEL_A, "reasons": [],
                                       "image_origin": False,
                                       "corroborated": False}


def test_the_axis_the_spec_does_hold_to_its_own_source_still_counts():
    """Otherwise the fix would silence the finding instead of aiming it: the
    carrier is the one coordinate the row itself really carries."""
    verdict = trust(_row(carrier_source=["table", 87517]), own=OWN)
    assert verdict["level"] == LEVEL_C
    assert verdict["reasons"] == ["nonlocal:carrier"]


def test_the_rule_is_read_per_parameter_not_per_axis_name():
    """Two parameters may name an axis the same way and hold it differently,
    so the pair decides. A set keyed by the bare name would carry one
    parameter's rule onto the other's coordinate."""
    row = _row(parameter="emission", carrier_source=["table", 87517])
    assert trust(row, own=OWN)["reasons"] == [], "OWN names only the other one"
    both = OWN | {("emission", "carrier")}
    assert trust(row, own=both)["reasons"] == ["nonlocal:carrier"]


def test_the_summary_hands_the_rule_down():
    """It is the line a reader of 1.082 plans actually reads; computed
    against the wrong rule it reports a clean run as a broken one."""
    rows = [_row(year_source=["table", 87517]) for _ in range(3)]
    assert document_summary(857, rows, [])["levels"][LEVEL_C] == 3
    with_rule = document_summary(857, rows, [], own=OWN)
    assert with_rule["levels"] == {LEVEL_A: 3, LEVEL_B: 0, LEVEL_C: 0}
    assert with_rule["reasons"] == {}


def test_own_evidence_reads_the_rule_off_the_spec():
    """The set has one source, and it is the spec the run was made with."""
    import json
    from pathlib import Path

    from docpipe.extraction.spec import load as load_spec, own_evidence

    root = Path(__file__).resolve().parent.parent
    spec = load_spec(json.loads(
        (root / "profiles" / "kwp" / "extraction_spec.json")
        .read_text(encoding="utf-8")))
    got = own_evidence(spec)
    assert ("energy_consumption", "carrier") in got
    assert ("energy_consumption", "sector") in got
    # Measured against the spec as it reads: year and scenario are "local",
    # aggregation and spatial_scope have no rule at all.
    for name in ("year", "scenario", "quantity", "aggregation",
                 "spatial_scope"):
        assert ("energy_consumption", name) not in got, name
    assert {axis for _uri, axis in got} == {"carrier", "sector"}
