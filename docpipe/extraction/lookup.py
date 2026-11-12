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

from .. import rules
from .pipeline import Source

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


def fetch_run(passages: list[Source], owner: tuple[str, int],
              forward: bool) -> list[Source]:
    """The sections an ask for "next" (*forward*) or "previous" brings in
    one go: as many as the rule `fetch_next` says, each the one after the
    one before it (`following`), fewer where the plan ends first. The
    nearest to *owner* first."""
    out: list[Source] = []
    here = tuple(owner)
    for _ in range(rules.get("fetch_next")):
        found = following(passages, here, 1 if forward else -1)
        if found is None:
            break
        out.append(found)
        here = (found.owner_kind, found.owner_id)
    return out


def sections_up_to(passages: list[Source], owner: tuple[str, int],
                   count: int) -> list[Source]:
    """The last `count` sections in reading order up to `owner`, its own
    included where it is a section, the earliest first; a table or figure
    counts from its own position, so its own section is the last. [] when
    `owner` is not in `passages`."""
    at = next((i for i, p in enumerate(passages)
               if (p.owner_kind, p.owner_id) == tuple(owner)), None)
    if at is None or count <= 0:
        return []
    out = [p for p in passages[:at + 1] if p.owner_kind == "section"]
    return out[-count:]


def page_of(passage: Source) -> Optional[int]:
    """The page a passage starts on, None where it names none."""
    try:
        return int((passage.provenance or {}).get("page"))
    except (TypeError, ValueError):
        return None


def head_of(text: str) -> str:
    """A transcribed table's title and head: its lines down to the rule that
    closes the head, the rule included; "" where it has no head."""
    lines = (text or "").splitlines()
    for at, line in enumerate(lines):
        line = line.strip()
        if line.count("|") >= 2 and "-" in line and set(line) <= set("|:- \t"):
            head = [one for one in lines[:at] if one.count("|") >= 2]
            return "\n".join(lines[:at + 1]).strip() if head else ""
    return ""


def continued(passages: list[Source]) -> list[Source]:
    """*passages*, a document's in reading order, each table that may
    continue the table right before it marked with that table's title and
    head (provenance "table_before": {"owner", "text"}). Owner decisions
    2026-11-06 and 2026-11-07: a table the layout cut in parts, at a page
    break or within a page, loses its title, head and unit in its later
    parts, and whether it is the same table is the model's reading. A table
    may continue the table right before it when that table stands on its
    page or up to the rule `table_continues_pages` pages before and has a
    transcribed head; what stands between
    them, a heading included, does not part them. The transcription asks
    and joins by the same rule (`docpipe.visuals.continuation`)."""
    out: list = []
    previous: Optional[Source] = None
    for passage in passages:
        if passage.owner_kind == "table":
            page = page_of(passage)
            head = head_of(previous.text) if previous is not None else ""
            before = page_of(previous) if previous is not None else None
            if (head and page is not None and before is not None
                    and page - rules.get("table_continues_pages")
                    <= before <= page):
                passage = Source(
                    passage.owner_kind, passage.owner_id, passage.text,
                    {**(passage.provenance or {}), "table_before": {
                        "owner": [previous.owner_kind, previous.owner_id],
                        "text": head}},
                    passage.image_path, passage.body)
            previous = passage
        out.append(passage)
    return out


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
    """The hit's line with the characters of the rule `pattern_hit_chars` on
    each side of the match."""
    around = rules.get("pattern_hit_chars")
    start, end = found.span()
    end = min(end, start + 2 * around)
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    lo = max(line_start, start - around)
    hi = min(line_end, end + around)
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
    # A pattern is written by the model and can backtrack without end: the
    # search gives up after the rule `pattern_timeout_s` seconds on one
    # passage and reports it instead of hanging the run.
    limit = rules.get("pattern_timeout_s")
    for p in passages:
        try:
            found = compiled.search(p.text or "", timeout=limit)
        except TimeoutError:
            return Matches([], 0, "timeout",
                           f"no result within {limit} s")
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


def two_pages(passages: list, pages: Optional[int],
              span: Optional[float] = None) -> int:
    """The text of *span* pages of this plan, in characters: *span* times
    its mean; the rule `compute_fetch_pages` pages unless said otherwise.
    What the compute step cuts a passage it fetches to. A figure's
    description is not counted: a figure is never cut, whatever its
    description's length."""
    if span is None:
        span = rules.get("compute_fetch_pages")
    chars = sum(len(p.text or "") for p in passages
                if p.owner_kind != "figure")
    if not pages:
        pages = max([(p.provenance or {}).get("page") or 0
                     for p in passages] or [0])
    return max(1, round(span * chars / max(pages or 1, 1)))
