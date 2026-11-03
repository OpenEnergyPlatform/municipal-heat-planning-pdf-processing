"""A closed list's answer is one of its entries, the value of a category
parameter too: a row whose value its parameter's list does not hold has that
parameter read AND its value asked again, in its own passage only, as one of
that list's entries, AND a value read so stands on that reading, its entry,
the wording it gave and its quote, AND a row that reads no entry keeps the
wording it was read with and is refused for its value without its axes ever
being asked; a value off its list is refused, never kept, AND a grown list
reopens its answer space, AND the window a run is served holds the widest
list a field request offers. A value left out with its wording beside it fits
any list."""
import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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


def test_the_value_is_asked_in_its_own_passage_alone():
    sweeper = runner.make_sweeper(lambda *a, **k: None,
                                  search_share={"value": 1.0})
    budget = sweeper.budget_of([fields.value_choice(TYPE)], TYPE.uri)
    assert budget["retrieval"] == budget["rest"] == 0
    assert budget["own"] == runner.FIELD_ATTEMPTS


def turned(reads):
    """A turn over three rows of one parameter, and what it asked: R1's value
    is on the list, R2 and R3 print wordings it does not hold, and R2 cites
    the half of the sentence that is not the wording its entry is read from.
    *reads* is what the value question reads per row, written as
    `merge_field` writes it: (entry, wording or None, quote)."""
    asked = []

    def sweeper(batch, rows, slots, anchor=""):
        names = [slot.name for slot in slots]
        asked.append((names, [row.label for row in rows], slots))
        if names == ["value"]:
            for row in rows:
                got = reads.get(row.label)
                if got is None:
                    row.claim["value_state"] = fields.UNBACKED
                    continue
                entry, wording, quote = got
                row.claim.update({"value_state": fields.READ, "value": entry,
                                  "value_quote": quote,
                                  "value_source": ["section", 2]})
                if wording:
                    row.claim["value_raw"] = wording
        return {}

    rows = [Row(label=label, item_index=0, claim={
        "value": value, "quote": quote, "parameter": TYPE.label,
        "parameter_state": fields.READ})
        for label, value, quote in (
            ("R1", "policy scenario", POLICY),
            ("R2", "WEM case", "the WEM case keeps today's policies"),
            ("R3", "a wording no list holds", POLICY))]
    batch = SimpleNamespace(document_id=7, parameter=None, sources=[],
                            frame=None, bases=())
    turn = runner.Turn(batch, rows, doc_spec=SPEC, sweeper=sweeper)
    turn.enter(rows)
    turn.run_jobs(parallel=False)
    return turn, {row.label: row.claim for row in rows}, asked


READ_AGAIN = {"R2": ("with existing measures scenario",
                     "With existing measures", POLICY)}


def test_only_a_value_off_its_list_is_asked_again_and_before_any_axis():
    _turn, claims, asked = turned(READ_AGAIN)
    names = [entry[0] for entry in asked]
    assert names[0] == ["value"] and asked[0][1] == ["R2", "R3"]
    offered = {opt.label for opt in asked[0][2][0].options}
    assert "with existing measures scenario" in offered
    assert "value_state" not in claims["R1"]


def test_a_value_read_again_stands_on_the_quote_that_read_it():
    _turn, claims, _asked = turned(READ_AGAIN)
    assert claims["R2"]["quote"] == POLICY
    assert claims["R2"]["value_raw"] == "With existing measures"
    tuple_ = verify_tuple(claims["R2"], TYPE, POLICY, owner_kind="section")
    assert isinstance(tuple_, Verified) and tuple_.tuple["value_uri"]


def test_a_value_read_again_without_a_wording_carries_none():
    _turn, claims, _asked = turned(
        {"R2": ("with existing measures scenario", None, POLICY)})
    assert "value_raw" not in claims["R2"]


def test_a_value_with_an_entry_goes_on_and_one_without_is_refused_unasked():
    _turn, claims, asked = turned(READ_AGAIN)
    axis_rows = {label for names, labels, _ in asked if names != ["value"]
                 for label in labels}
    assert axis_rows == {"R1", "R2"}
    assert claims["R3"]["scenario_state"] == fields.OUT_OF_SLICE
    assert claims["R3"]["value_raw"] == "a wording no list holds"
    refused = verify_tuple(claims["R3"], TYPE, POLICY, owner_kind="section")
    assert isinstance(refused, Refusal)
    assert any(re.match(p, refused.reason) for p in schema.REFUSAL_REASONS)


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
    assert runner.request_budget(spec, False) > offered / 4


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
