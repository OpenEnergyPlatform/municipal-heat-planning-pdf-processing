"""
topup_rest.py: Reads the passages of a stored harvest that were never asked
for values, and appends what they hold.

A harvest asked the passages its searches kept, and on a long plan most
values stand below that cut: the rest was read only when a follow-up happened
to walk it (`runner.plan_batches`). This pass reads the rest of a document
that was harvested before the rest was read, without harvesting it again.

Which passages were asked is in the harvest's trace: every `rows` event names
its sources. Those are left out, everything else of the document is read
under the pair it prints, with the pairs the stored rows carry and under the
index they carry them, and the rows it finds are asked every coordinate as in
the harvest. They follow the stored lines, which stay as they are, and a row
equal to a stored tuple is not written again.

A document without a trace is skipped and counted: what it read cannot be
told, and reading all of it again is the harvest's job. A document this pass
has read to its end says so in its stamp's list of producers and is not read
again; its own trace goes beside the harvest's (`TRACE_DIR`), since a trace is
truncated by the next pass that writes it.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from pathlib import Path

from .pipeline import drop_repeats
from .remap import _read_stamp as read_stamp
from .remap import enter_producer, next_producer, stamp_path_of
from .topup import pairs_of, read_harvest
from .topup_parameter import (_write_lines, appended_lines, drop_stored_repeats,
                              not_read, point)

log = logging.getLogger(__name__)

PASS = "rest"
TRACE_DIR = "trace-rest"
HARVEST_TRACE_DIR = "trace"


def owners_in(lines) -> set:
    """{(owner_kind, owner_id)} the rows requests among these trace lines were
    shown."""
    owners: set = set()
    for line in lines:
        if '"rows"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("t") != "rows":
            continue
        for source in event.get("sources") or ():
            if isinstance(source, (list, tuple)) and len(source) == 2:
                owners.add((source[0], source[1]))
    return owners


def read_owners(trace_path: Path) -> set:
    """`owners_in` over a trace file; empty when there is none."""
    try:
        with open(trace_path, encoding="utf-8") as handle:
            return owners_in(handle)
    except OSError:
        return set()


def read_to_end(stamp_path: Path) -> bool:
    """Whether this pass has already read the document to its end."""
    stamp = read_stamp(stamp_path) or {}
    return any(isinstance(p, dict) and p.get("pass") == PASS
               for p in stamp.get("producers") or ())


def append_rest(document_id: int, filename: str, out_dir: Path,
                deps: dict) -> tuple:
    """(written, failures, stats) for one stored document.

    `deps` holds what the run supplies: "plan" (`plan_batches` with the rest
    reader bound), "harvest" (`harvest_batches` over the run's pools),
    "locate", "frame_axes", "halted" and "fold" (`runner.fold_answers`),
    "not_happened", "unserved" (`runner.UNSERVED.of`), "producer"
    (`runner.producer`) and "model".
    """
    stats: Counter = Counter()
    name = Path(filename).stem
    path = Path(out_dir) / f"{name}.jsonl"
    stamp_path = stamp_path_of(path)
    if not path.is_file():
        stats["documents without a harvest (documents)"] += 1
        return False, 0, stats
    if read_to_end(stamp_path):
        stats["documents already read to their end (documents)"] += 1
        return False, 0, stats
    read = read_owners(Path(out_dir) / HARVEST_TRACE_DIR
                       / f"{name}.trace.jsonl")
    if not read:
        stats["documents without a trace of what was read (documents)"] += 1
        return False, 0, stats

    stored = read_harvest(path)
    stats["unreadable lines kept (lines)"] += stored.unreadable
    before = deps["unserved"](document_id)
    pairs = pairs_of(stored.tuples, deps.get("frame_axes"))
    planned = deps["plan"](document_id, filename, stored_pairs=pairs or None,
                           already_read=frozenset(read))
    report = planned.report
    if planned.failed:
        log.error("top-up-rest: %s: the frame or the plan of a pair failed, "
                  "nothing is written", name)
        stats["documents not read completely (documents)"] += 1
        return False, 1, stats
    if deps["halted"]():
        return False, 0, stats
    if not planned.batches:
        enter_producer(stamp_path, deps["producer"](PASS, deps["model"]))
        stats["documents with nothing unread (documents)"] += 1
        return True, 0, stats

    unfinished: set = set()
    answered = deps["harvest"](planned.batches, unfinished=unfinished)
    if report.document_id in unfinished:
        log.error("top-up-rest: %s left with batches never harvested, "
                  "nothing is written", name)
        return False, 0, stats
    deps["fold"](answered, report, locate=deps.get("locate"),
                 spec=planned.doc_spec)
    drop_repeats(report)
    verdict = deps["not_happened"](
        report, answered=len(answered),
        lost=deps["unserved"](document_id) - before)
    if verdict is not None:
        log.error("top-up-rest: %s was not read completely, %s; nothing is "
                  "written", name, not_read(*verdict))
        stats["documents not read completely (documents)"] += 1
        return False, 1, stats

    rows, identical = drop_stored_repeats(report.tuples, stored.tuples)
    position = next_producer(stamp_path)
    for row in rows:
        point(row, position)
    # Entered before the rows that point at it.
    enter_producer(stamp_path, deps["producer"](PASS, deps["model"]))
    _write_lines(path, appended_lines(stored, document_id, rows,
                                      report.refusals, []))
    stats["documents appended (documents)"] += 1
    stats["passages read (passages)"] += report.owners_harvested
    stats["tuples appended (tuples)"] += len(rows)
    stats["refusals appended (refusals)"] += len(report.refusals)
    stats["tuples identical to a stored tuple, not appended (tuples)"] += \
        identical
    log.info("top-up-rest: %s: %d passage(s) read, %d tuple(s) and %d "
             "refusal(s) appended", name, report.owners_harvested, len(rows),
             len(report.refusals))
    return True, 0, stats


class RestPass:
    """`harvest_document(document_id, filename) -> (written, failures)` for
    the run's own loop, with what it counted."""

    def __init__(self, out_dir: Path, deps: dict):
        self.out_dir, self.deps = Path(out_dir), deps
        self.stats: Counter = Counter()
        self._lock = threading.Lock()

    def __call__(self, document_id: int, filename: str) -> tuple:
        written, failed, stats = append_rest(document_id, filename,
                                             self.out_dir, self.deps)
        from . import trace
        trace.flush(document_id)
        with self._lock:
            self.stats.update(stats)
            self.stats["documents looked at (documents)"] += 1
        return written, failed

    def report(self) -> None:
        with self._lock:
            for key, value in sorted(self.stats.items()):
                log.info("top-up-rest: %-64s %d", key, value)
