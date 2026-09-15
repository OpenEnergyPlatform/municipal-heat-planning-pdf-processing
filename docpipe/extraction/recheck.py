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

from .fields import DERIVED, NUMBER, READ, UNANSWERED, asked_slots
from .pipeline import answer_in_quote
from .spec import Spec
from .trust import document_summary
from .verify import quote_in

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
        if row.get(f"{name}_state") == DERIVED:
            # The spec decided this one, so no passage was ever claimed to
            # carry it and the answer-in-quote rule has nothing to say about it.
            # Holding it to the rule would strip a correct coordinate for
            # failing a test it was never entered into.
            dropped["derived"] += 1
            continue
        if not quote:
            # Written by the whole-tuple contract, which never asked for one.
            # It is not evidence and was never checked, so it does not stay.
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
        row[f"{name}_state"] = UNANSWERED
    return dropped


def recheck_file(path: Path, spec: Spec) -> Counter:
    """Rewrite one harvest file in place. Returns what it dropped and why.

    The summary line is recomputed rather than carried over: it counts the
    trust levels of the tuples above it, and this pass is in the business of
    demoting them. A kept summary would report the run that no longer exists.
    """
    stats: Counter = Counter()
    lines = []
    tuples, refusals, document_id = [], [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            stats["unreadable line kept"] += 1
            lines.append(line)
            continue
        if row.get("kind") == "summary":
            document_id = row.get("document_id")
            stats["summaries rewritten"] += 1
            continue
        if row.get("kind") != "tuple":
            # Kept verbatim, and only a refusal counted as one: the rebuilt
            # summary's refusal count is read as a model-error rate, and a
            # parameter_state line is a fact about the run.
            if row.get("kind") == "refusal":
                refusals.append(row)
            lines.append(line)
            continue
        parameter = spec.by_uri.get(row.get("parameter"))
        if parameter is None:
            stats["unknown parameter kept"] += 1
            tuples.append(row)
            lines.append(line)
            continue
        slots = asked_slots(parameter)
        stats["tuples"] += 1
        stats["coordinates"] += len(slots)
        stats.update(recheck_row(row, slots))
        tuples.append(row)
        lines.append(json.dumps(row, ensure_ascii=False))
    if document_id is not None:
        lines.append(json.dumps(
            {"kind": "summary",
             **document_summary(document_id, tuples, refusals)},
            ensure_ascii=False))
    tmp = Path(path).with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return stats


def run(harvest_dir: Path, spec: Spec, *, drop_stamps: bool = True) -> Counter:
    """Recheck a whole harvest directory.

    The stamps go with it. A file rewritten by a rule the harvest did not
    apply is not the output of the run its stamp names, and leaving the stamp
    would make the next run skip the document — which is exactly how 205 plans
    kept a whole-tuple harvest through a field-wise corpus run.
    """
    stats: Counter = Counter()
    harvest_dir = Path(harvest_dir)
    for path in sorted(harvest_dir.glob("*.jsonl")):
        stats.update(recheck_file(path, spec))
        stats["documents"] += 1
    if drop_stamps:
        for stamp in harvest_dir.glob("*.stamp.json"):
            stamp.unlink()
            stats["stamps cleared"] += 1
    for key, value in sorted(stats.items()):
        log.info("recheck: %-32s %d", key, value)
    return stats
