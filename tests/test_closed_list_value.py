"""A closed list's answer is one of its entries, the value of a category
parameter too: a value off its list is refused, never kept, AND a grown list
reopens its answer space, AND the window a run is served holds the widest
list a request offers. A value left out with its wording beside it fits any
list."""
import json
import re
from dataclasses import replace
from pathlib import Path

from docpipe.extraction import fields, remap, runner, schema
from docpipe.extraction.pipeline import Row, Source, merge_field
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import Refusal, Verified, verify_tuple

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "scenarios"
     / "extraction_spec.json").read_text(encoding="utf-8")))
SECTOR = SPEC.by_uri["study_sector"]
TECHNOLOGY = SPEC.by_uri["study_technology"]
TYPE = SPEC.by_uri["scenario_type"]
SLOT = fields.parameter_slot(SPEC)
TEXT = "For Transport, RED4 is at 20%, RED3 at roughly 8%."
SHOWN = [Source("figure", 1, TEXT, {"document_id": 7})]
POLICY = "With existing measures: the WEM case keeps today's policies."


def asked(value, parameter, wording="Transport"):
    row = Row(label="R1", item_index=0, claim={"value": value})
    got = merge_field([row], SHOWN, SLOT, {"answers": {"R1": {
        "value": parameter.label, "value_raw": wording, "quote": TEXT}}})
    return row.claim, got["failed"]


def test_the_parameter_is_read_whether_or_not_its_list_holds_the_value():
    for value, parameter in (("transport sector", SECTOR),
                             ("transport sector", TECHNOLOGY),
                             (None, TECHNOLOGY)):
        claim, failed = asked(value, parameter)
        assert claim["parameter_state"] == fields.READ and not failed


def chosen(answer, value="WEM case"):
    row = Row(label="R1", item_index=0, claim={"value": value,
                                               "value_raw": value})
    got = merge_field([row], [Source("section", 2, POLICY, {})],
                      fields.value_choice(TYPE), {"answers": {"R1": answer}})
    return row.claim, got["failed"]


def test_the_value_asked_again_reads_an_entry_and_keeps_the_wording():
    claim, failed = chosen({"value": "with existing measures scenario",
                            "value_raw": "WEM case", "quote": POLICY})
    assert not failed and claim["value_state"] == fields.READ
    assert claim["value"] == "with existing measures scenario"
    assert claim["value_raw"] == "WEM case"
    tuple_ = verify_tuple({**claim, "quote": POLICY}, TYPE, POLICY,
                          owner_kind="section")
    assert isinstance(tuple_, Verified) and tuple_.tuple["value_uri"]


def test_a_wording_given_again_as_the_value_is_not_read():
    claim, failed = chosen({"value": "WEM case", "quote": POLICY})
    assert claim["value_state"] == fields.UNBACKED
    assert [f["why"] for f in failed] == ["not_an_option"]
    assert claim["value"] == "WEM case"


def test_the_window_holds_the_widest_list_a_field_request_offers():
    # Per construction: definitions that alone outgrow the window a run is
    # served when only the entries' names are counted.
    long = replace(SECTOR, definitions={
        uri: "a sector the plan names " * 80 for uri in SECTOR.vocabulary})
    spec = replace(SPEC, parameters=[long if p is SECTOR else p
                                     for p in SPEC.parameters])
    offered = len(json.dumps(fields.value_choice(long).answerable(),
                             ensure_ascii=False))
    # Four characters to a token is generous to the window.
    assert runner.request_budget(spec) > offered / 4


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
