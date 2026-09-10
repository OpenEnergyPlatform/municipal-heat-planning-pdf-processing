"""
topup.py: Re-reads the one coordinate a stamp names as moved, instead of the
whole document.

A question is reworded, or an option list gains a class the model can now
choose. The stamp knows exactly which key moved, and a
resume then does the only thing it can: it reports the document stale, and the
next run harvests it again from the first passage. For one axis of one
parameter, that is a full corpus run spent answering a question nothing else
asked.

This module instead takes the coordinate off the rows that carry it, walks the
same sweep the harvest walks (`runner.make_sweeper`, so there is one sweep and
one set of numbers), and writes the answer back. It then carries that one stamp
key forward and leaves every other key exactly as it was, so a later run still
sees what it has to redo.

What the module refuses to touch matters more than what it does. A key that
decided which rows exist, which passages were planned, or which model read them
does not name a coordinate: the rows are then not this run's product at all,
and the document is skipped whole rather than half repaired. The frame is
refused for the same reason one level up, because it decides how many passes a
document gets.

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
from pathlib import Path
from typing import Callable, Optional

from . import fields
from .pipeline import (Row, WorkItem, group_items, mark_unanswered, row_label)
from .remap import stamp_forward, stamp_path_of
from .spec import Spec
from .trust import document_summary
from .verify import Refusal, quote_in, verify_tuple

log = logging.getLogger(__name__)

# Every key one coordinate owns on a claim -- `schema._slot_properties`. Taking
# a coordinate off means taking all eight: `merge_field` short-circuits on
# `<name>_state` alone, but a leftover `_quote` or `_source` would then be
# evidence for an answer nobody gave.
SLOT_KEYS = ("", "_state", "_raw", "_raw_foreign", "_quote", "_source",
             "_window", "_seen")

# A coordinate that was read stays read unless the sweep reads it again.
KEEP_READ = (fields.READ, fields.DERIVED)
# A coordinate that was not read is bettered by any answer, "the passages do
# not say it" included -- that is an answer. Running out of budget is not.
KEEP_ASKED = KEEP_READ + (fields.SAID_UNSTATED,)

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
        # `slot_of` is the whole gate and it is narrow on purpose: it answers
        # only for `axis/<uri>/<name>` naming a coordinate this spec still
        # asks. `value/<uri>` is the list a row maker answers from and no
        # sweep ever asks the value slot, so it fails here.
        got = slot_of(spec, key)
        if got is None:
            blocked.append(key)
            continue
        parameter, slot = got
        if slot.name in set(frame_names or ()):
            # The frame decides how many passes the document gets, so a moved
            # frame coordinate can mean rows this file does not have.
            blocked.append(key)
            continue
        axis = (parameter.axes or {}).get(slot.name)
        if not dynamic_ok and getattr(axis, "dynamic", False):
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
    batches = group_items(items, max_sources=runner.BATCH_SOURCES,
                          max_chars=runner.BATCH_CHARS)
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
              locate: Optional[Callable]) -> Optional[dict]:
    """The swept claim back through the verifier, or None if it refuses.

    The same call `fold_claims` makes, and the provenance is kept rather than
    rebuilt: the rectangles a reader highlights come from a locator that is
    only configured when a PDF root is, and rebuilding blindly would drop
    every one of them.
    """
    finder = ((lambda quote, s=source: locate(s, quote))
              if locate is not None else None)
    outcome = verify_tuple(claim, parameter, source.text,
                           owner_kind=source.owner_kind, locate=finder,
                           repair_text=source.body)
    if isinstance(outcome, Refusal):
        return None
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
    if not gate:
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


def top_up_file(path: Path, spec: Spec, current: dict, deps: dict, *,
                only=None) -> Counter:
    """Re-sweep one harvest file's moved coordinates, then carry its stamp."""
    stats: Counter = Counter()
    stamp_path = stamp_path_of(Path(path))
    from . import runner
    changed = runner.stale(stamp_path, current)
    if not changed:
        stats["already current"] += 1
        return stats

    lines: list = []
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
            continue
        if row.get("kind") != "tuple":
            if row.get("kind") == "refusal":
                refusals.append(row)
            lines.append(line)
            continue
        tuples.append(row)
        lines.append(row)

    doc_spec = deps["document_spec"](document_id) if document_id else spec
    if doc_spec is None:
        stats["dynamic list unavailable"] += 1
        return stats
    keys, blocked = actionable(changed, doc_spec, deps.get("frame_names") or (),
                               dynamic_ok=deps.get("dynamic_ok", True),
                               only=only)
    if blocked or not keys:
        stats["blocked" if blocked else "nothing to sweep"] += 1
        return stats

    settled = set(keys)
    for key in keys:
        parameter, slot = slot_of(doc_spec, key)
        mine = [r for r in tuples if r.get("parameter") == parameter.uri]
        if not mine:
            continue
        if slot.derive:
            # No request: the spec decides this coordinate. Reopening is what
            # makes apply_derived write, because it skips a row that already
            # carries a state.
            rows = [Row(row_label(i), 0, r) for i, r in enumerate(mine)]
            for entry in rows:
                reopen(entry.claim, slot)
            stats["derived"] += fields.apply_derived(rows, slot)
            continue
        got = _sweep_one(mine, parameter, slot, doc_spec, deps, stats)
        if not got:
            settled.discard(key)

    # A row the gate had closed may now stay, and its other coordinates were
    # never asked. They carry `out_of_slice`, which is not a reading and not a
    # finding about the plan: it says the row left before the question.
    for parameter, slot, mine in reopened_by_gate(
            tuples, doc_spec, deps.get("slice_gate") or {},
            deps.get("frame_names") or ()):
        stats["closed rows reopened"] += len(mine)
        _sweep_one(mine, parameter, slot, doc_spec, deps, stats)

    if document_id is not None:
        lines.append({"kind": "summary",
                      **document_summary(document_id, tuples, refusals)})
    out = [json.dumps(row, ensure_ascii=False) if isinstance(row, dict)
           else row for row in lines]
    tmp = Path(path).with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(path)
    if stamp_forward(stamp_path, current, settled):
        stats["stamps carried forward"] += 1
    return stats


