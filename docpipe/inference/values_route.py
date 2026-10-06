"""
values_route.py: Answers a question for a number from the harvest, before
the documents are searched.

A question like "how much gas in 2030?" names a parameter and some of its
coordinates. The harvest has read exactly those out of the documents, each
with its quote, its page and a trust level. So the number is not looked for
a second time and not written by a model: the question is turned into the
parameter and the coordinates it names, and the values the harvest holds
for them are shown as they are (`docpipe/serve/values.py`).

The route does not guess. Which parameter and which coordinates the
question names is one closed question each over the spec's own lists (the
harvest's rule: one request per field, chosen from the list). An answer
outside the list leaves the coordinate open, and an open coordinate narrows
nothing. A question that names no parameter is not one for this route, and
the caller searches the documents as before.

Unlike `kg_route` this needs no graph and no query of the profile's: the
harvest and the spec are enough, so it works for every profile that has
both, across one document or all of them.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from . import kg_route

# The profile's prompt for one closed question, shared with the graph route.
COORDINATE_PROMPT_ID = kg_route.COORDINATE_PROMPT_ID

# Why the route did not answer. `no_store`: there is no harvest to ask.
# `no_parameter`: the question names none of the spec's parameters.
# `no_values`: the harvest holds nothing for what the question names.
REASONS = ("no_store", "no_parameter", "no_values")
DEFAULT_LIMIT = 50


def _fallback(reason: str, parameter=None,
              coordinates: Optional[dict] = None) -> dict:
    assert reason in REASONS, reason
    return {"route": "rag", "reason": reason, "values": [], "total": 0,
            "parameter": parameter, "coordinates": coordinates or {}}


def answer_from_values(task: str, store, *, ask,
                       document: Optional[str] = None,
                       level: Optional[str] = None,
                       limit: int = DEFAULT_LIMIT) -> dict:
    """The harvest's answer, or why there is none.

    {"route": "values", "reason": None, "values": [...], "total": n,
     "parameter": uri, "coordinates": {...}} when the harvest holds values
    for what the question names; otherwise route "rag" with one of REASONS.
    *document* limits it to one document (its harvest name); None asks the
    whole corpus. *ask(task, slot)* answers one closed question with one
    label or None. *level* is the worst trust level still shown.
    """
    if store is None or store.spec is None or not len(store):
        return _fallback("no_store")
    parameter = kg_route.parameter_of(task, store.spec, ask)
    if parameter is None:
        return _fallback("no_parameter")
    coordinates = kg_route.coordinates_of(task, parameter, ask)
    found = store.find(document=document, parameter=parameter.uri,
                       coordinates=coordinates, level=level, limit=limit)
    if not found["total"]:
        return _fallback("no_values", parameter.uri, coordinates)
    return {"route": "values", "reason": None, "values": found["values"],
            "total": found["total"], "parameter": parameter.uri,
            "coordinates": coordinates}


def as_passages(values: list) -> list:
    """The values as lines a model can be shown and a reader can check:
    what was read, for which coordinates, on which page, from which words.
    """
    lines = []
    for value in values:
        number = value.get("value")
        unit = value.get("unit") or ""
        label = value.get("label") or value.get("parameter")
        about = ", ".join(
            f"{name}: {coordinate.get('label') or coordinate.get('value')}"
            for name, coordinate in sorted(
                (value.get("coordinates") or {}).items())
            if coordinate.get("value") not in (None, ""))
        where = value["document"]
        if value.get("page") is not None:
            where += f", p. {value['page']}"
        lines.append({
            "id": value["id"],
            "text": f"{label}: {number} {unit}".strip()
                    + (f" ({about})" if about else ""),
            "where": where, "quote": value.get("quote"),
            "level": value["level"], "reasons": value["reasons"]})
    return lines
