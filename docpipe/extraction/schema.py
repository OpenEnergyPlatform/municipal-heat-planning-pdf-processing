"""
schema.py: Builds a JSON Schema for the harvest, the stamp and the trace.

The harvest is the durable artifact, and the graph is a function of
it. Until this module existed, every later question about a key (what
it means, which OEO predicate it becomes, whether it may be null,
what the closed list is) was answered by reading `runner.py`. That is
not an answer anyone outside this repository can use, and it is not
one this repository can check.

So the schema is generated from the spec, not written beside it. The
parameters, their axes, the closed lists, the questions and the `kg`
blocks all come from `profiles/<name>/extraction_spec.json`, so a
spec change that is not reflected in the schema is a failing test
rather than a stale document. Three schemas come out:

  harvest  one line of <name>.jsonl: an accepted tuple or a refused
           claim
  stamp    <name>.stamp.json, what produced that harvest
  trace    one line of <name>.trace.jsonl.gz, one event of the run

Every property carries a `description`, and every coordinate
additionally carries `x-question` (the German question the model was
asked), `x-options` (the closed list with the corpus spellings) and
`x-kg` (what it becomes in the graph). `x-kg` is the spec's own `kg`
block, the same one the serializer reads, so what a reader is told
and what is written cannot drift apart.

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
from .trust import (FLAG_REASONS, LEVEL_A, LEVEL_B, LEVEL_C, LEVEL_D, LEVELS,
                    PARAMETER_STATES)
from .verify import MIN_QUOTE_CHARS, TIER_TEXT, TIER_VISUAL

SCHEMA_NAME = "extraction_schema.json"
BASE_ID = "https://openenergyplatform.org/schema/mhpkg/extraction"

# The levels and the reason families of trust.py, so the published schema and
# the code that fills it cannot drift: a level the schema does not list is a
# level nobody downstream can act on.
TRUST_LEVELS = LEVELS

TRUST_LEVEL_DOC = {
    LEVEL_A: "read off its own passage, in the document's own text",
    LEVEL_B: "the same, but out of an image transcription or a page a model "
             "transcribed",
    LEVEL_C: "a coordinate was not read; see reasons",
    LEVEL_D: "something speaks against the reading; see reasons",
}

# Anchored, so a reason nobody named, or one without its axis, cannot slip in.
TRUST_REASONS = tuple(
    [f"^{r}$" for r in sorted(FLAG_REASONS.values())]
    + ["^conflict$", "^page_transcribed$",
       r"^(exhausted|unbacked|unanswered):[a-z_]+$"])

# What a coordinate's state can be, and what each one is a finding ABOUT. The
# distinction is the whole point of carrying seven of them instead of a null:
# "the plan does not say it" and "we stopped looking" are different facts.
STATE_DOC = {
    fields.READ: "answered, and the cited passage carries the answer",
    fields.DERIVED: ("not asked: the spec decides this coordinate from "
                     "something already on the row (the unit), or the "
                     "request names it (the parameter of a row read for "
                     "one field)"),
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
    fields.OUT_OF_SLICE: ("never asked: a coordinate asked before it had "
                          "read the value as no value of its field (an "
                          "entry other than the spec's `keep`)"),
}
STATES = list(STATE_DOC)

# The same four words about a whole question rather than about one coordinate
# of one row, and they say something else. Written out rather than reused,
# because "the passages shown do not state it" is about a window and "the
# document does not state it" is about a document.
PARAMETER_STATE_DOC = {
    fields.READ: "at least one value of this parameter was read and accepted",
    fields.UNBACKED: ("no value survived, and at least one was refused. A "
                      "finding about the model or about the passages, not "
                      "about the document"),
    fields.EXHAUSTED: ("no value, and the run did not finish this document. "
                       "Document-wide: there is no per-parameter run signal, "
                       "so a truncated run marks every unanswered parameter "
                       "exhausted together"),
    fields.SAID_UNSTATED: ("no value and nothing refused: the document was "
                           "read and does not carry this parameter. The one "
                           "of the four that is a finding about the document "
                           "rather than about the run"),
}

# Non-fatal findings of the verifier, as patterns rather than a list: the
# wording half of each is the document's and cannot be enumerated.
FLAG_PATTERN = (
    r"^(mapped:[a-z_]+:[\s\S]*->[\s\S]*|unmapped:[a-z_]+:[\s\S]*"
    r"|period:unstated"
    r"|review:(agree|disagree|unbacked)"
    r"|computed|catalogue|not_located|read_off)$")

# The fifteen families a refusal reason belongs to. Every one is raised in
# verify.py or pipeline.py and none is composed at runtime from user text.
REFUSAL_REASONS = [
    r"^claim names no parameter of the spec$",
    r"^claim names no source$",
    r"^tuple is not an object$",
    r"^value is not a number$",
    r"^a (text|category) parameter needs a non-empty string value$",
    r"^required axis '.*' (missing|is empty)$",
    r"^axis '.*': .* (not in vocabulary and axis is required"
    r"|is not an integer|not in enum .*)$",
    r"^quote missing or too short to identify anything$",
    r"^quote not found in the source it cites$",
    r"^value .* does not occur in the quote$",
    r"^value .* does not follow from its inputs$",
    r"^value .* not in vocabulary$",
    r"^text value not in its quote$",
    r"^passage is not of this pair$",
]

# Why a coordinate reading was dropped. Each is written by merge_field and
# each is a different repair, so they are enumerated rather than free text.
# tests/test_extraction_reasons.py holds merge_field to this list: a reason it
# writes that is not listed here is a check nobody agreed to.
DROP_REASONS = ["quote_not_in_source", "quote_too_short",
                "answer_not_in_quote", "not_an_option", "wrong_type",
                "unbacked", "not_an_address", "words_not_in_line"]


def _owner() -> dict:
    return {"type": "array", "description": "[owner_kind, owner_id]",
            "prefixItems": [{"enum": ["section", "table", "figure"]},
                            {"type": "integer"}],
            "minItems": 2, "maxItems": 2}


def _slot_value(slot, doc: str) -> dict:
    """The property for the coordinate itself: an entry of its list, a
    number, or a wording; a name or an entry beside the names where a
    coordinate of names takes some (`fields.beside_names`)."""
    if slot.options:
        value = {"type": ["string", "null"], "description": doc}
        if not fields.beside_names(slot):
            value["enum"] = [o.uri for o in slot.options] + [None]
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
    """What a wording resolved to, and, for a closed list, the list itself.

    An axis has published its options since the schema existed. A category
    PARAMETER answers from a list in exactly the same way and published none:
    the key said "the entry of the parameter's own vocabulary" and the schema
    never showed what that vocabulary is. Unseen until now because kwp has no
    category parameter at all: the gap only exists where the profile does.

    Three cases and they read differently on purpose. A text parameter has no
    list at all and never writes the key; a dynamic list exists but is the
    profile's to supply per document, so there is nothing static to publish;
    a closed list is published, meanings and all.
    """
    doc = ("The entry of the parameter's own vocabulary the wording resolved "
           "to. Null when the list does not hold it. ")
    if parameter.value_type != "category":
        return {"type": ["string", "null"],
                "description": doc + "Only a category parameter has a "
                                     "vocabulary. This one never writes "
                                     "the key at all."}
    if parameter.vocabulary_dynamic:
        return {"type": ["string", "null"],
                "description": doc + "The list is per document. The profile "
                                     "supplies it before the harvest, so it "
                                     "is not in this schema."}
    slot = fields.value_slot(parameter)
    out = _slot_value(slot, doc + "The list is closed. An entry beginning "
                                  "'out:' is a deliberate non-class answer "
                                  "and mints no node.")
    # `_slot_value` puts the slot's question on the value it types. Here it
    # would be the parameter's own description, which `parameter` already
    # publishes as x-description-source -- two copies, one of them under a
    # name that says it is a question.
    out.pop("x-question", None)
    return out


def _means(name: str) -> dict:
    """The entries of the document's list of names an answer means, as
    they were asked while it was read (`addressed.Names`)."""
    return {
        "type": "array", "items": {"type": "string", "minLength": 1},
        "description": f"The entries of the document's list of names "
                       f"(its scenarios, its works) '{name}' means: the "
                       f"entry its name is, or the entry of each member "
                       f"where its words name a group; empty where they "
                       f"name a group the field takes no members for, or "
                       f"where the request found they name no such thing "
                       f"(owner decision 2026-11-09). The graph writes the "
                       f"row to each of them, an empty list to none."}


def _slot_properties(name: str, slot, doc: str) -> dict:
    """Every key one coordinate writes.

    Not one. The value is what the graph takes; the rest is what makes the
    value re-checkable without the run that produced it: which state it ended
    in, the document's own wording, the passage, the source that passage came
    from and the window it was found in, and for a year read as a base year
    or a target year the row's own passage that names the state; for a name
    merged with the document's other names, the things it means.
    """
    out = {
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
                           f"'{name}': the model mapped a word the spec "
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
            "prefixItems": [{"enum": ["own", "near", "found", "piece",
                                      "entry", "retrieval", "rest",
                                      "places", "frame", "table",
                                      "base_year", "target_year", "head",
                                      "plan_years"]},
                            {"type": "integer"}],
            "minItems": 2, "maxItems": 2,
            "description": f"[stage, index] of the window '{name}' was read "
                           f"in. `own`: at the value's own place, its row "
                           f"with its table's title and head or its sentence "
                           f"with the sentences beside it. `near`: in the "
                           f"pieces right before and after it. `found`: in "
                           f"the pieces a search found for the sentence of "
                           f"how the plan would print it. `piece`: a work "
                           f"read once for the value's piece, the line that "
                           f"names it or shows the piece is this "
                           f"publication's own. `entry`: the work of the "
                           f"entry of the document's list the value's name "
                           f"is. `plan_years`: a "
                           f"year none of these found, read from the plan's "
                           f"base and target years in a request of its own. "
                           f"The other stages are those of harvests made "
                           f"before the reading in pieces: `frame` is "
                           f"the one that is not a window: the coordinate was "
                           f"read ONCE for the document and applied to this "
                           f"row, and the index is which of the document's "
                           f"pairs it came from. `base_year`: the row's "
                           f"passage names the document's base state by "
                           f"word, and the index is the pair whose quote "
                           f"prints the number. `target_year`: the same for "
                           f"the document's target. `table`: read once for "
                           f"the row's table and taken by this row. `head`: "
                           f"the "
                           f"year the head of the row's column prints, one "
                           f"of the document's pairs, taken off the table "
                           f"and not asked; the index is the column. "
                           f"`retrieval`, `rest` and `places` are the "
                           f"windows of the reading by passages."},
        f"{name}_link_quote": {
            "type": "string", "minLength": MIN_QUOTE_CHARS,
            "description": f"Only with window `base_year` or `target_year`: "
                           f"the passage where the row names that state "
                           f"('{name}_raw'). '{name}_quote' is then the "
                           f"frame's passage that prints the number."},
        f"{name}_link_source": {
            **_owner(),
            "description": f"Which source '{name}_link_quote' was found in."},
        f"{name}_seen": {
            "type": "string",
            "description": f"A wording the model noticed for '{name}' while "
                           f"answering 'not stated', or offered as an answer "
                           f"the closed list does not hold. Vocabulary review "
                           f"material, never evidence."},
        f"{name}{fields.PRODUCER}": {
            "type": "integer", "minimum": 0,
            "description": f"Who re-read '{name}': the position of its entry "
                           f"in the `producers` list of the stamp beside the "
                           f"harvest. Written by a top-up for each coordinate "
                           f"it re-read, and by a pass that appended a "
                           f"parameter for each coordinate of the rows it "
                           f"wrote, never by the harvest, so a missing "
                           f"key means the harvest read it. A position the "
                           f"stamp has no entry for (the stamps were "
                           f"deleted) means nobody can say. Recorded and "
                           f"never compared."},
    }
    # Any coordinate whose answer is an entry of the document's list of
    # names, a scenario or a work (`addressed.Names`).
    out[f"{name}_means"] = _means(name)
    return out


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
                                 "contains the value, checked by "
                                 "whitespace-collapsed containment."},
        "head": {"type": "string",
                 "description": "The head of the table column the number "
                                "stands in, as the plan prints it. Taken from "
                                "the table, never asked. Absent where the "
                                "number is no table cell or its column is not "
                                "certain."},
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
                                 "shown to be a yearly one; review:* is what "
                                 "a second reading of this value under a "
                                 "narrower window came to, and only "
                                 "review:disagree is a reason."},
        "provenance": {"$ref": "#/$defs/provenance"},
        fields.RANGE: {
            "type": "array", "items": {"type": "number"},
            "minItems": 2, "maxItems": 2,
            "description": "Both ends of the range this value is one end "
                           "of, [lower, upper] as the plan prints them: "
                           "written on both rows when one reads as the lower "
                           "and the next as the upper end under the same "
                           "quote with the same coordinates otherwise."},
        "computed": {"type": "boolean",
                     "description": "The value came out of the sandbox, not "
                                    "off the page; the quote proves the "
                                    "inputs it was computed from."},
        "compute": {"type": "array", "items": {"type": "object"},
                    "description": "The sandbox runs behind a computed "
                                   "value: {code, stdout, ok, error}, the "
                                   "last with the numbers it was worked out "
                                   "from (inputs) and what they make "
                                   "(expected)."},
        "catalogue": {"type": "object",
                      "description": "The open catalogue record a value was "
                                     "looked up in, not read off the page: "
                                     "its source and id, what was searched, "
                                     "what it holds and which of its values "
                                     "matched the document's. The quote is "
                                     "the read value it was looked up "
                                     "with; the flag catalogue goes with "
                                     "it."},
        "at": {"type": "object",
               "properties": {"owner": _owner(),
                              "line": {"type": "integer", "minimum": 1},
                              "cell": {"type": "integer", "minimum": 1},
                              "last": {"type": "integer", "minimum": 1}},
               "required": ["owner", "line"],
               "additionalProperties": False,
               "description": "Where the value stands (owner decisions "
                              "2026-11-08): its passage, the number of its "
                              "line there, the cell of a table row, and "
                              "the last line of a value over several lines. "
                              "The quote is that line."},
        "drawn": {"type": "boolean",
                  "description": "A figure's value only: whether its image "
                                 "only draws the number (a bar, a segment, an "
                                 "area, a point of a curve) rather than "
                                 "printing it, as the reading said. True sets "
                                 "the flag read_off."},
        "read_off": {"const": True,
                     "description": "The number stands in no text and was "
                                    "read off the figure's image: the "
                                    "reading is its evidence in place of a "
                                    "quote, and the flag read_off goes with "
                                    "it, a reason of level C (owner "
                                    "decisions 2026-11-05 and 2026-11-07)."},
        "reading": {"type": "string", "minLength": 1,
                    "description": "What was read off the figure's image: "
                                   "the element, the number and the unit of "
                                   "its axis. Present only with read_off."},
    }
    required = ["kind", "parameter", "parameter_state", "tier",
                "provenance", "value"]
    # A value read off a figure has its reading in place of a quote; every
    # other value has its quote.
    rules: list = [{"if": {"required": ["read_off"]},
                    "then": {"required": ["reading"]},
                    "else": {"required": ["quote"]}}]
    if parameter.is_numeric:
        units = ", ".join(sorted(parameter.units_accepted))
        props["value"] = {
            "type": "number",
            "description": "The number as the document prints it, with the "
                           "grouping removed and a decimal point."}
        # A coordinate of its own: one entry of the list, read with its own
        # passage, the document's spelling beside it in unit_raw. A tuple
        # only exists with the unit read, so its state is always 'read'.
        unit_slot = fields.unit_slot(spec, parameter)
        props.update(_slot_properties(
            "unit", unit_slot,
            f"The unit: one entry of units_accepted ({units}), read as a "
            f"coordinate with its own passage, or null where the unit the "
            f"plan prints means none of them: then unit_raw holds it, the "
            f"flag unmapped:unit:<print> goes with it and the value has no "
            f"value_target (owner decision 2026-11-07: a unit is never "
            f"refused). Which entry the document's wording means is the "
            f"model's reading; the wording itself is never looked up. "))
        props["value_target"] = {
            "type": "number",
            "description": f"value x factor(unit), in the spec's unit_target "
                           f"{parameter.unit_target}. This is the number the "
                           f"graph carries; absent where the unit is no "
                           f"entry of units_accepted."}
        required += ["unit", "unit_state"]
        # Read as an entry and converted, or read as the plan prints it,
        # without an entry and unconverted.
        unit_rule = _slot_rules("unit", unit_slot)
        unit_rule["then"] = {"anyOf": [
            {"properties": {"unit": {"type": "string"}},
             "required": ["unit", "value_target"]},
            {"properties": {"unit": {"type": "null"}},
             "required": ["unit", "unit_raw"]}]}
        rules.append(unit_rule)
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
        if getattr(parameter, "merged", None):
            props["value_means"] = _means("value")
        if parameter.value_type == "category":
            # Where the rows request wrote a wording the list does not hold,
            # the value was asked again as one of its entries, a coordinate
            # with its own passage (`fields.value_choice`).
            props.update({key: rule for key, rule in _slot_properties(
                "value", fields.value_choice(parameter),
                "The entry the value was read as.").items()
                if key not in ("value", "value_raw")})
        props["unit"] = {"type": "string", "maxLength": 0,
                         "description": "Empty: a wording has no unit. The "
                                        "key is present so every row has the "
                                        "same shape."}
        props["unit_raw"] = {"type": "string", "maxLength": 0,
                             "description": "Empty, as unit."}

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
        closed = ("A name the document prints, or one of the entries beside "
                  "the names, each beginning 'out:', a deliberate answer that "
                  "names nothing and mints no node. "
                  if fields.beside_names(slot)
                  else "A closed list; an entry beginning 'out:' is a "
                       "deliberate non-class answer and mints no node. "
                  if slot.options else "")
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
                       "(kind=refusal), what a whole parameter came to "
                       "(kind=parameter_state, one per parameter of the "
                       "spec), or the document's own summary (kind=summary, "
                       "the last line of the file). Generated from the "
                       "profile's extraction_spec.json by "
                       "docpipe/extraction/schema.py.",
        "oneOf": [{"$ref": f"#/$defs/tuple_{p.uri}"} for p in spec.parameters]
                 + [{"$ref": "#/$defs/refusal"},
                    {"$ref": "#/$defs/parameter_state"},
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
                                       "figure's caption, resolved to the "
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
                                       "A sentinel carries _harvest_failed "
                                       "with _why: the server was gone, it "
                                       "answered 429 or 5xx, the model "
                                       "answered nothing, or the reply did "
                                       "not fit and there was nothing left "
                                       "to split. A hole of a reading also "
                                       "carries _parameter, the parameter "
                                       "the passage was to be read for.",
                        "properties": {
                            "_harvest_failed": {"const": True},
                            "_parameter": {"type": "string"},
                            "_why": {"enum": ["unreachable", "unserved",
                                              "no_answer", "cut_off"]}}},
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
                               "pass, so neither is counted here. The "
                               "levels are a floor, and the graph side "
                               "recomputes them. A pass that appended a "
                               "parameter built this line again over every "
                               "tuple and refusal the file holds; the "
                               "refusals of the first pass are counted as "
                               "they were stored and are not revisited, so "
                               "a value refused then for want of that "
                               "parameter stays in the count.",
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
                        "description": "Values read out of a table or "
                                       "figure image rather than the "
                                       "document's text."},
                    "unlisted_units": {
                        "type": "object",
                        "description": "The units numbers were read with "
                                       "that are no entry of their "
                                       "parameter's list, as the plan prints "
                                       "them, counted: read and not "
                                       "converted, until the list grows and "
                                       "a top-up asks them again (owner "
                                       "decision 2026-11-07). Absent in a "
                                       "file written before.",
                        "additionalProperties": {"type": "integer"}},
                },
                "required": ["kind", "document_id", "tuples", "refusals",
                             "levels", "reasons", "image_origin"],
                "additionalProperties": False,
            },
            "parameter_state": {
                "type": "object",
                "description": "What one parameter of the spec came to in "
                               "this document. Every other state in this file "
                               "belongs to a row, so a parameter that "
                               "produced no row left no byte at all and "
                               "\"the document does not carry it\" and "
                               "\"it was never asked\" were the same empty "
                               "file.",
                "properties": {
                    "kind": {"const": "parameter_state"},
                    "document_id": {"type": "integer"},
                    "parameter": {
                        "type": "string",
                        "description": "The spec's uri for the parameter, the "
                                       "same key a tuple carries."},
                    "state": {"enum": list(PARAMETER_STATES),
                              "x-doc": PARAMETER_STATE_DOC},
                    "tuples": {"type": "integer"},
                    "refusals": {"type": "integer"},
                },
                "required": ["kind", "document_id", "parameter", "state",
                             "tuples", "refusals"],
                "additionalProperties": False,
            },
            **{f"tuple_{p.uri}": _tuple_schema(spec, p)
               for p in spec.parameters},
        },
    }


def stamp_schema() -> dict:
    """<name>.stamp.json: what produced the harvest beside it."""
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}/stamp",
        "title": "docpipe extraction resume stamp",
        "description": "The parameter/, value/, axis/ and slot/ keys, and "
                       "the sha256 in `document`, make the document stale "
                       "when they differ from the current run: it is "
                       "named in a warning, skipped, and harvested again "
                       "with --force-stale. Every other key is recorded and "
                       "never compared. `spec` is recorded so a reader can "
                       "say which file a harvest came from. Withheld when "
                       "the harvest did not happen. "
                       "The parameter/, value/, axis/ and slot/ keys record "
                       "which question changed, so a moving ontology costs "
                       "only the coordinates it touched rather than a full "
                       "re-read of the corpus. A stamp written before those "
                       "keys existed carries none of them, so for it "
                       "`spec` decides again, and it is stale in all of "
                       "them.",
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
                        "description": "The anchor prompt, the model and "
                                       "the version of the target set, "
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
            "docpipe": {"type": "string",
                        "description": "The version that wrote this stamp. "
                                       "Recorded and never compared."},
            "document": {
                "type": "object",
                "description": "Which bytes were read: the sha256 and the "
                               "size of the file as the database recorded "
                               "them. Absent for a database that records "
                               "none. Another sha256 than this one makes "
                               "the document stale, as a changed ontology "
                               "key does. The size is recorded and never "
                               "compared, and a stamp without this key is "
                               "not compared at all.",
                "properties": {"sha256": sha,
                               "bytes": {"type": ["integer", "null"]}},
                "required": ["sha256"], "additionalProperties": False},
            "producers": {
                "type": "array",
                "description": "Every pass that wrote into this harvest, in "
                               "order: the harvest, then each top-up that "
                               "rewrote the file, each pass that appended a "
                               "new parameter, each remap that carried a "
                               "key forward and each review that changed a "
                               "row. Entries are only ever added, so a "
                               "position is stable: a coordinate a top-up "
                               "re-read points at its entry with "
                               "`<axis>_producer`. `model` above names the "
                               "first only. Recorded and never compared.",
                "items": {
                    "type": "object",
                    "properties": {
                        "pass": {"type": "string"},
                        "model": {"type": ["string", "null"]},
                        "provider": {"type": "string"},
                        "prompts": {"type": "object"},
                        "docpipe": {"type": "string"},
                        "utc": {"type": "string"},
                        "parameters": {
                            "type": "array", "items": {"type": "string"},
                            "description": "A pass that appended parameters "
                                           "to a stored harvest: their "
                                           "URIs."},
                        "frame": {
                            "type": "string",
                            "description": "A pass that appended parameters "
                                           "to a stored harvest: where the "
                                           "frame's pairs of the document "
                                           "came from."},
                        "flow": {
                            "type": "string",
                            "enum": ["survey", "fieldwise"],
                            "description": "Which flow the pass harvested "
                                           "with, written whenever a model "
                                           "is named. Recorded and never "
                                           "compared."},
                        "numbers": {
                            "type": "object",
                            "additionalProperties": {"type": "integer"},
                            "description": "The numbers of the flow the "
                                           "pass read with, every one in "
                                           "effect, a setting that won "
                                           "over the flow file included; "
                                           "written whenever a model is "
                                           "named. Recorded and never "
                                           "compared: a changed number "
                                           "makes no harvest stale."},
                        "flow_file": {
                            **sha,
                            "description": "sha256 of the profile's flow "
                                           "file as laid over the ones it "
                                           "extends, its steps and its "
                                           "numbers. Recorded and never "
                                           "compared."}},
                    "required": ["pass"], "additionalProperties": False}},
            "page_text_transcribed": {
                "type": ["integer", "null"],
                "description": "How many pages of this document a model read "
                               "rather than the PDF. A harvest from a "
                               "transcribed document is a reading of a "
                               "reading."},
        },
        "patternProperties": {
            "^extraction/(harvest|queries|anchors|rows|field|phrase|frame"
            "|survey|read_values|read_text|comb|match|settings|seek"
            "|transcribe|find|docfield|coord|list|names|search|check"
            "|follow|work)$":
                {**sha, "description": "sha256 of the prompt file; "
                                       "`transcribe`, `find`, `docfield`, "
                                       "`coord`, `list`, `names`, `search`, "
                                       "`check`, `follow`, `work` and "
                                       "`phrase` are the prompts of a "
                                       "harvest piece by piece; the others "
                                       "are in stamps of older releases"},
            "^question_text/[^/]+$": {
                "type": "array", "items": {"type": "string"},
                "description": "The sentence THIS document was searched "
                               "with. Recorded and never compared: it is "
                               "written per document, so the document itself "
                               "is part of it and no two runs produce the "
                               "same one. What decides whether the harvest is "
                               "current is its recipe, and that is already "
                               "here: the generator prompt, the model, and "
                               "the annotation inside parameter/."},
            "^parameter/[^/]+$": {
                **sha,
                "description": "What this parameter asks, without its axes "
                               "and without its own list: label, description, "
                               "value type, accepted units and the example. A "
                               "new option on ONE axis, or in the list the "
                               "parameter answers from, must not make every "
                               "value of the parameter stale. Those have "
                               "keys of their own."},
            "^value/[^/]+$": {
                **sha,
                "description": "The list a category parameter answers from: "
                               "its classes and their spellings, which is "
                               "all the rows request shows the model. Not "
                               "their definitions. Its own key, because a "
                               "moved option can be re-mapped from the "
                               "wording the harvest kept while a rewritten "
                               "question cannot."},
            "^slot/parameter$": {
                **sha,
                "description": "The one coordinate that belongs to no "
                               "parameter: which quantity a number is. Its "
                               "question and the parameters it offers, uri "
                               "and label. Also the only key that moves when "
                               "a parameter is dropped."},
            "^review/(prompt|model)$": {
                "type": "string",
                "description": "What read this document a second time. "
                               "Recorded and never compared: the review does "
                               "not decide whether the harvest is current, "
                               "and comparing it would report every reviewed "
                               "document stale the day the review prompt "
                               "changes."},
            "^axis/[^/]+/[^/]+$": {
                **sha,
                "description": "What this coordinate asks and what it may "
                               "answer: the question and the offered list "
                               "with its spellings and its definitions. "
                               "Everything the model sees for this axis, and "
                               "nothing else."}},
        # The prompts a stamp names are those of the flow it was harvested
        # with, so none of them is required.
        "required": ["spec", "model", "anchors"],
        "additionalProperties": False,
    }


# The stages whose every request writes `<stage>_ask` to the trace: the
# requests of the harvest piece by piece (`runner.ask_in_grammar`,
# addressed.py), and the search sentences of a document's fields and of a
# coordinate's search, the frame, the review and the compute step
# (`runner._asked`, `phrase`).
PIECE_ASKS = ("transcribe", "find", "docfield", "coord", "list", "names",
              "search", "check", "follow", "work")
ASK_STAGES = PIECE_ASKS + ("phrase", "frame", "review", "compute")


def trace_schema() -> dict:
    """One line of <name>.trace.jsonl.gz: one event, never an aggregate."""
    owner = _owner()
    # `via_base`: of `filled`, the years read as one of the plan's base years
    # by the word the row's passage uses for its state. `via_target`: the
    # same for the plan's target years. `via_table`: rows that took the frame
    # their table was asked for.
    counts = {k: {"type": "integer"} for k in
              ("filled", "unquoted", "unbacked", "unstated", "raw_missing",
               "raw_foreign", "via_base", "via_target", "via_table")}
    by_field = {"type": "object", "additionalProperties": {"type": "integer"}}
    kinds = {
        "plan": {"rank": {"type": ["integer", "null"]},
                 "origin": {"enum": ["structure", "retrieval", "rest",
                                      "front", "found"]},
                 "kind": {"enum": ["section", "table", "figure"]},
                 "owner": {"type": "integer"}, "chars": {"type": "integer"},
                 "image": {"type": "boolean"}},
        # The sentence this document was searched with. It is written per
        # document and exists nowhere else once the run is over, so a harvest
        # that is not recorded here cannot be placed at all.
        "anchor": {"parameter": {"type": "string"},
                   "text": {"type": "string"}},
        # Which scenarios and which years this document really carries, and
        # what a deterministic scan of the same passages found that the model
        # did not name. A finding, not a question: it is discovered once and
        # then every value is asked for one of its pairs.
        "frame": {"pairs": {"type": "integer"},
                  "scenarios": {"type": "array", "items": {"type": "string"}},
                  "years": {"type": "array", "items": {"type": "integer"}},
                  "missed": {"type": "array", "items": {"type": "integer"}},
                  "sources": {"type": "array", "items": owner},
                  "status": {"enum": ["complete", "exhausted"]},
                  "attempt": {"type": "integer"},
                  # Pairs this round refused for their evidence or for naming
                  # a scenario off the list, and therefore asked again for.
                  "rejected": {"type": "integer"},
                  "prompt_tokens": {"type": ["integer", "null"]},
                  "completion_tokens": {"type": ["integer", "null"]},
                  "ms": {"type": "integer"}},
        "rows": {"prompt": {"type": "string"}, "attempt": {"type": "integer"},
                 "rows": {"type": "integer"},
                 "status": {"type": ["string", "null"]},
                 "sources": {"type": "array", "items": owner},
                 "ranks": {"type": "array"}, "origins": {"type": "array"},
                 "prompt_tokens": {"type": ["integer", "null"]},
                 "completion_tokens": {"type": ["integer", "null"]},
                 "ms": {"type": "integer"}},
        # A sandbox round: what the model ran and what came back, so a run
        # can say whether it computed anything at all.
        "code": {"attempt": {"type": "integer"}, "code": {"type": "string"},
                 "stdout": {"type": "string"}, "ok": {"type": "boolean"},
                 "error": {"type": ["string", "null"]}},
        # One open question of the compute step and how it ended: `read` is a
        # new row, `refused` a number the check did not take, `same` a number
        # another question already came to with the same coordinates, `none`
        # the model saying there is nothing to compute. `runs` counts its
        # sandbox rounds, `fetched` and `searched` the passages and searches
        # it asked of the plan, `taken` and `untaken` the numbers it took
        # from a passage and those not taken, `misquoted` its answers whose
        # quote stood in no passage of the number it chose, `rejected` its
        # answers the row's own check refused and the model was told, and
        # `reason` the last such refusal.
        "compute": {"kind": {"type": "string"},
                    "numbers": {"type": "integer"},
                    "outcome": {"enum": ["read", "refused", "same", "none",
                                         "too_long", "unanswered", "stopped"]},
                    "runs": {"type": "integer"},
                    "fetched": {"type": "integer"},
                    "searched": {"type": "integer"},
                    "taken": {"type": "integer"},
                    "untaken": {"type": "integer"},
                    "misquoted": {"type": "integer"},
                    "rejected": {"type": "integer"},
                    "reason": {"type": ["string", "null"]}},
        "field": {"slot": {"type": "string"}, "anchor": {"type": "string"},
                  "window": {"type": "integer"},
                  "stage": {"enum": ["own", "found", "retrieval", "rest",
                                     "places", "frame"]},
                  "attempt": {"type": "integer"},
                  "parameter": {"type": ["string", "null"]},
                  # How many batches the rows of the request came from: one
                  # for a batch's own stage, the document's for its search.
                  "batches": {"type": "integer"},
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
                  "exhausted": {"type": "integer"},
                  # Windows asked ahead and withdrawn unsent: the rows were
                  # read by a window before them.
                  "withdrawn": {"type": "integer"},
                  # What the sweep covered: a batch's own stage alone (`own`),
                  # the search of a document's open rows after the own
                  # stages (`document`), or every stage for one batch
                  # (`batch`), which is what a pass over a stored harvest
                  # walks. `batches` is how many batches its rows came from.
                  "scope": {"enum": ["own", "document", "batch"]},
                  "batches": {"type": "integer"}, **counts},
        "drop": {"slot": {"type": "string"},
                 "field": {"type": ["string", "null"]},
                 "window": {"type": "integer"},
                 "attempt": {"type": "integer"},
                 # A label of a search over several batches names no batch.
                 "batches": {"type": "integer"},
                 "row": {"type": "string", "pattern": "^R[0-9]+$"},
                 "why": {"enum": DROP_REASONS},
                 # What was answered: the model's value and wording as they
                 # came back, whatever their type, and the first 300
                 # characters of the quote it cited.
                 "given": {}, "raw": {},
                 "quote": {"type": ["string", "null"], "maxLength": 300}},
        "error": {"where": {"type": "string"},
                  "kind": {"enum": ["unreadable", "exception", "gave_up",
                                    "split"]},
                  # WHY a reply could not be read, so a run can say whether
                  # its retries were spent on answers that were cut off,
                  # wrapped in prose, or simply broken.
                  "cause": {"enum": ["cut_off", "empty", "reasoning_only",
                                     "no_object", "syntax", "outside_text",
                                     "missing_key", "not_an_object",
                                     "wrong_shape"]},
                  "slot": {"type": ["string", "null"]},
                  "attempt": {"type": "integer"},
                  "finish": {"type": ["string", "null"]},
                  "status": {"type": ["integer", "string", "null"]},
                  "detail": {"type": "string"},
                  # Both ends of a reply that was cut off.
                  "head": {"type": "string"}, "tail": {"type": "string"},
                  "why": {"enum": ["unreachable", "unserved", "no_answer",
                                   "cut_off"]},
                  "owner": owner,
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
        # The document's map of places (places.py): its passages and
        # requests, the places taken and not, the requests that came back
        # unread (then the map is not used), and the places per axis and
        # per parameter.
        "places": {"passages": {"type": "integer"},
                   "windows": {"type": "integer"},
                   "places": {"type": "integer"},
                   "dropped": {"type": "integer"},
                   "unread": {"type": "integer"},
                   "complete": {"type": "boolean"},
                   "by_axis": by_field, "by_parameter": by_field},
        "invalid": {"kind": {"enum": ["tuple", "refusal",
                                      "parameter_state"]},
                    "where": {"type": "string"},
                    "why": {"type": "string"},
                    "detail": {"type": "string"}},
        # The order one document's passages are read in (survey.py): `scope`
        # what it covered, `passages` how many, each read for every one of
        # `parameters`, `first` the first five owners of each parameter.
        "order": {"scope": {"type": ["string", "null"]},
                  "passages": {"type": "integer"},
                  "parameters": {"type": "integer"},
                  "first": {"type": "object", "additionalProperties": {
                      "type": "array", "items": {"type": "array"}}}},
        # One request that got a reply, per kind (`ASK_STAGES`). Which of
        # `parameter`, `owner`, `kind` it carries depends on the kind; a
        # coordinate's request names the `value` it asks for, the label of
        # its row. The requests piece by piece (addressed.py, `PIECE_ASKS`)
        # carry besides the piece of the passage, how many pieces a request
        # showed, the coordinate asked, the step of a list asked in two, the
        # kind of names and how many a list showed, and the request a
        # follow-up follows.
        **{f"{stage}_ask": {"attempt": {"type": "integer"},
                            "parameter": {"type": ["string", "null"]},
                            "owner": {}, "kind": {},
                            "value": {"type": "string"},
                            **({"chunk": {"type": "integer"},
                                "chunks": {"type": "integer"},
                                "coordinate": {"type": "string"},
                                "step": {"enum": ["group", "plan_years"]},
                                "names": {"type": "integer"},
                                "asked": {"type": "string"}}
                               if stage in PIECE_ASKS
                               else {"coordinate": {"type": "string"}}
                               if stage == "phrase" else {}),
                            "prompt_tokens": {"type": ["integer", "null"]},
                            "completion_tokens": {"type": ["integer", "null"]},
                            "ms": {"type": "integer"}}
           for stage in ASK_STAGES},
        # One field read in one passage (addressed.py), its values found in
        # its pieces. A passage that came to no readable reply is `unread`
        # with `why` and no values.
        "read": {"parameter": {"type": "string"},
                 "kind": {"enum": ["section", "table", "figure"]},
                 "owner": {"type": "integer"},
                 "values": {"type": "integer"},
                 "asked": {"type": "integer"}, "failed": by_field,
                 "unanswered": {"type": "integer"},
                 "unread": {"type": "boolean"},
                 "why": {"enum": ["cut_off", "no_answer"]}},
        # A field asked once of a document (addressed.py): the values it
        # came to, and `why` where a request came to nothing.
        "docfield": {"parameter": {"type": "string"},
                     "values": {"type": "integer"},
                     "why": {"enum": ["cut_off", "no_answer"]}},
        # What a plan settles for all its values and its own years, asked
        # once per plan: the settings' lines and the base and target years.
        "settled": {"settings": {"type": "integer"},
                    "base": {"type": "array", "items": {"type": "integer"}},
                    "target": {"type": "array",
                               "items": {"type": "integer"}}},
        # The works a publication presents, compares or cites: the entries
        # of its list and the new ones asked their details.
        "works": {"works": {"type": "integer"}, "new": {"type": "integer"}},
        # What the requests of one document came to: per kind, refusals per
        # reason, the search sentences that were questions, its pieces.
        "asked": {"requests": by_field, "refused": by_field,
                  "question_queries": {"type": "integer"},
                  "chunks": {"type": "integer"},
                  "scope": {"type": ["string", "null"]}},
        # A sentence the passages are ranked with for a parameter, written
        # for the document or once per run (`per`).
        "seek_probe": {"parameter": {"type": "string"},
                       "per": {"enum": ["document", "run"]},
                       "text": {"type": "string"}},
        # What a profile's lookup outside the document came to
        # (`runner.make_completer`): its `outcome`, the parameters still
        # `open` and those `filled`, the record's `id`, the `key` it was
        # found by and the family names it `matched`.
        "completion": {"outcome": {"type": "string"},
                       "open": {"type": "array", "items": {"type": "string"}},
                       "filled": {"type": "array",
                                  "items": {"type": "string"}},
                       "id": {"type": ["string", "null"]},
                       "key": {"type": "string"},
                       "matched": {"type": "array",
                                   "items": {"type": "string"}},
                       "detail": {"type": "string"}},
        # A text the requests of a document repeat (a system prompt, a reply
        # format, a passage, a list of options, a picture), written once
        # before the first event that refers to it by `id` (trace.py).
        "piece": {"id": {"type": "string"}, "text": {"type": "string"}},
    }
    # An event that reports a model request carries the request as it was
    # sent and what came back, the reply or the error (`trace.sent` puts the
    # request back together); one that reports no request carries neither.
    # With them its times in seconds since the epoch, and `once` where the
    # answer is that of the same request sent before in the document and
    # nothing was sent (`scheduler.Once`, owner decision 2026-11-07).
    exchange = {"input": {"type": "object"}, "output": {"type": "object"},
                "asked_at": {"type": "number"}, "sent_at": {"type": "number"},
                "answered_at": {"type": "number"},
                "once": {"type": "boolean"}}
    for kind, props in kinds.items():
        if "prompt_tokens" in props or kind == "error":
            props.update(exchange)
    # Of the harvest's events, the fields only some of them carry.
    optional = {
        # The requests piece by piece carry what their kind names.
        **{f"{stage}_ask": {"parameter", "owner", "kind", "value", "chunk",
                            "chunks", "coordinate", "step", "names",
                            "asked"}
           for stage in PIECE_ASKS},
        # A search sentence, the frame, the review and the compute step say
        # their attempt and what it cost; a parameter where they have one,
        # and a sentence for a coordinate's search its coordinate.
        **{f"{stage}_ask": {"parameter", "owner", "kind", "value"}
           for stage in ("frame", "review", "compute")},
        "phrase_ask": {"parameter", "owner", "kind", "value", "coordinate"},
        "docfield": {"why"},
        "asked": {"scope"},
        "read": {"failed", "unanswered", "unread", "why"},
        "completion": {"filled", "id", "key", "matched"},
    }
    # Optional on every event: what the run could not always know. Requiring
    # them would refuse a legitimate record from a request that never reached
    # the server.
    loose = {"detail", "status", "finish", "why", "sources", "ms", "slot",
             "prompt_tokens", "completion_tokens", "filled_by", "unbacked_by",
             "field", "raw_missing", "raw_foreign", "cause", "owner",
             "rejected", "given", "raw", "quote", "via_base", "via_target",
             "via_table", "scope", "withdrawn",
             "batches", "input", "output", "asked_at", "sent_at",
             "answered_at", "once"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}/trace-record",
        "title": "docpipe extraction trace record",
        "description": "One event per line; `t` names it and `doc` the "
                       "document. An event that reports a model request "
                       "carries it as sent (`input`) and what came back "
                       "(`output`); a text the requests repeat is a `piece` "
                       "they refer to. Read by scripts/trace_report.py.",
        "oneOf": [{"type": "object",
                   "properties": {"t": {"const": t},
                                  "doc": {"type": "integer"}, **props},
                   "required": ["t", "doc"] + [
                       k for k in props
                       if k not in loose and k not in optional.get(t, ())],
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


def _profile_dir(profile_name: str) -> Path:
    """Where a profile lives: wherever profiles are found (a project's own
    directory, the search path), else the checkout's `profiles/`."""
    from docpipe.profile import load_profile
    try:
        return Path(load_profile(profile_name).package_dir)
    except (LookupError, ImportError, ValueError):  # not a profile yet
        return (Path(__file__).resolve().parent.parent.parent / "profiles"
                / profile_name)


def schema_path(profile_name: str) -> Path:
    return _profile_dir(profile_name) / SCHEMA_NAME


def _spec_file(profile_name: str) -> Path:
    """The spec the run reads: the one the profile names
    (`extraction.SPEC_PATH`), wherever it lies. For a name that is no
    profile yet, the file where a profile keeps it."""
    from docpipe.profile import load_profile
    try:
        named = load_profile(profile_name).component("extraction",
                                                     "SPEC_PATH")
    except (LookupError, ImportError, ValueError):
        named = None
    return (Path(named) if named
            else _profile_dir(profile_name) / "extraction_spec.json")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="profile name, e.g. kwp")
    parser.add_argument("--write", action="store_true",
                        help=f"write {SCHEMA_NAME} into the profile's "
                             f"directory")
    args = parser.parse_args(argv)

    spec_file = _spec_file(args.profile)
    if not spec_file.is_file():
        print(f"no spec: {spec_file}")
        return 1
    text = serialize(build(load_spec(spec_file)))
    if args.write:
        out = schema_path(args.profile)
        with io.open(out, "w", encoding="utf-8", newline=chr(10)) as handle:
            handle.write(text)
        print(f"{out} ({len(text)} bytes)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
