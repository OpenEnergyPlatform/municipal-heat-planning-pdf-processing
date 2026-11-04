"""
lookup.py: What the model may ask of the rest of one document, resolved by
code. Pure functions over the document's passages in reading order, no model
call and no judgement of a value.

The model names what it wants (the next section, a table by its placeholder,
a pattern); these functions find it or say why they cannot. A name that fits
nothing, or fits two passages, is None, never a guess.

Author: Felix Vossel
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import regex

from .pipeline import Source

# A pattern is written by the model and can backtrack without end; the search
# gives up after this many seconds and reports it instead of hanging the run.
PATTERN_TIMEOUT_S = 1.0

# Characters kept on each side of the match in a hit's line.
NEIGHBOURHOOD = 60

_ITEM_KINDS = ("table", "figure")


def following(passages: list[Source], owner: tuple[str, int],
              step: int = 1) -> Optional[Source]:
    """The `step`-th section after `owner` in reading order (before it for a
    negative step), tables and figures skipped. A table or figure counts from
    its own position. None past either end, for step 0, and when `owner` is
    not in `passages`."""
    if step == 0:
        return None
    at = next((i for i, p in enumerate(passages)
               if (p.owner_kind, p.owner_id) == tuple(owner)), None)
    if at is None:
        return None
    direction = 1 if step > 0 else -1
    left = abs(step)
    i = at + direction
    while 0 <= i < len(passages):
        if passages[i].owner_kind == "section":
            left -= 1
            if left == 0:
                return passages[i]
        i += direction
    return None


def _block_id(name: str) -> str:
    """`p17_img1`, `[p17_img1]` and `[p17_img1: Abbildung 2-3 ...]` all name
    p17_img1."""
    name = (name or "").strip()
    if name.startswith("["):
        name = name[1:]
    return name.split(":", 1)[0].strip().strip("[]").strip()


def item(passages: list[Source], block_id: str) -> Optional[Source]:
    """The table or figure whose placeholder is `block_id`, in any form the
    text prints it. None when no passage carries it and when two do: a block
    id is unique within a document only by convention."""
    wanted = _block_id(block_id)
    if not wanted:
        return None
    found = [p for p in passages
             if p.owner_kind in _ITEM_KINDS
             and (p.provenance or {}).get("block_id") == wanted]
    return found[0] if len(found) == 1 else None


@dataclass
class Matches:
    """`hits` are the passages that fit in `room`, `total` how many passages
    matched at all (so the caller can say the list is cut). `fault` is None,
    "invalid_pattern" or "timeout"; `detail` is the reason to pass back."""
    hits: list[dict]
    total: int = 0
    fault: Optional[str] = None
    detail: str = ""


def title_of(p: Source) -> str:
    prov = p.provenance or {}
    return (prov.get("title") or prov.get("section_title")
            or (p.text or "").split("\n", 1)[0]).strip()


def _neighbourhood(text: str, found) -> str:
    start, end = found.span()
    end = min(end, start + 2 * NEIGHBOURHOOD)
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    lo = max(line_start, start - NEIGHBOURHOOD)
    hi = min(line_end, end + NEIGHBOURHOOD)
    return text[lo:hi].strip()


def matching(passages: list[Source], pattern: str, room: int) -> Matches:
    """The passages whose text matches `pattern` (case-insensitive), each as
    {"owner": [kind, id], "title", "line"}, in reading order, as many as fit
    in `room` characters of JSON; `total` counts every matching passage. An
    invalid pattern and a pattern that times out come back as `fault` with
    no hits, never as an exception."""
    try:
        compiled = regex.compile(pattern, regex.IGNORECASE | regex.MULTILINE)
    except (regex.error, TypeError, ValueError) as exc:
        return Matches([], 0, "invalid_pattern", str(exc))
    hits: list[dict] = []
    total = used = 0
    full = False
    for p in passages:
        try:
            found = compiled.search(p.text or "", timeout=PATTERN_TIMEOUT_S)
        except TimeoutError:
            return Matches([], 0, "timeout",
                           f"no result within {PATTERN_TIMEOUT_S} s")
        if not found:
            continue
        total += 1
        if full:
            continue
        hit = {"owner": [p.owner_kind, p.owner_id], "title": title_of(p),
               "line": _neighbourhood(p.text, found)}
        cost = len(json.dumps(hit, ensure_ascii=False))
        if used + cost > room:
            full = True
            continue
        used += cost
        hits.append(hit)
    return Matches(hits, total)