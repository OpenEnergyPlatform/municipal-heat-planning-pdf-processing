"""
topup_rest.py: Reads the passages of a stored harvest that were never asked
for values, and appends what they hold.

A harvest asked the passages its searches kept, and on a long plan most
values stand below that cut: the rest was read only when a follow-up happened
to walk it. This pass reads the rest of a document
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

import logging
from pathlib import Path

from .. import rules
from . import trace
from .remap import _read_stamp as read_stamp

log = logging.getLogger(__name__)

PASS = "rest"
TRACE_DIR = "trace-rest"
HARVEST_TRACE_DIR = "trace"


def owners_in(events) -> set:
    """{(owner_kind, owner_id)} the rows requests among these trace events
    were shown."""
    owners: set = set()
    for event in events:
        if not isinstance(event, dict) or event.get("t") != "rows":
            continue
        for source in event.get("sources") or ():
            if isinstance(source, (list, tuple)) and len(source) == 2:
                owners.add((source[0], source[1]))
    return owners


def read_owners(directory: Path, name: str) -> set:
    """`owners_in` over the trace of *name* in *directory*, read for its rows
    requests alone; empty when there is none."""
    path = trace.path_of(directory, name)
    return owners_in(trace.lines(path, kinds=("rows",))) if path else set()


def skips_unknown_reading() -> bool:
    """Whether a document whose earlier readings cannot be told (no record,
    no survey) is skipped and not read whole (rule
    `rest_without_trace`)."""
    return rules.get("rest_without_trace") == "skip"


def done_to_end(stamp_path: Path) -> bool:
    """Whether the pass for the rest of the plan reads the document no more
    because it has read it to its end (rule `rest_once_per_document`)."""
    return bool(rules.get("rest_once_per_document")) \
        and read_to_end(stamp_path)


def read_to_end(stamp_path: Path) -> bool:
    """Whether this pass has already read the document to its end."""
    stamp = read_stamp(stamp_path) or {}
    return any(isinstance(p, dict) and p.get("pass") == PASS
               for p in stamp.get("producers") or ())


