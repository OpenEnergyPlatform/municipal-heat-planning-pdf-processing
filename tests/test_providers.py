"""The provider layer: one client shape for every API.

What is promised, sentence by sentence:

  * a server of one's own is asked exactly as before: `openai.OpenAI` with
    the stage's own arguments, and a reply format only where there was one;
  * a hosted model is asked for JSON inside a schema AND never without one;
  * a reply schema is rewritten into what the APIs generate in AND the reply
    is read back in the shape the stage asked for AND a reply that is not
    JSON is handed on untouched;
  * a refused request raises with its HTTP status AND closes the endpoint's
    gate for every other request AND is not retried by the layer;
  * every request a stage sends names its reply, or asks for plain text;
  * the clients of one endpoint pass ONE gate AND a refusal that names its
    wait holds the next request for that long, before it is sent;
  * the limit of a hosted run starts at the minimum AND steps down once the
    API says to wait AND does not grow while the gate is closed;
  * each role (text, vision) has its own provider AND its own reply format
    AND is preflighted as itself.
"""
import ast
import contextlib
import io
import json
import sys
import threading
import time
import types
import urllib.error
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import pytest

from docpipe import llm_preflight, providers
from docpipe.extraction import fields, replies as extraction_replies, runner
from docpipe.extraction import throttle
from docpipe.inference import replies as chat_replies
from docpipe.providers import base, gemini_api, governor, openai_api, schema
from docpipe.refinement import replies as refinement_replies
from docpipe.visuals import replies as visual_replies

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _own_server(monkeypatch):
    for name in ("LLM_PROVIDER", "VLM_PROVIDER", "EMBEDDING_PROVIDER",
                 "LLM_SCHEMA", "LLM_REQUEST_OPTIONS", "VLM_REQUEST_OPTIONS",
                 "LLM_THINKING_ROOM", "LLM_BASE_URL", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(base, "_NO_TEMPERATURE", set())
    monkeypatch.setattr(governor, "_GATES", {})


# -- the schema dialect -------------------------------------------------------

NATURAL = {
    "type": "object",
    "properties": {
        "fields": {"type": "object", "properties": {"year": {
            "type": "object",
            "properties": {
                "answers": {"type": "object", "additionalProperties": {
                    "type": "object",
                    "properties": {"value": {"anyOf": [
                        {"type": "integer"}, {"enum": ["out:unstated"]}]},
                        "quote": {"type": "string", "minLength": 8}},
                    "additionalProperties": False}}},
            "additionalProperties": False}},
            "required": ["year"], "additionalProperties": False},
        "need_more": {"type": "array", "items": {"type": "string"}},
        "note": {"type": ["string", "null"]}},
    "required": ["fields"], "additionalProperties": False}


def _nodes(node, found=None):
    """Every schema of a schema: itself, its properties, items, alternatives.
    A property is reached through `properties`, so one that is called
    "title" or "format" is a property and not a keyword."""
    found = [] if found is None else found
    found.append(node)
    for inner in (node.get("properties") or {}).values():
        _nodes(inner, found)
    for word in ("items", "additionalProperties"):
        if isinstance(node.get(word), dict):
            _nodes(node[word], found)
    for word in ("anyOf", "oneOf", "allOf"):
        for inner in node.get(word) or ():
            _nodes(inner, found)
    return found


def _in_subset(strict_schema, optional=False) -> list:
    """What still stands in a rewritten schema that an API would refuse.
    With *optional*, for the dialect that takes keys that may be left out."""
    wrong = []
    for node in _nodes(strict_schema):
        if node.get("type") == "object" or "properties" in node:
            if node.get("additionalProperties") is not False:
                wrong.append(("open object", node))
            required = set(node.get("required") or ())
            named = set(node.get("properties") or ())
            if not required <= named or (required != named and not optional):
                wrong.append(("optional key", node))
        wrong.extend(("keyword", word) for word in schema.DROPPED
                     if word in node)
        if "oneOf" in node or isinstance(node.get("type"), list):
            wrong.append(("alternatives", node))
        if node.get("type") == "array" and "items" not in node:
            wrong.append(("list of anything", node))
    return wrong


def test_a_schema_is_rewritten_into_closed_objects_with_every_key_required():
    strict, _ = schema.strict(NATURAL)
    assert _in_subset(strict) == []
    year = strict["properties"]["fields"]["properties"]["year"]
    answers = year["properties"]["answers"]["anyOf"][0]
    # a keyed object is a list of entries, a bare enum has a type
    assert answers["type"] == "array"
    entry = answers["items"]
    assert entry["required"] == ["key", "value"]
    value = entry["properties"]["value"]["properties"]["value"]
    assert {"type": "string", "enum": ["out:unstated"]} in value["anyOf"]
    assert {"type": "null"} in value["anyOf"]          # it was optional


def test_the_reply_is_read_back_in_the_shape_that_was_asked_for():
    _, decode = schema.strict(NATURAL)
    hosted = {"fields": {"year": {"answers": [
        {"key": "R1", "value": {"value": 2030, "quote": "bis 2030 erreicht"}},
        {"key": "R2", "value": {"value": "out:unstated", "quote": None}}]}},
        "need_more": None, "note": None}
    assert decode(hosted) == {"fields": {"year": {"answers": {
        "R1": {"value": 2030, "quote": "bis 2030 erreicht"},
        "R2": {"value": "out:unstated"}}}},
        # null under a key that may be left out reads as left out; null under
        # a key whose own type has null is the answer null
        "note": None}


def test_the_dialect_with_optional_keys_leaves_them_and_drops_their_null():
    natural = {"type": "object", "properties": {
        "markdown": {"type": "string"},
        "caption": {"type": ["string", "null"]},
        "rows": {"type": "object", "additionalProperties": {
            "type": ["integer", "null"]}}},
        "required": ["markdown"]}
    made, decode = schema.strict(natural, schema.OPTIONAL)
    assert _in_subset(made, optional=True) == []
    assert made["required"] == ["markdown"]
    # leaving the key out says what null said
    assert made["properties"]["caption"] == {"type": "string"}
    # inside a list entry the value is asked for, so its null stays
    entry = made["properties"]["rows"]["items"]["properties"]["value"]
    assert {"type": "null"} in entry["anyOf"]
    assert schema.complexity(made) == (2, 1)
    assert decode({"markdown": "m", "rows": [{"key": "R", "value": None}]}) \
        == {"markdown": "m", "rows": {"R": None}}


def test_what_is_over_the_count_of_optional_keys_is_asked_for_always():
    natural = {"type": "object", "properties": {
        name: {"type": "string"} for name in "abcde"}}
    made, decode = schema.strict(natural, schema.OPTIONAL, budget=(3, 16))
    assert schema.complexity(made) == (3, 2)
    assert len(made["required"]) == 2
    # a null under such a key still reads as left out
    said = {name: None for name in made["required"]}
    assert decode({**said, "e": "x"}) == {"e": "x"} or decode(
        {**said, "e": "x"}) == {k: v for k, v in {**said, "e": "x"}.items()
                                if v is not None}
    with pytest.raises(schema.SchemaError, match="5 optional|alternatives"):
        schema.strict(natural, schema.OPTIONAL, budget=(1, 2))


def test_a_nullable_object_keeps_its_null_and_an_ambiguous_choice_is_refused():
    made, decode = schema.strict({"type": "object", "properties": {"x": {
        "type": ["object", "null"],
        "properties": {"a": {"type": "string"}}, "required": ["a"]}},
        "required": ["x"]})
    assert {"type": "null"} in made["properties"]["x"]["anyOf"]
    assert decode({"x": None}) == {"x": None}
    assert decode({"x": {"a": "b"}}) == {"x": {"a": "b"}}
    with pytest.raises(schema.SchemaError, match="cannot be told apart"):
        schema.strict({"type": "object", "properties": {"x": {"anyOf": [
            {"type": "object", "additionalProperties": {"type": "string"}},
            {"type": "array", "items": {"type": "string"}}]}},
            "required": ["x"]})


def test_a_reply_that_is_not_json_is_handed_on_untouched():
    _, decode = schema.strict(NATURAL)
    cut = '{"fields": {"year": {"answers": [{"key": "R1", "value": {"val'
    assert schema.decoder_text(decode, cut) == cut
    assert schema.decoder_text(decode, "") == ""


@pytest.mark.parametrize("free", [
    {"type": "object"},
    {"type": "array"},
    {"type": "object", "properties": {"a": {"type": "string"}},
     "additionalProperties": {"type": "string"}},
])
def test_a_shape_nobody_can_generate_in_is_refused_and_says_where(free):
    with pytest.raises(schema.SchemaError):
        schema.strict({"type": "object", "properties": {"inner": free},
                       "required": ["inner"]})
    with pytest.raises(providers.ProviderError) as refused:
        base.enforced({"type": "json_schema", "json_schema": {
            "name": "x", "schema": {"type": "object", "properties": {
                "inner": free}}}})
    assert refused.value.status_code == 400


def _encode(value, node):
    """A reply in the stage's shape, as an API would have generated it."""
    options = schema._branches(node) if isinstance(node, dict) else None
    if options is not None:
        for option in options:
            if _natural_fits(value, option):
                return _encode(value, option)
        return value
    if not isinstance(node, dict):
        return value
    if schema._keyed(node):
        return [{"key": key, "value": _encode(item,
                                              node["additionalProperties"])}
                for key, item in value.items()]
    if schema._is_object(node) and isinstance(value, dict):
        return {name: (_encode(value[name], inner) if name in value else None)
                for name, inner in node["properties"].items()}
    if node.get("type") == "array" and isinstance(value, list):
        return [_encode(item, node["items"]) for item in value]
    return value


def _encode_keyed(value, node):
    """A reply with its keyed objects as lists and nothing else changed."""
    options = schema._branches(node) if isinstance(node, dict) else None
    if options is not None:
        for option in options:
            if _natural_fits(value, option):
                return _encode_keyed(value, option)
        return value
    if not isinstance(node, dict):
        return value
    if schema._keyed(node) and isinstance(value, dict):
        return [{"key": key, "value": _encode_keyed(
            item, node["additionalProperties"])}
            for key, item in value.items()]
    if schema._is_object(node) and isinstance(value, dict):
        return {name: _encode_keyed(item, node["properties"].get(name))
                for name, item in value.items()}
    if node.get("type") == "array" and isinstance(value, list):
        return [_encode_keyed(item, node["items"]) for item in value]
    return value


def _lean(value, node):
    """The reply with a null under every key the schema asks for always."""
    options = node.get("anyOf") if isinstance(node, dict) else None
    if options:
        for option in options:
            if schema._fits(value, option):
                return _lean(value, option)
        return value
    if isinstance(node, dict) and "properties" in node \
            and isinstance(value, dict):
        out = {name: _lean(item, node["properties"].get(name) or {})
               for name, item in value.items()}
        for name in node.get("required") or ():
            out.setdefault(name, None)
        return out
    if isinstance(node, dict) and node.get("type") == "array" \
            and isinstance(value, list):
        return [_lean(item, node["items"]) for item in value]
    return value


def _natural_fits(value, node):
    if schema._keyed(node) or schema._is_object(node):
        return isinstance(value, dict)
    return schema._fits(value, node)


def _said(value):
    """A reply without the keys that say null."""
    if isinstance(value, dict):
        return {key: _said(item) for key, item in value.items()
                if item is not None}
    if isinstance(value, list):
        return [_said(item) for item in value]
    return value


def _year():
    return fields.Slot(name="year", kind=fields.NUMBER, question="?")


def _scenario():
    return fields.Slot(name="scenario", kind=fields.CHOICE, question="?",
                       options=(fields.Option(label="Bestand", uri="s"),
                                fields.Option(label="Ziel", uri="t")))


def _every_shape():
    """(name, schema, a reply in that shape) for every request kind."""
    year, scenario = _year(), _scenario()
    value = fields.Slot(name=fields.VALUE, kind=fields.NUMBER)
    window = [{"title": "1 Einleitung", "content": "Text", "page_number": 3,
               "level": 1, "tables": [{"id": "p3_t1", "path": "a.png",
                                       "caption": None, "bbox": [1, 2.5, 3, 4],
                                       "page_number": 3}],
               "figures": []}]
    out = [
        ("phrase", extraction_replies.phrase(), {"phrase": "Der Bedarf"}),
        ("anchors", extraction_replies.anchors(), {"anchors": ["a", "b"]}),
        ("frame", extraction_replies.frame([scenario, year]), {
            "pairs": [{"scenario": "Ziel", "scenario_quote": "Zielszenario",
                       "scenario_source": "Q1", "year": 2040,
                       "year_raw": None, "year_quote": "im Jahr 2040"}],
            "status": "complete"}),
        ("review", extraction_replies.review([value, scenario]), {
            "value": 241.0, "unit": "GWh/a", "unit_raw": "GWh",
            "value_quote": "241 GWh", "scenario": "Ziel",
            "scenario_raw": None}),
        ("field number", runner.field_response_format(year)["json_schema"]
         ["schema"], {"fields": {"year": {
             "groups": [{"rows": ["R1", "R2"], "value": 2030,
                         "quote": "bis 2030"}],
             "answers": {"R3": {"value": "out:unstated"}}}},
             "need_more": ["Tabelle 4"]}),
        ("field choice", runner.field_response_format(scenario)
         ["json_schema"]["schema"], {"fields": {"scenario": {
             "answers": {"R1": {"value": "Ziel", "value_raw": "Zielbild",
                                "quote": "im Zielbild"}}}}}),
        ("split", refinement_replies.SPLIT, {
            "first_title": None, "cuts": [{"at": 4, "title": "Teil 2"}]}),
        ("corrections", refinement_replies.CORRECTIONS, {"sections": [{
            "index": 0, "captions": {"p3_t1": "Tabelle 1", "p3_f1": None},
            "corrections": [{"find": "Wärme-\nplan", "replace": "Wärmeplan"}],
            "_action": "keep"}]}),
        ("window", refinement_replies.window(window), {"sections": [{
            "title": "1 Einleitung", "content": ["@book{a}"],
            "page_number": 3, "level": 1, "figures": [],
            "tables": [{"id": "p3_t1", "path": "a.png", "caption": None,
                        "bbox": [1, 2.5, 3, 4], "page_number": 3}],
            "_action": "keep"}]}),
        ("table", visual_replies.TABLE[1], {"markdown": "|a|", "caption": None}),
        ("figure", visual_replies.FIGURE[1], {"description": "Karte",
                                              "caption": "Abb. 1"}),
        ("page", visual_replies.PAGE[1], {"markdown": ""}),
        ("choose", chat_replies.CHOOSE[1], {"answer": 2030}),
        ("search phrase", chat_replies.PHRASE[1], {"phrase": "x",
                                                   "repetition": False}),
        ("chunk", chat_replies.CHUNK[1], {"found": False}),
        ("readoff", chat_replies.READOFF[1], {"reading": "etwa 40",
                                              "value": None, "unit": None}),
        ("compare", chat_replies.COMPARE[1], {"comparison": "x"}),
        ("answer", chat_replies.answer()[1], {
            "statements": [
                {"statement": "Es sind 42.", "basis": "text", "index": 0,
                 "quote": "zweiundvierzig"},
                {"statement": "Etwa 42 GWh.", "basis": "image", "index": 1,
                 "reading": "42 GWh"},
                {"statement": "Etwa 7 GWh.", "basis": "image",
                 "block": "p17_img1", "reading": "7 GWh"},
                {"statement": "Zusammen 49.", "basis": "computed",
                 "index": 0, "quote": "42 und 7", "run": 1}],
            "complete": False}),
        ("answer action", chat_replies.answer()[1],
         {"action": "python", "code": "print(1)"}),
        ("answer image action", chat_replies.answer()[1],
         {"action": "image", "id": "p17_img1"}),
        ("answer, last call", chat_replies.answer(actions=False)[1],
         {"statements": [], "complete": False}),
    ]
    out.append(("rows", extraction_replies.rows(), {
        "tuples": [{"source": "Q1", "value": 12.5, "unit_raw": "GWh/a",
                    "quote": "12,5 GWh/a", "computed": True},
                   {"source": "Q2", "value": "Stadtwerke",
                    "value_raw": None, "quote": "die Stadtwerke"}],
        "defaults": {"source": "Q1"}, "status": "partial",
        "need_more": ["die Tabelle auf Seite 4"]}))
    out.append(("rows action", extraction_replies.rows(),
                {"action": "python", "code": "print(2)"}))
    return out


@pytest.mark.parametrize("name,natural,answer",
                         _every_shape(), ids=lambda v: v if isinstance(v, str)
                         else None)
def test_every_request_kind_has_a_shape_a_hosted_api_generates_in(
        name, natural, answer):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(answer, natural)            # the stage's own shape
    strict, decode = schema.strict(natural)
    assert _in_subset(strict) == []
    generated = _encode(answer, natural)
    jsonschema.validate(generated, strict)          # what the API generates
    read = decode(generated)
    jsonschema.validate(read, natural)              # what the stage reads
    # A key left out comes back as null where the shape's own type has null,
    # which is what the prompt lets the model write there anyway.
    assert _said(read) == _said(answer)
    # The dialect that takes optional keys: the stage's own reply, with a
    # keyed object as a list, validates against it and reads back the same.
    counted, decode = schema.strict(natural, schema.OPTIONAL, (24, 16))
    assert _in_subset(counted, optional=True) == []
    lean = _lean(_encode_keyed(_said(answer), natural), counted)
    jsonschema.validate(lean, counted)
    assert _said(decode(lean)) == _said(answer)


def test_a_rows_schema_without_a_sandbox_has_no_action():
    assert "action" in extraction_replies.rows()["properties"]
    assert "action" not in extraction_replies.rows(
        sandbox=False)["properties"]
    assert "action" not in chat_replies.answer(actions=False)[1]["properties"]


def test_the_answer_schema_is_the_statement_shape():
    """The answer is a list of statements, each with its own evidence, and no
    prose beside them. The last call of a turn has to hold statements; a call
    that may ask for an action holds statements or an action. A reply in the
    shape the chat used to ask for is no reply of this one."""
    jsonschema = pytest.importorskip("jsonschema")
    name, last = chat_replies.answer(actions=False)
    _name, open_ = chat_replies.answer()
    assert name == _name == chat_replies.ANSWER
    assert last["required"] == ["statements"]
    assert set(open_["properties"]) == {"statements", "complete", "action",
                                        "code", "id"}
    assert set(last["properties"]) == {"statements", "complete"}
    statement = open_["properties"]["statements"]["items"]
    assert set(statement["properties"]) == {
        "statement", "basis", "index", "quote", "reading", "block", "run"}
    assert statement["required"] == ["statement", "basis"]
    assert statement["properties"]["basis"]["enum"] == list(chat_replies.BASES)
    old_shape = {"found": True, "complete": False, "answer": "42",
                 "supports": [{"index": 0, "quote": "zweiundvierzig"}]}
    for natural in (last, open_):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(old_shape, natural)
        with pytest.raises(jsonschema.ValidationError):     # no basis
            jsonschema.validate({"statements": [{"statement": "x"}]}, natural)
        with pytest.raises(jsonschema.ValidationError):     # no such basis
            jsonschema.validate({"statements": [
                {"statement": "x", "basis": "memory"}]}, natural)
        with pytest.raises(jsonschema.ValidationError):     # no prose answer
            jsonschema.validate({"statements": [], "answer": "x"}, natural)
    with pytest.raises(jsonschema.ValidationError):         # the last call
        jsonschema.validate({"complete": True}, last)       # has to answer


def test_what_the_reader_needs_of_a_reply_is_read_from_its_schema():
    """`needs` is the one place that says which key a reply has to carry:
    the schema's own required key, with the kind of thing under it."""
    assert chat_replies.needs(chat_replies.PHRASE) == ("phrase", str, "")
    assert chat_replies.needs(chat_replies.COMPARE) == ("comparison", str, "")
    assert chat_replies.needs(chat_replies.READOFF) == ("reading", str, "")
    assert chat_replies.needs(chat_replies.CHOOSE) == ("answer", object, "")
    assert chat_replies.needs(chat_replies.answer(actions=False)) == (
        "statements", list, "")
    # while an action may stand in its place
    assert chat_replies.needs(chat_replies.answer()) == (
        "statements", list, "action")
    # no shape: one object and nothing more
    assert chat_replies.needs(None) == ("", object, "")


# -- which client a role gets -------------------------------------------------

def test_a_server_of_ones_own_is_asked_exactly_as_before(monkeypatch):
    import openai
    built = []
    monkeypatch.setattr(openai, "OpenAI",
                        lambda **kw: built.append(kw) or "the client")
    assert providers.client("llm", base_url="http://x/v1", api_key="EMPTY",
                            timeout=7, max_retries=0) == "the client"
    assert built == [{"base_url": "http://x/v1", "api_key": "EMPTY",
                      "timeout": 7, "max_retries": 0}]
    assert providers.client("embedding", base_url="u", api_key="k")
    assert built[1] == {"base_url": "u", "api_key": "k"}
    assert providers.gate("llm") is None
    assert providers.reply_format("llm", "n", {"type": "object"}) is None
    assert providers.reply_format("llm", "n", {}, {"type": "json_object"}) \
        == {"type": "json_object"}
    assert providers.formatted("llm", "n", {}) == {}


def test_llm_schema_all_sends_the_schema_to_ones_own_server(monkeypatch):
    monkeypatch.setenv("LLM_SCHEMA", "all")
    shape = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert providers.reply_format("llm", "n", shape, {"type": "json_object"}) \
        == {"type": "json_schema", "json_schema": {"name": "n",
                                                   "schema": shape}}


def test_grammar_is_the_schema_on_every_provider(monkeypatch):
    """The promise: the schema is the grammar of the request on a server of
    one's own as on a hosted API, whatever LLM_SCHEMA says, in the one shape
    the harvest's field request builds and the hosted adapters read."""
    shape = {"type": "object", "properties": {"a": {"type": "string"}},
             "required": ["a"]}
    inside = {"type": "json_schema",
              "json_schema": {"name": "n", "schema": shape}}
    for provider in ("openai-compatible", "openai", "anthropic", "gemini"):
        monkeypatch.setenv("LLM_PROVIDER", provider)
        for schema_setting in ("auto", "all", ""):
            monkeypatch.setenv("LLM_SCHEMA", schema_setting)
            assert providers.grammar("n", shape) == inside, (
                provider, schema_setting)
    # the shape of the harvest's own field request, and what an adapter reads
    slot = _year()
    field = runner.field_response_format(slot)
    assert providers.grammar("field_reply",
                             field["json_schema"]["schema"]) == field
    assert base.wanted_schema(providers.grammar("n", shape)) == ("n", shape)
    # reply_format builds with it exactly where it enforces, and only there
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_SCHEMA", "all")
    assert providers.reply_format("llm", "n", shape) == providers.grammar(
        "n", shape)


def test_grammar_does_not_ask_the_installation_whether_to_send_the_schema(
        monkeypatch):
    """The case built to break it: what reply_format leaves out for a server
    of one's own (the default), grammar still sends."""
    monkeypatch.delenv("LLM_SCHEMA", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    shape = {"type": "object"}
    assert providers.reply_format("llm", "n", shape,
                                  {"type": "json_object"}) == {
        "type": "json_object"}
    assert providers.grammar("n", shape)["type"] == "json_schema"


def test_a_provider_nobody_knows_is_named(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vertex")
    with pytest.raises(ValueError, match="LLM_PROVIDER.*anthropic"):
        providers.client("llm")


def test_a_hosted_role_enforces_schemas_and_ignores_a_local_default_address(
        monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "gemini")
    assert providers.hosted("vlm") and not providers.hosted("llm")
    assert providers.enforces_schema("vlm")
    # the stage's default address is a local server: not this API's
    where = providers.endpoint("vlm", base_url="http://localhost:8001/v1",
                               api_key="EMPTY", timeout=30)
    assert (where.base_url, where.api_key, where.timeout) == (None, None, 30)
    assert where.thinking_room == 8192
    monkeypatch.setenv("VLM_BASE_URL", "https://gateway.example/v1beta")
    monkeypatch.setenv("LLM_THINKING_ROOM", "0")
    monkeypatch.setenv("VLM_REQUEST_OPTIONS", '{"generationConfig": {"x": 1}}')
    where = providers.endpoint("vlm", base_url="https://gateway.example/v1beta",
                               api_key="secret")
    assert where.base_url == "https://gateway.example/v1beta"
    assert where.api_key == "secret" and where.thinking_room == 0
    assert where.options == {"generationConfig": {"x": 1}}
    monkeypatch.setenv("VLM_REQUEST_OPTIONS", "[1]")
    with pytest.raises(ValueError, match="VLM_REQUEST_OPTIONS"):
        providers.endpoint("vlm")


# -- the gate -----------------------------------------------------------------

class _Clock:
    def __init__(self):
        self.now, self.slept = 100.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class _Status(Exception):
    def __init__(self, status, retry_after=None, headers=None):
        super().__init__(f"HTTP {status}")
        self.status_code = status
        if retry_after is not None:
            self.retry_after = retry_after
        if headers is not None:
            self.response = NS(status_code=status, headers=headers)


def test_the_gate_holds_every_request_for_as_long_as_the_api_said():
    clock = _Clock()
    gate = governor.Gate("x", clock=clock, sleep=clock.sleep)
    gate.wait()
    assert clock.slept == []                    # open: nobody waits
    told = []
    gate.listen(lambda: told.append(1))
    assert gate.limited(30) == 30
    gate.wait()
    assert clock.slept == [30] and told == [1]
    gate.wait()
    assert clock.slept == [30]                  # and open again


def _round(gate):
    """One round of refusals: told to wait, and waited."""
    hold = gate.limited()
    gate.wait()
    return hold


def test_without_a_number_the_hold_doubles_with_every_round_until_served():
    clock = _Clock()
    gate = governor.Gate("x", clock=clock, sleep=clock.sleep)
    assert [_round(gate), _round(gate), _round(gate)] == [2, 4, 8]
    gate.served()
    assert _round(gate) == 2
    # a long outage: the wait stays at its bound and the count does not run off
    for _ in range(1500):
        last = _round(gate)
    assert last == governor.HOLD_MAX


def test_the_requests_of_one_round_are_one_round():
    """Sixteen requests under way come back refused together. That is one
    thing learned, not sixteen."""
    clock = _Clock()
    gate = governor.Gate("x", clock=clock, sleep=clock.sleep)
    assert not gate.closed()
    assert [gate.limited() for _ in range(16)] == [2.0] * 16
    assert gate.closed()
    gate.wait()
    assert clock.slept == [2] and not gate.closed()
    assert gate.limited() == 4          # the next round is the second
    # a number from the API is taken also from a request of the same round
    assert gate.limited(30) == 30


@pytest.mark.parametrize("status,held", [(429, 1), (503, 1), (529, 1),
                                         (400, 0), (401, 0), (500, 0)])
def test_only_not_now_closes_the_gate_and_nothing_is_retried(status, held):
    clock = _Clock()
    gate = governor.Gate("x", clock=clock, sleep=clock.sleep)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise _Status(status, headers={"retry-after": "12"})

    client = governor.Governed(base.facade(create), gate)
    with pytest.raises(_Status):
        client.chat.completions.create(model="m")
    assert len(calls) == 1 and gate.holds == held
    if held:
        gate.wait()
        assert clock.slept == [12]


def test_a_served_request_passes_through_and_resets_the_streak():
    clock = _Clock()
    gate = governor.Gate("x", clock=clock, sleep=clock.sleep)
    gate.limited()
    client = governor.Governed(base.facade(lambda **kw: kw,
                                           embeddings=lambda **kw: "vectors"),
                               gate)
    assert client.chat.completions.create(model="m") == {"model": "m"}
    assert client.embeddings.create(model="e", input=["a"]) == "vectors"
    assert gate.limited() == 2


def test_retry_after_is_read_from_the_error_or_its_headers():
    assert governor.retry_after(_Status(429, retry_after=3)) == 3
    assert governor.retry_after(_Status(429, headers={"retry-after": "7"})) == 7
    assert governor.retry_after(_Status(429, headers={})) is None
    assert governor.retry_after(_Status(429, headers={"retry-after": "x"})) \
        is None
    assert governor.retry_after(RuntimeError("down")) is None
    assert governor.status_of(_Status(418)) == 418
    assert governor.status_of(RuntimeError("down")) is None


def test_the_hosted_limit_steps_down_when_told_to_wait_and_grows_in_use():
    limit = throttle.AdaptiveLimit(start=40, minimum=16, maximum=512)
    control = throttle.RateController(limit, step=8, backoff=0.5)
    assert control.decide(used=40) == (48, None)        # in use: grow
    assert control.decide(used=10) == (40, None)        # not in use: stay
    control.limited()
    assert control.decide(used=40) == (20, "the API asked to wait")
    limit.resize(20)
    for _ in range(throttle.HOLD_SAMPLES):
        assert control.decide(used=20) == (20, None)    # holding
    assert control.decide(used=20) == (28, None)
    limit.resize(16)
    control.limited()
    assert control.decide(used=16)[0] == 16             # never below minimum
    # at a closed gate the waiting requests hold their places: no growth
    control = throttle.RateController(
        throttle.AdaptiveLimit(start=40, minimum=16, maximum=512), step=8)
    assert control.decide(used=40, closed=True) == (40, None)
    assert control.decide(used=40, closed=False) == (48, None)


# -- Gemini -------------------------------------------------------------------

class _Web:
    """urllib's opener, answering from a script."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request, timeout=None):
        self.requests.append(NS(url=request.full_url, method=request.method,
                                headers=dict(request.header_items()),
                                body=json.loads(request.data)
                                if request.data else None, timeout=timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return io.BytesIO(json.dumps(answer).encode("utf-8"))


def _http(status, body, headers=None):
    return urllib.error.HTTPError("u", status, "x", headers or {},
                                  io.BytesIO(json.dumps(body).encode()))


def _gemini(web, **endpoint):
    where = base.Endpoint(role="llm", provider="gemini", api_key="k",
                          timeout=50, thinking_room=1000, **endpoint)
    return gemini_api.GeminiChat(where, opener=web).client()


PNG = "data:image/png;base64,QUJD"
SHAPE = {"type": "json_schema", "json_schema": {"name": "n", "schema": {
    "type": "object", "properties": {"markdown": {"type": "string"},
                                     "caption": {"type": ["string", "null"]},
                                     "rows": {"type": "object",
                                              "additionalProperties": {
                                                  "type": "integer"}}},
    "required": ["markdown"]}}}


def test_gemini_gets_one_generate_content_request_and_is_read_back():
    web = _Web({"candidates": [{"content": {"parts": [
        {"text": "thinking", "thought": True},
        {"text": json.dumps({"markdown": "|a|", "caption": None,
                             "rows": [{"key": "R1", "value": 4}]})}]},
        "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 90, "candidatesTokenCount": 7,
                          "thoughtsTokenCount": 3},
        "modelVersion": "gemini-x-001"})
    reply = _gemini(web).chat.completions.create(
        model="gemini-x", max_tokens=400, temperature=0.1,
        messages=[{"role": "system", "content": "Transcribe."},
                  {"role": "user", "content": [
                      {"type": "text", "text": "Table 3"},
                      {"type": "image_url", "image_url": {"url": PNG}}]},
                  {"role": "assistant", "content": "not json"},
                  {"role": "user", "content": "Again."}],
        response_format=SHAPE,
        extra_body={"chat_template_kwargs": {"enable_thinking": False},
                    "reasoning_effort": "low", "repetition_penalty": 1.3})
    sent = web.requests[0]
    assert sent.url.endswith("/v1beta/models/gemini-x:generateContent")
    assert sent.headers["X-goog-api-key"] == "k" and sent.timeout == 50
    assert sent.body["systemInstruction"] == {"parts": [{"text":
                                                         "Transcribe."}]}
    assert [turn["role"] for turn in sent.body["contents"]] == [
        "user", "model", "user"]
    assert sent.body["contents"][0]["parts"] == [
        {"text": "Table 3"},
        {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]
    made = sent.body["generationConfig"]
    assert made["maxOutputTokens"] == 1400 and made["temperature"] == 0.1
    assert made["responseMimeType"] == "application/json"
    assert _in_subset(made["responseJsonSchema"], optional=True) == []
    assert made["responseJsonSchema"]["required"] == ["markdown"]
    # nothing only a server of one's own takes
    assert "chat_template_kwargs" not in json.dumps(sent.body)
    assert "repetition_penalty" not in json.dumps(sent.body)
    choice = reply.choices[0]
    assert json.loads(choice.message.content) == {
        "markdown": "|a|", "caption": None, "rows": {"R1": 4}}
    assert choice.finish_reason == "stop"
    assert (reply.usage.prompt_tokens, reply.usage.completion_tokens) == (90,
                                                                          10)
    assert reply.model == "gemini-x-001"


def test_gemini_says_cut_off_and_refused_in_the_stages_words():
    web = _Web({"candidates": [{"content": {"parts": [{"text": '{"mark'}]},
                                "finishReason": "MAX_TOKENS"}]},
               {"candidates": [{"finishReason": "SAFETY"}]},
               {"promptFeedback": {"blockReason": "SAFETY"}})
    ask = _gemini(web).chat.completions.create
    cut = ask(model="m", messages=[{"role": "user", "content": "x"}],
              response_format=SHAPE)
    assert cut.choices[0].finish_reason == "length"
    assert cut.choices[0].message.content == '{"mark'      # not repaired
    for _ in range(2):
        refused = ask(model="m", messages=[{"role": "user", "content": "x"}])
        assert refused.choices[0].finish_reason == "content_filter"
        assert refused.choices[0].message.content == ""
        assert refused.usage is None


def test_gemini_failures_carry_the_status_and_the_wait():
    web = _Web(
        _http(429, {"error": {"message": "quota", "details": [
            {"@type": "x.RetryInfo", "retryDelay": "32s"}]}}),
        _http(429, {"error": {"message": "quota"}}, {"Retry-After": "5"}),
        _http(400, {"error": {"message": "bad schema"}}),
        urllib.error.URLError(TimeoutError("timed out")),
        TimeoutError("timed out"),
        urllib.error.URLError("refused"))
    ask = _gemini(web).chat.completions.create
    seen = []
    for _ in range(6):
        with pytest.raises(providers.ProviderError) as failed:
            ask(model="m", messages=[{"role": "user", "content": "x"}])
        seen.append((type(failed.value).__name__, failed.value.status_code,
                     failed.value.retry_after))
    assert seen == [("ProviderError", 429, 32.0), ("ProviderError", 429, 5.0),
                    ("ProviderError", 400, None),
                    ("ProviderTimeout", None, None),
                    ("ProviderTimeout", None, None),
                    ("ProviderError", None, None)]
    assert providers.timed_out(providers.ProviderTimeout("x"))
    assert not providers.timed_out(providers.ProviderError("x", 500))


def test_gemini_takes_no_empty_turn_and_no_request_waits_for_good():
    web = _Web({"candidates": [{"content": {"parts": [{"text": "x"}]},
                                "finishReason": "STOP"}]})
    where = base.Endpoint(role="llm", provider="gemini", api_key="k")
    gemini_api.GeminiChat(where, opener=web).client().chat.completions.create(
        model="m", messages=[{"role": "user", "content": "x"},
                             {"role": "assistant", "content": " \n"},
                             {"role": "user", "content": "again"}])
    assert web.requests[0].body["contents"][1]["parts"] == [
        {"text": "(no reply)"}]
    assert web.requests[0].timeout == gemini_api.TIMEOUT


@pytest.mark.parametrize("broken", [
    "an html page", ConnectionResetError("reset"), OSError("short read")])
def test_a_gemini_answer_that_cannot_be_read_is_not_served(broken):
    class _Body:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            if isinstance(broken, BaseException):
                raise broken
            return b"<html>proxy</html>"

    where = base.Endpoint(role="llm", provider="gemini", api_key="k")
    client = gemini_api.GeminiChat(
        where, opener=lambda request, timeout=None: _Body()).client()
    with pytest.raises(providers.ProviderError) as failed:
        client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "x"}])
    assert failed.value.status_code is None
    assert not isinstance(failed.value, providers.ProviderTimeout)


def test_gemini_is_only_asked_for_json_inside_a_schema():
    web = _Web()
    with pytest.raises(providers.ProviderError) as refused:
        _gemini(web).chat.completions.create(
            model="m", messages=[{"role": "user", "content": "x"}],
            response_format={"type": "json_object"})
    assert refused.value.status_code == 400 and web.requests == []


def test_gemini_lists_models_and_embeds_texts(monkeypatch):
    web = _Web({"models": [{"name": "models/gemini-x",
                            "inputTokenLimit": 1048576},
                           {"name": "models/embed-1"}]},
               {"embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]})
    client = _gemini(web)
    cards = client.models.list().data
    assert [(c.id, c.max_model_len) for c in cards] == [
        ("gemini-x", 1048576), ("embed-1", None)]
    got = client.embeddings.create(model="embed-1", input=["a", "b"])
    assert [d.embedding for d in got.data] == [[0.1, 0.2], [0.3, 0.4]]
    assert web.requests[1].url.endswith("models/embed-1:batchEmbedContents")
    assert web.requests[1].body["requests"][1] == {
        "model": "models/embed-1", "content": {"parts": [{"text": "b"}]}}


def test_gemini_without_a_key_says_which_variable(monkeypatch):
    where = base.Endpoint(role="llm", provider="gemini")
    with pytest.raises(providers.ProviderError, match="GEMINI_API_KEY"):
        gemini_api.GeminiChat(where, opener=_Web()).client().models.list()
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    web = _Web({"models": []})
    gemini_api.GeminiChat(where, opener=web).client().models.list()
    assert web.requests[0].headers["X-goog-api-key"] == "g"


# -- Anthropic ----------------------------------------------------------------

class _FakeAnthropic(types.ModuleType):
    """The part of the SDK the adapter uses."""

    def __init__(self):
        super().__init__("anthropic")
        module = self

        class APIConnectionError(Exception):
            pass

        class APITimeoutError(APIConnectionError):
            pass

        class APIStatusError(Exception):
            def __init__(self, status, message="refused", headers=None):
                super().__init__(message)
                self.status_code = status
                self.response = NS(headers=headers or {})

        class _Stream:
            def __init__(self, outcome):
                self.outcome = outcome

            def __enter__(self):
                if isinstance(self.outcome, BaseException):
                    raise self.outcome
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return self.outcome

        class Anthropic:
            def __init__(self, **kwargs):
                module.built.append(kwargs)
                self.messages = NS(stream=self._plain)
                self.beta = NS(messages=NS(stream=self._beta))
                self.models = NS(list=lambda: iter(module.cards))

            def with_options(self, **kwargs):
                module.options.append(kwargs)
                return self

            def _plain(self, **body):
                module.sent.append(("messages", body))
                return _Stream(module.answers.pop(0))

            def _beta(self, **body):
                module.sent.append(("beta", body))
                return _Stream(module.answers.pop(0))

        self.Anthropic = Anthropic
        self.APIConnectionError = APIConnectionError
        self.APITimeoutError = APITimeoutError
        self.APIStatusError = APIStatusError
        self.built, self.sent, self.options = [], [], []
        self.answers, self.cards = [], []


def _message(text, stop="end_turn", model="claude-x", **usage):
    counted = {"input_tokens": 10, "output_tokens": 5,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    counted.update(usage)
    return NS(content=[NS(type="thinking", thinking=""),
                       NS(type="text", text=text)],
              stop_reason=stop, model=model, usage=NS(**counted))


@pytest.fixture
def anthropic(monkeypatch):
    fake = _FakeAnthropic()
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return fake


def _claude(fake, **endpoint):
    from docpipe.providers import anthropic_api
    endpoint.setdefault("thinking_room", 2000)
    where = base.Endpoint(role="llm", provider="anthropic", **endpoint)
    return anthropic_api.AnthropicChat(where).client()


def test_anthropic_gets_one_messages_request_and_is_read_back(anthropic):
    anthropic.answers.append(_message(
        json.dumps({"markdown": "|a|", "caption": None, "rows": []}),
        cache_read_input_tokens=80, cache_creation_input_tokens=7))
    reply = _claude(anthropic, api_key="k", timeout=99).chat.completions.create(
        model="claude-haiku-4-5", max_tokens=300, temperature=0,
        messages=[{"role": "system", "content": "Transcribe."},
                  {"role": "user", "content": [
                      {"type": "text", "text": "Table 3"},
                      {"type": "image_url", "image_url": {"url": PNG}}]},
                  {"role": "assistant", "content": ""},
                  {"role": "user", "content": "Again."}],
        response_format=SHAPE, timeout=20,
        extra_body={"chat_template_kwargs": {"enable_thinking": False},
                    "reasoning_effort": "low"})
    assert anthropic.built == [{"max_retries": 0, "api_key": "k",
                                "timeout": 99}]
    assert anthropic.options == [{"timeout": 20}]
    path, body = anthropic.sent[0]
    assert path == "messages"                   # no fallback for this model
    assert body["model"] == "claude-haiku-4-5" and body["max_tokens"] == 2300
    assert body["system"] == [{"type": "text", "text": "Transcribe.",
                               "cache_control": {"type": "ephemeral"}}]
    assert body["messages"][0]["content"] == [
        {"type": "text", "text": "Table 3"},
        {"type": "image", "source": {"type": "base64",
                                     "media_type": "image/png",
                                     "data": "QUJD"}}]
    # an empty turn stays a turn the API takes
    assert body["messages"][1] == {"role": "assistant", "content": [
        {"type": "text", "text": "(no reply)"}]}
    assert body["output_config"]["effort"] == "low"
    made = body["output_config"]["format"]
    assert made["type"] == "json_schema"
    assert _in_subset(made["schema"], optional=True) == []
    assert made["schema"]["required"] == ["markdown"]
    assert "chat_template_kwargs" not in body
    assert json.loads(reply.choices[0].message.content) == {
        "markdown": "|a|", "caption": None, "rows": {}}
    assert reply.choices[0].finish_reason == "stop"
    assert (reply.usage.prompt_tokens, reply.usage.completion_tokens) == (97,
                                                                          5)


def test_anthropic_models_that_can_decline_are_asked_with_the_fallback(
        anthropic):
    anthropic.answers += [_message("{}", model="claude-opus-4-8"),
                          _message("", stop="refusal"),
                          _message('{"a', stop="max_tokens"),
                          _message("{}")]
    ask = _claude(anthropic).chat.completions.create
    said = [{"role": "user", "content": "x"}]
    served = ask(model="claude-opus-5-5", messages=said, max_tokens=10)
    path, body = anthropic.sent[0]
    assert path == "beta" and body["fallbacks"] == "default"
    assert body["betas"] == ["server-side-fallback-2026-07-01"]
    assert served.model == "claude-opus-4-8"    # the reply names who answered
    assert "system" not in body and "output_config" not in body
    refused = ask(model="claude-opus-5-5", messages=said, max_tokens=10)
    assert refused.choices[0].finish_reason == "content_filter"
    cut = ask(model="claude-opus-5-5", messages=said, max_tokens=10)
    assert cut.choices[0].finish_reason == "length"
    assert cut.choices[0].message.content == '{"a'
    # behind a gateway of one's own the fallback is not asked for
    _claude(anthropic, base_url="https://gw.example").chat.completions.create(
        model="claude-opus-5-5", messages=said, max_tokens=10)
    assert anthropic.sent[-1][0] == "messages"
    assert anthropic.built[-1]["base_url"] == "https://gw.example"


def test_a_model_that_refuses_the_temperature_is_asked_again_without_it(
        anthropic):
    refusal = anthropic.APIStatusError(
        400, "temperature: not supported for this model")
    anthropic.answers += [refusal, _message("{}"), _message("{}")]
    ask = _claude(anthropic).chat.completions.create
    said = [{"role": "user", "content": "x"}]
    ask(model="claude-opus-5-5", messages=said, max_tokens=5, temperature=0)
    assert ["temperature" in body for _, body in anthropic.sent] == [True,
                                                                    False]
    ask(model="claude-opus-5-5", messages=said, max_tokens=5, temperature=0)
    assert "temperature" not in anthropic.sent[2][1]    # learned, not re-tried
    # another refusal is not swallowed
    anthropic.answers.append(anthropic.APIStatusError(400, "bad schema"))
    with pytest.raises(providers.ProviderError) as failed:
        ask(model="claude-opus-5-5", messages=said, max_tokens=5)
    assert failed.value.status_code == 400


def test_anthropic_failures_carry_the_status_and_the_wait(anthropic):
    anthropic.answers += [
        anthropic.APIStatusError(429, headers={"retry-after": "9"}),
        anthropic.APIStatusError(529),
        anthropic.APITimeoutError("slow"),
        anthropic.APIConnectionError("down")]
    ask = _claude(anthropic).chat.completions.create
    seen = []
    for _ in range(4):
        with pytest.raises(providers.ProviderError) as failed:
            ask(model="claude-haiku-4-5", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        seen.append((type(failed.value).__name__, failed.value.status_code,
                     failed.value.retry_after))
    assert seen == [("ProviderError", 429, 9.0), ("ProviderError", 529, None),
                    ("ProviderTimeout", None, None),
                    ("ProviderError", None, None)]


def test_anthropic_reads_what_was_answered_after_a_hand_over(anthropic):
    """A model that declines part-way leaves its half sentence in the reply,
    and the model that took over writes the answer after it."""
    handed = NS(content=[NS(type="text", text='{"tuples": ['),
                         NS(type="fallback"),
                         NS(type="text", text='{"tuples": '),
                         NS(type="text", text="[]}")],
                stop_reason="end_turn", model="claude-opus-4-8",
                usage=NS(input_tokens=1, output_tokens=1))
    anthropic.answers.append(handed)
    reply = _claude(anthropic).chat.completions.create(
        model="claude-opus-5-5", max_tokens=5,
        messages=[{"role": "user", "content": "x"},
                  {"role": "assistant", "content": "\n"},
                  {"role": "user", "content": "again"}])
    assert reply.choices[0].message.content == '{"tuples": []}'
    assert anthropic.sent[0][1]["messages"][1]["content"] == [
        {"type": "text", "text": "(no reply)"}]


def test_an_error_inside_an_anthropic_stream_keeps_its_kind(anthropic):
    """After the status line said 200, the body says what happened: an
    overload is "not now", not a permanent refusal."""
    for kind, status in (("overloaded_error", 529), ("rate_limit_error", 429),
                         ("something_new", 500)):
        streamed = anthropic.APIStatusError(200)
        streamed.body = {"type": "error", "error": {"type": kind}}
        anthropic.answers.append(streamed)
        with pytest.raises(providers.ProviderError) as failed:
            _claude(anthropic).chat.completions.create(
                model="claude-haiku-4-5", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        assert failed.value.status_code == status


def test_an_old_sdk_and_a_schema_too_large_are_refused_in_words(anthropic):
    anthropic.answers.append(TypeError("unexpected keyword 'output_config'"))
    with pytest.raises(providers.ProviderError, match="pip install -U") as old:
        _claude(anthropic).chat.completions.create(
            model="claude-haiku-4-5", max_tokens=5,
            messages=[{"role": "user", "content": "x"}])
    assert old.value.status_code == 400
    wide = {"type": "json_schema", "json_schema": {"name": "wide", "schema": {
        "type": "object", "properties": {
            f"k{i}": {"type": ["string", "integer"]} for i in range(60)}}}}
    sent = len(anthropic.sent)
    with pytest.raises(providers.ProviderError, match="compiles 24") as big:
        _claude(anthropic).chat.completions.create(
            model="claude-haiku-4-5", max_tokens=5, response_format=wide,
            messages=[{"role": "user", "content": "x"}])
    assert big.value.status_code == 400 and len(anthropic.sent) == sent


def test_every_request_refused_over_its_temperature_is_sent_again(anthropic):
    """Not only the first: the ones under way when it was learned too."""
    refusal = anthropic.APIStatusError(400, "temperature is not supported")
    assert base.refused_temperature("anthropic", "m", refusal)
    assert base.refused_temperature("anthropic", "m", refusal)
    assert not base.sends_temperature("anthropic", "m")
    assert not base.refused_temperature(
        "anthropic", "m", anthropic.APIStatusError(400, "bad schema"))
    assert not base.refused_temperature(
        "anthropic", "m", anthropic.APIStatusError(500, "temperature"))


def test_anthropic_lists_models_and_has_no_embeddings(anthropic):
    anthropic.cards = [NS(id="claude-opus-5-5", max_input_tokens=1000000),
                       NS(id="claude-old")]
    client = _claude(anthropic)
    assert [(c.id, c.max_model_len) for c in client.models.list().data] == [
        ("claude-opus-5-5", 1000000), ("claude-old", None)]
    with pytest.raises(providers.ProviderError, match="no embeddings"):
        client.embeddings.create(model="m", input=["a"])


def test_without_the_sdk_the_anthropic_provider_says_what_to_install(
        monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    from docpipe.providers import anthropic_api
    with pytest.raises(ImportError, match=r"docpipe\[anthropic\]"):
        anthropic_api.AnthropicChat(base.Endpoint(role="llm",
                                                  provider="anthropic"))


# -- hosted OpenAI ------------------------------------------------------------

def _openai(monkeypatch, *answers, **endpoint):
    import openai
    sent, built = [], []
    script = list(answers)

    def create(**body):
        sent.append(body)
        answer = script.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def build(**kwargs):
        built.append(kwargs)
        return NS(chat=NS(completions=NS(create=create)),
                  models=NS(list=lambda: "cards"),
                  embeddings=NS(create=lambda **kw: ("vectors", kw)))

    monkeypatch.setattr(openai, "OpenAI", build)
    where = base.Endpoint(role="llm", provider="openai", thinking_room=500,
                          **endpoint)
    return openai_api.OpenAIChat(where).client(), sent, built


def _completion(text, finish="stop", refusal=None):
    return NS(choices=[NS(message=NS(content=text, refusal=refusal),
                          finish_reason=finish)],
              usage=NS(prompt_tokens=11, completion_tokens=4), model="gpt-x-1")


def test_hosted_openai_gets_a_strict_schema_and_none_of_the_local_extras(
        monkeypatch):
    client, sent, built = _openai(
        monkeypatch,
        _completion(json.dumps({"markdown": "m", "caption": None,
                                "rows": [{"key": "R", "value": 1}]})),
        options={"service_tier": "flex"}, api_key="k")
    reply = client.chat.completions.create(
        model="gpt-x", max_tokens=100, temperature=0.2,
        messages=[{"role": "user", "content": "x"}], response_format=SHAPE,
        extra_body={"chat_template_kwargs": {"enable_thinking": False},
                    "reasoning_effort": "low", "repetition_penalty": 1.1},
        timeout=15)
    assert built == [{"max_retries": 0, "api_key": "k"}]
    body = sent[0]
    assert body["extra_body"] == {"max_completion_tokens": 600,
                                  "reasoning_effort": "low",
                                  "service_tier": "flex"}
    assert "max_tokens" not in body and body["timeout"] == 15
    assert body["temperature"] == 0.2
    made = body["response_format"]["json_schema"]
    assert made["strict"] is True and _in_subset(made["schema"]) == []
    assert json.loads(reply.choices[0].message.content) == {
        "markdown": "m", "caption": None, "rows": {"R": 1}}
    assert reply.usage.prompt_tokens == 11 and reply.model == "gpt-x-1"
    assert client.models.list() == "cards"
    assert client.embeddings.create(model="e", input=["a"])[0] == "vectors"


def test_hosted_openai_learns_a_refused_temperature_and_reads_a_refusal(
        monkeypatch):
    client, sent, _ = _openai(
        monkeypatch,
        _Status(400), _Status(400, headers={}),
        _completion("{}"), _completion(None, refusal="I cannot"))
    said = [{"role": "user", "content": "x"}]
    with pytest.raises(_Status):                # some other 400: raised
        client.chat.completions.create(model="o9", messages=said,
                                       temperature=0)
    refusal = _Status(400)
    refusal.args = ("Unsupported value: 'temperature' does not support 0",)
    sent.clear()
    client, sent, _ = _openai(monkeypatch, refusal, _completion("{}"),
                              _completion(None, refusal="I cannot"))
    client.chat.completions.create(model="o9", messages=said, temperature=0)
    assert ["temperature" in body for body in sent] == [True, False]
    declined = client.chat.completions.create(model="o9", messages=said,
                                              temperature=0)
    assert "temperature" not in sent[2]
    assert declined.choices[0].finish_reason == "content_filter"
    assert declined.choices[0].message.content == ""
    with pytest.raises(providers.ProviderError):
        client.chat.completions.create(
            model="o9", messages=said,
            response_format={"type": "json_object"})


# -- the preflight of a hosted role -------------------------------------------

def _hosted_llm(monkeypatch, cards, create):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    client = base.facade(create, models=lambda: NS(data=cards))
    monkeypatch.setattr(providers, "client", lambda role, **kw: client)
    monkeypatch.setattr(llm_preflight.providers, "client",
                        lambda role, **kw: client)


def _ok(**kwargs):
    return base.reply('{"ok": true}', "stop")


def test_a_hosted_model_is_checked_for_its_window_and_its_schema(monkeypatch):
    asked = []
    _hosted_llm(monkeypatch, [NS(id="gemini-x", max_model_len=50000)],
                lambda **kw: asked.append(kw) or _ok())
    assert llm_preflight.assert_serving("u", "k", "gemini-x", 40000) == 50000
    assert asked[0]["response_format"]["type"] == "json_schema"
    assert asked[0]["extra_body"] == llm_preflight.request_extras()
    with pytest.raises(llm_preflight.PreflightError, match="takes 50000"):
        llm_preflight.assert_serving("u", "k", "gemini-x", 60000)
    with pytest.raises(llm_preflight.PreflightError,
                       match=r"(?s)does not serve 'gemini-y'.*gemini-x"):
        llm_preflight.assert_serving("u", "k", "gemini-y", 10)


@pytest.mark.parametrize("outcome,raises", [
    (_Status(400), True),                # the model takes no schema
    (_Status(404), True),
    (_Status(429), False),               # not now: says nothing about it
    (_Status(500), False),
    (RuntimeError("no route"), False),
    (base.reply("Sure! Here you go", "stop"), True),
    (base.reply('{"ok": "yes"}', "stop"), True),
    (base.reply('{"ok": false}', "stop"), False),
])
def test_a_model_that_does_not_answer_inside_a_schema_is_refused_at_once(
        monkeypatch, outcome, raises):
    def create(**kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    _hosted_llm(monkeypatch, [NS(id="m", max_model_len=None)], create)
    if raises:
        with pytest.raises(llm_preflight.PreflightError) as refused:
            llm_preflight.assert_serving("u", "k", "m", 10)
        if isinstance(outcome, _Status):
            assert "LLM_REQUEST_OPTIONS" in str(refused.value)
    else:
        assert llm_preflight.assert_serving("u", "k", "m", 10) is None


# -- every request names its reply --------------------------------------------

# The requests that ask for no JSON: the one-token probe of a server of one's
# own. (The plain-text rescue of the visuals stage is gone, and with it the
# one request that asked for a reply in no schema.)
PLAIN = {("docpipe/llm_preflight.py", "assert_request_extras")}
# The layer itself, which passes a stage's request on.
PASSING_ON = ("docpipe/providers/", "docpipe/extraction/throttle.py")


def _requests():
    """(file, enclosing function, call) of every chat request in docpipe."""
    for path in sorted((ROOT / "docpipe").rglob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        if name.startswith(PASSING_ON):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if (isinstance(node, ast.Call)
                        and ast.unparse(node.func).endswith(
                            "chat.completions.create")):
                    yield name, function.name, node


def test_every_request_names_its_reply_or_asks_for_plain_text():
    seen, unnamed = set(), []
    for name, function, call in _requests():
        seen.add((name, function))
        named = any(keyword.arg == "response_format"
                    for keyword in call.keywords) or any(
            keyword.arg is None
            and "providers.formatted" in ast.unparse(keyword.value)
            for keyword in call.keywords)
        if not named and (name, function) not in PLAIN:
            unnamed.append((name, function, call.lineno))
    assert not unnamed, unnamed
    # the scan sees the requests at all, and the exceptions are real
    assert len(seen) >= 10 and PLAIN <= seen


def test_a_hosted_extraction_request_goes_out_with_its_schema(monkeypatch):
    """The field request through a hosted provider: asked inside the strict
    schema, read in the shape `merge_field` reads."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    web = _Web({"candidates": [{"content": {"parts": [{"text": json.dumps({
        "fields": {"year": {"groups": None, "answers": [
            {"key": "R1", "value": {"value": 2030, "value_raw": None,
                                    "quote": "bis zum Jahr 2030"}}]}},
        "need_more": None})}]}, "finishReason": "STOP"}]})
    where = providers.endpoint("llm")
    client = governor.Governed(
        gemini_api.GeminiChat(where, opener=web).client(),
        governor.Gate("test", sleep=lambda s: None))
    monkeypatch.setattr(runner, "_client", lambda: client)
    rows = [NS(label="R1", claim={"value": 4, "quote": "bis zum Jahr 2030"})]
    answer = runner.make_field_asker()([], rows, _year())
    made = web.requests[0].body["generationConfig"]
    assert _in_subset(made["responseJsonSchema"], optional=True) == []
    assert answer["fields"]["year"]["answers"] == {
        "R1": {"value": 2030, "quote": "bis zum Jahr 2030"}}


