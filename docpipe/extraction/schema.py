"""
schema.py – A JSON Schema for the harvest, the stamp and the trace.

The harvest is the durable artifact. The graph is a function of it, and every
later question — what does this key mean, which OEO predicate does it become,
may it be null, what is the closed list — was answered until now by reading
`runner.py`. That is not an answer anyone outside this repository can use, and
it is not one this repository can check.

So the schema is GENERATED from the spec, not written beside it. The parameters,
their axes, the closed lists, the questions and the `kg` blocks all come from
`profiles/<name>/extraction_spec.json`, which means a spec change that is not
reflected in the schema is a failing test rather than a stale document. Three
schemas come out:

  harvest  one line of <name>.jsonl: an accepted tuple or a refused claim
  stamp    <name>.stamp.json, what produced that harvest
  trace    one line of <name>.trace.jsonl, one event of the run

Every property carries a `description`, and every coordinate additionally
carries `x-question` (the German question the model was asked), `x-options`
(the closed list with the corpus spellings) and `x-kg` (what it becomes in the
graph). `x-kg` is the spec's own `kg` block, the same one the serializer reads,
so what a reader is told and what is written cannot drift apart.

    python -m docpipe.extraction.schema kwp            # print
    python -m docpipe.extraction.schema kwp --write    # write into the profile

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from . import fields
from .spec import load as load_spec
from .trust import FLAG_REASONS, LEVEL_A, LEVEL_B, LEVEL_C
from .verify import MIN_QUOTE_CHARS, TIER_TEXT, TIER_VISUAL

SCHEMA_NAME = "extraction_schema.json"
BASE_ID = "https://openenergyplatform.org/schema/mhpkg/extraction"

# The levels and the reason families of trust.py, so the published schema and
# the code that fills it cannot drift: a level the schema does not list is a
# level nobody downstream can act on.
TRUST_LEVELS = (LEVEL_A, LEVEL_B, LEVEL_C)

TRUST_LEVEL_DOC = {
    LEVEL_A: "read off its own passage, in the document's own text",
    LEVEL_B: "the same, but out of an image transcription or a page a model "
             "transcribed",
    LEVEL_C: "something is off; see reasons",
}

# Anchored, so "nonlocal" alone or a reason nobody named cannot slip in.
TRUST_REASONS = tuple(
    [f"^{r}$" for r in sorted(FLAG_REASONS.values())]
    + ["^conflict$", "^page_transcribed$", "^review:disagree$",
       r"^(nonlocal|exhausted|unbacked):[a-z_]+$"])

# What a coordinate's state can be, and what each one is a finding ABOUT. The
# distinction is the whole point of carrying seven of them instead of a null:
# "the plan does not say it" and "we stopped looking" are different facts.
STATE_DOC = {
    fields.READ: "answered, and the cited passage carries the answer",
    fields.DERIVED: ("not asked: the spec decides this coordinate from "
                     "something already on the row (the unit)"),
    fields.SAID_UNSTATED: ("answered: the passages shown do not state it. A "
                           "finding about the document, and only final once "
                           "the sweep ran out of it"),
    fields.UNANSWERED: ("the field reply never mentioned this row. A finding "
                        "about the model"),
    fields.EXHAUSTED: ("still open when the window budget ended with the "
                       "document unread. A finding about the run"),
    fields.UNBACKED: ("answered, but no shown passage carried the answer, or "
                      "the passage belonged to another row, and no later "
                      "window fixed it"),
    fields.OUT_OF_SLICE: ("never asked: a gate coordinate (the profile's "
                          "SLICE) had already put the row outside what this "
                          "run serializes"),
}
STATES = list(STATE_DOC)

# Non-fatal findings of the verifier, as patterns rather than a list: the
# wording half of each is the document's and cannot be enumerated.
FLAG_PATTERN = (
    r"^(mapped:[a-z_]+:[\s\S]*->[\s\S]*|unmapped:[a-z_]+:[\s\S]*"
    r"|unit_not_chosen:[\s\S]*|unit_spelling:[\s\S]*"
    r"|period:(annual_in_quote|unstated)"
    r"|quote_repaired|computed|not_located)$")

# The eleven families a refusal reason belongs to. Every one is raised in
# verify.py or pipeline.py and none is composed at runtime from user text.
REFUSAL_REASONS = [
    r"^claim names no parameter of the spec$",
    r"^claim names no source$",
    r"^tuple is not an object$",
    r"^value is not a number$",
    r"^unit .* not in units_accepted \(.*\)$",
    r"^a (text|category) parameter needs a non-empty string value$",
    r"^required axis '.*' (missing|is empty)$",
    r"^axis '.*': .* (not in vocabulary and axis is required"
    r"|is not an integer|not in enum .*)$",
    r"^quote missing or too short to identify anything$",
    r"^quote not found in the source it cites$",
    r"^value .* does not occur in the quote$",
    r"^text value not in its quote$",
]

# Why a coordinate reading was dropped. Each is written by merge_field and
# each is a different repair, so they are enumerated rather than free text.
DROP_REASONS = ["quote_not_in_source", "quote_not_local", "quote_too_short",
                "answer_not_in_quote", "unbacked"]


def _owner() -> dict:
    return {"type": "array", "description": "[owner_kind, owner_id]",
            "prefixItems": [{"enum": ["section", "table", "figure"]},
                            {"type": "integer"}],
            "minItems": 2, "maxItems": 2}


def _slot_value(slot, doc: str) -> dict:
    """The property for the coordinate itself."""
    if slot.options:
        value = {"type": ["string", "null"],
                 "enum": [o.uri for o in slot.options] + [None],
                 "description": doc}
        value["x-options"] = {
            o.label: {k: v for k, v in
                      (("uri", o.uri), ("meaning", o.definition),
                       ("spellings", list(o.synonyms))) if v}
            for o in slot.options}
    elif slot.kind == fields.NUMBER:
        value = {"type": ["integer", "null"], "description": doc}
    else:
        value = {"type": ["string", "null"], "description": doc}
    if slot.question:
        value["x-question"] = slot.question
    return value


def _value_uri(parameter) -> dict:
    """What a wording resolved to, and — for a closed list — the list itself.

    An axis has published its options since the schema existed. A category
    PARAMETER answers from a list in exactly the same way and published none:
    the key said "the entry of the parameter's own vocabulary" and the schema
    never showed what that vocabulary is. Unseen until now because kwp has no
    category parameter at all -- the gap only exists where the profile does.

    Three cases and they read differently on purpose. A text parameter has no
    list at all and never writes the key; a dynamic list exists but is the
    profile's to supply per document, so there is nothing static to publish;
    a closed list is published, meanings and all.
    """
    doc = ("The entry of the parameter's own vocabulary the wording resolved "
           "to; null when the list did not hold it. ")
    if parameter.value_type != "category":
        return {"type": ["string", "null"],
                "description": doc + "Only a category parameter has a "
                                     "vocabulary, so this one never writes "
                                     "the key at all."}
    if parameter.vocabulary_dynamic:
        return {"type": ["string", "null"],
                "description": doc + "The list is per document: the profile "
                                     "supplies it before the harvest, so it "
                                     "is not in this schema."}
    slot = fields.value_slot(parameter)
    out = _slot_value(slot, doc + "The list is closed; an entry beginning "
                                  "'out:' is a deliberate non-class answer "
                                  "and mints no node.")
    # `_slot_value` puts the slot's question on the value it types. Here it
    # would be the parameter's own description, which `parameter` already
    # publishes as x-description-source -- two copies, one of them under a
    # name that says it is a question.
    out.pop("x-question", None)
    return out


def _slot_properties(name: str, slot, doc: str) -> dict:
    """Every key one coordinate writes.

    Seven, not one. The value is what the graph takes; the rest is what makes
    the value re-checkable without the run that produced it — which state it
    ended in, the document's own wording, the passage, the source that passage
    came from and the window it was found in.
    """
    return {
        name: _slot_value(slot, doc),
        f"{name}_state": {
            "$ref": "#/$defs/state",
            "description": f"How the coordinate '{name}' ended. Always "
                           f"present: a missing key and a refused reading "
                           f"must not look alike."},
        f"{name}_raw": {
            "type": "string",
            "description": f"The document's own wording '{name}' was read "
                           f"from. This is what a later re-mapping onto a "
                           f"changed vocabulary works on, so a choice "
                           f"without it is counted (raw_missing)."},
        f"{name}_raw_foreign": {
            "type": "boolean",
            "description": f"The wording does not name the option chosen for "
                           f"'{name}' -- the model mapped a word the spec "
                           f"does not list onto this class. Kept and counted, "
                           f"not refused: some of those mappings are right."},
        f"{name}_quote": {
            "type": "string", "minLength": MIN_QUOTE_CHARS,
            "description": f"The verbatim passage carrying '{name}'. Present "
                           f"exactly when {name}_state is 'read'."},
        f"{name}_source": {
            **_owner(),
            "description": f"Which source the passage for '{name}' was found "
                           f"in. How far that may be from the row is the "
                           f"axis' own rule (own | local | any)."},
        f"{name}_window": {
            "type": "array",
            "prefixItems": [{"enum": ["own", "retrieval", "rest"]},
                            {"type": "integer"}],
            "minItems": 2, "maxItems": 2,
            "description": f"[stage, index] of the window '{name}' was read "
                           f"in. A coordinate read in window 1 and one read "
                           f"in window 22 cost different amounts."},
        f"{name}_seen": {
            "type": "string",
            "description": f"A wording the model noticed for '{name}' while "
                           f"answering 'not stated'. Vocabulary review "
                           f"material, never evidence."},
    }


def _slot_rules(name: str, slot) -> dict:
    """read means a value and a passage; anything else means null."""
    if slot.options:
        non_null: dict = {"type": "string"}
    elif slot.kind == fields.NUMBER:
        non_null = {"type": "integer"}
    else:
        non_null = {"type": "string"}
    return {
        "if": {"properties": {f"{name}_state": {"enum": [fields.READ,
                                                         fields.DERIVED]}},
               "required": [f"{name}_state"]},
        "then": {"properties": {name: non_null}, "required": [name]},
        "else": {"properties": {name: {"type": "null"}}},
    }


def _tuple_schema(spec, parameter) -> dict:
    props: dict = {
        "kind": {"const": "tuple"},
        "quote": {"type": "string", "minLength": MIN_QUOTE_CHARS,
                  "description": "The passage of the owner source that "
                                 "contains the value. Whitespace-collapsed "
                                 "containment; a retyped table row may be "
                                 "repaired, which sets the flag "
                                 "quote_repaired."},
        "tier": {"enum": [TIER_TEXT, TIER_VISUAL],
                 "description": "text_located: the quote sits in the "
                                "document's own refined text, so it can be "
                                "checked against the PDF. visual_source: it "
                                "sits in a table transcription, a caption or "
                                "a figure description, which are model "
                                "output and want human curation."},
        "flags": {"type": "array",
                  "items": {"type": "string", "pattern": FLAG_PATTERN},
                  "description": "Non-fatal verifier findings. "
                                 "mapped:<axis>:<wording>-><uri> is the model "
                                 "mapping a word the spec does not list; "
                                 "period:* says whether a bare amount was "
                                 "shown to be a yearly one."},
        "provenance": {"$ref": "#/$defs/provenance"},
        "computed": {"type": "boolean",
                     "description": "The value came out of the sandbox, not "
                                    "off the page; the quote proves the "
                                    "inputs it was computed from."},
        "compute": {"type": "array", "items": {"type": "object"},
                    "description": "The sandbox runs behind a computed "
                                   "value: {code, stdout, ok, error}."},
    }
    required = ["kind", "parameter", "parameter_state", "quote", "tier",
                "provenance", "value"]
    if parameter.is_numeric:
        units = ", ".join(sorted(parameter.units_accepted))
        props["value"] = {
            "type": "number",
            "description": "The number as the document prints it, with the "
                           "grouping removed and a decimal point."}
        props["unit"] = {
            "type": "string",
            "description": f"The unit, chosen from units_accepted ({units}). "
                           f"A spelling the list does not hold is accepted "
                           f"with the flag unit_spelling."}
        props["unit_raw"] = {
            "type": "string",
            "description": "The unit exactly as the source writes it. This "
                           "is evidence and is never looked up."}
        props["value_target"] = {
            "type": "number",
            "description": f"value x factor(unit), in the spec's unit_target "
                           f"{parameter.unit_target}. This is the number the "
                           f"graph carries."}
        required += ["unit", "unit_raw", "value_target"]
    else:
        props["value"] = {
            "type": "string", "minLength": 1,
            "description": "The wording as the document writes it."}
        props["value_raw"] = {
            "type": "string",
            "description": "The wording before any tidying (an "
                           "organisation's legal form, a title's line "
                           "break)."}
        props["value_uri"] = _value_uri(parameter)
        props["unit"] = {"type": "string", "maxLength": 0,
                         "description": "Empty: a wording has no unit. The "
                                        "key is present so every row has the "
                                        "same shape."}
        props["unit_raw"] = {"type": "string", "maxLength": 0,
                             "description": "Empty, as unit."}

    rules: list = []
    parameter_slot = fields.parameter_slot(spec)
    props.update(_slot_properties(
        "parameter", parameter_slot,
        "Which parameter of the spec this number is. The unit decides it "
        "wherever the accepted unit lists are disjoint, and then the state "
        "is 'derived' rather than 'read'."))
    props["parameter"] = {
        "const": parameter.uri,
        "description": f"Spec parameter: {parameter.label}.",
        "x-description-source": parameter.description,
        "x-question": parameter_slot.question}
    for slot in fields.axis_slots(parameter):
        closed = ("A closed list; an entry beginning 'out:' is a deliberate "
                  "non-class answer and mints no node. " if slot.options
                  else "")
        props.update(_slot_properties(
            slot.name, slot,
            f"Axis '{slot.name}' of {parameter.label}. {closed}"
            f"null unless {slot.name}_state is 'read' or 'derived'."))
        axis = parameter.axes.get(slot.name)
        if axis is not None and axis.kg:
            props[slot.name]["x-kg"] = axis.kg
        required += [slot.name, f"{slot.name}_state"]
        rules.append(_slot_rules(slot.name, slot))

    out = {"type": "object", "properties": props, "required": required,
           "additionalProperties": False}
    if parameter.kg:
        out["x-kg"] = parameter.kg
    if rules:
        out["allOf"] = rules
    return out


def harvest_schema(spec) -> dict:
    """One line of <name>.jsonl."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}/harvest-line",
        "title": "docpipe extraction harvest line (one JSON object per line)",
        "description": "An accepted tuple (kind=tuple), a refused claim "
                       "(kind=refusal), or the document's own summary "
                       "(kind=summary, the last line of the file). Generated "
                       "from the profile's extraction_spec.json by "
                       "docpipe/extraction/schema.py.",
        "oneOf": [{"$ref": f"#/$defs/tuple_{p.uri}"} for p in spec.parameters]
                 + [{"$ref": "#/$defs/refusal"},
                    {"$ref": "#/$defs/summary"}],
        "$defs": {
            "state": {"enum": STATES, "x-doc": STATE_DOC},
            "provenance": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "integer",
                        "description": "Documents.id. What the serializer "
                                       "joins from the database to mint the "
                                       "document's IRI is not carried here: "
                                       "which columns those are is the "
                                       "profile's business, not the row's."},
                    "page": {"type": ["integer", "null"],
                             "description": "1-based PDF page of the owner."},
                    "section_number": {"type": ["integer", "null"]},
                    "section_title": {"type": ["string", "null"]},
                    "title": {
                        "type": ["string", "null"],
                        "description": "The section title, or a table's or "
                                       "figure's caption -- resolved to the "
                                       "sentence before its placeholder "
                                       "where the stored caption is a "
                                       "footnote."},
                    "parent_section": {
                        "type": ["integer", "null"],
                        "description": "Sections.id of the section a table "
                                       "or figure stands in."},
                    "block_id": {"type": ["string", "null"],
                                 "description": "Placeholder of the item in "
                                                "that section, e.g. "
                                                "p85_tbl0."},
                    "owner_kind": {"enum": ["section", "table", "figure"]},
                    "owner_id": {"type": "integer",
                                 "description": "Sections.id, Tables.id or "
                                                "Images.id."},
                    "image": {"type": "string",
                              "description": "Crop path relative to the "
                                             "image root."},
                    "rects": {"type": "array",
                              "description": "Highlight boxes on the page, "
                                             "when the passage could be "
                                             "located."},
                    "via": {"type": "string",
                            "description": "How this source reached the "
                                           "window: a retrieval probe, or "
                                           "'parent' for the section a table "
                                           "stands in."},
                },
                "required": ["document_id", "owner_kind", "owner_id"],
                "additionalProperties": False,
            },
            "refusal": {
                "type": "object",
                "properties": {
                    "kind": {"const": "refusal"},
                    "parameter": {
                        "type": ["string", "null"],
                        "description": "The spec parameter, or whatever the "
                                       "claim named."},
                    "reason": {
                        "type": "string",
                        "anyOf": [{"pattern": p} for p in REFUSAL_REASONS],
                        "description": "Why the claim was refused; one of "
                                       "the reason families of verify.py and "
                                       "pipeline.py."},
                    "claim": {
                        "type": "object",
                        "description": "The claim as the model returned it. "
                                       "A dead-server sentinel carries "
                                       "_harvest_failed with _why, or "
                                       "_cut_off.",
                        "properties": {
                            "_harvest_failed": {"const": True},
                            "_why": {"enum": ["unreachable", "no_answer"]},
                            "_cut_off": {"const": True}}},
                    "owner": _owner(),
                },
                "required": ["kind", "parameter", "reason", "claim", "owner"],
                "additionalProperties": False,
            },
            "summary": {
                "type": "object",
                "description": "The last line of the file: how this "
                               "document's own values are distributed. A "
                               "contested identity is decided by the "
                               "serializer and a second reading is a later "
                               "pass, so neither is counted here -- the "
                               "levels are a floor, and the graph side "
                               "recomputes them.",
                "properties": {
                    "kind": {"const": "summary"},
                    "document_id": {"type": "integer"},
                    "tuples": {"type": "integer"},
                    "refusals": {"type": "integer"},
                    "levels": {
                        "type": "object",
                        "description": "How many values reached each level.",
                        "properties": {level: {"type": "integer"}
                                       for level in TRUST_LEVELS},
                        "required": list(TRUST_LEVELS),
                        "additionalProperties": False,
                        "x-doc": TRUST_LEVEL_DOC},
                    "reasons": {
                        "type": "object",
                        "description": "Why values are not an A, counted. "
                                       "A closed list: a reason nobody can "
                                       "enumerate is a reason nobody can "
                                       "count.",
                        "propertyNames": {
                            "anyOf": [{"pattern": p} for p in TRUST_REASONS]},
                        "additionalProperties": {"type": "integer"}},
                    "image_origin": {
                        "type": "integer",
                        "description": "Values read out of a table or figure "
                                       "image rather than the document's text."},
                },
                "required": ["kind", "document_id", "tuples", "refusals",
                             "levels", "reasons", "image_origin"],
                "additionalProperties": False,
            },
            **{f"tuple_{p.uri}": _tuple_schema(spec, p)
               for p in spec.parameters},
        },
    }


