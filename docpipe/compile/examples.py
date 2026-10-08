"""
examples.py: Proposes, from the corpus, the example a parameter still lacks.

Every parameter of a spec carries one real example: a snippet of a document
and the tuples it yields. It is the prompt's demonstration and the dry run's
test, and writing one per parameter is the heaviest part of a new spec. This
module finds candidate passages in a processed corpus, asks the model which
values of the parameter a passage states, and keeps a proposal only where
each value brings a quote that stands in the passage and contains the value.
Those are the checks every harvested value passes, and nothing else is
asked of a proposal.

A proposal is never an example. It goes into a review file beside the
draft, with the document it came from; a person reads it, sets `accept`,
and `apply` carries exactly the accepted ones into the spec. What a model
drafted becomes a demonstration only after somebody has read it.

The two things this module needs from a run are handed in: `find`, which
returns passages for a parameter, and `ask`, which returns the model's
reply for one passage. So the logic is tested without a corpus and without
a model.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

from ..extraction import spec as spec_module
from ..extraction.verify import MIN_QUOTE_CHARS, quote_in, value_in_quote

log = logging.getLogger(__name__)

EXAMPLE_PROMPT_ID = "extraction/example"
REVIEW_FILE = "examples.review.json"
# Characters of the passage kept around the quotes of a proposal.
SNIPPET_MARGIN = 240
SNIPPET_MAX = 1800
NOT_IN_PASSAGE = "quote_not_in_passage"
TOO_SHORT = "quote_too_short"
NOT_IN_QUOTE = "value_not_in_quote"
# Counted and not held against a value: the reply's item is no tuple, the
# quote lies outside the part of the passage an example can show, the
# request got no reply that could be read.
NOT_A_TUPLE = "not_a_tuple"
NOT_SHOWN = "quote_outside_the_part_shown"
NO_REPLY = "reply"


def review_path(draft) -> Path:
    """Where the proposals for a draft are kept: beside it and under its
    name, so that two drafts in one folder do not share one file."""
    draft = Path(draft)
    return draft.with_name(f"{draft.stem}.{REVIEW_FILE}")


def reply_shape(numeric: bool) -> tuple:
    """(name, JSON schema) of the reply to one example request."""
    value = {"type": "number"} if numeric else {"type": "string"}
    properties = {"value": value,
                  "value_raw": {"type": ["string", "null"]},
                  "quote": {"type": "string"}}
    if numeric:
        properties["unit"] = {"type": ["string", "null"]}
    return "example_reply", {
        "type": "object", "additionalProperties": False,
        "required": ["tuples"],
        "properties": {"tuples": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["value", "quote"], "properties": properties}}}}


def payload(parameter: dict, passage: str) -> dict:
    """What one request shows the model: the parameter as the spec writes
    it, and one passage."""
    shown = {key: parameter[key] for key in ("label", "description",
                                             "value_type") if key in parameter}
    if parameter.get("units_accepted"):
        shown["units_accepted"] = sorted(parameter["units_accepted"])
    if isinstance(parameter.get("vocabulary"), dict):
        shown["options"] = {
            (entry.get("label") if isinstance(entry, dict) else entry[0]): (
                {key: entry[key] for key in ("definition", "spellings")
                 if entry.get(key)} if isinstance(entry, dict)
                else list(entry[1:]))
            for entry in parameter["vocabulary"].values()}
    return {"parameter": shown, "passage": passage}


def checked(drafted, passage: str, parameter: dict) -> tuple:
    """(the tuples that carry their own evidence, [(tuple, why not)]).

    The quote stands in the passage, it is long enough to name a place, and
    the value stands in the quote: for a number its digits, for anything
    else its wording as the document writes it (`value_raw`, else `value`).
    """
    numeric = parameter.get("value_type") in spec_module.NUMERIC_TYPES
    stand_in = SimpleNamespace(is_numeric=numeric)
    kept, dropped = [], []
    for raw in drafted if isinstance(drafted, list) else ():
        if not isinstance(raw, dict):
            dropped.append((raw, NOT_A_TUPLE))
            continue
        quote = raw.get("quote")
        if not isinstance(quote, str) or not quote_in(passage, quote):
            dropped.append((raw, NOT_IN_PASSAGE))
        elif len(quote.strip()) < MIN_QUOTE_CHARS:
            dropped.append((raw, TOO_SHORT))
        elif not value_in_quote(raw, stand_in, quote):
            dropped.append((raw, NOT_IN_QUOTE))
        else:
            kept.append({key: value for key, value in raw.items()
                         if value is not None})
    return kept, dropped


def snippet(passage: str, quotes: list) -> str:
    """The part of the passage an example shows: the quotes with what
    stands around them, never more than `SNIPPET_MAX` characters. A quote
    that cannot be placed letter for letter (it stands in the passage with
    other spacing) is placed by nobody here: the start of the passage is
    shown. Whether a quote is in what is shown is the caller's to check."""
    spans = []
    for quote in quotes:
        at = passage.find(quote)
        if at < 0:
            return passage[:SNIPPET_MAX]
        spans.append((at, at + len(quote)))
    if not spans:
        return passage[:SNIPPET_MAX]
    low = max(0, min(start for start, _ in spans) - SNIPPET_MARGIN)
    high = min(len(passage), max(end for _, end in spans) + SNIPPET_MARGIN)
    if high - low > SNIPPET_MAX:
        return passage[:SNIPPET_MAX] if high <= SNIPPET_MAX else \
            passage[low:low + SNIPPET_MAX]
    # whole lines: a table row cut in half reads as another row
    low = passage.rfind("\n", 0, low) + 1
    newline = passage.find("\n", high)
    high = len(passage) if newline < 0 else newline
    return passage[low:high].strip()


