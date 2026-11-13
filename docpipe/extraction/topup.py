"""
topup.py: Re-reads the one coordinate a stamp names as moved, instead of the
whole document.

A question is reworded, or an option list gains a class the model can now
choose. The stamp knows exactly which key moved, and a
resume then does the only thing it can: it reports the document stale, and the
next run harvests it again from the first passage. For one axis of one
parameter, that is a full corpus run spent answering a question nothing else
asked.

This module instead takes the coordinate off the rows that carry it, asks it
as the harvest asks it (`surveyed.SurveyedHarvest.sweep`, so there is one
question and one set of numbers), and writes the answer back. It then carries that one stamp
key forward and leaves every other key exactly as it was, so a later run still
sees what it has to redo. Who read is recorded apart from that: the pass enters
the stamp's `producers` list whether or not it earned a key, and each
coordinate it re-read points at its entry (`<axis>_producer`), so a file with
two readings of one coordinate's rows says which is which.

What the module refuses to touch matters more than what it does. A key that
decided which rows exist, which passages were planned, or which model read them
does not name a coordinate: the rows are then not this run's product at all,
and the document is skipped whole rather than half repaired. The frame is
refused for the same reason one level up, because it decides how many passes a
document gets.

A parameter the spec has gained is not a coordinate. Its keys are taken out
of the list before anything is asked (`topup_parameter.explained_keys`), so
they neither block the document nor are written by this pass, and the pass
that appends the parameter answers for them.

The old reading is restored whenever the re-sweep fails to improve on it. No
coordinate is required in either profile, so an emptied one would otherwise
pass verification in silence, with the reading gone and nothing recording the
loss. Unlike `--recheck` and `--remap`, the pass is neither model-free nor
index-free: it needs the database, the index, the embedder, and a served model,
and what it saves is the plan, the row requests, and the frame.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .. import jsonl, rules
from . import fields
from .pipeline import (Row, WorkItem, group_items, mark_unanswered,
                       named_years, row_label)
from .spec import Spec
from .verify import Refusal, quote_in, verify_tuple

log = logging.getLogger(__name__)

# Every key one coordinate owns on a claim (`fields.COORDINATE_KEYS`). Taking
# a coordinate off means taking all of them: `merge_field` short-circuits on
# `<name>_state` alone, but a leftover `_quote` or `_source` would then be
# evidence for an answer nobody gave.
SLOT_KEYS = fields.COORDINATE_KEYS


def keep_read() -> tuple:
    """A coordinate that was read stays read unless the sweep reads it
    again: the states of a new reading that replace it (rule
    `reread_keep_states`)."""
    return tuple(rules.get("reread_keep_states"))


def keep_asked() -> tuple:
    """A coordinate that was not read is bettered by any answer, "the
    passages do not say it" included -- that is an answer. Running out of
    budget is not (rule `reread_improves_states`)."""
    return tuple(rules.get("reread_improves_states"))


# What a claim carries that is not a claim: written by the verifier and by
# fold_claims, and rebuilt by them.
NOT_A_CLAIM = ("kind", "tier", "provenance", "flags")


def actionable(changed, spec: Spec, frame_names=(), *, dynamic_ok: bool = True,
               only=None) -> tuple:
    """(keys this pass may sweep, keys that block the document).

    A key blocks unless it names one coordinate of one parameter that the
    profile does not put in the frame and that this run can actually close.
    Anything else means the rows themselves are not what this run would
    produce, and sweeping one coordinate of them would leave a file that is
    half one run and half another with a stamp saying it is all one.
    """
    keys, blocked = [], []
    wanted = set(only or ())
    for key in sorted(changed or ()):
        # `targets_of` is the whole gate and it is narrow on purpose: it
        # answers only for a key naming a coordinate this spec still asks.
        # `value/<uri>` is the list a row maker answers from and no sweep
        # ever asks the value slot, so it fails here.
        targets = targets_of(spec, key)
        if not targets:
            blocked.append(key)
            continue
        if rules.get("reread_blocks_frame") and any(
                slot.name in set(frame_names or ()) for _p, slot in targets):
            # The frame decides how many passes the document gets, so a moved
            # frame coordinate can mean rows this file does not have.
            blocked.append(key)
            continue
        if rules.get("reread_blocks_dynamic_list") and not dynamic_ok \
                and any(
                getattr((parameter.axes or {}).get(slot.name), "dynamic", False)
                for parameter, slot in targets):
            # A dynamic list is filled per document, and swept against an
            # empty one the coordinate degrades to a wording: a wording
            # written where a class used to stand is a silent demotion.
            blocked.append(key)
            continue
        if wanted and key not in wanted:
            continue
        keys.append(key)
    return keys, blocked


def slot_of(spec: Spec, key: str):
    """"axis/<uri>/<name>" -> (parameter, slot), or None."""
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "axis":
        return None
    parameter = spec.by_uri.get(parts[1])
    if parameter is None:
        return None
    for slot in fields.axis_slots(parameter):
        if slot.name == parts[2]:
            return parameter, slot
    return None


def targets_of(spec: Spec, key: str) -> list:
    """[(parameter, slot)] a stamp key names; [] when it names no coordinate.

    "axis/<uri>/<name>" is one coordinate of one parameter. "slot/unit" is
    the unit of every numeric parameter: one question in the harvest, asked
    before the parameter is known, so one key -- and swept here parameter by
    parameter with that parameter's own list, because a stored row already
    knows its parameter.
    """
    if key == f"slot/{fields.UNIT}":
        out = []
        for parameter in spec.parameters:
            slot = fields.unit_slot(spec, parameter)
            if slot is not None:
                out.append((parameter, slot))
        return out
    got = slot_of(spec, key)
    return [got] if got is not None else []


def in_order(keys: list, spec: Spec) -> list:
    """[(key, parameter, slot)] of the moved coordinates in the order they
    are read again (rule `reread_order`): by the key of the stamp, each
    with its parameters in the spec's order, or by the order of the
    parameters in the spec."""
    triples = [(key, parameter, slot) for key in keys
               for parameter, slot in targets_of(spec, key)]
    if rules.get("reread_order") == "spec_order":
        place = {p.uri: at for at, p in enumerate(spec.parameters)}
        triples.sort(key=lambda t: place.get(t[1].uri, len(place)))
    return triples


def reopen(claim: dict, slot) -> dict:
    """Take this coordinate off the claim and hand back what was taken.

    A flag on `merge_field` would have been the other way, and it would have
    been the wrong way: the short-circuit it would bypass is what keeps one
    window from overwriting what an earlier one read, and that rule is not
    this pass's to soften.
    """
    taken = {}
    for suffix in SLOT_KEYS:
        key = f"{slot.name}{suffix}"
        if key in claim:
            taken[key] = claim.pop(key)
    return taken


def restore(claim: dict, slot, taken: dict, *, keep: tuple) -> bool:
    """Put the old block back unless the new state is one of `keep`.

    True when the old reading was restored, which is also what says the key
    cannot be written forward: the document still holds a coordinate this
    run's question never answered.
    """
    state = claim.get(f"{slot.name}_state")
    if state in keep:
        return False
    for suffix in SLOT_KEYS:
        claim.pop(f"{slot.name}{suffix}", None)
    claim.update(taken)
    return True


def owners_of(row: dict, slots: list) -> list:
    """The row's own passage, and every passage its coordinates were read in.

    The second half is what lets the sweep offer a coordinate the passage it
    was last read in: the re-entry rule works off the sources of the batch,
    and a passage nobody put in the batch cannot be offered.
    """
    provenance = row.get("provenance") or {}
    out = []
    own = (provenance.get("owner_kind"), provenance.get("owner_id"))
    if own[0] and own[1] is not None:
        out.append(own)
    for slot in slots:
        source = row.get(f"{slot.name}_source")
        if isinstance(source, (list, tuple)) and len(source) == 2:
            pair = (source[0], source[1])
            if pair not in out:
                out.append(pair)
    return out


def pairs_of(tuples: list, frame_axes) -> dict:
    """{index: pair} the frame wrote onto these stored rows.

    The harvest wrote each pair onto its rows with the window ["frame", i],
    so the pairs are recoverable from the file: one per index, from the first
    row that carries it, with the wording, quote and source the pair was read
    by. The indices have gaps where a pair no row carries, and the pairs come
    back under the index they were stored with, never renumbered.
    """
    if not frame_axes:
        return {}
    names = [slot.name for slot in frame_axes]
    pairs: dict = {}
    for row in tuples:
        windows = [row.get(f"{name}_window") for name in names]
        if not all(isinstance(w, (list, tuple)) and len(w) == 2
                   and w[0] == "frame" for w in windows):
            continue
        index = windows[0][1]
        if not isinstance(index, int) or index in pairs:
            continue
        pair = {}
        for name in names:
            for suffix in ("", "_raw", "_quote", "_source"):
                pair[f"{name}{suffix}"] = row.get(f"{name}{suffix}")
        pairs[index] = pair
    return pairs


def named_years_of(tuples: list, frame_axes, year_states) -> tuple:
    """The document's base years and target years, rebuilt from the frame's
    own readings.

    Without them a re-swept year that says "Basisjahr" or "Zieljahr" and
    prints no number cannot be read (`pipeline.named_year`): the main harvest
    could and this pass could not, which would cost the full run this pass
    exists to spare.
    """
    if not frame_axes or not any((year_states or {}).values()):
        return ()
    pairs = pairs_of(tuples, frame_axes)
    if not pairs:
        return ()
    ordered = [pairs.get(i) for i in range(max(pairs) + 1)]
    return tuple(named_years(ordered, frame_axes, year_states))


def rebuild(rows: list, parameter, sources: dict, carry: list) -> tuple:
    """(batches, {batch index: [Row]}) for a re-sweep of these stored tuples.

    One work item per row's own passage, plus one per carried-over passage, so
    the sweep's own window holds both. The parameter object is the same one on
    every item: `group_items` groups on identity.
    """
    items, owned = [], []
    for row in rows:
        provenance = row.get("provenance") or {}
        key = (provenance.get("owner_kind"), provenance.get("owner_id"))
        source = sources.get(key)
        if source is None:
            continue
        items.append(WorkItem(provenance.get("document_id"), parameter, source))
        owned.append(row)
    for key in carry:
        source = sources.get(key)
        if source is not None and not any(
                (i.source.owner_kind, i.source.owner_id) == key for i in items):
            items.append(WorkItem(source.provenance.get("document_id"),
                                  parameter, source))
    if not items:
        return [], {}
    from . import runner
    batches = group_items(items, max_sources=rules.get("batch_sources"),
                          max_chars=rules.get("batch_chars"))
    by_batch: dict = {}
    for index, batch in enumerate(batches):
        where = {(s.owner_kind, s.owner_id): i
                 for i, s in enumerate(batch.sources)}
        listed = []
        for row in owned:
            provenance = row.get("provenance") or {}
            at = where.get((provenance.get("owner_kind"),
                            provenance.get("owner_id")))
            if at is None:
                continue
            claim = {k: v for k, v in row.items() if k not in NOT_A_CLAIM}
            listed.append((row, Row(row_label(len(listed)), at, claim)))
        if listed:
            by_batch[index] = listed
    return batches, by_batch


def _reverify(row: dict, claim: dict, parameter, source,
              locate: Optional[Callable]):
    """The swept claim back through the verifier: the tuple, or its refusal.

    The same call `fold_claims` makes, and the provenance is kept rather than
    rebuilt: the rectangles a reader highlights come from a locator that is
    only configured when a PDF root is, and rebuilding blindly would drop
    every one of them.
    """
    finder = ((lambda quote, s=source: locate(s, quote))
              if locate is not None else None)
    outcome = verify_tuple(claim, parameter, source.text,
                           owner_kind=source.owner_kind, locate=finder)
    if isinstance(outcome, Refusal):
        return outcome
    out = dict(outcome.tuple)
    out["kind"] = "tuple"
    out["tier"] = outcome.tier
    if outcome.flags:
        out["flags"] = outcome.flags
    provenance = dict(row.get("provenance") or {})
    if outcome.rects:
        provenance["rects"] = outcome.rects
    out["provenance"] = provenance
    return out


def reopened_by_gate(tuples: list, spec: Spec, gate: dict,
                     frame_names=()) -> list:
    """[(parameter, slot, rows)] for coordinates a re-swept gate has released.

    The gate decides whether a row belongs in the slice this run serializes at
    all, and a row that left it was never asked its other coordinates. If the
    gate reads differently now, those questions were never put and the row
    would otherwise keep a coordinate saying it left a slice it is in.
    """
    if not gate or not rules.get("reread_reopen_closed_rows"):
        return []
    from . import runner
    out: list = []
    for parameter in spec.parameters:
        mine = [r for r in tuples if r.get("parameter") == parameter.uri]
        if not mine:
            continue
        slots = [s for s in fields.asked_slots(parameter)
                 if s.name not in set(frame_names or ())]
        gates = [s for s in slots if s.name in gate]
        if not gates:
            continue
        staying = [r for r in mine
                   if all(runner.keeps_row(s, r.get(s.name), gate[s.name])
                          for s in gates)]
        for slot in slots:
            if slot.name in gate:
                continue
            rows = [r for r in staying
                    if r.get(f"{slot.name}_state") == fields.OUT_OF_SLICE]
            if rows:
                out.append((parameter, slot, rows))
    return out


@dataclass
class Stored:
    """A harvest file as it lies on disk, read once.

    `entries` holds every line but the summary, in order, as (the line as it
    stands in the file, the record it parses to or None). A pass that
    rewrites a line puts its own record in the line's place and a pass that
    does not writes the line back byte for byte; the summary is always built
    again, so the old one is left out.
    """
    entries: list = field(default_factory=list)
    tuples: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    states: list = field(default_factory=list)
    document_id: Optional[int] = None
    unreadable: int = 0

    @property
    def lines(self) -> list:
        return [raw for raw, _row in self.entries]


def read_harvest(path) -> Stored:
    """The lines of one harvest file, sorted by what they are.

    The file is read as bytes and split at the line feed alone, so a line is
    what it was down to a carriage return (`jsonl.lines`). A line that is not
    JSON, or is JSON and no record, is kept as it stands and counted. An empty
    line is not a record and is not kept.
    """
    stored = Stored()
    for line in jsonl.lines(Path(path).read_bytes().decode("utf-8")):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            row = None
        if not isinstance(row, dict):
            stored.unreadable += 1
            stored.entries.append((line, None))
            continue
        kind = row.get("kind")
        if kind == "summary":
            stored.document_id = row.get("document_id")
            continue
        stored.entries.append((line, row))
        if kind == "tuple":
            stored.tuples.append(row)
        elif kind == "refusal":
            stored.refusals.append(row)
        elif kind == "parameter_state":
            stored.states.append(row)
    return stored


# A coordinate this pass asks again: still open when the budget ended, never
# answered, or answered with a passage that did not carry it.
OPEN = fields.OPEN                 # the rule `open_states`
OPEN_PASS = "top-up-open"


def open_coordinates(tuples: list, spec: Spec) -> list:
    """[(parameter, slot, rows)] of every asked coordinate some row left open.

    The frame's coordinates are among them: a row whose year is open was not
    under a pair, and its year is asked per row like any other coordinate.
    """
    out: list = []
    for parameter in spec.parameters:
        mine = [r for r in tuples if r.get("parameter") == parameter.uri]
        if not mine:
            continue
        for slot in fields.asked_slots(parameter):
            rows = [r for r in mine if r.get(f"{slot.name}_state") in OPEN]
            if rows:
                out.append((parameter, slot, rows))
    return out


def point(claim: dict, slot, position: Optional[int]) -> None:
    """Say that this pass wrote this coordinate: `<axis>_producer` is the
    position of its entry in the stamp's list. Nothing to point at, nothing
    written."""
    if position is not None:
        claim[f"{slot.name}{fields.PRODUCER}"] = position


@dataclass
class Sweep:
    """One dimension asked again, between asking and deciding: the rows,
    their batches, and what each row's entry held before it was taken
    off."""
    rows: list
    parameter: object
    slot: object
    usable: list = field(default_factory=list)
    batches: list = field(default_factory=list)
    by_batch: dict = field(default_factory=dict)
    taken: dict = field(default_factory=dict)   # batch index -> {label: block}
    settled: bool = True
    ended: bool = False             # no row had a passage to be read in
    locate: Optional[Callable] = None


def sweep_ask(rows: list, parameter, slot, doc_spec: Spec, deps: dict,
              stats: Counter, bases: tuple = ()) -> Sweep:
    """Take one coordinate off these rows and ask it again.

    The coordinate is asked as the harvest asks it (`deps["sweep"]`), over
    the passages its rows were read in. What the rows held is kept in the
    returned `Sweep` for `sweep_decide`, which keeps it or the new answer.
    """
    slots = [slot]
    owners: list = []
    for row in rows:
        for pair in owners_of(row, slots):
            if pair not in owners:
                owners.append(pair)
    sources = deps["owner_sources"](owners)

    sweep = Sweep(rows, parameter, slot, locate=deps.get("locate"))
    for row in rows:
        provenance = row.get("provenance") or {}
        source = sources.get((provenance.get("owner_kind"),
                              provenance.get("owner_id")))
        if source is None or not quote_in(source.text or "",
                                          row.get("quote") or ""):
            # The database moved under the harvest. Left byte-identical: a
            # row whose own passage no longer carries its quote cannot be
            # re-read against that passage at all.
            stats["source moved"] += 1
            sweep.settled = False
            continue
        sweep.usable.append(row)
    if not sweep.usable:
        sweep.settled, sweep.ended = False, True
        return sweep

    own = {(provenance.get("owner_kind"), provenance.get("owner_id"))
           for provenance in ((r.get("provenance") or {})
                              for r in sweep.usable)}
    carry = [pair for pair in owners if pair not in own]
    sweep.batches, sweep.by_batch = rebuild(sweep.usable, parameter,
                                            sources, carry)
    for batch in sweep.batches:
        # The document's, not the request's: they hold for every passage.
        batch.bases = tuple(bases)
    from . import runner
    # The unit's set is written once for all parameters, under its own
    # key; a per-parameter id would find no set and search with the
    # question instead.
    anchor_id = (runner.UNIT_ANCHOR if slot.name == fields.UNIT
                 else runner.anchor_key(parameter.uri, slot.name))
    for index, batch in enumerate(sweep.batches):
        listed = sweep.by_batch.get(index) or []
        if not listed:
            continue
        entries = [entry for _row, entry in listed]
        sweep.taken[index] = {entry.label: reopen(entry.claim, slot)
                              for entry in entries}
        deps["sweep"](batch, entries, slots, anchor_id)
    return sweep


def sweep_decide(sweep: Sweep, stats: Counter,
                 position: Optional[int] = None) -> tuple:
    """Keep what the coordinate was asked again, or what it held.

    (every row settled, the rows the verifier refused afterwards). A refused
    row was rewritten in place as the refusal it now is: the re-read said the
    coordinate is not what the tuple carried -- a unit no list holds, a
    required axis the passages do not state -- and that is the finding, with
    the claim kept beside the reason for the audit. Keeping the old tuple
    instead would leave in the graph exactly the reading the re-read was
    asked to check.

    A coordinate whose new reading stands points at `position`, this pass's
    entry in the stamp's list (`point`). One whose old block was put back
    keeps the pointer that block had, or none.
    """
    parameter, slot = sweep.parameter, sweep.slot
    refused: list = []
    settled = sweep.settled
    if sweep.ended:
        return False, refused
    for index, batch in enumerate(sweep.batches):
        listed = sweep.by_batch.get(index) or []
        if not listed:
            continue
        entries = [entry for _row, entry in listed]
        taken = sweep.taken[index]
        wrote = []
        for _row, entry in listed:
            keep = (keep_read() if taken[entry.label].get(
                f"{slot.name}_state") in keep_read() else keep_asked())
            if restore(entry.claim, slot, taken[entry.label], keep=keep):
                settled = False
                # Nothing was there to put back (a spec that gained this
                # axis): what is written below is this pass's.
                if taken[entry.label]:
                    continue
            wrote.append(entry)
        # After the restores and not before. A spec that GAINED this axis has
        # rows with no block to put back, so `restore` leaves a bare absence
        # -- and the schema requires a state on every coordinate of every row.
        mark_unanswered(entries, [slot])
        for entry in wrote:
            point(entry.claim, slot, position)
        for row, entry in listed:
            source = batch.sources[entry.item_index]
            fresh = _reverify(row, entry.claim, parameter, source,
                              sweep.locate)
            if isinstance(fresh, Refusal):
                if rules.get("reread_refused_becomes_refusal") == "keep_old":
                    # The row stays as it was, and the coordinate is not
                    # settled: the stamp of its key is not carried forward.
                    stats["kept after refused re-reading"] += 1
                    settled = False
                    continue
                stats["refused after re-reading"] += 1
                row.clear()
                row.update({"kind": "refusal", "parameter": parameter.uri,
                            "reason": fresh.reason, "claim": fresh.raw,
                            "owner": [source.owner_kind, source.owner_id]})
                refused.append(row)
                continue
            row.clear()
            row.update(fresh)
            stats["rows"] += 1
    return settled, refused


def _sweep_one(rows: list, parameter, slot, doc_spec: Spec, deps: dict,
               stats: Counter, bases: tuple = (),
               position: Optional[int] = None) -> tuple:
    """Ask one coordinate again over these rows and decide it: (every row
    settled, the rows refused afterwards)."""
    sweep = sweep_ask(rows, parameter, slot, doc_spec, deps, stats, bases)
    return sweep_decide(sweep, stats, position)
