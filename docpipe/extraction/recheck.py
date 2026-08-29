"""
recheck.py – The evidence rule, applied to a harvest that was written without it.

A coordinate is only as good as the passage cited for it, and for one corpus
run that passage was checked against the wrong thing: merge_field held it to
sitting verbatim in the source and never to containing the answer. 27.6% of
the years that came out of that run cite a passage with no year in it, one of
them the caption "Tabelle 1: Bestehende Wärmenetze und Heiz(kraft)werke"
offered as evidence for 1990.

Both halves are in the harvest files already — the wording in <axis>_raw, the
passage in <axis>_quote — so the rule can be applied to what is written
without asking a model anything. That is the whole point of keeping the
evidence next to the claim: a rule that tightens can be enforced backwards.

What this cannot do is fill anything. A coordinate dropped here is a
coordinate the next run has to read properly, and it is marked so the
difference between "the plan does not say" and "the last run did not check"
stays visible instead of collapsing into an empty cell.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from .fields import NUMBER, READ, UNANSWERED, axis_slots
from .pipeline import answer_in_quote
from .spec import Spec
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
    """Rewrite one harvest file in place. Returns what it dropped and why."""
    stats: Counter = Counter()
    lines = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            stats["unreadable line kept"] += 1
            lines.append(line)
            continue
        if row.get("kind") != "tuple":
            lines.append(line)
            continue
        parameter = spec.by_uri.get(row.get("parameter"))
        if parameter is None:
            stats["unknown parameter kept"] += 1
            lines.append(line)
            continue
        slots = axis_slots(parameter)
        stats["tuples"] += 1
        stats["coordinates"] += len(slots)
        stats.update(recheck_row(row, slots))
        lines.append(json.dumps(row, ensure_ascii=False))
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