def by_rank(ranked: list) -> list:
    """Several rankings as one list: the best of each before the second
    best of any. Of the passages of several documents, each document's
    best is then asked about before anybody's second."""
    return [hits[rank] for rank in range(max(map(len, ranked), default=0))
            for hits in ranked if rank < len(hits)]


def lacking(raw_spec: dict, only: Optional[list] = None) -> list:
    """The parameters a proposal is wanted for."""
    return [parameter for parameter in raw_spec.get("parameters") or ()
            if (parameter.get("uri") in only if only
                else not parameter.get("example"))]


def propose(raw_spec: dict, find: Callable, ask: Callable, *,
            only: Optional[list] = None, per_parameter: int = 2,
            passages: int = 6) -> dict:
    """The review file's content: per parameter, the proposals that carry
    their evidence, and a count of what was read and dropped."""
    out: dict = {}
    for parameter in lacking(raw_spec, only):
        name = parameter["uri"]
        entry = {"label": parameter.get("label"), "proposals": [],
                 "passages_read": 0, "dropped": {}}
        for found in find(parameter)[:passages]:
            if len(entry["proposals"]) >= per_parameter:
                break
            text = found.get("text") or ""
            if len(text.split()) < 5:
                continue
            reply = ask(parameter, text)
            if not isinstance(reply, dict) \
                    or not isinstance(reply.get("tuples"), list):
                # No reply that could be read: the passage was not read,
                # and the count says why (`ask` gives the cause as a text).
                why = NO_REPLY + ":" + (reply if isinstance(reply, str)
                                        else "not_served" if reply is None
                                        else "wrong_shape")
                entry["dropped"][why] = entry["dropped"].get(why, 0) + 1
                continue
            entry["passages_read"] += 1
            kept, dropped = checked(reply["tuples"], text, parameter)
            # An example shows a part of its passage. A tuple whose quote
            # is not in that part would be refused when it is applied, so
            # it is not proposed.
            source = snippet(text, [t["quote"] for t in kept])
            shown = [t for t in kept if quote_in(source, t["quote"])]
            dropped += [(t, NOT_SHOWN) for t in kept if t not in shown]
            for _raw, why in dropped:
                entry["dropped"][why] = entry["dropped"].get(why, 0) + 1
            if not shown:
                continue
            entry["proposals"].append({
                "accept": False,
                "document": found.get("document"),
                "where": found.get("where"),
                "source": source,
                "tuples": shown,
            })
        log.info("%s: %d proposal(s) from %d passage(s)", name,
                 len(entry["proposals"]), entry["passages_read"])
        out[name] = entry
    return {"_comment": (
        "Proposed by a model from the corpus and checked for their quotes. "
        "Read each one, edit it where it is wrong, set \"accept\": true on "
        "the one to keep per parameter, and run `docpipe compile apply`."),
        "parameters": out}


def apply(raw_spec: dict, review: dict) -> tuple:
    """(the spec with the accepted examples, the parameters that got one,
    what stands in the way). Nothing is written where something does."""
    out = copy.deepcopy(raw_spec)
    by_uri = {parameter.get("uri"): parameter
              for parameter in out.get("parameters") or ()}
    applied, problems = [], []
    for name, entry in (review.get("parameters") or {}).items():
        accepted = [proposal for proposal in entry.get("proposals") or ()
                    if proposal.get("accept") is True]
        if not accepted:
            continue
        if name not in by_uri:
            problems.append(f"{name}: the spec has no such parameter")
            continue
        if len(accepted) > 1:
            problems.append(f"{name}: {len(accepted)} proposals are "
                            f"accepted; a parameter has one example")
            continue
        parameter, chosen = by_uri[name], accepted[0]
        example = {"source": chosen.get("source"),
                   "tuples": chosen.get("tuples")}
        # An accepted proposal may have been edited by hand, so it is held
        # to its evidence again, and to what the spec's loader asks of it.
        kept, dropped = checked(example["tuples"], example["source"] or "",
                                parameter)
        if dropped or not kept:
            why = ", ".join(sorted({reason for _raw, reason in dropped})) \
                or "no tuple"
            problems.append(f"{name}: the accepted example does not carry "
                            f"its own evidence ({why})")
            continue
        try:
            spec_module._validate_example(
                f"{name}.example", example,
                parameter.get("value_type", "float"),
                parameter.get("units_accepted") or {})
        except spec_module.SpecError as exc:
            problems.append(str(exc))
            continue
        parameter["example"] = example
        applied.append(name)
    return (raw_spec if problems else out), applied, problems


def write_review(path: Path, review: dict) -> None:
    Path(path).write_text(json.dumps(review, ensure_ascii=False, indent=1)
                          + "\n", encoding="utf-8")
