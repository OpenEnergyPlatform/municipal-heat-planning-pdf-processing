"""Every request that goes out with a grammar has its reply written in the
order its prompt's example names the keys: for any two keys of one object
in the example, the schema lists the first before the second, unless they
belong to two different coordinates or entries, whose order the spec or the
passage decides; AND every key of the example is a key the schema allows. A
server that holds a reply to its schema writes the keys in the schema's
order, so an optional key listed before one already written can no longer
come (owner decision 2026-11-04: the schema follows the prompt), and a key
the schema does not allow can never come.

Checked for every prompt of both profiles whose reply goes out with a
grammar, each beside a case that breaks it by construction."""
import json
import re
from pathlib import Path

import pytest

from docpipe.extraction import (combing, fields, places, reading, replies,
                                runner, survey)
from docpipe.extraction.spec import load as load_spec

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ("kwp", "scenarios")
# A key that names an entry of the passage: a passage, a row, a number.
LABEL = re.compile(r"[A-Z]\d+")
# What a coordinate's own keys end in besides its name.
SUFFIXES = ("raw", "quote", "source")


def spec_of(profile):
    return load_spec(json.loads((ROOT / "profiles" / profile
                                 / "extraction_spec.json")
                                .read_text(encoding="utf-8")))


def all_slots(spec) -> dict:
    """{name: slot} of every coordinate the profile asks, frame included."""
    out: dict = {}
    for parameter in spec.parameters:
        for slot in reading.slots_of(spec, parameter):
            out.setdefault(slot.name, slot)
    for group in survey.tuple_slots(spec).values():
        for slot in group:
            out.setdefault(slot.name, slot)
    return out


def unwrapped(shape: dict) -> dict:
    return shape["json_schema"]["schema"] if "json_schema" in shape else shape


def schemas(spec) -> dict:
    """{prompt name: (the schema its reply goes out with, given the example)}
    for every request of the extraction stage that sends a grammar."""
    slots = all_slots(spec)
    listed = list(slots.values())
    parameter = max(spec.parameters,
                    key=lambda p: len(reading.slots_of(spec, p)))
    value = fields.value_slot(parameter)

    def field(example):
        (name,) = example["fields"]
        return runner.field_response_format(slots[name])

    return {
        "survey": lambda example: survey.response_format(
            [None] * 9, survey.parameters_of(spec), survey.tuple_slots(spec)),
        "read_cells": lambda example: reading.cells_response_format(),
        "read_table": lambda example: reading.table_response_format(listed),
        "read_values": lambda example: reading.values_response_format(
            parameter),
        "read_text": lambda example: reading.text_response_format(
            listed, ["R1", "R2"]),
        "comb": lambda example: combing.comb_response_format(
            listed, ["R1", "R2"]),
        "places": lambda example: places.response_format(
            [None] * 9, {name: "" for name in slots},
            {p.uri: "" for p in spec.parameters}),
        "field": field,
        "compute": lambda example: replies.compute(["N1", "N2", "N3"]),
        "rows": lambda example: replies.rows(sandbox=True),
        "review": lambda example: replies.review([value, *listed]),
        "anchors": lambda example: replies.anchors(),
        "phrase": lambda example: replies.phrase(),
    }


def unquoted_placeholders_as_numbers(line: str) -> str:
    """An example line with each <...> that stands outside a string, the
    prompt's description of a number, written as 0."""
    out, inside, i = [], False, 0
    while i < len(line):
        char = line[i]
        if char == '"' and (i == 0 or line[i - 1] != "\\"):
            inside = not inside
        if char == "<" and not inside:
            end = line.index(">", i)
            out.append("0")
            i = end + 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def examples(profile: str, name: str) -> list:
    """The JSON examples of a prompt: its lines that are one object."""
    text = (ROOT / "profiles" / profile / "prompts" / "extraction"
            / f"{name}.md").read_text(encoding="utf-8")
    body = text.split("---", 2)[2] if text.startswith("---") else text
    return [json.loads(unquoted_placeholders_as_numbers(line))
            for line in body.splitlines() if line.startswith("{")]


def branch(schema: dict, example: dict) -> dict:
    """The object schema of *schema* that fits the example's keys best."""
    choices = schema.get("anyOf") or schema.get("oneOf")
    if not choices:
        return schema
    return max(choices, key=lambda s: len(set(example)
                                          & set(s.get("properties") or {})))


