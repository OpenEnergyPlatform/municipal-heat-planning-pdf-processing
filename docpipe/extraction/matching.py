"""
matching.py: The entry of a list that a wording the document prints is, asked
in a request of its own (owner decision 2026-11-05).

A list the spec marks `matched_apart` (the AR6 runs of one publication) is
not shown to the reading: the reading reads the wording the document prints,
with its quote, as it reads a free-text coordinate. Once a wording is read,
one request asks which entry of the document's list it is, shown the list,
the passage the wording stands in, the text around a table or figure, the
wording and its quote (`extraction/match`). The entry becomes the answer and
the wording its `value_raw`, and the check runs as on any closed list
(`pipeline.merge_field`, `verify.value_refused`). A reply that is no entry
is asked once more with the reason (`not_an_option`); one still none leaves
the entry empty and keeps the wording, as an answer whose entry the model is
unsure of (`verify._check_value`: unmapped; `merge_field`: the wording
seen). Every wording read is matched on its own: no answer is kept for the
next wording of the same name. A value stated for several wordings is one
row per wording, each matched on its own (`reading.answers_each`, owner
decision 2026-11-06), and no reading request shows the entry a wording was
matched to (`reading.printed`).

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Callable, Optional

from . import fields
from .pipeline import Source, option_named
from .wording import say

MATCH_PROMPT_ID = "extraction/match"


def matched_apart(spec) -> bool:
    """Does *spec* hold a list matched apart, a parameter's own or an
    axis'?"""
    return any(getattr(parameter, "matched_apart", False)
               or any(getattr(axis, "matched_apart", False)
                      for axis in parameter.axes.values())
               for parameter in spec.parameters)


def options_of(slot) -> dict:
    """The entries a wording may be, as a request shows a closed list,
    without UNSTATED: a wording was read, so the document states it."""
    return {label: entry for label, entry in slot.answerable().items()
            if label != fields.UNSTATED}


def match_payload(slot, name: str, quote, source: Source,
                  around: Optional[str] = None,
                  corrections: Optional[list] = None) -> dict:
    """One request: what the requests of a document share first, the list,
    then the passage and the text around it, the wording and its quote
    last; with *corrections* the same request asked once more."""
    payload = {"options": options_of(slot),
               "source": {"kind": source.owner_kind,
                          "section": (source.provenance or {}).get(
                              "section_title"),
                          "text": source.text},
               **({"around": around} if around else {}),
               "name": name, "quote": quote}
    if corrections:
        payload["corrections"] = corrections
    return payload


def match_response_format(slot) -> dict:
    """One entry of the list."""
    schema = {"type": "object",
              "properties": {"value": {"enum": list(options_of(slot))}},
              "required": ["value"], "additionalProperties": False}
    return {"type": "json_schema",
            "json_schema": {"name": "match_reply", "schema": schema}}


class Matcher:
    """(document_id, parameter, slot, name, quote, source, around) -> the
    entry of *slot*'s list the wording *name* is, or "" where none is.

    *ask(payload, shape, document_id, source, parameter)* is one request:
    the reply as a dict, CUT, or None.
    """

    def __init__(self, ask: Callable):
        self.ask = ask

    def __call__(self, document_id: int, parameter, slot, name: str, quote,
                 source: Source, around: Optional[str] = None) -> str:
        shape = match_response_format(slot)
        corrections = None
        for _ in range(2):
            reply = self.ask(match_payload(slot, name, quote, source, around,
                                           corrections),
                             shape, document_id, source, parameter)
            if not isinstance(reply, dict):
                return ""
            given = reply.get("value")
            if option_named(slot, given) is not None:
                return given
            corrections = [{"value": given,
                            "what": say("not_an_option", given=given)}]
        return ""


def matched(match: Optional[Callable], document_id: int, parameter,
            slots: list, answers: dict, source: Source,
            around: Optional[str] = None) -> dict:
    """*answers*, {coordinate: answer}, with the wording of each list
    matched apart replaced by its entry (`Matcher`), the wording kept as
    `value_raw`. An answer that says the document does not state it, or
    names nothing, stays as it is; so does every answer without *match*."""
    if match is None:
        return answers
    out = dict(answers)
    for slot in slots:
        entry = out.get(slot.name)
        if not slot.matched_apart or not slot.is_closed \
                or not isinstance(entry, dict):
            continue
        name = entry.get("value")
        if not isinstance(name, str) or not name.strip() \
                or name.strip() == fields.UNSTATED:
            continue
        wording = entry.get("value_raw")
        out[slot.name] = {
            **entry,
            "value": match(document_id, parameter, slot, name.strip(),
                           entry.get("quote"), source, around),
            "value_raw": wording.strip() if isinstance(wording, str)
            and wording.strip() else name.strip()}
    return out
