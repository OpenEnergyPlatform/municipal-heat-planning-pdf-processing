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
from docpipe.extraction.trust import LEVEL_A, LEVEL_B, LEVEL_C, sentence, trust
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
