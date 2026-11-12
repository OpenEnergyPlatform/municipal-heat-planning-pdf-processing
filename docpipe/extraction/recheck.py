"""
recheck.py: Reapplies the answer-in-quote rule to a harvest written before
the rule existed.

A coordinate is only as good as the passage cited for it. For one corpus run,
that passage was checked against the wrong thing: `merge_field` held it to
sitting verbatim in the source, never to containing the answer. In that run,
27.6% of the years cite a passage that contains no year at all; one of them is
a table caption listing existing heat networks and heating plants, offered as
evidence for the year 1990.

Both halves of a coordinate are already in the harvest file, the wording in
`<axis>_raw` and the passage in `<axis>_quote`, so the rule can be applied to
what is written without asking a model anything. Keeping the evidence next to
the claim is what makes this possible: a rule that tightens later can still be
enforced on an earlier harvest.

The pass cannot fill a coordinate it drops. A dropped coordinate is one the
next run has to read again, and it is marked so that the difference between the
plan not stating a value and the last run not having checked it stays visible
instead of collapsing into an empty cell.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from .. import jsonl, rules
from .fields import DERIVED, READ, UNANSWERED
from .pipeline import answer_in_quote
from .spec import Spec

log = logging.getLogger(__name__)


def recheck_row(row: dict, slots: list) -> Counter:
    """Strip every coordinate of one tuple whose quote does not carry it."""
    dropped: Counter = Counter()
    for slot in slots:
        name = slot.name
        given = row.get(name)
        quote = row.get(f"{name}_quote")
        if given in (None, ""):
            row.setdefault(f"{name}_state", UNANSWERED)
            continue
        if row.get(f"{name}_state") == DERIVED \
                and rules.get("recheck_keeps_derived"):
            # The spec decided this one, so no passage was ever claimed to
            # carry it and the answer-in-quote rule has nothing to say about it.
            # Holding it to the rule would strip a correct coordinate for
            # failing a test it was never entered into.
            dropped["derived"] += 1
            continue
        if not quote:
            # A harvest from before each coordinate carried a quote has none.
            # It is not evidence and was never checked, so it does not stay
            # (rule `recheck_drop_without_quote`).
            if not rules.get("recheck_drop_without_quote"):
                dropped["no evidence kept"] += 1
                continue
            dropped["no evidence at all"] += 1
        elif not answer_in_quote(slot, given,
                                 row.get(f"{name}_raw"), quote):
            dropped["quote does not carry the answer"] += 1
        else:
            row[f"{name}_state"] = READ
            dropped["read"] += 1
            continue
        for key in (name, f"{name}_raw", f"{name}_quote"):
            row.pop(key, None)
        row[f"{name}_state"] = rules.get("recheck_dropped_state")
    return dropped


def _document_of(text: str):
    """The document id a harvest file's summary line names, or None."""
    for line in jsonl.lines(text):
        if '"summary"' not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("kind") == "summary":
            return row.get("document_id")
    return None


def recheck_file(path: Path, spec: Spec,
                 spec_for: Optional[Callable] = None) -> Counter:
    """Rewrite one harvest file in place, as the flow `recheck` does for a
    file. Returns what it dropped and why.

    The summary line is recomputed rather than carried over: it counts the
    trust levels of the tuples above it, and this pass is in the business of
    demoting them. A kept summary would report the run that no longer exists.

    *spec_for* gives the spec as the file's document sees it (document id ->
    Spec, or None when its lists cannot be closed). A coordinate the harvest
    backed as an entry of the document's list is held to the same list here:
    against the run's spec the entry is a bare identifier no quote prints.
    """
    from . import passflow
    from ..profile import active_profile
    from .remap import _spec_of
    run = passflow.Run(out=Path(path).parent, spec=spec,
                       document_spec=_spec_of(spec, spec_for))
    tree = [node for node in passflow.load("recheck", active_profile())
            if node.get("box") != "clear_stamps"]
    return passflow.one(tree, run, None, Path(path).name).stats


def run(harvest_dir: Path, spec: Spec, *,
        drop_stamps: Optional[bool] = None,
        spec_for: Optional[Callable] = None) -> Counter:
    """Recheck a whole harvest directory: the flow `recheck`
    (`passflow`).

    The stamps go with it. A file rewritten by a rule the harvest did not
    apply is not the output of the run its stamp names, and leaving the stamp
    would make the next run skip the document -- which is exactly how 205 plans
    kept an old harvest through a corpus run meant to redo them. A file left
    alone keeps its stamp: it still is that run's output. *drop_stamps* None
    leaves it to the rule `recheck_clear_stamps`.
    """
    from . import passflow
    from .remap import _spec_of
    made = passflow.Run(out=Path(harvest_dir), spec=spec,
                        document_spec=_spec_of(spec, spec_for))
    if drop_stamps is None:
        return passflow.run_named("recheck", made)
    with rules.overlaid(recheck_clear_stamps=bool(drop_stamps)):
        return passflow.run_named("recheck", made)