# -- a server of one's own is asked as before, site by site --------------------

def test_no_extraction_request_gains_a_reply_format_on_its_own_server():
    """The five requests that never had a reply format name their reply only
    through `providers.formatted("llm", ...)`, which adds nothing for a
    server of one's own; the field request keeps the one it had."""
    assert providers.formatted("llm", "x_reply", {"type": "object"}) == {}
    sites = {}                  # by line: a nested function is walked twice
    for name, function, call in _requests():
        if name != "docpipe/extraction/runner.py":
            continue
        direct = any(k.arg == "response_format" for k in call.keywords)
        splat = [ast.unparse(k.value) for k in call.keywords
                 if k.arg is None and "formatted" in ast.unparse(k.value)]
        sites[call.lineno] = (direct, splat)
    with_format = [line for line, (direct, _) in sites.items() if direct]
    assert len(with_format) == 1, with_format           # the field request
    rest = [(line, splat) for line, (direct, splat) in sites.items()
            if not direct]
    assert len(rest) == 5, rest
    for line, splat in rest:
        assert len(splat) == 1, line
        assert splat[0].replace("'", '"').startswith(
            'providers.formatted("llm", "'), splat


def test_the_chat_names_its_reply_as_the_grammar_on_every_provider(
        monkeypatch):
    """The shape of a reply is the grammar of the request, on a server of
    one's own as on a hosted API and whatever LLM_SCHEMA says: LLM_SCHEMA has
    no value that turns it off. The one reply with no shape, the answer
    reshaped into the user's own JSON, is asked as a JSON object."""
    from docpipe.inference import llm_client
    assert llm_client._reply_format() == {"type": "json_object"}
    for provider in ("openai-compatible", "openai", "anthropic", "gemini"):
        monkeypatch.setenv("LLM_PROVIDER", provider)
        for schema_setting in ("auto", "all", ""):
            monkeypatch.setenv("LLM_SCHEMA", schema_setting)
            token = llm_client._SHAPE.set(chat_replies.COMPARE)
            try:
                assert llm_client._reply_format() == providers.grammar(
                    *chat_replies.COMPARE), (provider, schema_setting)
                assert llm_client._reply_format()["type"] == "json_schema"
            finally:
                llm_client._SHAPE.reset(token)