def group_of(key: str, slots: set):
    """The coordinate or entry a key belongs to, or None for a key of its
    own: a coordinate's name with its wording, quote and source, a label."""
    if key in slots or LABEL.fullmatch(key):
        return key
    for suffix in SUFFIXES:
        if key.endswith("_" + suffix) and key[:-len(suffix) - 1] in slots:
            return key[:-len(suffix) - 1]
    return None


def disorder(example, schema: dict, slots: set = frozenset(),
             path: str = "$") -> list:
    """[(path, what)] of each place where *example* names keys in another
    order than *schema*, or a key *schema* does not allow."""
    out: list = []
    if isinstance(example, list):
        items = schema.get("items")
        for entry in example:
            if isinstance(items, dict):
                out += disorder(entry, items, slots, path + "[]")
        return out
    if not isinstance(example, dict):
        return out
    schema = branch(schema, example)
    properties = schema.get("properties") or {}
    extra = schema.get("additionalProperties")
    order = list(properties)
    keys = list(example)
    for i, first in enumerate(keys):
        for second in keys[i + 1:]:
            if first not in properties or second not in properties:
                continue
            a, b = group_of(first, slots), group_of(second, slots)
            if a is not None and b is not None and a != b:
                continue        # two coordinates: their order is the spec's
            if order.index(first) > order.index(second):
                out.append((path, f"{first} before {second}"))
    for key, value in example.items():
        if key in properties:
            out += disorder(value, properties[key], slots, f"{path}.{key}")
        elif isinstance(extra, dict):
            out += disorder(value, extra, slots, f"{path}.{key}")
        elif extra is False or properties:
            out.append((path, f"{key} not in the schema"))
    return out


CASES = [(profile, name) for profile in PROFILES
         for name in schemas(spec_of(profile))
         if (ROOT / "profiles" / profile / "prompts" / "extraction"
             / f"{name}.md").is_file()]


@pytest.mark.parametrize("profile,name", CASES)
def test_a_reply_is_written_in_the_order_its_prompt_names_the_keys(profile,
                                                                    name):
    spec = spec_of(profile)
    slots = set(all_slots(spec))
    shown = examples(profile, name)
    assert shown, f"{profile}/{name}: no example to hold the schema to"
    for example in shown:
        schema = unwrapped(schemas(spec)[name](example))
        assert disorder(example, schema, slots) == [], (profile, name)


def test_every_prompt_of_the_new_flow_is_held_to_its_schema():
    names = {prompt_id.split("/")[-1] for prompt_id in runner.SURVEY_PROMPT_IDS}
    for profile in PROFILES:
        assert names <= {name for p, name in CASES if p == profile}, profile


CELL = {"row": 2, "column": 2, "parts": 2, "part": 1}


def test_a_key_listed_after_one_the_example_names_later_is_found():
    cells = unwrapped(reading.cells_response_format())
    value = cells["properties"]["values"]["items"]
    assert disorder({"values": [CELL]}, cells) == []
    swapped = dict(value, properties={key: value["properties"][key] for key
                                      in ("row", "column", "part", "parts")})
    broken = dict(cells, properties=dict(cells["properties"],
                                         values={"type": "array",
                                                 "items": swapped}))
    assert disorder({"values": [CELL]}, broken) == [
        ("$.values[]", "parts before part")]


def test_a_coordinate_s_own_keys_keep_their_order_and_two_coordinates_any():
    schema = {"type": "object", "properties": {
        "unit": {}, "unit_raw": {}, "unit_quote": {},
        "carrier": {}, "carrier_raw": {}, "carrier_quote": {}}}
    slots = {"unit", "carrier"}
    assert disorder({"carrier": "Erdgas", "unit": "MWh"}, schema, slots) == []
    assert disorder({"carrier_quote": "q", "carrier_raw": "r"}, schema,
                    slots) == [("$", "carrier_quote before carrier_raw")]


def test_a_key_the_schema_does_not_allow_is_found():
    schema = {"type": "object", "properties": {"value": {}},
              "additionalProperties": False}
    assert disorder({"value": 1, "head": "x"}, schema) == [
        ("$", "head not in the schema")]
    labelled = {"type": "object", "additionalProperties": {
        "type": "object", "properties": {"value": {}}}}
    assert disorder({"R4": {"value": 1}}, labelled) == []


def test_a_placeholder_for_a_number_reads_as_a_number_and_text_stays():
    assert json.loads(unquoted_placeholders_as_numbers(
        '{"value": <die Zahl>, "quote": "<<Satz>>"}')) == {
            "value": 0, "quote": "<<Satz>>"}
