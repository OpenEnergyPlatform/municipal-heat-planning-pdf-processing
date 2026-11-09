"""
surveyed.py: One document harvested piece by piece, both profiles (owner
decisions 2026-11-08 evening).

The document's passages as numbered lines in pieces of at most eight, its
figures transcribed once (`addressed.Transcripts`); what the plan settles
for all its values and its own years asked once (`addressed.Reader.settled`);
then every field read: a field the document has once asked once, every other
field in every piece, the pieces best first for its sentences
(`addressed.Orders`), and each value's coordinates asked one by one
(`addressed.Reader`). The run folds what they read, works out what the
profile computes and writes the file with its stamp, as it writes every
harvest.

What could not be read is a hole with its reason, never a plan that seems
silent: a passage a field was to be read in that came to no readable reply
goes to the fold as the harvest's sentinel (`_harvest_failed`, `_why`
cut_off or no_answer). The fold keeps it as a refusal, and a field that has
no row then ends `exhausted` and not `unstated` (`trust.parameter_states`).
The hole of a reading names its field (`_parameter`), so a pass over the
harvest knows what to read again.

The passes over a stored harvest go through the same steps. `--start-at`
reads the passages earlier harvests found something in (`take_found`);
`--top-up-parameters` reads the whole plan for the fields the spec gained
(`append_parameters`); `--top-up-open` asks every coordinate left open again
(`SurveyedHarvest.sweep` under `topup._sweep_one`) and then reads what
nothing has read yet (`append_unread`); `--top-up` asks the coordinates
whose question moved (`SurveyedHarvest.sweep`). An order of part of a plan
is kept under its own scope beside the whole one's.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import copy
import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .lookup import continued
from . import fields
from .addressed import Counts, Plan
from .pipeline import (Batch, DocumentReport, Row, WorkItem, drop_repeats,
                       row_label)
from .reading import NO_ANSWER, Read
from .survey import Answer, Found
from .units import CHUNK_UNITS
from .verify import canonical_number, flat, quote_in

log = logging.getLogger(__name__)

# The stage a passage of a plan read piece by piece was read in
# (`DocumentReport.planned`).
STAGE = "survey"
# Where the frame of a field appended to a stored harvest came from.
FRAME_SURVEYED = "the survey of the new parameters"
# Documents whose pieces a pass over a stored harvest keeps at once.
PLANS_KEPT = 8


def hole(document_id: int, source, why: str,
         parameter: Optional[str] = None) -> tuple:
    """(batch, reply) the fold turns into the refusal of a passage nothing
    could read: the sentinel claim with its reason, filed under no parameter
    as every sentinel is, the parameter it was read for beside it."""
    batch = Batch(document_id, None, [WorkItem(document_id, None, source)])
    claim = {"_harvest_failed": True, "_why": why, "source": batch.label(0)}
    if parameter:
        claim["_parameter"] = parameter
    return batch, {"tuples": [claim]}


def derive_left(reads: list) -> int:
    """What the spec derives from the unit, on every value no request read
    it for once its coordinates are asked (owner decision 2026-11-07: asked
    first, and only where no answer is read taken from the unit,
    `fields.derives`). Returns how many coordinates."""
    done = 0
    for read in reads:
        parameter = read.batch.parameter
        if parameter is None:
            continue
        for slot in fields.axis_slots(parameter):
            if not slot.derive:
                continue
            done += fields.apply_derived(
                [Row(row_label(i), 0, claim)
                 for i, claim in enumerate(read.claims)
                 if fields.derives(slot, claim, parameter)], slot)
    return done


@dataclass
class Taken:
    """What the reading of one document came to, in the shape the fold and
    the stamp read."""
    reads: list = field(default_factory=list)
    # (batch, reply) for the fold: every reading's values and every hole.
    answered: list = field(default_factory=list)
    # Readings that came back with a reply: none of them means no reply at
    # all (`runner.not_happened`).
    replies: int = 0
    passages: int = 0
    # parameter uri -> the passages it was read in (`trust.parameter_states`).
    sources_of: dict = field(default_factory=dict)


def taken_of(document_id: int, spec, reads: list) -> Taken:
    """The fold's view of one document's reading, holes included. A field's
    sources are the passages it was read in."""
    answered: list = []
    sources_of: dict = {p.uri: set() for p in spec.parameters}
    for read in reads:
        source = read.batch.items[0].source
        uri = read.batch.parameter.uri
        sources_of.setdefault(uri, set()).add((source.owner_kind,
                                               source.owner_id))
        if read.unread:
            answered.append(hole(document_id, source, read.why or NO_ANSWER,
                                 uri))
            continue
        answered.append((read.batch, {"tuples": read.claims}))
        # A piece of the passage no reply answered, the others read.
        answered.extend(hole(document_id, source, why, uri)
                        for why in read.lost)
    replies = sum(1 for read in reads if not read.unread)
    passages = len({(r.batch.items[0].source.owner_kind,
                     r.batch.items[0].source.owner_id) for r in reads})
    return Taken(reads, answered, replies, passages, sources_of)


def locate_value(plan: Plan, source, claim: dict) -> Optional[dict]:
    """The address of a stored value in its passage (`at`): the line its
    quote stands in, the cell of a table row that alone holds its number or
    words; None where no line of the passage holds the quote. A value read
    with its address keeps it."""
    if isinstance(claim.get("at"), dict):
        return claim["at"]
    passage = plan.passages.get((source.owner_kind, source.owner_id))
    quote = claim.get("quote")
    if passage is None or not isinstance(quote, str):
        return None
    lines = [line for line in passage.lines
             if quote_in(line.text, quote) or quote_in(quote, line.text)]
    if not lines:
        return None
    line = lines[0]
    at = {"owner": list(passage.owner), "line": line.number}
    words = str(claim.get("value_raw") or claim.get("value") or "")
    number = canonical_number(words)
    if line.cells:
        holding = [i for i, cell in enumerate(line.cells, start=1)
                   if (number is not None and canonical_number(cell)
                       == number) or (words and flat(words).casefold()
                                      in flat(cell).casefold())]
        if len(holding) == 1:
            at["cell"] = holding[0]
    return at


class SurveyedHarvest:
    """document_id -> Taken, or None when the run was halted on the way.

    *make_reader(spec)* is the run's reading (`addressed.Reader`), made
    once per spec; *spec_for(document_id)* the document's spec, its lists
    closed (`runner.closed_spec`); *passages_of(document_id)* every passage
    of the document in its order; *transcripts(document_id, figures, each)*
    its figures' lines (`addressed.Transcripts`); *orders(plan, parameters,
    chunk_units, scope, chunks)* the pieces of each field best first
    (`addressed.Orders`); *halted()* whether the run stops. *chunk_units*
    is how many lines a piece holds; *each(jobs, run)* runs jobs side by
    side; *trace* writes what a document's requests came to.
    """

    def __init__(self, spec, make_reader: Callable, passages_of: Callable,
                 *, spec_for: Optional[Callable] = None,
                 halted: Optional[Callable] = None,
                 transcripts: Optional[Callable] = None,
                 orders: Optional[Callable] = None,
                 chunk_units: int = CHUNK_UNITS,
                 each: Optional[Callable] = None, trace=None):
        self.spec = spec
        self.make_reader = make_reader
        self.passages_of = passages_of
        self.spec_for = spec_for or (lambda document_id: spec)
        self.halted = halted or (lambda: False)
        self.transcripts = transcripts
        self.orders = orders
        self.chunk_units = int(chunk_units)
        self.each = each
        self.trace = trace
        self._made: dict = {}
        self._plans: collections.OrderedDict = collections.OrderedDict()
        self._lock = threading.Lock()

    def reader_of(self, spec):
        # The spec is held with what was made of it, so its id is not given
        # to another spec while the entry stands.
        with self._lock:
            key = id(spec)
            if key not in self._made:
                self._made[key] = (spec, self.make_reader(spec))
            return self._made[key][1]

    def plan_of(self, document_id: int) -> tuple:
        """(the document's Plan, its Counts): its pieces, its figures'
        lines, what it settles and its years. A pass over a stored harvest
        asks several batches of one document and finds it made."""
        with self._lock:
            if document_id in self._plans:
                self._plans.move_to_end(document_id)
                return self._plans[document_id]
        spec = self.spec_for(document_id)
        sources = continued(self.passages_of(document_id))
        figures = [s for s in sources if s.owner_kind == "figure"]
        lines, asked = {}, 0
        if self.transcripts is not None and figures:
            lines, asked = self.transcripts(document_id, figures, self.each)
        plan = Plan(document_id, sources, lines, self.chunk_units)
        counts = Counts()
        if asked:
            counts.ask("transcribe", asked)
        reader = self.reader_of(spec)
        reader.lists_of(plan)
        reader.settled(plan, counts)
        with self._lock:
            self._plans[document_id] = (plan, counts)
            while len(self._plans) > PLANS_KEPT:
                self._plans.popitem(last=False)
        return plan, counts

    def forget(self, document_id: int) -> None:
        with self._lock:
            self._plans.pop(document_id, None)

    def __call__(self, document_id: int, *, only=(), scope: str = "",
                 passages: Optional[list] = None,
                 also: Optional[Found] = None) -> Optional[Taken]:
        """The whole plan, or part of it: for the fields *only*, the
        *passages* given, under *scope*. *also* names passages to read for
        some fields besides (`take_found`, `append_unread`)."""
        spec = self.spec_for(document_id)
        plan, counts = self.plan_of(document_id)
        self.forget(document_id)
        if self.halted():
            return None
        wanted = set(only or ())
        parameters = [p for p in spec.parameters
                      if not wanted or p.uri in wanted]
        chosen = None
        if passages is not None:
            owners = {(s.owner_kind, s.owner_id) for s in passages}
            chosen = [c for c in plan.chunks if c.owner in owners]
        chunks: dict = {p.uri: (list(chosen) if chosen is not None
                                else None) for p in parameters}
        if also is not None:
            for owner, answer in also.answers.items():
                extra = [c for c in plan.chunks if c.owner == tuple(owner)]
                for uri in answer.parameters:
                    parameter = spec.by_uri.get(uri)
                    if parameter is None:
                        continue
                    if uri not in chunks:
                        parameters.append(parameter)
                        chunks[uri] = []
                    if chunks[uri] is not None:
                        chunks[uri] += [c for c in extra
                                        if c not in chunks[uri]]
        located = [p for p in parameters
                   if not getattr(p, "once_per_document", False)]
        if any(got is None for got in chunks.values()):
            read_in = list(plan.chunks)
        else:
            read_in = sorted({c for got in chunks.values() for c in got},
                             key=lambda c: plan.position[c.key])
        order_of = (self.orders(plan, located, self.chunk_units, scope,
                                read_in)
                    if self.orders is not None and located else {})
        reads = self.reader_of(spec)(plan, parameters, chunks, counts,
                                     order_of)
        if self.halted():
            return None
        derive_left(reads)
        if self.trace is not None:
            self.trace("asked", document_id, requests=dict(counts.asked),
                       refused=dict(counts.failed),
                       question_queries=counts.questions,
                       chunks=len(plan.chunks), scope=scope or None)
        return taken_of(document_id, spec, reads)

    def sweep(self, batch, rows, slots, anchor=None) -> None:
        """What a pass over a stored harvest asks a coordinate again with
        (`topup._sweep_one`): each row's value at the line its quote stands
        in, each coordinate of *slots* asked as the harvest asks it
        (`addressed.Reader.coordinate`); what it leaves open is restored by
        the pass as it restores any sweep's."""
        document_id = batch.document_id
        spec = self.spec_for(document_id)
        reader = self.reader_of(spec)
        plan, counts = self.plan_of(document_id)
        read = Read(batch, [])
        groups = {name: group for group in spec.groups.values()
                  for name in group.coordinates}
        made = {"n": 0}

        def clone(row: Row) -> Row:
            made["n"] += 1
            return Row(f"{row.label}.{made['n']}", row.item_index,
                       copy.deepcopy(row.claim))
        for row in rows:
            source = batch.items[row.item_index].source
            at = locate_value(plan, source, row.claim)
            if at is None:
                continue
            row.claim["at"] = at
            for slot in slots:
                row.claim.pop(f"{slot.name}_state", None)
                reader.coordinate(plan, read, row, groups.get(slot.name),
                                  slot, counts, clone)


def take_found(whole: SurveyedHarvest, document_id: int, kept: list,
               gained: list) -> Optional[Taken]:
    """--start-at: the passages earlier harvests found something in, and
    for a field none of them was asked (*gained*) the rest of the plan as
    well, so that it is read over the whole plan as in any run (owner
    decision 2026-11-03)."""
    also = None
    if gained:
        held = {(s.owner_kind, s.owner_id) for s in kept}
        rest = [s for s in whole.passages_of(document_id)
                if (s.owner_kind, s.owner_id) not in held]
        if rest:
            also = Found(True)
            for source in rest:
                owner = (source.owner_kind, source.owner_id)
                also.answers[owner] = Answer(owner, list(gained))
    return whole(document_id, scope="found", passages=kept, also=also)


def _counted(log_label: str):
    """A pass in the run's own loop: harvest_document(document_id, filename)
    -> (written, failures), with what it counted, logged at the end."""

    class Counted:
        def __init__(self, step: Callable):
            self.step = step
            self.stats: Counter = Counter()
            self._lock = threading.Lock()

        def __call__(self, document_id: int, filename: str) -> tuple:
            written, failed, stats = self.step(document_id, filename)
            from . import trace
            trace.flush(document_id)
            with self._lock:
                self.stats.update(stats)
                self.stats["documents looked at (documents)"] += 1
            return written, failed

        def report(self) -> None:
            with self._lock:
                for key, value in sorted(self.stats.items()):
                    log.info("%s: %-64s %d", log_label, key, value)

    return Counted


def append_parameters(document_id: int, filename: str, out_dir: Path,
                      spec, current: dict, deps: dict) -> tuple:
    """(written, failures, stats) of --top-up-parameters for one stored
    document, in a run that harvests from the survey.

    The rules of `topup_parameter.append_document`, which this is for such a
    run: only the addition may have moved, the stored lines stay as they
    are, and nothing is written, neither file nor stamp, unless the new
    parameters were read. They are read by a survey of the whole plan for
    them alone (*deps["take"](document_id, uris)*), read piece by piece
    with their coordinates asked and searched for; the frame of their rows
    comes from that survey.

    *deps* holds "document_spec" (id -> the document's spec, None when its
    lists cannot be closed), "take", "locate", "frame_names" and
    "dynamic_ok".
    """
    from . import runner
    from .remap import (enter_producer, next_producer, stamp_forward,
                        stamp_path_of)
    from .topup_parameter import (PASS, _write_lines, appended_lines,
                                  classify, drop_stored_repeats, not_read,
                                  point)
    from .trust import parameter_states
    stats: Counter = Counter()
    name = Path(filename).stem
    path = Path(out_dir) / f"{name}.jsonl"
    stamp_path = stamp_path_of(path)
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
        if stamp_forward(stamp_path, current, settled):
            stats["stamps completed, the file already held the parameters "
                  "(documents)"] += 1
            return True, 0, stats
        log.error("top-up-parameters: %s holds %s and its stamp could not be "
                  "completed", name, ", ".join(uris))
        stats["documents not taken (documents)"] += 1
        return False, 1, stats

    doc_spec = deps["document_spec"](document_id) or spec
    before = runner.UNSERVED.of(document_id)
    taken = deps["take"](document_id, uris)
    if taken is None:
        return False, 0, stats
    report = DocumentReport(document_id=document_id,
                            owners_harvested=taken.passages,
                            planned={STAGE: taken.passages},
                            sources_of=taken.sources_of)
    runner.fold_answers(taken.answered, report, locate=deps.get("locate"),
                        spec=doc_spec)
    drop_repeats(report)
    verdict_run = runner.not_happened(
        report, answered=taken.replies,
        lost=runner.UNSERVED.of(document_id) - before)
    if verdict_run is not None:
        log.error("top-up-parameters: %s: %s was not read completely, %s; "
                  "nothing is written", name, ", ".join(uris),
                  not_read(*verdict_run))
        stats["documents not read completely (documents)"] += 1
        return False, 1, stats

    only = runner.narrow_spec(doc_spec, uris)
    states = parameter_states(only, report.tuples, report.refusals,
                              harvested=report.owners_harvested,
                              answered=taken.replies,
                              sources_of=report.sources_of)
    rows, identical = drop_stored_repeats(report.tuples, stored.tuples)
    position = next_producer(stamp_path)
    for row in rows:
        point(row, position)
    report.tuples = rows
    runner.check_against_schema(report, name, spec, states)
    # Entered before the rows that point at it.
    enter_producer(stamp_path, {**runner.producer(PASS, runner.LLM_MODEL),
                                "parameters": uris, "frame": FRAME_SURVEYED})
    _write_lines(path, appended_lines(stored, document_id, rows,
                                      report.refusals, states))
    if not stamp_forward(stamp_path, current, settled):
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


def surveyed_owners(out_dir: Path, document_id: int) -> tuple:
    """({owner: Answer} every stored survey of the document answered, and
    the owners none of them could) from `survey/<document>[.<scope>].json`.
    What was surveyed is read from the files whatever key they were kept
    under: a pass reads what the harvest covered, not what it would ask
    today."""
    answers: dict = {}
    unanswered: set = set()
    folder = Path(out_dir) / "survey"
    for path in sorted(folder.glob(f"{document_id}.json")) + sorted(
            folder.glob(f"{document_id}.*.json")):
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in kept.get("answers") or ():
            owner = tuple(entry.get("owner") or ())
            if len(owner) != 2:
                continue
            answers.setdefault(owner, Answer(
                owner, list(entry.get("parameters") or ()),
                dict(entry.get("tuples") or {}),
                list(entry.get("dropped") or ())))
        unanswered.update(tuple(o) for o in kept.get("unanswered") or ()
                          if len(o) == 2)
    return answers, unanswered - set(answers)


def holes_of(refusals: list) -> tuple:
    """({owner} of passages nothing read, {owner: {parameter}} of passages a
    parameter's reading came to nothing in) among a harvest's refusals."""
    passages: set = set()
    readings: dict = {}
    for refusal in refusals:
        claim = refusal.get("claim") or {}
        owner = refusal.get("owner")
        if not claim.get("_harvest_failed") or not owner or len(owner) != 2:
            continue
        parameter = claim.get("_parameter")
        if parameter:
            readings.setdefault(tuple(owner), set()).add(parameter)
        else:
            passages.add(tuple(owner))
    return passages, readings


def append_unread(document_id: int, filename: str, out_dir: Path,
                  deps: dict) -> tuple:
    """(written, failures, stats) of the second half of --top-up-open for
    one stored document, in a run that harvests from the survey: what
    nothing has read yet, read now and appended after the stored lines.

    Unread is a passage no survey of the harvest answered (one it left
    unanswered, or one outside the found places of a harvest read in part),
    and a passage a parameter's reading came to nothing in (a hole that
    names its parameter, `_parameter`), which is read again for that
    parameter alone with what its survey said of the passage. A harvest of
    the old flow has no surveys: what its rows requests were shown counts as
    read (`topup_rest.read_owners`). A document with neither is skipped, as
    in that flow. A document this pass has read to its end says so in its
    stamp (`topup_rest.PASS`) and is not read again.

    *deps* holds "take" (document_id, passages, also -> Taken), "passages_of"
    (document_id -> every passage), "locate" and "spec".
    """
    from . import runner
    from .remap import enter_producer, next_producer, stamp_path_of
    from .topup import read_harvest
    from .topup_parameter import (_write_lines, appended_lines,
                                  drop_stored_repeats, not_read, point)
    from .topup_rest import (HARVEST_TRACE_DIR, PASS, read_owners,
                             read_to_end)
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
    answers, unanswered = surveyed_owners(out_dir, document_id)
    read = set(answers) | read_owners(Path(out_dir) / HARVEST_TRACE_DIR,
                                      name)
    if not read and not unanswered:
        stats["documents without a trace of what was read (documents)"] += 1
        return False, 0, stats
    stored = read_harvest(path)
    stats["unreadable lines kept (lines)"] += stored.unreadable
    passage_holes, reading_holes = holes_of(stored.refusals)
    passages = [s for s in deps["passages_of"](document_id)
                if (s.owner_kind, s.owner_id) not in read - passage_holes]
    surveyed_again = {(s.owner_kind, s.owner_id) for s in passages}
    also = Found(True)
    for owner, parameters in reading_holes.items():
        if owner in surveyed_again:
            continue               # surveyed again whole
        said = answers.get(owner)
        also.answers[owner] = Answer(
            owner, sorted(parameters),
            {k: list(v) for k, v in (said.tuples if said else {}).items()},
            [])
    if not passages and not also.answers:
        enter_producer(stamp_path, runner.producer(PASS, runner.LLM_MODEL))
        stats["documents with nothing unread (documents)"] += 1
        return True, 0, stats

    before = runner.UNSERVED.of(document_id)
    taken = deps["take"](document_id, passages, also)
    if taken is None:
        return False, 0, stats
    report = DocumentReport(document_id=document_id,
                            owners_harvested=taken.passages,
                            planned={STAGE: taken.passages},
                            sources_of=taken.sources_of)
    runner.fold_answers(taken.answered, report, locate=deps.get("locate"),
                        spec=deps["spec"])
    drop_repeats(report)
    verdict = runner.not_happened(
        report, answered=taken.replies,
        lost=runner.UNSERVED.of(document_id) - before)
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
    enter_producer(stamp_path, runner.producer(PASS, runner.LLM_MODEL))
    _write_lines(path, appended_lines(stored, document_id, rows,
                                      report.refusals, []))
    stats["documents appended (documents)"] += 1
    stats["passages read (passages)"] += len(passages)
    stats["readings read again (passages x parameters)"] += sum(
        len(a.parameters) for a in also.answers.values())
    stats["tuples appended (tuples)"] += len(rows)
    stats["refusals appended (refusals)"] += len(report.refusals)
    stats["tuples identical to a stored tuple, not appended (tuples)"] += \
        identical
    log.info("top-up-rest: %s: %d passage(s) surveyed, %d reading(s) read "
             "again, %d tuple(s) and %d refusal(s) appended", name,
             len(passages), len(also.answers), len(rows),
             len(report.refusals))
    return True, 0, stats


class ParameterPass(_counted("top-up-parameters")):
    """--top-up-parameters in a run that harvests from the survey."""

    def __init__(self, out_dir: Path, spec, current: dict, deps: dict):
        super().__init__(lambda document_id, filename: append_parameters(
            document_id, filename, out_dir, spec, current, deps))


class UnreadPass(_counted("top-up-rest")):
    """The second half of --top-up-open in a run that harvests from the
    survey."""

    def __init__(self, out_dir: Path, deps: dict):
        super().__init__(lambda document_id, filename: append_unread(
            document_id, filename, out_dir, deps))
