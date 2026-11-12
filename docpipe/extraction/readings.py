"""
readings.py: Which reading of a value the graph takes, where a document
has several.

Three parts of the program that writes a drawing (`graph.py`), each with
the rules of the graph file it reads:

- the pages a publication states itself on (`front_pages`, `in_order`):
  for the fields of the rule `front_first_fields` a reading on a front page
  goes first, then the catalogue's record, then any other (owner decisions
  2026-11-05);
- one reading where the shapes allow one (`pick_one`): the one the most
  sources agree on, a tie to the one located on its page, then to the
  longer, and a reading contained in another never wins (rule
  `pick_one_order`);
- the numbers of one address (`settle`): one number several times is one
  node, different numbers are told apart by the plan's wording, a rounded
  statement loses to the precise one (rule `rounding_tolerance`), a lower
  trust level to the higher, and what is left is either kept as nodes
  marked contested (rule `contested_in_full`, the full graph) or left out
  (the order of these decisions is the rule `settle_order`).

Every choice stands in a rule of the graph file, handed in by `graph.py` and
by the profile's front page code where it is used (`RULES`).

Author: Felix Vossel
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Optional

from ..rules import rule
from .trust import CATALOGUE, LEVELS, trust

_RANK = {level: rank for rank, level in enumerate(LEVELS)}


# -- the front pages --

def page_of(row: dict) -> Optional[int]:
    """The page a row was read on, None where it names none."""
    try:
        return int((row.get("provenance") or {}).get("page"))
    except (TypeError, ValueError):
        return None


def front_pages(titles: list, *, which: str, extra: int) -> set:
    """The front pages: page 1 and the first page the document's title was
    read on (*titles*, its rows of the title), its title page, where a cover
    stands before it, as *which* says (rule `front_pages_rule`), and the
    *extra* pages after each of them (rule `front_pages_extra`)."""
    pages = [page for page in map(page_of, titles) if page is not None]
    first = {1} if which != "title page" else set()
    title = {min(pages)} if pages and which != "first page" else set()
    found = (first | title) or {1}
    return found | {page + step for page in found
                    for step in range(1, int(extra) + 1)}


def looked_up(row: dict) -> bool:
    """Whether *row* holds a value looked up outside the document
    (`completion.row_of`). Such a row keeps the page of the reading it was
    found with, so its page says nothing of where its value stands."""
    return CATALOGUE in (row.get("flags") or ()) \
        or isinstance(row.get("catalogue"), dict)


def read_in_front(rows: list, front: set) -> list:
    """The rows of *rows* read on one of the *front* pages."""
    return [row for row in rows
            if not looked_up(row) and page_of(row) in front]


def in_order(rows: list, front: set, order: list) -> list:
    """The readings of a front field that count: the first of the ways in
    *order* (rule `front_order`) that has any. "front": those read on a
    *front* page, "catalogue": those looked up in the catalogue, "any":
    every one of *rows*."""
    ways = {"front": lambda: read_in_front(rows, front),
            "catalogue": lambda: [row for row in rows if looked_up(row)],
            "any": lambda: list(rows)}
    for way in order:
        found = ways[way]()
        if found:
            return found
    return []


# -- one reading --

def pick_one(rows: list, order: list) -> tuple:
    """(value, how many other readings were offered) for a field the shapes
    allow once, decided by the checks of *order* (rule `pick_one_order`).

    "not_contained": a reading contained in another never wins. A running
    header is a prefix of the title and is harvested from every page it
    stands on, so it outvotes the one reading that was located on the title
    page, and the truncation then becomes the document's IRI, stably, on
    every re-run. "most_sources": the reading the most sources agree on
    wins. "located": a tie goes to the one that could be located on its PDF
    page. "longer": then to the longer text, because a truncated title is a
    common failure and the full one is never the shorter reading of the same
    passage. What is left stays in the order the readings came in.
    """
    by_value: dict = {}
    for row in rows:
        by_value.setdefault(row["value"], []).append(row)
    if "not_contained" in order:
        contained = [value for value in by_value
                     if any(value != other and value in other
                            for other in by_value)]
        if len(contained) < len(by_value):
            for value in contained:
                del by_value[value]
    criteria = {
        "most_sources": lambda kv: len(kv[1]),
        "located": lambda kv: any(r.get("provenance", {}).get("rects")
                                  for r in kv[1]),
        "longer": lambda kv: len(kv[0])}
    wanted = [criteria[name] for name in order if name in criteria]
    ranked = sorted(by_value.items(),
                    key=lambda kv: tuple(one(kv) for one in wanted),
                    reverse=True)
    return ranked[0][0], len(ranked) - 1


# -- the numbers of one address --

def place(row: dict) -> tuple:
    """The passage a row was read from, where the plan prints its number."""
    provenance = row.get("provenance") or {}
    return provenance.get("owner_kind"), provenance.get("owner_id")


def precision(row: dict) -> int:
    """Significant digits of the number as the document printed it."""
    printed = (row.get("value") if row.get("value") is not None
               else row.get("value_target"))
    try:
        digits = re.sub(r"[^0-9]", "", format(float(printed), "f"))
    except (TypeError, ValueError):
        digits = re.sub(r"[^0-9]", "", str(printed))
    return len(digits.strip("0")) or len(digits)


def wording_key(row: dict, fields: tuple) -> str:
    """The document's words for what tells two numbers on one address
    apart, the *fields* of the row joined: "Wirtschaftlich genutzte
    Gebäude" and "Öffentliche Gebäude" are one class and not one number."""
    return " / ".join(str(row.get(key) or "").strip()
                      for key in fields).strip(" /")


