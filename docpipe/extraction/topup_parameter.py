"""
topup_parameter.py: Appends the rows of a parameter the spec has gained to a
harvest that is already on disk, instead of harvesting the document again.

A parameter added to the spec leaves every stored document without that
parameter's key in its stamp, and the resume can only answer that by reading
the whole document again. What the new parameter needs is smaller: the
document searched for it, one rows request that offers it and nothing else,
and the coordinates of the rows that request produced. The old parameters'
rows, and the coordinate sweeps that took most of the first run, are not
asked again.

The stamp is what says the pass may be taken: the key `parameter/<uri>` is
absent for the new parameter and nothing else moved but what the addition
moves (`addition`). A reworded, renamed or removed parameter, a grown value
list or a moved question is not an addition and the document stays stale as a
whole, as it does for every such change; so does a document whose stored rows
were decided under another derivation of their parameter because of the new
one (`derivation_moved`).

What the pass writes is kept apart from what was there. Every stored line goes
back as the same bytes in the same order, and the new tuples, refusals and one
`parameter_state` line per new parameter follow, with a summary that describes
the file as it now stands. The summary says nothing new about the refusals of
the first pass: they are not revisited, and the pass says so in its log.
Nothing stored ever becomes a `Row`, so no request can touch it.

A pass that did not read the parameter completely writes nothing, neither the
file nor the stamp, and its document counts as failed: an appended half
reading and its state line would be indistinguishable from a finished one, and
the stamp would then vouch for it. The one window the pass has is between the
file and the stamp; a file that already holds the state line of every new
parameter gets its stamp and no request (`applied`).

The checks are the harvest's own, because the rows go through the harvest's
own fold (`runner.fold_answers`): the quote stands in a shown passage, the
answer stands in the quote, and the quote has its minimum length. This module
decides no value and refuses none.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

from . import fields
from .pipeline import drop_repeats, repeat_key
from .remap import _read_stamp as read_stamp
from .remap import (enter_producer, next_producer, stamp_forward,
                    stamp_path_of)
from .spec import Spec, fingerprints
from .topup import actionable, pairs_of, read_harvest
from .trust import document_summary, parameter_states

log = logging.getLogger(__name__)

# The name this pass enters into the stamp's `producers` list.
PASS = "top-up-parameter"
# Where the frame of a pass came from, as its producers entry says.
FRAME_NONE = "none"
FRAME_SEEDED = "stored rows, then asked over the new passages"

# The keys no parameter owns that a new parameter can still move: the one
# coordinate that says which quantity a number is, and the one that says which
# unit it is in. Both are written from every parameter of the spec at once.
SHARED_KEYS = ("slot/parameter", f"slot/{fields.UNIT}")


def owned_keys(uri: str, keys) -> set:
    """The stamp keys of one parameter among *keys*: its own, its list and
    every one of its axes."""
    return {k for k in keys
            if k in (f"parameter/{uri}", f"value/{uri}")
            or k.startswith(f"axis/{uri}/")}


def without(spec: Spec, new) -> Spec:
    """The spec as it read before these parameters were added."""
    gone = {p.uri for p in new}
    return replace(spec, parameters=[p for p in spec.parameters
                                     if p.uri not in gone])


@dataclass
class Addition:
    """What a stored stamp says about the parameters the spec gained.

    `owned` are the keys of the new parameters, stored or current: the pass
    answers for them. `shared` are the keys of the questions that belong to no
    parameter and that the addition alone moved: the pass answers for them
    with the rest. `unexplained` is every other key the stamp and the spec
    still differ in. An empty list is "nothing but the addition moved".
    """
    stored: dict
    new: list = field(default_factory=list)
    owned: set = field(default_factory=set)
    shared: set = field(default_factory=set)
    unexplained: list = field(default_factory=list)

    @property
    def explained(self) -> set:
        return self.owned | self.shared


def addition(stamp_path: Path, current: dict, spec: Spec) -> tuple:
    """(Addition or None, why it could not be told).

    New is told from reworded by the stamp keys alone: a parameter whose
    `parameter/<uri>` the stored stamp has never seen is new, one whose key is
    there and differs is reworded, and that is the whole difference. Stored
    `axis/<uri>/..` and `value/<uri>` keys of a parameter are ignored for it
    on purpose: `--remap` writes them for every parameter of the spec, read
    or not, so they say nothing about whether anybody read the parameter.

    None when the stamp cannot vouch for anything: it is not there or not
    readable (`stale` returns every key of the run for it, and every
    parameter would look new), or it predates the per-parameter keys.
    """
    stored = read_stamp(stamp_path)
    if stored is None:
        return None, "no readable stamp"
    if "slot/parameter" not in stored or not any(
            k.startswith("parameter/") for k in stored):
        return None, "stamp predates the per-parameter keys"
    new = [p for p in spec.parameters
           if f"parameter/{p.uri}" not in stored]
    if not new:
        return Addition(stored), ""
    from . import runner
    owned: set = set()
    for parameter in new:
        owned |= owned_keys(parameter.uri, set(current) | set(stored))
    # What the run would stamp for the spec as it was before the addition.
    # Every key that still differs from the stored stamp is something other
    # than the addition: a reworded or removed parameter shows up here.
    before = {k: v for k, v in current.items()
              if not k.startswith(runner.QUESTION_KEYS)}
    before.update(fingerprints(without(spec, new)))
    unexplained = [k for k in runner.stale(stamp_path, before)
                   if k not in owned]
    shared = {k for k in SHARED_KEYS
              if k in current and stored.get(k) != current[k]
              and k not in unexplained}
    return Addition(stored, new, owned, shared, unexplained), ""


def gained(stamp_path: Path, spec: Spec) -> list:
    """The uris of the parameters of *spec* a stored stamp has never seen.

    Only a stamp that carries per-parameter keys can say so: one that
    predates them, or none at all, says nothing and yields none.
    """
    stored = read_stamp(stamp_path)
    if stored is None or not any(k.startswith("parameter/") for k in stored):
        return []
    return [p.uri for p in spec.parameters
            if f"parameter/{p.uri}" not in stored]


def explained_keys(stamp_path: Path, current: dict, spec: Spec) -> set:
    """The keys of *current* that only the parameters the spec gained moved.

    What a pass for coordinates (`topup.top_up_file`) takes out of its list
    before it asks what blocks it: these are this pass's to answer, and it
    writes none of them.
    """
    found, _why = addition(stamp_path, current, spec)
    return set() if found is None else found.explained


def derivation_moved(spec: Spec, new, tuples: list) -> bool:
    """Did the new parameters change which parameter a stored row derives to?

    A numeric parameter that shares a unit with a stored one leaves a unit two
    parameters accept, and a second text parameter leaves a wording two
    parameters could hold (`fields.derive_parameter`). The stored rows were
    decided without it. The rows of the new parameters are not asked: they are
    this pass's own.
    """
    uris = {p.uri for p in new}
    before = without(spec, new)
    for row in tuples:
        if row.get("parameter") in uris:
            continue
        was = fields.derive_parameter(before, row)
        now = fields.derive_parameter(spec, row)
        if (was.uri if was else None) != (now.uri if now else None):
            return True
    return False


@dataclass
class Verdict:
    """What the pass does with one stored document.

    `kind` is one of: "none" (no new parameter), "blocked" (the document
    stays stale as a whole, not a failure), "failed" (the pass cannot be
    taken and the run says so in its exit code), "applied" (the file already
    holds every new parameter's state line, only the stamp is missing) and
    "new" (read the document for the new parameters).
    """
    kind: str
    why: str = ""
    new: list = field(default_factory=list)
    owned: set = field(default_factory=set)
    shared: set = field(default_factory=set)
    stored: object = None          # the harvest file, read, when it was needed


def classify(stamp_path: Path, current: dict, spec: Spec, harvest_path: Path,
             *, doc_spec_of: Callable, frame_names=(),
             dynamic_ok: bool = True) -> Verdict:
    """The verdict for one stored document, by the rules in this order.

    A document with no stamp, or one that predates the per-parameter keys, is
    blocked. One with no new parameter has nothing to append. Then what the
    document is asked through has to be what it was, apart from the
    addition: a key that is not a coordinate of an old parameter blocks
    (`topup.actionable`, the rule the coordinate pass uses), and a key that
    is one is left to that pass and never written by this one. The marker of
    an earlier pass of this one comes before the derivation, because the
    rows it appended are not rows decided under the old one.

    The harvest file is read, and *doc_spec_of* closes the document's lists,
    only when a rule needs them, so a corpus with nothing to append reads
    nothing but its stamps. A verdict that goes on to read the document
    carries the file it read.
    """
    found, why = addition(stamp_path, current, spec)
    if found is None:
        return Verdict("blocked", why)
    if not found.new:
        return Verdict("none", "no new parameter")
    doc_spec = doc_spec_of()
    if doc_spec is None:
        return Verdict("failed", "choice lists unreadable")
    stored = read_harvest(harvest_path)
    _keys, blocked = actionable(found.unexplained, doc_spec, frame_names,
                                dynamic_ok=dynamic_ok)
    if blocked:
        return Verdict("blocked", "another question moved besides the "
                                  "addition: " + ", ".join(blocked))
    # The state line is the pass's marker: a file holds one for a parameter
    # only once the parameter was read for it. A file from before the lines
    # existed holds none, which means the parameter was never read there, and
    # the pass runs.
    have = {state.get("parameter") for state in stored.states}
    present = [p for p in found.new if p.uri in have]
    if present and len(present) < len(found.new):
        return Verdict("failed", "the file holds the state line of only "
                                 "some of the new parameters")
    if present:
        return Verdict("applied", "", found.new, found.owned, found.shared,
                       stored)
    if derivation_moved(doc_spec, found.new, stored.tuples):
        return Verdict("blocked", "stored rows were decided under another "
                                  "derivation of their parameter")
    return Verdict("new", "", found.new, found.owned, found.shared, stored)


def drop_stored_repeats(rows: list, stored: list) -> tuple:
    """(rows that are new, how many were a stored tuple again).

    A row equal to a stored tuple in everything but its provenance, whatever
    its parameter, is that tuple and is not written a second time. Not a
    check on a value: it says nothing the stored one did not. Stored tuples
    are never compared with each other and none is removed, so a file that
    already holds a repeat keeps both. A stored row carries `kind` and a
    report row does not, and who read a coordinate says nothing about what was
    read: both are left out of the key, or no repeat would ever be found.
    """
    def key(row: dict) -> str:
        return repeat_key({k: v for k, v in row.items()
                           if k != "kind" and not k.endswith(fields.PRODUCER)})

    held = {key(row) for row in stored}
    kept = [row for row in rows if key(row) not in held]
    return kept, len(rows) - len(kept)


def point(row: dict, position: Optional[int]) -> None:
    """Say that this pass wrote every coordinate of this row: each
    `<axis>_producer` is the position of its entry in the stamp's list."""
    if position is None:
        return
    for key in [k for k in row if k.endswith("_state")]:
        row[key[:-len("_state")] + fields.PRODUCER] = position


def appended_lines(stored, document_id, rows: list, refusals: list,
                   states: list) -> list:
    """The file as it stands after the pass: every stored line as it was,
    then the new tuples, refusals and parameter states, the summary last.

    The stored tuples are not dumped again, they are the strings they were,
    so no key moves, no number is spelled another way and no character is
    escaped. Only the old summary is replaced.
    """
    def dump(record: dict) -> str:
        return json.dumps(record, ensure_ascii=False)

    lines = list(stored.lines)
    lines += [dump({"kind": "tuple", **row}) for row in rows]
    lines += [dump({"kind": "refusal", **refusal}) for refusal in refusals]
    lines += [dump({"kind": "parameter_state", "document_id": document_id,
                    **state}) for state in states]
    summary = document_summary(document_id, stored.tuples + rows,
                               stored.refusals + refusals)
    lines.append(dump({"kind": "summary", **summary}))
    return lines


def not_read(cause: str, found: int, of: int) -> str:
    """What `runner.not_happened` counted, said in the unit it counted."""
    if cause == "unreachable":
        return f"{found} of {of} source(s) never reached the server"
    if cause == "no_reply":
        return f"{of} source(s) planned and not one reply"
    return f"{found} request(s) ended on a 429 or a 5xx"


def _write_lines(path: Path, lines: list) -> None:
    """The file replaced in one step, bytes as given: a text-mode write would
    spell the line feed the way the platform does."""
    tmp = Path(path).with_suffix(".jsonl.tmp")
    tmp.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    tmp.replace(path)


def append_document(document_id: int, filename: str, out_dir: Path,
                    spec: Spec, current: dict, deps: dict) -> tuple:
    """(written, failures, stats) for one stored document.

    `deps` is what the run supplies: "document_spec" (id -> this document's
    spec, None when a list it closes cannot be), "plan" (the run's
    `plan_batches`, everything but the document bound), "harvest" (the run's
    `harvest_batches` over its pools, everything but the batches and the
    unfinished set bound), "questions" (name -> the sentences this document
    was searched with, taken), "locate", "frame_axes", "frame_names",
    "dynamic_ok" and "halted".

    Nothing is written unless the new parameters were read: a document the
    server did not serve, a frame or a plan that raised, or one the run halted
    in leaves the file and the stamp as they were.
    """
    from . import runner
    stats: Counter = Counter()
    name = Path(filename).stem
    path = Path(out_dir) / f"{name}.jsonl"
    stamp_path = stamp_path_of(path)
    # The PDF is part of what the stamp is held against (`runner.stale`): a
    # document read from another file than the one the rows came from is
    # another thing that moved. It is not a key this pass answers for, so the
    # stamp is carried forward from the run's keys without it.
    verdict = classify(
        stamp_path, {**current, **runner.document_current(name)}, spec, path,
        doc_spec_of=lambda: deps["document_spec"](document_id),
        frame_names=deps.get("frame_names") or (),
        dynamic_ok=deps.get("dynamic_ok", True))
    if verdict.kind == "none":
        stats["documents without a new parameter (documents)"] += 1
        return False, 0, stats
    if verdict.kind == "blocked":
        log.info("top-up-parameters: %s stays stale as a whole: %s", name,
                 verdict.why)
        stats["documents left stale as a whole (documents)"] += 1
        return False, 0, stats
    if verdict.kind == "failed":
        log.error("top-up-parameters: %s not taken: %s", name, verdict.why)
        stats["documents not taken (documents)"] += 1
        return False, 1, stats
    settled = verdict.owned | verdict.shared
    uris = [p.uri for p in verdict.new]
    stored = verdict.stored
    stats["unreadable lines kept (lines)"] += stored.unreadable
    if verdict.kind == "applied":
        # The file was written and the stamp never was. Nothing is asked.
        if stamp_forward(stamp_path, current, settled):
            stats["stamps completed, the file already held the parameters "
                  "(documents)"] += 1
            return True, 0, stats
        log.error("top-up-parameters: %s holds %s and its stamp could not be "
                  "completed", name, ", ".join(uris))
        stats["documents not taken (documents)"] += 1
        return False, 1, stats

    before = runner.UNSERVED.of(document_id)
    pairs = pairs_of(stored.tuples, deps.get("frame_axes"))
    planned = deps["plan"](document_id, filename, only=tuple(uris),
                           stored_pairs=pairs or None)
    report = planned.report
    asked = deps["questions"](name)
    if planned.failed:
        log.error("top-up-parameters: %s: the frame or the plan of a pair "
                  "failed, so %s was not read completely and nothing is "
                  "written", name, ", ".join(uris))
        stats["documents not read completely (documents)"] += 1
        return False, 1, stats
    if deps["halted"]():
        return False, 0, stats

    unfinished: set = set()
    answered = deps["harvest"](planned.batches, unfinished=unfinished)
    if report.document_id in unfinished:
        log.error("top-up-parameters: %s left with batches never harvested, "
                  "nothing is written", name)
        return False, 0, stats
    runner.fold_answers(answered, report, locate=deps.get("locate"),
                        spec=planned.doc_spec)
    drop_repeats(report)
    verdict_run = runner.not_happened(
        report, answered=len(answered),
        lost=runner.UNSERVED.of(document_id) - before)
    if verdict_run is not None:
        log.error("top-up-parameters: %s: %s was not read completely, %s; "
                  "nothing is written", name, ", ".join(uris),
                  not_read(*verdict_run))
        stats["documents not read completely (documents)"] += 1
        return False, 1, stats

    only = runner.narrow_spec(planned.doc_spec, uris)
    states = parameter_states(only, report.tuples, report.refusals,
                              harvested=report.owners_harvested,
                              answered=len(answered),
                              sources_of=report.sources_of)
    rows, identical = drop_stored_repeats(report.tuples, stored.tuples)
    position = next_producer(stamp_path)
    for row in rows:
        point(row, position)
    report.tuples = rows
    runner.check_against_schema(report, name, spec, states)

    entry = {**runner.producer(PASS, runner.LLM_MODEL), "parameters": uris,
             "frame": FRAME_SEEDED if deps.get("frame_axes") else FRAME_NONE}
    # Entered before the rows that point at it, as the coordinate pass does.
    enter_producer(stamp_path, entry)
    _write_lines(path, appended_lines(stored, document_id, rows,
                                      report.refusals, states))
    if not stamp_forward(stamp_path, current, settled,
                         record=runner.recorded_questions(asked)):
        log.error("top-up-parameters: %s was appended to and its stamp could "
                  "not be written; the next run completes it", name)
        stats["documents not taken (documents)"] += 1
        return True, 1, stats
    stats["documents appended (documents)"] += 1
    stats["tuples appended (tuples)"] += len(rows)
    stats["refusals appended (refusals)"] += len(report.refusals)
    stats["tuples identical to a stored tuple, not appended (tuples)"] += \
        identical
    stats["stored refusals not revisited (refusals)"] += len(stored.refusals)
    for state in states:
        stats[f"parameters {state['state']} (parameters x documents)"] += 1
    log.info("top-up-parameters: %s: %s appended, %d tuple(s) and %d "
             "refusal(s)", name, ", ".join(uris), len(rows),
             len(report.refusals))
    return True, 0, stats


class DocumentPass:
    """`harvest_document(document_id, filename) -> (written, failures)` for the
    run's own loop (`runner.harvest_documents`), with what it counted.

    The loop calls it from several threads, one document each; the counts are
    added under a lock.
    """

    def __init__(self, out_dir: Path, spec: Spec, current: dict, deps: dict):
        self.out_dir, self.spec = Path(out_dir), spec
        self.current, self.deps = current, deps
        self.stats: Counter = Counter()
        self._lock = threading.Lock()

    def __call__(self, document_id: int, filename: str) -> tuple:
        written, failed, stats = append_document(
            document_id, filename, self.out_dir, self.spec, self.current,
            self.deps)
        from . import trace
        trace.flush(document_id)
        with self._lock:
            self.stats.update(stats)
            self.stats["documents looked at (documents)"] += 1
        return written, failed

    def report(self) -> None:
        """One line per count, each with what it counts."""
        with self._lock:
            for key, value in sorted(self.stats.items()):
                log.info("top-up-parameters: %-64s %d", key, value)
            if self.stats["stored refusals not revisited (refusals)"]:
                log.info("top-up-parameters: the refusals of the first pass "
                         "are not revisited: a value refused then for want "
                         "of a parameter stays a refusal, and the summary of "
                         "a file counts it")


def with_harvest(documents: list, out_dir: Path) -> tuple:
    """(the documents that have a harvest file, how many have none).

    A document nobody has harvested has nothing to append to; the harvest
    itself reads it, with every parameter.
    """
    kept = [(did, fn) for did, fn in documents
            if (Path(out_dir) / f"{Path(fn).stem}.jsonl").is_file()]
    return kept, len(documents) - len(kept)
