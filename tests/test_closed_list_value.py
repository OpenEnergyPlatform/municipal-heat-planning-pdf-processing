"""A closed list's answer is one of its entries, the value of a category
parameter too: a row takes a parameter only if that parameter's list holds its
value, otherwise the parameter is never read AND is asked again with the value
named; a value off its list is refused, never kept, AND a grown list reopens
its answer space. A value left out with its wording beside it fits any list."""
import json
import re
from pathlib import Path

from docpipe.extraction import fields, remap, schema
from docpipe.extraction.pipeline import Row, Source, merge_field
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import Refusal, Verified, verify_tuple

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "scenarios"
     / "extraction_spec.json").read_text(encoding="utf-8")))
SECTOR = SPEC.by_uri["study_sector"]
TECHNOLOGY = SPEC.by_uri["study_technology"]
PROJECT = SPEC.by_uri["study_project_name"]
SLOT = fields.parameter_slot(SPEC)
TEXT = "For Transport, RED4 is at 20%, RED3 at roughly 8%."
SHOWN = [Source("figure", 1, TEXT, {"document_id": 7})]


def asked(value, parameter, wording="Transport"):
    row = Row(label="R1", item_index=0, claim={"value": value})
    got = merge_field([row], SHOWN, SLOT, {"answers": {"R1": {
        "value": parameter.label, "value_raw": wording, "quote": TEXT}}})
    return row.claim, got["failed"]


def test_a_parameter_whose_list_holds_the_value_is_read():
    claim, failed = asked("transport sector", SECTOR)
    assert claim["parameter_state"] == fields.READ and not failed


def test_a_parameter_whose_list_lacks_the_value_is_asked_again_and_never_read():
    claim, failed = asked("transport sector", TECHNOLOGY)
    assert claim["parameter_state"] == fields.UNBACKED
    assert "parameter" not in claim or claim["parameter"] != TECHNOLOGY.label
    assert [f["why"] for f in failed] == ["not_an_option"]
    assert "transport sector" in failed[0]["reason"]
    assert failed[0]["why"] in schema.DROP_REASONS


def test_a_text_parameter_and_a_no_class_answer_fit_any_list():
    assert asked("transport sector", PROJECT)[0]["parameter_state"] == \
        fields.READ
    assert asked(None, TECHNOLOGY)[0]["parameter_state"] == fields.READ


def claim(value):
    return {"value": value, "value_raw": "Transport", "quote": TEXT}


def test_a_value_off_its_list_is_refused_and_one_on_it_is_kept():
    off = verify_tuple(claim("2050"), SECTOR, TEXT, owner_kind="figure")
    assert isinstance(off, Refusal)
    assert any(re.match(p, off.reason) for p in schema.REFUSAL_REASONS)
    on = verify_tuple(claim("transport sector"), SECTOR, TEXT,
                      owner_kind="figure")
    assert isinstance(on, Verified) and on.tuple["value_uri"]


def test_a_value_refusal_reopens_its_own_answer_space_only():
    spaces = {"value/study_sector", "value/study_technology"}
    refused = [{"parameter": "study_sector",
                "reason": "value '2050' not in vocabulary"}]
    assert remap.refused_spaces(refused, spaces) == {"value/study_sector"}
