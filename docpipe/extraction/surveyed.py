"""
surveyed.py: One document harvested from its survey.

The survey of the whole plan (survey.py), the reading of every parameter in
the passages it named (reading.py) and the combing for what the reading left
open (combing.py). The run folds what they read, works out what the profile
computes and writes the file with its stamp, as it writes every harvest.

A parameter the survey of the whole plan named no passage for is searched
for once before it can count as not stated (owner decision 2026-11-04): the
combing's search over the whole plan ranks the passages for its label, and
the reading reads it in the first of them with its own tools to look
further (`sought_survey`). The passage it was read in is one of its
sources, so a request that came to nothing there leaves a hole and not a
silent plan.

What none of them could read is a hole with its reason, never a plan that
seems silent: a passage the survey left unanswered, and a passage a parameter
was to be read in that came to no readable reply, each go to the fold as the
harvest's sentinel (`_harvest_failed`, `_why` cut_off or no_answer). The fold
keeps it as a refusal, and a parameter that has no row then ends `exhausted`
and not `unstated`: `trust.parameter_states` looks for its holes among the
passages the survey named for it, and a passage the survey could not answer
counts for every parameter. The hole of a reading names its parameter
(`_parameter`), so a pass over the harvest knows what to read again.

The passes over a stored harvest go through the same steps. `--start-at`
surveys the passages earlier harvests found something in (`take_found`);
`--top-up-parameters` surveys the whole plan for the parameters the spec
gained (`append_parameters`); `--top-up-open` combs every coordinate left
open (`comb_sweep` under `topup._sweep_one`) and then reads what nothing has
read yet (`append_unread`); `--top-up` combs the coordinates whose question
moved (`comb_sweep`). A survey of part of a plan is kept under its own scope
beside the whole one's.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .pipeline import Batch, DocumentReport, WorkItem, drop_repeats
from .reading import NO_ANSWER
from .survey import Answer, Found, budget_of, merge

log = logging.getLogger(__name__)

# The stage a passage of a surveyed plan was read in (`DocumentReport.planned`).
STAGE = "survey"
# Where the frame of a parameter appended to a stored harvest came from.
FRAME_SURVEYED = "the survey of the new parameters"


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


def frame_pairs(found: Found) -> list:
    """The frame tuples of a survey, each once, in the order of the plan."""
    pairs: list = []
    for answer in found.answers.values():
        for one in answer.tuples.get("frame", ()):
            if one not in pairs:
                pairs.append(one)
    return pairs


def joined(found: Found, also: Found) -> Found:
    """One survey of both: what *also* names is read beside what *found*
    names, a passage both answer with the parameters of both."""
    out = Found(found.complete and also.complete)
    merge(out, [Answer(a.owner, list(a.parameters), a.quote,
                       {k: list(v) for k, v in a.tuples.items()},
                       list(a.dropped)) for a in found.answers.values()])
    merge(out, [Answer(a.owner, list(a.parameters), a.quote,
                       {k: list(v) for k, v in a.tuples.items()},
                       list(a.dropped)) for a in also.answers.values()])
    for owner in found.unanswered + also.unanswered:
        if owner not in out.answers and owner not in out.unanswered:
            out.unanswered.append(owner)
    return out


@dataclass
class Taken:
    """What the survey, the reading and the combing of one document came to,
    in the shape the fold and the stamp read."""
    found: Found
    reads: list = field(default_factory=list)
    combed: list = field(default_factory=list)
    # (batch, reply) for the fold: every reading's values and every hole.
    answered: list = field(default_factory=list)
    # Passages the survey answered: none of them means no reply at all.
    replies: int = 0
    passages: int = 0
    # parameter uri -> the passages the survey named for it, and every
    # passage it could not answer (`trust.parameter_states`).
    sources_of: dict = field(default_factory=dict)
    # The parameters the survey named no passage for, each with the passage
    # a search of the whole plan read it in (`sought_survey`).
    sought: Found = field(default_factory=lambda: Found(True))


def sought_survey(found: Found, rank: Callable, document_id: int,
                  parameters: list,
                  probes: Optional[Callable] = None) -> Found:
    """The survey of *parameters*, which the survey of the whole plan named
    no passage for: each named for the passage the combing's search over the
    whole plan (*rank*) ranks first for its search sentences,
    *probes(parameter, document_id)* (owner decision 2026-11-05: HyDE
    sentences, one written for the document for a field about the document
    itself, one written per run for any other, `runner.make_seek_probes`),
    and for its label where it has none. What the survey said of every
    passage stands beside it without its parameters, so the reading sees the
    plan's pairs and years as it does anywhere else. A parameter the search
    finds no passage for is left out."""
    out = Found(True)
    merge(out, [Answer(owner, [], answer.quote,
                       {k: list(v) for k, v in answer.tuples.items()}, [])
                for owner, answer in found.answers.items()])
    for parameter in parameters:
        sentences = ((probes(parameter, document_id) if probes else None)
                     or [parameter.label])
        ranked = rank(document_id, sentences, set())
        if ranked:
            merge(out, [Answer((ranked[0].owner_kind, ranked[0].owner_id),
                               [parameter.uri])])
    return out


def taken_of(document_id: int, spec, found: Found, reads: list,
             combed: list, shown: dict,
             sought: Optional[Found] = None) -> Taken:
    """The fold's view of one document's reading, holes included. A
    parameter's sources are the passages the survey named for it, the one a
    search read it in (*sought*) and every passage the survey could not
    answer."""
    sought = sought if sought is not None else Found(True)
    answered: list = []
    for read in reads:
        source = read.batch.items[0].source
        if read.unread:
            answered.append(hole(document_id, source, read.why or NO_ANSWER,
                                 read.batch.parameter.uri))
        else:
            answered.append((read.batch, {"tuples": read.claims}))
            # A part of a table no reply answered, the others read.
            answered.extend(hole(document_id, source, why,
                                 read.batch.parameter.uri)
                            for why in read.lost)
    for owner in found.unanswered:
        source = shown.get(tuple(owner))
        if source is not None:
            answered.append(hole(document_id, source, NO_ANSWER))
    unanswered = {tuple(owner) for owner in found.unanswered}
    sources_of = {parameter.uri: {tuple(owner) for owner
                                  in found.passages_of(parameter.uri)
                                  + sought.passages_of(parameter.uri)}
                  | unanswered for parameter in spec.parameters}
    return Taken(found, reads, combed, answered, len(found.answers),
                 len(found.answers) + len(unanswered), sources_of, sought)


class SurveyedHarvest:
    """document_id -> Taken, or None when the run was halted on the way.

    *make_survey(spec, only, scope)* is the run's survey of the parameters
    *only* (all when empty) under *scope*, *make_reader(spec)* and
    *make_comber(spec)* its reading and combing (the comber None where
    nothing is combed), each made once per spec. *spec_for(document_id)* is
    the document's spec, its lists closed (`runner.closed_spec`),
    *passages_of(document_id)* every passage of the document in its order,
    *pages_of(document_id)* its page count, *halted()* whether the run stops.
    """

    def __init__(self, spec, make_survey: Callable, make_reader: Callable,
                 make_comber: Callable, passages_of: Callable,
                 pages_of: Callable, *, spec_for: Optional[Callable] = None,
                 halted: Optional[Callable] = None):
        self.spec = spec
        self.make_survey = make_survey
        self.make_reader = make_reader
        self.make_comber = make_comber
        self.passages_of = passages_of
        self.pages_of = pages_of
        self.spec_for = spec_for or (lambda document_id: spec)
        self.halted = halted or (lambda: False)
        self._made: dict = {}
        self._lock = threading.Lock()

    def _once(self, key: tuple, spec, make: Callable):
        # The spec is held with what was made of it, so its id is not
        # given to another spec while the entry stands.
        with self._lock:
            if key not in self._made:
                self._made[key] = (spec, make())
            return self._made[key][1]

    def survey_of(self, spec, only=(), scope: str = ""):
        only = tuple(sorted(only))
        return self._once(("survey", id(spec), only, scope), spec,
                          lambda: self.make_survey(spec, only, scope))

    def reader_of(self, spec):
        return self._once(("reader", id(spec)), spec,
                          lambda: self.make_reader(spec))

    def comber_of(self, spec):
        return self._once(("comber", id(spec)), spec,
                          lambda: self.make_comber(spec))

    def __call__(self, document_id: int, *, only=(), scope: str = "",
                 passages: Optional[list] = None,
                 also: Optional[Found] = None) -> Optional[Taken]:
        """The whole plan, or the survey of part of it: of the parameters
        *only*, of the *passages* given, under *scope*. *also* is read with
        it: what another survey named (`take_found`, `append_unread`)."""
        spec = self.spec_for(document_id)
        sources = self.passages_of(document_id)
        shown = {(s.owner_kind, s.owner_id): s for s in sources}
        budget = budget_of(sources, self.pages_of(document_id))
        wanted = sources if passages is None else list(passages)
        found = (self.survey_of(spec, only, scope)(document_id, wanted)
                 if wanted else Found(True))
        if also is not None:
            found = joined(found, also)
        if self.halted():
            return None
        reads = self.reader_of(spec)(document_id, found, shown, budget)
        if self.halted():
            return None
        combed: list = []
        comber = self.comber_of(spec)
        sought = Found(True)
        # Only after a survey of the whole plan: a survey of some passages
        # names none for a parameter the rest of the plan may hold.
        if comber is not None and passages is None and also is None:
            missing = [parameter for parameter in spec.parameters
                       if (not only or parameter.uri in only)
                       and not found.passages_of(parameter.uri)]
            sought = sought_survey(found, comber.rank, document_id, missing,
                                   getattr(comber, "seek", None))
            if comber.trace is not None:
                for owner, answer in sought.answers.items():
                    for uri in answer.parameters:
                        comber.trace("seek", document_id, parameter=uri,
                                     kind=owner[0], owner=owner[1])
            reads = reads + self.reader_of(spec)(document_id, sought, shown,
                                                 budget)
            if self.halted():
                return None
        if comber is not None:
            combed = comber(document_id, reads, shown, frame_pairs(found),
                            budget)
            if self.halted():
                return None
        return taken_of(document_id, spec, found, reads, combed, shown,
                        sought)


def take_found(whole: SurveyedHarvest, document_id: int, kept: list,
               gained: list) -> Optional[Taken]:
    """--start-at: the survey of the passages earlier harvests found
    something in, and for a parameter none of them was asked (*gained*) the
    survey of the rest of the plan as well, so that it is surveyed over the
    whole plan as in any run (owner decision 2026-11-03)."""
    also = None
    if gained:
        held = {(s.owner_kind, s.owner_id) for s in kept}
        rest = [s for s in whole.passages_of(document_id)
                if (s.owner_kind, s.owner_id) not in held]
        if rest:
            spec = whole.spec_for(document_id)
            also = whole.survey_of(spec, gained, "gained")(document_id, rest)
    return whole(document_id, scope="found", passages=kept, also=also)


def comb_sweep(comber_of: Callable, spec_for: Callable, every: Callable,
               pages_of: Callable) -> Callable:
    """sweep(batch, rows, slots, anchor) of a pass over a stored harvest
    (`topup._sweep_one`) in a run that harvests from the survey: the
    coordinates the pass re-reads are combed per passage of the rows and
    group of the spec (`combing.Comber.comb_groups`), their own passage
    and its section shown first, since the reading that asked them there
    ran under an older question, and with the years the stored rows give
    (`batch.bases`). What it leaves open is restored by the pass as it
    restores any sweep's."""
    def sweep(batch, rows, slots, anchor=None) -> None:
        document_id = batch.document_id
        comber = comber_of(spec_for(document_id))
        if comber is None:
            return
        sources = every(document_id, set())
        shown = {(s.owner_kind, s.owner_id): s for s in sources}
        budget = budget_of(sources, pages_of(document_id))
        names = [slot.name for slot in slots]
        by_item: dict = {}
        for row in rows:
            by_item.setdefault(row.item_index, []).append(row)
        for index, group in by_item.items():
            comber.comb_groups(document_id, batch.parameter,
                               batch.items[index].source, list(slots),
                               [row.claim for row in group], shown, [],
                               budget, coordinates=names, own=True,
                               bases=tuple(batch.bases or ()))
    return sweep


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
    them alone (*deps["take"](document_id, uris)*), their reading and their
    combing; the frame of their rows comes from that survey.

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
                entry.get("quote"), dict(entry.get("tuples") or {}),
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
    read = set(answers) | read_owners(Path(out_dir) / HARVEST_TRACE_DIR
                                      / f"{name}.trace.jsonl")
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
            owner, sorted(parameters), said.quote if said else None,
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