def settle(iri: str, rows: list, address: Callable, *, fold: Callable,
           wording: tuple, tolerance: float, order: list,
           corroborate: bool, transcribed: bool = False,
           keep_open: bool = False) -> tuple:
    """({iri: row} kept, Counter skipped, {iri: marks}) for one address.

    *address(row, label)* names a node split off by its wording or kept as
    contested, *fold* is the graph's folding of a name. One number several
    times is one node, marked as confirmed where a second passage prints it
    (only with *corroborate*, rule `corroborated_by_place`): one passage
    read twice is one statement, whatever its quotes (owner decision
    2026-11-05). Different numbers are settled in the order of *order* (rule
    `settle_order`, standard from owner decision 2026-09-23): "wording", the
    document's different wording splits them into a node each, named by that
    wording; "rounding", a rounded statement of the other loses to the more
    precise one; "trust", a lower trust grade loses to the higher; and
    "contested", what is left is a question for a human. With *keep_open*
    each of those stays as a node of its own, marked as contested (owner
    decision 2026-11-02); without it, as for the strict graph, nothing
    stays. A decision not in *order* is not made. The counts are per tuple
    that left the graph: a repeat of the winner is a `duplicate`, a repeat
    of a loser is one too, and the losers are `conflict:<rule>`.
    `conflict:open` counts nodes kept, not tuples lost.
    """
    kept: dict = {}
    skipped: Counter = Counter()
    marks: dict = {}
    claims: dict = {}
    for row in rows:
        claims.setdefault(row["value_target"], []).append(row)

    def keep(row: dict, **mark) -> None:
        kept[iri] = row
        if corroborate and len(
                {place(other) for other in claims[row["value_target"]]}) > 1:
            mark["corroborated"] = True
        if mark:
            marks[iri] = mark

    def split() -> bool:
        by_wording: dict = {}
        for row in rows:
            by_wording.setdefault(fold(wording_key(row, wording)),
                                  []).append(row)
        if len(by_wording) < 2:
            return False
        for key, group in by_wording.items():
            label = wording_key(group[0], wording)
            sub_iri = address(group[0], key)
            got, lost, named = settle(
                sub_iri, group, address, fold=fold, wording=wording,
                tolerance=tolerance, order=order, corroborate=corroborate,
                transcribed=transcribed, keep_open=keep_open)
            kept.update(got)
            skipped.update(lost)
            for node in got:
                marks[node] = dict(named.get(node, {}), named=label)
        skipped["split:wording"] += 1
        return True

    if len(claims) == 1:
        skipped["duplicate"] += len(rows) - len(claims)
        keep(rows[0])
        return kept, skipped, marks
    distinct = [group[0] for group in claims.values()]
    for decision in order:
        if decision == "wording" and split():
            return kept, skipped, marks
        if decision == "rounding":
            low, high = min(claims), max(claims)
            if high and (high - low) / abs(high) <= tolerance:
                best = max(precision(r) for r in distinct)
                top = [r for r in distinct if precision(r) == best]
                if len(top) == 1:
                    skipped["duplicate"] += len(rows) - len(claims)
                    keep(top[0], resolved="rounding")
                    skipped["conflict:rounding"] += len(distinct) - 1
                    return kept, skipped, marks
        if decision == "trust":
            graded = [(_RANK[trust(r, transcribed=transcribed)["level"]],
                       i, r) for i, r in enumerate(distinct)]
            best_rank = min(g[0] for g in graded)
            winners = [g for g in graded if g[0] == best_rank]
            if len(winners) == 1:
                skipped["duplicate"] += len(rows) - len(claims)
                keep(winners[0][2], resolved="trust")
                skipped["conflict:trust"] += len(distinct) - 1
                return kept, skipped, marks
        if decision == "contested":
            if not keep_open:
                break
            skipped["duplicate"] += len(rows) - len(claims)
            for row in distinct:
                node = address(row, "|".join((
                    wording_key(row, wording), fold(row.get("quote") or ""),
                    str(row["value_target"]))))
                kept[node] = row
                marks[node] = {"conflict": True}
            skipped["conflict:open"] += len(distinct)
            return kept, skipped, marks
    skipped["duplicate"] += len(rows) - len(claims)
    skipped["conflict"] += len(distinct)
    return kept, skipped, marks