def stamp_schema() -> dict:
    """<name>.stamp.json — what produced the harvest beside it."""
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}/stamp",
        "title": "docpipe extraction resume stamp",
        "description": "A key that differs from the current run makes the "
                       "document stale and it is harvested again -- every "
                       "key but `spec`, which is recorded so a reader can "
                       "say which file a harvest came from and is not "
                       "compared. Withheld when the harvest did not happen. "
                       "The parameter/, value/, axis/ and slot/ keys say "
                       "WHICH question changed, so a moving ontology costs "
                       "the coordinates it touched rather than a full "
                       "re-read of the corpus; a stamp written before they "
                       "existed carries none of them, and for it `spec` "
                       "decides again, so it is stale in all of them.",
        "type": "object",
        "properties": {
            "spec": {**sha,
                     "description": "sha256 of extraction_spec.json. A "
                                    "record, not a verdict: it moves on a "
                                    "comment, an indent or a graph "
                                    "annotation, none of which any question "
                                    "is asked through. Compared, it would "
                                    "outvote every key below it."},
            "model": {"type": "string", "description": "the serving model"},
            "anchors": {"type": "string", "pattern": "^([0-9a-f]{16})?$",
                        "description": "The anchor prompt, the model, the "
                                       "version of the target set and the "
                                       "profile's frozen anchor file, "
                                       "together. NOT the questions: which "
                                       "question was asked is carried by the "
                                       "parameter/, value/, axis/ and slot/ "
                                       "keys, and a question that is GONE by "
                                       "the rule that a key the stamp still "
                                       "carries and the run no longer asks "
                                       "makes the document stale. The "
                                       "anchors decide which passages a "
                                       "document was read from, so a "
                                       "document read under one set is not "
                                       "the same result as one read under "
                                       "another. Empty when anchors were "
                                       "off."},
            "page_text_transcribed": {
                "type": ["integer", "null"],
                "description": "How many pages of this document a model read "
                               "rather than the PDF. A harvest from a "
                               "transcribed document is a reading of a reading."},
        },
        "patternProperties": {
            "^extraction/(harvest|queries|anchors|rows|field)$":
                {**sha, "description": "sha256 of the prompt file"},
            "^parameter/[^/]+$": {
                **sha,
                "description": "What this parameter asks, without its axes "
                               "and without its own list: label, description, "
                               "value type, accepted units and the example. A "
                               "new option on ONE axis, or in the list the "
                               "parameter answers from, must not make every "
                               "value of the parameter stale -- those have "
                               "keys of their own."},
            "^value/[^/]+$": {
                **sha,
                "description": "The list a category parameter answers from. "
                               "Its own key, because a moved option can be "
                               "re-mapped from the wording the harvest kept "
                               "while a rewritten question cannot."},
            "^slot/parameter$": {
                **sha,
                "description": "The one coordinate that belongs to no "
                               "parameter: which quantity a number is. Its "
                               "question and the parameters it offers, uri "
                               "and label. Also the only key that moves when "
                               "a parameter is dropped."},
            "^axis/[^/]+/[^/]+$": {
                **sha,
                "description": "What this coordinate asks and what it may "
                               "answer: the question, the evidence rule, and "
                               "the offered list with its spellings and its "
                               "definitions. Everything the model sees for "
                               "this axis, and nothing else."}},
        "required": ["spec", "model", "anchors", "extraction/harvest",
                     "extraction/queries", "extraction/anchors",
                     "extraction/rows", "extraction/field"],
        "additionalProperties": False,
    }