# -- the gate, through the clients that carry it --------------------------------

def test_two_clients_of_one_hosted_endpoint_share_its_gate(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    first, second = providers.client("llm"), providers.client("llm")
    assert first is not second
    assert first.gate is second.gate is providers.gate("llm")
    # another address is another endpoint, and another API is another one
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1beta")
    gateway = providers.client("llm")
    assert gateway.gate is not first.gate
    assert gateway.gate is providers.gate("llm")
    assert providers.client("llm").gate is gateway.gate
    assert governor.gate_for("gemini", None) \
        is not governor.gate_for("openai", None)


class _TimedWeb(_Web):
    """The opener, noting what the gate had slept when a request was sent."""

    def __init__(self, clock, *answers):
        super().__init__(*answers)
        self.clock, self.slept_before = clock, []

    def __call__(self, request, timeout=None):
        self.slept_before.append(list(self.clock.slept))
        return super().__call__(request, timeout)


def test_a_gemini_refusal_that_names_its_wait_holds_the_next_request_that_long():
    clock = _Clock()
    gate = governor.Gate("gemini", clock=clock, sleep=clock.sleep)
    web = _TimedWeb(
        clock,
        _http(429, {"error": {"message": "quota"}}, {"Retry-After": "17"}),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]},
                         "finishReason": "STOP"}]})
    where = base.Endpoint(role="llm", provider="gemini", api_key="k")
    client = governor.Governed(
        gemini_api.GeminiChat(where, opener=web).client(), gate)
    said = [{"role": "user", "content": "x"}]
    with pytest.raises(providers.ProviderError) as refused:
        client.chat.completions.create(model="m", messages=said)
    assert (refused.value.status_code, refused.value.retry_after) == (429, 17.0)
    served = client.chat.completions.create(model="m", messages=said)
    assert served.choices[0].message.content == "ok"
    # the first request waited for nothing; the second slept the 17 seconds
    # the API named, and only then was sent
    assert web.slept_before == [[], [17.0]]
    assert clock.now == 117.0