# -- the rules these choices are --
# Declared in the `GRAPH` of each profile that uses them (`graphfile`), their
# values in its graph.json; read where a choice is made, never earlier.

GROUP = "One value, several occurrences"

RULES = (
    rule("pick_one_order", "graph", GROUP, "texts",
         "How the graph chooses between several readings of a field it may "
         "write only once, such as a title or a name. The list gives the "
         "checks in the order they are made. not_contained drops a reading "
         "that is part of a longer one, because that is usually a cut-off "
         "title or a running header. most_sources prefers the reading that "
         "most sources agree on. located prefers a reading that could be "
         "found on its page of the PDF. longer prefers the longer text. "
         "Each check only matters where the checks before it leave a tie. "
         "A check that is removed is not made, and where every check ties "
         "the reading that came first wins.",
         choices=("not_contained", "most_sources", "located", "longer"),
         empty=True, where="docpipe/extraction/readings.py (pick_one)"),
    rule("settle_order", "graph", "One number, several readings", "texts",
         "In which order the graph decides between different numbers that "
         "one place of the graph would hold. wording gives each number the "
         "plan's own words for what it counts, so that two classes of "
         "buildings stay two numbers. rounding keeps the more precise of "
         "two numbers that differ only by rounding (see rounding_tolerance). "
         "trust keeps the number with the better trust level. contested "
         "keeps what is still left as numbers marked as contested (see "
         "contested_in_full), or leaves them out. The first decision that "
         "settles the numbers ends the matter. A decision that is removed "
         "is not made. Decided on 2026-09-23.",
         choices=("wording", "rounding", "trust", "contested"), empty=True,
         decided="2026-09-23",
         where="docpipe/extraction/readings.py (settle)"),
    rule("corroborated_by_place", "graph", "One number, several readings",
         "switch",
         "On: a value that two different passages of the document print, "
         "a number or a name, is marked as confirmed. The same passage "
         "read twice counts once, whatever its quotes. Off: no value is "
         "marked as confirmed. Decided on 2026-11-05.",
         decided="2026-11-05",
         where="docpipe/extraction/readings.py (settle), graph.py "
               "(_evidence)"),
)

FRONT_RULES = (
    rule("front_pages_rule", "graph", GROUP, "choice",
         "Which pages count as the front pages of a publication: its first "
         "page and the page its title was read on, its first page only, or "
         "its title page only. Decided on 2026-11-05.",
         choices=("first page and title page", "first page", "title page"),
         decided="2026-11-05",
         where="docpipe/extraction/readings.py (front_pages)"),
    rule("front_pages_extra", "graph", GROUP, "whole",
         "How many pages after each front page count as front pages too. 0 "
         "means only the front pages themselves. A larger number helps "
         "where a title, its authors and its date stand over several pages "
         "of a publication, and may take a value from a page that belongs "
         "to another work.",
         least=0, most=20,
         where="docpipe/extraction/readings.py (front_pages)"),
    rule("front_order", "graph", GROUP, "texts",
         "In which order the readings of a front field count: those read "
         "on a front page (front), those looked up in the catalogue "
         "(catalogue) and any other reading (any). The first of them that "
         "has a reading decides. Remove one to never take from it. Decided "
         "on 2026-11-05.",
         choices=("front", "catalogue", "any"), decided="2026-11-05",
         where="docpipe/extraction/readings.py (in_order)"),
)