def trace_schema() -> dict:
    """One line of <name>.trace.jsonl — one event, never an aggregate."""
    owner = _owner()
    counts = {k: {"type": "integer"} for k in
              ("filled", "unquoted", "unbacked", "unstated", "raw_missing",
               "raw_foreign")}
    by_field = {"type": "object", "additionalProperties": {"type": "integer"}}
    kinds = {
        "plan": {"rank": {"type": ["integer", "null"]},
                 "origin": {"enum": ["structure", "retrieval"]},
                 "kind": {"enum": ["section", "table", "figure"]},
                 "owner": {"type": "integer"}, "chars": {"type": "integer"},
                 "image": {"type": "boolean"}},
        "rows": {"prompt": {"type": "string"}, "attempt": {"type": "integer"},
                 "rows": {"type": "integer"},
                 "status": {"type": ["string", "null"]},
                 "sources": {"type": "array", "items": owner},
                 "ranks": {"type": "array"}, "origins": {"type": "array"},
                 "prompt_tokens": {"type": ["integer", "null"]},
                 "completion_tokens": {"type": ["integer", "null"]},
                 "ms": {"type": "integer"}},
        "field": {"slot": {"type": "string"}, "anchor": {"type": "string"},
                  "window": {"type": "integer"},
                  "stage": {"enum": ["own", "retrieval", "rest"]},
                  "attempt": {"type": "integer"},
                  "parameter": {"type": ["string", "null"]},
                  "open": {"type": "integer"}, "reply": {"type": "boolean"},
                  "shown": {"type": "array", "items": owner},
                  "filled_by": by_field, "unbacked_by": by_field,
                  "prompt_tokens": {"type": ["integer", "null"]},
                  "completion_tokens": {"type": ["integer", "null"]},
                  "ms": {"type": "integer"}, **counts},
        "sweep": {"slot": {"type": "string"}, "anchor": {"type": "string"},
                  "windows": {"type": "integer"}, "rows": {"type": "integer"},
                  "combed": {"type": "boolean"},
                  "retried": {"type": "integer"}, "asked": {"type": "integer"},
                  "exhausted": {"type": "integer"}, **counts},
        "drop": {"slot": {"type": "string"},
                 "field": {"type": ["string", "null"]},
                 "window": {"type": "integer"},
                 "attempt": {"type": "integer"},
                 "row": {"type": "string", "pattern": "^R[0-9]+$"},
                 "why": {"enum": DROP_REASONS}},
        "error": {"where": {"type": "string"},
                  "kind": {"enum": ["unparsable", "exception", "gave_up"]},
                  "slot": {"type": ["string", "null"]},
                  "attempt": {"type": "integer"},
                  "finish": {"type": ["string", "null"]},
                  "status": {"type": ["integer", "string", "null"]},
                  "detail": {"type": "string"},
                  "why": {"enum": ["unreachable", "no_answer"]},
                  "sources": {"type": "array", "items": owner},
                  "ms": {"type": "integer"}},
        "coord": {"parameter": {"type": ["string", "null"]}, "value": {},
                  "unit": {"type": ["string", "null"]},
                  "tier": {"enum": [TIER_TEXT, TIER_VISUAL]},
                  "kind": {"enum": ["section", "table", "figure"]},
                  "owner": {"type": "integer"},
                  "states": {"type": "object",
                             "additionalProperties": {"enum": STATES}}},
        "refusal": {"parameter": {"type": ["string", "null"]},
                    "reason": {"type": "string"}, "owner": owner},
        # A row this very schema refuses. Written, not blocked: the harvest
        # is the durable artifact and an unrecognised row is still evidence,
        # but the schema is what everyone downstream reads instead of the
        # file, so a row it does not describe must not pass unnoticed.
        "invalid": {"kind": {"enum": ["tuple", "refusal"]},
                    "where": {"type": "string"},
                    "why": {"type": "string"},
                    "detail": {"type": "string"}},
    }
    # Optional on every event: what the run could not always know. Requiring
    # them would refuse a legitimate record from a request that never reached
    # the server.
    loose = {"detail", "status", "finish", "why", "sources", "ms", "slot",
             "prompt_tokens", "completion_tokens", "filled_by", "unbacked_by",
             "field", "raw_missing", "raw_foreign"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}/trace-record",
        "title": "docpipe extraction trace record",
        "description": "One event per line; `t` names it and `doc` the "
                       "document. Read by scripts/trace_report.py.",
        "oneOf": [{"type": "object",
                   "properties": {"t": {"const": t},
                                  "doc": {"type": "integer"}, **props},
                   "required": ["t", "doc"] + [k for k in props
                                               if k not in loose],
                   "additionalProperties": False}
                  for t, props in kinds.items()],
    }


def build(spec) -> dict:
    """The three schemas of one profile's extraction output."""
    return {"harvest": harvest_schema(spec),
            "stamp": stamp_schema(),
            "trace": trace_schema()}


def serialize(schema: dict) -> str:
    """One byte-stable rendering, so 'is it current' is a file comparison."""
    return json.dumps(schema, ensure_ascii=False, indent=1,
                      sort_keys=True) + "\n"


def schema_path(profile_name: str) -> Path:
    return (Path(__file__).resolve().parent.parent.parent / "profiles"
            / profile_name / SCHEMA_NAME)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="profile name, e.g. kwp")
    parser.add_argument("--write", action="store_true",
                        help=f"write profiles/<profile>/{SCHEMA_NAME}")
    args = parser.parse_args(argv)

    spec_file = (Path(__file__).resolve().parent.parent.parent / "profiles"
                 / args.profile / "extraction_spec.json")
    if not spec_file.is_file():
        print(f"kein Spec: {spec_file}")
        return 1
    text = serialize(build(load_spec(spec_file)))
    if args.write:
        out = schema_path(args.profile)
        with io.open(out, "w", encoding="utf-8", newline=chr(10)) as handle:
            handle.write(text)
        print(f"{out} ({len(text)} Bytes)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