def test_each_hosted_provider_name_gets_its_own_adapter():
    from docpipe.providers import anthropic_api
    for name, module, adapter in (
            ("openai", openai_api, openai_api.OpenAIChat),
            ("anthropic", anthropic_api, anthropic_api.AnthropicChat),
            ("gemini", gemini_api, gemini_api.GeminiChat)):
        assert providers._adapter(name) is adapter, name
        assert module.NAME == name
    assert {providers._adapter(name) for name in providers.HOSTED} == {
        openai_api.OpenAIChat, anthropic_api.AnthropicChat,
        gemini_api.GeminiChat}


# -- the limit of a hosted run, steered by a thread -----------------------------

class _PolledGate(governor.Gate):
    """A gate that counts how often the steering loop looked at it, and ends
    that loop (the only way out of it) once told to."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.polls, self.stopped = 0, False

    def closed(self):
        if self.stopped:
            raise SystemExit            # a thread that exits this way is silent
        self.polls += 1
        return super().closed()


def _really_sleep(seconds):
    """A sleep the suite's no-sleep fixture (which replaces `time.sleep` for
    every test) leaves alone: a thread that polls would otherwise spin."""
    threading.Event().wait(seconds)


@contextlib.contextmanager
def _steered(gate, **kwargs):
    """`throttle.start_hosted` with a poll of 10 ms; its thread is ended and
    joined afterwards, so that no test leaves one running."""
    previous = threading.excepthook

    def end_quietly(args):
        if args.exc_type is not SystemExit:
            previous(args)

    with mock.patch.object(throttle, "time", NS(sleep=_really_sleep)),             mock.patch.object(threading, "excepthook", end_quietly):
        before = set(threading.enumerate())
        limit = throttle.start_hosted(gate, poll=0.01, **kwargs)
        mine = [t for t in threading.enumerate()
                if t not in before and t.name == "llm-limit"]
        assert len(mine) == 1
        try:
            yield limit
        finally:
            gate.stopped = True
            mine[0].join(timeout=5)
        assert not mine[0].is_alive()


def _until(done, what, seconds=5.0):
    """Wait for done() to hold. Bounded, so that a test cannot hang."""
    stop = time.monotonic() + seconds
    while not done():
        if time.monotonic() > stop:
            pytest.fail(f"gave up waiting for {what}")
        _really_sleep(0.005)


def test_a_hosted_limit_starts_at_the_minimum_and_grows_only_while_in_use():
    gate = _PolledGate("x")
    with _steered(gate) as limit:
        assert limit.limit == throttle.MINIMUM
        # open, but nothing is asked: it stays where it is
        polls = gate.polls
        _until(lambda: gate.polls >= polls + 3 * throttle.HOLD_SAMPLES,
               "polls of an unused limit")
        assert limit.limit == throttle.MINIMUM
        # open and every place taken: it grows
        for _ in range(limit.limit):
            limit.acquire()
        _until(lambda: limit.limit > throttle.MINIMUM, "growth in use")


def test_a_hosted_limit_steps_down_within_a_few_polls_of_the_api_saying_wait():
    gate = _PolledGate("x", clock=lambda: 100.0)
    start = 100
    taken = throttle.AdaptiveLimit(start=start, minimum=16, maximum=512)
    with _steered(gate, limit=taken) as limit:
        assert limit is taken and limit.limit == start
        polls = gate.polls
        gate.limited(retry_after=60)
        _until(lambda: limit.limit < start, "the step down")
        assert gate.polls - polls <= 3
        stepped = limit.limit
        assert stepped == int(start * throttle.BACKOFF)
        # one refusal is one step: nothing is asked and nothing moves
        polls = gate.polls
        _until(lambda: gate.polls >= polls + 3 * throttle.HOLD_SAMPLES,
               "polls after the step down")
        assert limit.limit == stepped


def test_a_hosted_limit_does_not_grow_while_the_gate_is_closed():
    clock = _Clock()
    gate = _PolledGate("x", clock=clock, sleep=clock.sleep)
    gate.limited(retry_after=60)
    with _steered(gate) as limit:
        for _ in range(limit.limit):            # in use right up to the limit
            limit.acquire()
        polls = gate.polls
        # well past the samples a step down would hold it for
        _until(lambda: gate.polls >= polls + 3 * throttle.HOLD_SAMPLES,
               "polls at a closed gate")
        assert limit.limit == throttle.MINIMUM
        clock.now += 61                         # the wait is over
        _until(lambda: limit.limit > throttle.MINIMUM,
               "growth once the gate is open")


# -- a schema that cannot be generated in names its place -----------------------

@pytest.mark.parametrize("natural, place, why", [
    ({"type": "object", "properties": {"inner": {"type": "object"}}},
     "reply.inner", "an object of any shape"),
    ({"type": "object", "properties": {"inner": {"type": "array"}}},
     "reply.inner", "a list of anything"),
    ({"type": "object", "properties": {"inner": {
        "type": "object", "properties": {"a": {"type": "string"}},
        "additionalProperties": {"type": "string"}}}},
     "reply.inner", "named keys and keys of its own"),
    ({"type": "object", "properties": {"rows": {
        "type": "array", "items": {"type": "object"}}}},
     "reply.rows[]", "an object of any shape"),
    ({"type": "object", "properties": {"m": {
        "type": "object", "additionalProperties": {"type": "array"}}}},
     "reply.m.*", "a list of anything"),
    ({"type": "object", "properties": {"x": {"anyOf": [
        {"type": "string"}, {"type": "object"}]}}},
     "reply.x|1", "an object of any shape"),
    ({"type": "object"}, "reply:", "an object of any shape"),
])
def test_the_refusal_of_a_shape_names_the_place_in_the_schema(
        natural, place, why):
    with pytest.raises(schema.SchemaError) as refused:
        schema.strict(natural)
    assert place in str(refused.value) and why in str(refused.value)
    with pytest.raises(providers.ProviderError) as asked:
        base.enforced({"type": "json_schema",
                       "json_schema": {"name": "nm", "schema": natural}})
    assert place in str(asked.value) and "nm" in str(asked.value)
    assert asked.value.status_code == 400


KEYED = {"type": "object", "properties": {"answers": {
    "type": "object", "additionalProperties": {"type": "integer"}}},
    "required": ["answers"]}


def test_a_keyed_list_that_is_not_one_object_stays_the_list_it_came_as():
    """Choosing among the entries of a list with a key twice, or with an entry
    that has none, would be a repair; the stage gets the list and refuses it."""
    _, decode = schema.strict(KEYED)
    good = {"answers": [{"key": "R1", "value": 1}, {"key": "R2", "value": 2}]}
    assert decode(good) == {"answers": {"R1": 1, "R2": 2}}
    twice = {"answers": [{"key": "R1", "value": 1}, {"key": "R1", "value": 2}]}
    assert decode(twice) == twice
    unkeyed = {"answers": [{"key": "R1", "value": 1}, {"value": 2}]}
    assert decode(unkeyed) == unkeyed
    assert decode({"answers": ["R1", "R2"]}) == {"answers": ["R1", "R2"]}
    # through the text of a reply, as a stage gets it
    for reply in (twice, unkeyed):
        said = json.dumps(reply)
        assert json.loads(schema.decoder_text(decode, said)) == reply
    assert json.loads(schema.decoder_text(decode, json.dumps(good))) == {
        "answers": {"R1": 1, "R2": 2}}


# -- what base.py promises to every provider --------------------------------------

def test_endpoint_options_are_laid_over_the_request_table_by_table():
    web = _Web({"candidates": [{"content": {"parts": [{"text": "x"}]},
                                "finishReason": "STOP"}]})
    _gemini(web, options={"generationConfig": {"temperature": 0.5}}) \
        .chat.completions.create(model="m", max_tokens=100, temperature=0.1,
                                 messages=[{"role": "user", "content": "x"}])
    made = web.requests[0].body["generationConfig"]
    assert made["maxOutputTokens"] == 1100          # kept: 100 and the room
    assert made["temperature"] == 0.5               # laid over the stage's own
    assert base.merge({"a": {"x": 1}, "b": 1},
                      {"a": {"y": 2}, "b": {"z": 3}}) == {
        "a": {"x": 1, "y": 2}, "b": {"z": 3}}
    assert base.merge({"a": 1}, None) == {"a": 1}


def test_system_messages_are_one_text_and_the_turns_stay_apart():
    system, turns = base.split_messages([
        {"role": "system", "content": "First."},
        {"role": "system", "content": [{"type": "text", "text": "Sec"},
                                       {"type": "text", "text": "ond."}]},
        {"role": "system", "content": ""},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "yes"},
                                          {"type": "image_url",
                                           "image_url": {"url": PNG}}]}])
    assert system == "First.\n\nSecond."
    assert turns == [("user", [("text", "hi")]),
                     ("assistant", [("text", "yes"),
                                    ("image", "image/png", "QUJD")])]


@pytest.mark.parametrize("part, said", [
    ({"type": "image_url", "image_url": {"url": "https://example.org/a.png"}},
     "example.org/a.png"),
    ({"type": "image_url", "image_url": {"url": "http://example.org/b.png"}},
     "example.org/b.png"),
    ({"type": "image_url", "image_url": {}}, "data URL"),
    ({"type": "input_audio", "input_audio": {}}, "input_audio"),
])
def test_an_image_that_is_no_data_url_and_an_unknown_part_are_refused(
        part, said):
    with pytest.raises(providers.ProviderError, match="no place|data URL") \
            as refused:
        base.split_messages([{"role": "user", "content": [part]}])
    assert refused.value.status_code == 400 and said in str(refused.value)
    # and nothing is sent for it
    web = _Web()
    with pytest.raises(providers.ProviderError) as asked:
        _gemini(web).chat.completions.create(
            model="m", messages=[{"role": "user", "content": [part]}])
    assert asked.value.status_code == 400 and web.requests == []


def test_a_gemini_400_carries_the_apis_own_words():
    web = _Web(
        _http(400, {"error": {"message": "Invalid JSON payload: unknown"}}),
        urllib.error.HTTPError("u", 400, "x", {},
                               io.BytesIO(b"<html>\nproxy says no")))
    ask = _gemini(web).chat.completions.create
    said = [{"role": "user", "content": "x"}]
    with pytest.raises(providers.ProviderError) as failed:
        ask(model="m", messages=said)
    assert failed.value.status_code == 400
    assert str(failed.value) == "HTTP 400: Invalid JSON payload: unknown"
    with pytest.raises(providers.ProviderError) as proxy:
        ask(model="m", messages=said)
    assert str(proxy.value) == "HTTP 400: <html>"
    assert base.json_error(b'{"error": "plain"}') == "plain"
    assert base.json_error(b"") == ""


# -- where a request goes, and for how long ---------------------------------------

def test_gemini_sends_to_the_address_it_was_given_and_to_google_otherwise():
    answer = {"candidates": [{"content": {"parts": [{"text": "x"}]},
                              "finishReason": "STOP"}], "models": []}
    said = [{"role": "user", "content": "x"}]
    web = _Web(answer, answer)
    _gemini(web, base_url="https://gw.example/v1beta/") \
        .chat.completions.create(model="m", messages=said)
    assert web.requests[0].url == \
        "https://gw.example/v1beta/models/m:generateContent"
    web = _Web(answer, answer)
    client = _gemini(web, base_url="https://gw.example/v1beta/")
    client.models.list()
    assert web.requests[0].url == \
        "https://gw.example/v1beta/models?pageSize=1000"
    web = _Web(answer)
    _gemini(web).chat.completions.create(model="m", messages=said)
    assert web.requests[0].url == f"{gemini_api.BASE_URL}/models/m:generateContent"


def test_hosted_openai_is_built_with_the_address_and_the_time_it_was_given(
        monkeypatch):
    _, _, built = _openai(monkeypatch, base_url="https://gw.example/v1",
                          api_key="k", timeout=44)
    assert built == [{"max_retries": 0, "base_url": "https://gw.example/v1",
                      "api_key": "k", "timeout": 44}]
    _, _, built = _openai(monkeypatch)
    assert built == [{"max_retries": 0}]            # the SDK's own defaults


def test_the_time_a_request_was_given_reaches_the_opener():
    web = _Web({"candidates": [{"content": {"parts": [{"text": "x"}]},
                                "finishReason": "STOP"}]},
               {"candidates": [{"content": {"parts": [{"text": "x"}]},
                                "finishReason": "STOP"}]})
    ask = _gemini(web).chat.completions.create          # the endpoint's is 50
    said = [{"role": "user", "content": "x"}]
    ask(model="m", messages=said, timeout=7)
    ask(model="m", messages=said)
    assert [sent.timeout for sent in web.requests] == [7, 50]


def test_gemini_embeds_a_hundred_texts_to_a_request_and_keeps_their_order():
    texts = [f"t{i}" for i in range(101)]
    assert gemini_api.EMBED_BATCH == 100
    web = _Web(
        {"embeddings": [{"values": [float(i)]} for i in range(100)]},
        {"embeddings": [{"values": [100.0]}]})
    got = _gemini(web).embeddings.create(model="e", input=texts)
    assert [len(sent.body["requests"]) for sent in web.requests] == [100, 1]
    asked = [r["content"]["parts"][0]["text"]
             for sent in web.requests for r in sent.body["requests"]]
    assert asked == texts
    assert [d.embedding for d in got.data] == [[float(i)] for i in range(101)]
    assert [d.index for d in got.data] == list(range(101))
    # one text, given bare, is one text and not its letters
    web = _Web({"embeddings": [{"values": [1.0]}]})
    assert len(_gemini(web).embeddings.create(model="e", input="abc").data) == 1
    assert [r["content"]["parts"][0]["text"]
            for r in web.requests[0].body["requests"]] == ["abc"]


# -- each role has its own provider -----------------------------------------------

SHAPE_OF_A_REPLY = {"type": "object", "properties": {"a": {"type": "string"}}}
JSON_OBJECT = {"type": "json_object"}


@pytest.mark.parametrize("role, other", [("llm", "vlm"), ("vlm", "llm")])
def test_a_role_set_to_a_hosted_provider_is_asked_in_a_schema_and_only_it(
        monkeypatch, role, other):
    monkeypatch.setenv(providers.ROLES[role]["provider"], "gemini")
    inside = {"type": "json_schema",
              "json_schema": {"name": "n", "schema": SHAPE_OF_A_REPLY}}
    assert providers.reply_format(role, "n", SHAPE_OF_A_REPLY,
                                  JSON_OBJECT) == inside
    assert providers.formatted(role, "n", SHAPE_OF_A_REPLY,
                               JSON_OBJECT) == {"response_format": inside}
    # the other role is still a server of one's own: asked as it was before
    assert providers.reply_format(other, "n", SHAPE_OF_A_REPLY,
                                  JSON_OBJECT) == JSON_OBJECT
    assert providers.formatted(other, "n", SHAPE_OF_A_REPLY) == {}
    assert providers.enforces_schema(role)
    assert not providers.enforces_schema(other)


@pytest.mark.parametrize("role", ["llm", "vlm"])
def test_llm_schema_all_reaches_the_server_of_every_role(monkeypatch, role):
    """One setting for every role: it is named after the text model and its
    stages include the one that asks the vision model."""
    assert providers.reply_format(role, "n", SHAPE_OF_A_REPLY,
                                  JSON_OBJECT) == JSON_OBJECT
    monkeypatch.setenv("LLM_SCHEMA", " All ")
    assert providers.enforces_schema(role)
    assert providers.reply_format(role, "n", SHAPE_OF_A_REPLY,
                                  JSON_OBJECT)["type"] == "json_schema"
    monkeypatch.setenv("LLM_SCHEMA", "auto")
    assert not providers.enforces_schema(role)
    # and a hosted role is asked in a schema whatever the setting says
    monkeypatch.setenv(providers.ROLES[role]["provider"], "gemini")
    assert providers.enforces_schema(role)


@pytest.mark.parametrize("role", ["llm", "vlm"])
def test_the_preflight_of_ones_own_server_asks_about_the_role_it_was_given(
        monkeypatch, role):
    seen = []

    def serving(base_url, api_key, timeout=30.0, role="llm"):
        seen.append(("models", role))
        return ["m"], 4096

    def extras(base_url, api_key, model, *, what="x", role="llm"):
        seen.append(("reasoning", role))

    monkeypatch.setattr(llm_preflight, "serving_limits", serving)
    monkeypatch.setattr(llm_preflight, "assert_request_extras", extras)
    assert llm_preflight.assert_serving("u", "k", "m", 100, role=role) == 4096
    assert seen == [("models", role), ("reasoning", role)]


@pytest.mark.parametrize("role", ["llm", "vlm"])
def test_the_models_of_a_role_are_listed_through_that_role(monkeypatch, role):
    roles = []
    client = base.facade(lambda **kw: None, models=lambda: NS(
        data=[NS(id="m", max_model_len=4096)]))
    monkeypatch.setattr(providers, "client",
                        lambda r, **kw: roles.append(r) or client)
    assert llm_preflight.serving_limits("u", "k", role=role) == (["m"], 4096)
    assert roles == [role]


@pytest.mark.parametrize("role", ["llm", "vlm"])
def test_the_preflight_of_a_hosted_role_asks_that_role_and_names_its_options(
        monkeypatch, role):
    monkeypatch.setenv(providers.ROLES[role]["provider"], "gemini")
    roles, outcome = [], []

    def cards():
        return NS(data=[NS(id="m", max_model_len=5000)])

    def create(**kwargs):
        if outcome:
            raise outcome[0]
        return _ok()

    client = base.facade(create, models=cards)
    monkeypatch.setattr(providers, "client",
                        lambda r, **kw: roles.append(r) or client)
    assert llm_preflight.assert_serving("u", "k", "m", 100, role=role) == 5000
    assert roles == [role, role]            # the model list, the schema probe
    # a model that takes no schema is told to change the role's own options
    outcome.append(_Status(400))
    with pytest.raises(llm_preflight.PreflightError) as refused:
        llm_preflight.assert_serving("u", "k", "m", 100, role=role)
    other = "vlm" if role == "llm" else "llm"
    assert providers.ROLES[role]["options"] in str(refused.value)
    assert providers.ROLES[other]["options"] not in str(refused.value)


# ---------------------------------------------------------------------------
# What the cache served
# ---------------------------------------------------------------------------

def _booked(client_reply, monkeypatch, tmp_path):
    """What the ledger holds after the stages' own counter saw this reply."""
    import sqlite3

    from docpipe import usage
    monkeypatch.setenv("DOCPIPE_USAGE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    monkeypatch.setattr(usage.atexit, "register", lambda fn: None)
    usage.begin("extraction")
    usage.reply(client_reply, "m")
    usage.flush()
    with sqlite3.connect(str(tmp_path / "usage.db")) as conn:
        row = conn.execute("SELECT input_tokens, cached_tokens "
                           "FROM token_usage").fetchone()
    conn.close()
    return row


def test_a_cache_hit_the_anthropic_api_reports_reaches_the_ledger(
        anthropic, monkeypatch, tmp_path):
    anthropic.answers.append(_message('{"markdown": "m"}',
                                      cache_read_input_tokens=80,
                                      cache_creation_input_tokens=7))
    reply = _claude(anthropic).chat.completions.create(
        model="claude-haiku-4-5", max_tokens=10, temperature=0,
        messages=[{"role": "user", "content": "x"}])
    # the cached tokens are a part of the input, which counts all three kinds
    assert (reply.usage.prompt_tokens, reply.usage.cached_tokens) == (97, 80)
    assert _booked(reply, monkeypatch, tmp_path) == (97, 80)


def test_a_cache_hit_the_gemini_api_reports_reaches_the_ledger(
        monkeypatch, tmp_path):
    web = _Web({"candidates": [{"content": {"parts": [{"text": "{}"}]},
                                "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 90,
                                  "candidatesTokenCount": 7,
                                  "cachedContentTokenCount": 64}})
    reply = _gemini(web).chat.completions.create(
        model="g", max_tokens=10, messages=[{"role": "user", "content": "x"}])
    assert reply.usage.cached_tokens == 64
    assert _booked(reply, monkeypatch, tmp_path) == (90, 64)


def test_a_cache_hit_the_openai_api_reports_reaches_the_ledger(
        monkeypatch, tmp_path):
    answer = _completion("{}")
    answer.usage.prompt_tokens_details = NS(cached_tokens=8)
    client, _sent, _built = _openai(monkeypatch, answer)
    reply = client.chat.completions.create(
        model="gpt-x", max_tokens=10, messages=[{"role": "user",
                                                 "content": "x"}])
    assert reply.usage.cached_tokens == 8
    assert _booked(reply, monkeypatch, tmp_path) == (11, 8)


def test_an_api_that_says_nothing_of_a_cache_has_none_booked(
        anthropic, monkeypatch, tmp_path):
    """The violating case: no cache fields, or a null where the count would
    be. Nothing is invented, and the input is still counted."""
    anthropic.answers.append(_message('{"markdown": "m"}'))
    reply = _claude(anthropic).chat.completions.create(
        model="claude-haiku-4-5", max_tokens=10, temperature=0,
        messages=[{"role": "user", "content": "x"}])
    assert _booked(reply, monkeypatch, tmp_path) == (10, 0)
    answer = _completion("{}")
    answer.usage.prompt_tokens_details = NS(cached_tokens=None)
    client, _sent, _built = _openai(monkeypatch, answer)
    reply = client.chat.completions.create(
        model="gpt-x", max_tokens=10, messages=[{"role": "user",
                                                 "content": "x"}])
    assert not hasattr(reply.usage, "cached_tokens")
