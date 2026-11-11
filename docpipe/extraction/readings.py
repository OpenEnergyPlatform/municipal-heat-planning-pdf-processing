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
  longer, and a reading contained in another never wins;
- the numbers of one address (`settle`): one number several times is one
  node, different numbers are told apart by the plan's wording, a rounded
  statement loses to the precise one (rule `rounding_tolerance`), a lower
  trust level to the higher, and what is left is either kept as nodes
  marked contested (rule `contested_in_full`, the full graph) or left out.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Optional

from .trust import CATALOGUE, LEVELS, trust

_RANK = {level: rank for rank, level in enumerate(LEVELS)}


# -- the front pages ---------------------------------------------------------

def page_of(row: dict) -> Optional[int]:
    """The page a row was read on, None where it names none."""
    try:
        return int((row.get("provenance") or {}).get("page"))
    except (TypeError, ValueError):
        return None


def front_pages(titles: list) -> set:
    """Page 1 and the first page the document's title was read on (*titles*,
    its rows of the title): its title page, where a cover stands before
    it."""
    pages = [page for page in map(page_of, titles) if page is not None]
    return {1, min(pages)} if pages else {1}


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


def in_order(rows: list, front: set) -> list:
    """The readings of a front field that count: those read on a *front*
    page where there are any, else those looked up in the catalogue, else
    every one of *rows*."""
    return (read_in_front(rows, front)
            or [row for row in rows if looked_up(row)] or list(rows))


# -- one reading -------------------------------------------------------------

def pick_one(rows: list) -> tuple:
    """(value, how many other readings were offered) for a field the shapes
    allow once.

    The reading the most sources agree on wins. A tie goes to the one that
    could be located on its PDF page, then to the longer text: a truncated
    title is a common failure and the full one is never the shorter reading
    of the same passage.
    """
    by_value: dict = {}
    for row in rows:
        by_value.setdefault(row["value"], []).append(row)
    # A running header is a prefix of the title and is harvested from every
    # page it stands on, so it outvotes the one reading that was located on
    # the title page -- and the truncation then becomes the document's IRI,
    # stably, on every re-run. A candidate contained in another candidate is
    # that truncation, and it never wins.
    contained = [value for value in by_value
                 if any(value != other and value in other
                        for other in by_value)]
    if len(contained) < len(by_value):
        for value in contained:
            del by_value[value]
    ranked = sorted(
        by_value.items(),
        key=lambda kv: (len(kv[1]),
                        any(r.get("provenance", {}).get("rects")
                            for r in kv[1]),
                        len(kv[0])),
        reverse=True)
    return ranked[0][0], len(ranked) - 1


# -- the numbers of one address ----------------------------------------------

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
           wording: tuple, tolerance: float, transcribed: bool = False,
           keep_open: bool = False) -> tuple:
    """({iri: row} kept, Counter skipped, {iri: marks}) for one address.

    *address(row, label)* names a node split off by its wording or kept as
    contested, *fold* is the graph's folding of a name. One number several
    times is one node, marked as confirmed where a second passage prints it:
    one passage read twice is one statement, whatever its quotes (owner
    decision 2026-11-05). Different numbers are settled in this order (owner
    decision 2026-09-23): the document's different wording splits them into
    a node each, named by that wording; a rounded statement of the other
    loses to the more precise one; a lower trust grade loses to the higher;
    and what is left is a question for a human. With *keep_open* each of
    those stays as a node of its own, marked as contested (owner decision
    2026-11-02); without it, as for the strict graph, nothing stays. The
    counts are per tuple that left the graph: a repeat of the winner is a
    `duplicate`, a repeat of a loser is one too, and the losers are
    `conflict:<rule>`. `conflict:open` counts nodes kept, not tuples lost.
    """
    kept: dict = {}
    skipped: Counter = Counter()
    marks: dict = {}
    targets = {r["value_target"] for r in rows}
    by_wording: dict = {}
    for row in rows:
        by_wording.setdefault(fold(wording_key(row, wording)), []).append(row)
    if len(targets) > 1 and len(by_wording) > 1:
        for key, group in by_wording.items():
            label = wording_key(group[0], wording)
            sub_iri = address(group[0], key)
            got, lost, named = settle(sub_iri, group, address, fold=fold,
                                      wording=wording, tolerance=tolerance,
                                      transcribed=transcribed,
                                      keep_open=keep_open)
            kept.update(got)
            skipped.update(lost)
            for node in got:
                marks[node] = dict(named.get(node, {}), named=label)
        skipped["split:wording"] += 1
        return kept, skipped, marks
    claims: dict = {}
    for row in rows:
        claims.setdefault(row["value_target"], []).append(row)
    skipped["duplicate"] += len(rows) - len(claims)

    def keep(row: dict, **mark) -> None:
        kept[iri] = row
        if len({place(other) for other in claims[row["value_target"]]}) > 1:
            mark["corroborated"] = True
        if mark:
            marks[iri] = mark

    if len(claims) == 1:
        keep(rows[0])
        return kept, skipped, marks
    distinct = [group[0] for group in claims.values()]
    low, high = min(claims), max(claims)
    if high and (high - low) / abs(high) <= tolerance:
        best = max(precision(r) for r in distinct)
        top = [r for r in distinct if precision(r) == best]
        if len(top) == 1:
            keep(top[0], resolved="rounding")
            skipped["conflict:rounding"] += len(distinct) - 1
            return kept, skipped, marks
    graded = [(_RANK[trust(r, transcribed=transcribed)["level"]], i, r)
              for i, r in enumerate(distinct)]
    best_rank = min(g[0] for g in graded)
    winners = [g for g in graded if g[0] == best_rank]
    if len(winners) == 1:
        keep(winners[0][2], resolved="trust")
        skipped["conflict:trust"] += len(distinct) - 1
        return kept, skipped, marks
    if keep_open:
        for row in distinct:
            node = address(row, "|".join((
                wording_key(row, wording), fold(row.get("quote") or ""),
                str(row["value_target"]))))
            kept[node] = row
            marks[node] = {"conflict": True}
        skipped["conflict:open"] += len(distinct)
        return kept, skipped, marks
    skipped["conflict"] += len(distinct)
    return kept, skipped, marks
