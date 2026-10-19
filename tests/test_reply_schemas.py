"""The reply schemas: what the field grammar lets a model say, and that a
reply generated inside the strict form a hosted API takes comes home in the
shape the stage asked for."""
import json
from pathlib import Path

import jsonschema
import pytest

from docpipe import providers
from docpipe.extraction import fields, replies, runner
from docpipe.extraction.spec import load as load_spec
from docpipe.providers import schema as strict_schema

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
PARAMETER = SPEC.by_uri["energy_consumption"]
SLOTS = {slot.name: slot for slot in fields.axis_slots(PARAMETER)}
CARRIER, YEAR = SLOTS["carrier"], SLOTS["year"]


def field_schema(slot):
    return runner.field_response_format(slot)["json_schema"]["schema"]


def field_reply(slot, value):
    return {"fields": {slot.name: {"answers": {"R1": {
        "value": value, "quote": "eine Passage"}}}}}


def test_a_choice_answer_is_one_of_its_options_or_unstated():
    schema = field_schema(CARRIER)
    option = CARRIER.options[0].label
    jsonschema.validate(field_reply(CARRIER, option), schema)
    jsonschema.validate(field_reply(CARRIER, fields.UNSTATED), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(field_reply(CARRIER, "Fernwärme frei erfunden"),
                            schema)


def test_a_number_answer_is_an_integer_or_unstated():
    schema = field_schema(YEAR)
    jsonschema.validate(field_reply(YEAR, 2045), schema)
    jsonschema.validate(field_reply(YEAR, fields.UNSTATED), schema)
    for wrong in ("2045", 2045.5, "2030-2045"):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(field_reply(YEAR, wrong), schema)


def test_a_field_reply_holds_only_its_own_field_and_no_text_beside_it():
    schema = field_schema(YEAR)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"fields": {"carrier": {}}}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**field_reply(YEAR, 2045), "note": "x"}, schema)


def every_reply_schema():
    frame = fields.frame_slots(SPEC, ("scenario", "year"))
    return {"rows": replies.rows(), "frame": replies.frame(frame),
            "review": replies.review(fields.slots(PARAMETER)),
            "anchors": replies.anchors(), "phrase": replies.phrase(),
            "field": field_schema(CARRIER)}


def objects(node):
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        yield node
    for inner in (node.get("properties") or {}).values():
        yield from objects(inner)
    for word in ("items", "additionalProperties"):
        yield from objects(node.get(word))
    for inner in node.get("anyOf") or ():
        yield from objects(inner)


@pytest.mark.parametrize("name", sorted(every_reply_schema()))
def test_every_reply_schema_has_a_strict_form(name):
    """Every key required, nothing beside them: what an all-required API
    compiles. A schema it could not generate in raises instead."""
    rewritten, _decode = strict_schema.strict(every_reply_schema()[name])
    for node in objects(rewritten):
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


def test_a_left_out_key_comes_home_left_out():
    rewritten, decode = strict_schema.strict(replies.rows())
    generated = {"tuples": [{"source": "Q1", "unit_raw": None, "value": 12,
                             "value_raw": None, "quote": "| Gas | 12 |",
                             "computed": None}],
                 "defaults": None, "status": "complete", "need_more": None,
                 "action": None, "code": None}
    jsonschema.validate(generated, rewritten)
    # A null the stage's own schema allows is an answer and stays; one it
    # does not allow says the key was left out.
    assert decode(generated) == {
        "tuples": [{"source": "Q1", "unit_raw": None, "value": 12,
                    "value_raw": None, "quote": "| Gas | 12 |"}],
        "status": "complete"}


def test_an_object_keyed_per_row_comes_home_as_that_object():
    rewritten, decode = strict_schema.strict(field_schema(YEAR))
    answer = {"value": 2045, "value_raw": None, "quote": "Zieljahr 2045"}
    generated = {"fields": {"year": {
        "groups": None,
        "answers": [{"key": "R1", "value": answer},
                    {"key": "R2", "value": answer}]}},
        "need_more": None}
    jsonschema.validate(generated, rewritten)
    got = decode(generated)
    assert set(got["fields"]["year"]["answers"]) == {"R1", "R2"}
    assert got["fields"]["year"]["answers"]["R1"] == {
        "value": 2045, "quote": "Zieljahr 2045"}


def test_a_keyed_list_with_a_key_twice_is_not_turned_into_an_object():
    """Choosing one of two entries for R1 would be a repair."""
    _rewritten, decode = strict_schema.strict(field_schema(YEAR))
    twice = [{"key": "R1", "value": {"value": 2030}},
             {"key": "R1", "value": {"value": 2045}}]
    got = decode({"fields": {"year": {"answers": twice}}})
    assert got["fields"]["year"]["answers"] == twice


def test_a_schema_no_api_can_generate_in_is_refused():
    for impossible in ({"type": "object"},
                       {"type": "array"},
                       {"type": "object", "properties": {"a": {"type": "string"}},
                        "additionalProperties": {"type": "string"}}):
        with pytest.raises(strict_schema.SchemaError):
            strict_schema.strict(impossible)


def test_a_schema_over_the_apis_budget_is_refused():
    with pytest.raises(strict_schema.SchemaError):
        strict_schema.strict(replies.rows(), strict_schema.OPTIONAL,
                             budget=(1, 0))


def test_the_schema_goes_out_where_the_installation_says(monkeypatch):
    schema = replies.phrase()
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_SCHEMA", "auto")
    assert providers.formatted("llm", "phrase", schema) == {}
    monkeypatch.setenv("LLM_SCHEMA", "all")
    sent = providers.formatted("llm", "phrase", schema)
    assert sent["response_format"]["json_schema"]["schema"] is schema
    monkeypatch.setenv("LLM_SCHEMA", "auto")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert "response_format" in providers.formatted("llm", "phrase", schema)
    monkeypatch.setenv("LLM_PROVIDER", "nobody")
    with pytest.raises(ValueError):
        providers.provider("llm")


def test_request_options_are_one_json_object(monkeypatch):
    monkeypatch.setenv("LLM_REQUEST_OPTIONS", '{"top_k": 20}')
    assert providers.request_options("llm") == {"top_k": 20}
    monkeypatch.setenv("LLM_REQUEST_OPTIONS", "[1]")
    with pytest.raises(ValueError):
        providers.request_options("llm")
    monkeypatch.setenv("LLM_REQUEST_OPTIONS", "{nope")
    with pytest.raises(ValueError):
        providers.request_options("llm")