def _sweep_one(rows: list, parameter, slot, doc_spec: Spec, deps: dict,
               stats: Counter) -> bool:
    """Re-read one coordinate over these rows. True when every row settled."""
    slots = [slot]
    owners: list = []
    for row in rows:
        for pair in owners_of(row, slots):
            if pair not in owners:
                owners.append(pair)
    sources = deps["owner_sources"](owners)

    usable, settled = [], True
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
            settled = False
            continue
        usable.append(row)
    if not usable:
        return False

    own = {(provenance.get("owner_kind"), provenance.get("owner_id"))
           for provenance in ((r.get("provenance") or {}) for r in usable)}
    carry = [pair for pair in owners if pair not in own]
    batches, by_batch = rebuild(usable, parameter, sources, carry)
    from . import runner
    anchor_id = runner.anchor_key(parameter.uri, slot.name)
    for index, batch in enumerate(batches):
        listed = by_batch.get(index) or []
        if not listed:
            continue
        entries = [entry for _row, entry in listed]
        taken = {entry.label: reopen(entry.claim, slot) for entry in entries}
        deps["sweep"](batch, entries, slots, anchor_id)
        for _row, entry in listed:
            keep = (KEEP_READ if taken[entry.label].get(f"{slot.name}_state")
                    in KEEP_READ else KEEP_ASKED)
            if restore(entry.claim, slot, taken[entry.label], keep=keep):
                settled = False
        # After the restores and not before. A spec that GAINED this axis has
        # rows with no block to put back, so `restore` leaves a bare absence
        # -- and the schema requires a state on every coordinate of every row.
        mark_unanswered(entries, slots)
        for row, entry in listed:
            source = batch.sources[entry.item_index]
            fresh = _reverify(row, entry.claim, parameter, source,
                              deps.get("locate"))
            if fresh is None:
                # The re-verification refuses what the sweep produced. The row
                # keeps the reading it had, which is what it still holds --
                # nothing has been written to the file yet.
                stats["re-verification refused"] += 1
                settled = False
                continue
            row.clear()
            row.update(fresh)
            stats["rows"] += 1
    return settled


def run(harvest_dir: Path, spec: Spec, current: dict, deps: dict, *,
        only=None) -> Counter:
    """Top up a whole harvest directory against the spec as it reads today."""
    stats: Counter = Counter()
    harvest_dir = Path(harvest_dir)
    for path in sorted(harvest_dir.glob("*.jsonl")):
        if path.name.endswith(".trace.jsonl"):
            continue
        stats.update(top_up_file(path, spec, current, deps, only=only))
        stats["documents"] += 1
    for key, value in sorted(stats.items()):
        log.info("top-up: %-32s %d", key, value)
    return stats
