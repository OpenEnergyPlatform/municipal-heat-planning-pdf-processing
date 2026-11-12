"""
passboxes.py: What each box of a follow-up pass does (`passflow`, library
entries with `flow == "pass"` in `blocks`).

A box works on one document: its harvest file, as it lies on disk and as the
boxes before it have changed it (`Doc`). The logic of each box is that of the
pass it was cut out of, at the step boundaries the pass had:

- `topup.py`: the questions that moved, the dimensions read again and kept
  or put back;
- `topup_parameter.py`, `surveyed.py`: a parameter the spec gained, the
  passages nobody read;
- `remap.py`, `recheck.py`: the lists mapped again, the quotes checked again,
  no model;
- `review.py`: the second reading of the rows nobody can stand behind.

A box leaves `doc.stop` where the document is done or left alone, and the
chain goes no further for it. What a box counts goes in `doc.stats`; the
stamp keys a pass may carry forward in `doc.settled`.

Author: Felix Vossel
"""
from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Optional

from .. import rules
from . import archive, fields, trace
from . import passflow
from .pipeline import Row, drop_repeats, row_label
from .remap import (enter_producer, next_producer, refused_spaces,
                    remap_row, spaces_of, stamp_forward, stamp_path_of)
from .topup import (Stored, actionable, in_order, named_years_of,
                    open_coordinates, read_harvest, reopened_by_gate,
                    sweep_ask, sweep_decide)
from .trust import document_summary

log = logging.getLogger(__name__)

UNREADABLE = fields.LISTS_UNREADABLE
_UNSET = object()


def _plain(raw: str) -> str:
    """A stored line without the carriage return a CRLF file adds."""
    return raw[:-1] if raw.endswith("\r") else raw


class Unit:
    """One dimension a pass reads again: the stamp key it came from (None
    where the dimension was open), its parameter and slot, its rows where
    they are known, and what asking it left for the step that decides it."""

    def __init__(self, key, parameter, slot, rows=None):
        self.key, self.parameter, self.slot = key, parameter, slot
        self.rows = rows
        self.sweep = None
        self.skip = False
        self.refused: list = []


class Doc:
    """One document of a pass: its harvest file, and what the boxes before
    have made of it."""

    def __init__(self, run, path, document_id: Optional[int] = None,
                 filename: Optional[str] = None):
        self.run = run
        self.path = Path(path)
        self.name = self.path.stem
        self.stamp_path = stamp_path_of(self.path)
        self.document_id = document_id
        self.filename = filename
        self.stats: Counter = Counter()
        self.stop = False
        self.written = False
        self.failed = 0
        self.stored: Optional[Stored] = None
        self.lines: list = []
        self.doc_spec = None
        self.changed: list = []
        self.units: list = []
        self.unit: Optional[Unit] = None
        self.settled: set = set()
        self.demoted: list = []
        self.guard = False              # a request lost to the server holds
        self.unserved = 0               # the stamp back
        self.open_mode = False
        self._bases = _UNSET
        self._position = _UNSET
        self.append: Optional[dict] = None
        self.report = None
        self.read = False               # the second reading was here
        self.reviewed = 0
        self.new_uris: list = []
        self.label = ""

    @property
    def tuples(self) -> list:
        return self.stored.tuples

    @property
    def refusals(self) -> list:
        return self.stored.refusals

    @property
    def bases(self) -> tuple:
        """The document's base and target years, rebuilt from the frame's
        own readings of the stored rows."""
        if self._bases is _UNSET:
            deps = self.run.deps
            self._bases = named_years_of(self.tuples, deps.get("frame_axes"),
                                         deps.get("year_states"))
        return self._bases

    @property
    def position(self) -> Optional[int]:
        """Where this pass will stand in the stamp's list. What it writes
        points at that position and the rows are written before the list
        is, so it is asked for before anything is entered."""
        if self._position is _UNSET:
            self._position = next_producer(self.stamp_path)
        return self._position


def files_of(run, which: str) -> list:
    """The harvest files a chain takes: those of the folder, or of the
    documents the run names, or of those it would harvest."""
    paths = sorted(path for path in Path(run.out).glob("*.jsonl")
                   if not trace.is_trace(path))
    if which == "documents":
        wanted = run.named()
    elif which == "to_harvest":
        wanted = {Path(fn).stem for _did, fn in run.documents}
    else:
        wanted = None
    return [path for path in paths
            if wanted is None or path.stem in wanted]


# -- the stored harvest -------------------------------------------------------

def box_stored(run, doc: Doc, node: dict) -> None:
    """The file as it lies on disk, and the lists its document closed."""
    from . import runner
    stored = read_harvest(doc.path)
    doc.stored = stored
    doc.stats["unreadable line kept"] += stored.unreadable
    if doc.document_id is None:
        doc.document_id = stored.document_id
    # The tuples stand in the file as the dicts a pass rewrites in place;
    # every other line goes back as it was, but for a carriage return: a
    # pass has always read a file with its line endings folded and writes
    # the line feed alone, and a line that kept its own would end in two.
    doc.lines = [row if row is not None and row.get("kind") == "tuple"
                 else _plain(raw) for raw, row in stored.entries]
    doc.doc_spec = run.document_spec(doc.document_id)
    if doc.doc_spec is None:
        doc.stats["dynamic list unavailable"] += 1
        doc.stats[UNREADABLE] += 1
        run.untouched.add(doc.name)
        doc.stop = True
        return
    doc.unserved = runner.UNSERVED.of(doc.document_id)


def box_changed(run, doc: Doc, node: dict) -> None:
    """The questions the stamp says moved, but for those only a gained
    parameter moved."""
    from . import runner
    from .topup_parameter import explained_keys
    changed = runner.stale(doc.stamp_path, run.current)
    if not changed:
        doc.stats["already current"] += 1
        doc.stop = True
        return
    # What only a parameter the spec gained moved is for the pass that
    # appends it (`topup_parameter`), and this pass writes none of it. Taken
    # out here, a new parameter beside one moved coordinate does not block
    # that coordinate: the keys stay stale and the stamp says so.
    explained = explained_keys(doc.stamp_path, run.current, run.spec)
    doc.changed = [key for key in changed if key not in explained]
    if not doc.changed:
        doc.stats["left to --top-up-parameters"] += 1
        doc.stop = True


def box_movable(run, doc: Doc, node: dict) -> None:
    """Which of the moved questions may be read again; one that blocks
    leaves the file as it is."""
    deps = run.deps
    keys, blocked = actionable(doc.changed, doc.doc_spec,
                               deps.get("frame_names") or (),
                               dynamic_ok=deps.get("dynamic_ok", True),
                               only=run.only)
    if blocked or not keys:
        doc.stats["blocked" if blocked else "nothing to sweep"] += 1
        doc.stop = True
        return
    doc.settled = set(keys)
    doc.guard = True
    doc.units = [Unit(key, parameter, slot)
                 for key, parameter, slot in in_order(keys, doc.doc_spec)]


def box_open(run, doc: Doc, node: dict) -> None:
    """Every dimension some row left open, each read to the end of the
    plan."""
    from . import runner
    work = open_coordinates(doc.tuples, doc.doc_spec)
    if not work:
        doc.stats["nothing open"] += 1
        doc.stop = True
        return
    runner.read_to_end()
    doc.open_mode = True
    doc.units = [Unit(None, parameter, slot, rows)
                 for parameter, slot, rows in work]
    doc.stats["open coordinates asked"] += sum(len(rows)
                                               for _p, _s, rows in work)


# -- one dimension ------------------------------------------------------------

def box_take_back(run, doc: Doc, node: dict) -> None:
    """The dimension taken off its rows and asked again."""
    unit = doc.unit
    doc.position            # asked now, before anything is entered
    if unit.rows is None:
        unit.rows = [row for row in doc.tuples
                     if row.get("parameter") == unit.parameter.uri]
        if not unit.rows:
            unit.skip = True
            return
    unit.sweep = sweep_ask(unit.rows, unit.parameter, unit.slot,
                           doc.doc_spec, run.deps, doc.stats,
                           bases=doc.bases)


def box_better(run, doc: Doc, node: dict) -> None:
    """The new answer where it is better, else the old one."""
    unit = doc.unit
    if unit.skip or unit.sweep is None:
        return
    settled, unit.refused = sweep_decide(unit.sweep, doc.stats,
                                         doc.position)
    doc.demoted.extend(unit.refused)
    if not settled and unit.key is not None:
        doc.settled.discard(unit.key)


def box_derive(run, doc: Doc, node: dict) -> None:
    """The dimension the spec decides from the unit, taken from it."""
    unit = doc.unit
    if unit.skip or unit.sweep is None or not unit.slot.derive:
        return
    # Asked as in the harvest, and taken from the unit only where no answer
    # was read (`fields.derives`, owner decision 2026-11-07).
    rows = [Row(row_label(i), 0, r) for i, r in enumerate(unit.rows)
            if not any(r is d for d in unit.refused)
            and fields.derives(unit.slot, r, unit.parameter)]
    doc.stats["derived"] += fields.apply_derived(rows, unit.slot)
    # Written by this pass, so it says so: a missing key reads as the
    # harvest.
    from .topup import point
    for entry in rows:
        point(entry.claim, unit.slot, doc.position)


def box_reopen_closed(run, doc: Doc, node: dict) -> None:
    """Rows a moved gate released are asked the dimensions they never were
    asked. They carry `out_of_slice`, which is not a reading and not a
    finding about the plan: it says the row left before the question."""
    deps = run.deps
    for parameter, slot, mine in reopened_by_gate(
            doc.tuples, doc.doc_spec, deps.get("slice_gate") or {},
            deps.get("frame_names") or ()):
        doc.stats["closed rows reopened"] += len(mine)
        doc.position
        sweep = sweep_ask(mine, parameter, slot, doc.doc_spec, deps,
                          doc.stats, bases=doc.bases)
        _got, refused = sweep_decide(sweep, doc.stats, doc.position)
        doc.demoted.extend(refused)


def box_demote(run, doc: Doc, node: dict) -> None:
    """A refused row is a refusal now, in the file and in the summary. The
    line keeps its place: the dict was rewritten where it stands."""
    for row in doc.demoted:
        if row in doc.tuples:
            doc.tuples.remove(row)
            doc.refusals.append(row)
    doc.demoted = []


def box_summary(run, doc: Doc, node: dict) -> None:
    if doc.open_mode:
        doc.stats["open coordinates left"] += sum(
            len(rows) for _p, _s, rows in open_coordinates(doc.tuples,
                                                           doc.doc_spec))
    if doc.document_id is not None:
        doc.lines.append({"kind": "summary",
                          **document_summary(doc.document_id, doc.tuples,
                                             doc.refusals)})


# -- the lists, the quotes, the second reading --------------------------------

def box_remap(run, doc: Doc, node: dict) -> None:
    """The recorded wording of each row mapped onto the lists as the spec
    reads them today. The stamp keys that stay settled are the answer spaces
    every row could be mapped in."""
    settled = set(spaces_of(run.current))
    for index, (raw, row) in enumerate(doc.stored.entries):
        if row is None or row.get("kind") != "tuple":
            continue
        parameter = doc.doc_spec.by_uri.get(row.get("parameter"))
        if parameter is None:
            # No list to map against, so nothing this pass may touch -- and
            # nothing it may vouch for either.
            doc.stats["unknown parameter kept"] += 1
            settled = set()
            doc.lines[index] = _plain(raw)
            continue
        doc.stats["tuples"] += 1
        counts, open_spaces = remap_row(row, parameter)
        doc.stats.update(counts)
        settled -= open_spaces
    blocked = refused_spaces(doc.refusals, spaces_of(run.current))
    doc.stats["refusals may now map"] += len(blocked & settled)
    doc.settled = settled - blocked


def box_recheck(run, doc: Doc, node: dict) -> None:
    """Every coordinate of every row held to the rule that its answer
    stands in its quote."""
    from .recheck import recheck_row
    if doc.stored.document_id is not None:
        doc.stats["summaries rewritten"] += 1
    for index, (raw, row) in enumerate(doc.stored.entries):
        if row is None or row.get("kind") != "tuple":
            continue
        parameter = doc.doc_spec.by_uri.get(row.get("parameter"))
        if parameter is None:
            doc.stats["unknown parameter kept"] += 1
            doc.lines[index] = _plain(raw)
            continue
        slots = fields.asked_slots(parameter)
        doc.stats["tuples"] += 1
        doc.stats["coordinates"] += len(slots)
        doc.stats.update(recheck_row(row, slots))


def box_review(run, doc: Doc, node: dict) -> None:
    """Each row of the trust levels in the rule read a second time."""
    from .review import (_working_lines, disputed, review_fields,
                         review_row, rows_to_review)
    from .trust import trust
    limit = rules.get("review_limit")
    if limit and run.reviewed >= limit:
        run.ended = True
        doc.stop = True
        return
    left = limit - run.reviewed if limit else 0
    stats = doc.stats
    for row in rows_to_review(doc.tuples):
        if left and stats["reviewed"] >= left:
            break
        parameter = doc.doc_spec.by_uri.get(row.get("parameter"))
        if parameter is None:
            stats["unknown parameter kept"] += 1
            continue
        slots = review_fields(parameter, disputed(trust(row)))
        shown = run.sources_for(row) or []
        if not shown:
            stats["no passage"] += 1
            continue
        captured: dict = {}
        flag = review_row(row, parameter, slots, shown, run.ask, captured)
        if not flag:
            stats["no reply"] += 1
            continue
        stats["reviewed"] += 1
        stats[flag.split(":", 1)[1]] += 1
        run.working.extend(_working_lines(doc.name, row, parameter, slots,
                                          captured, flag))
    doc.read = True
    doc.reviewed = stats["reviewed"]
    run.reviewed += stats["reviewed"]
    if limit and run.reviewed >= limit:
        run.ended = True


def box_worklist(run, doc, node: dict) -> None:
    """What the second reading said, beside the harvest."""
    from .review import COLUMNS
    if not run.working:
        return
    out_path = Path(run.out) / "review.csv"
    archive.keep(out_path)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(run.working)
    run.stats["working list lines"] = len(run.working)
    log.info("review: %d line(s) -> %s", len(run.working), out_path)


def box_clear_stamps(run, doc, node: dict) -> None:
    """The stamps of the files a pass rewrote, kept in the archive and
    deleted, so that the next run reads those documents again."""
    if not rules.get("recheck_clear_stamps"):
        return
    for stamp in sorted(Path(run.out).glob("*.stamp.json")):
        if stamp.name[:-len(".stamp.json")] in run.untouched:
            continue
        archive.keep(stamp)
        stamp.unlink()
        run.stats["stamps cleared"] += 1
    log.info("recheck: %-32s %d", "stamps cleared",
             run.stats["stamps cleared"])


# -- writing ------------------------------------------------------------------

def box_replace(run, doc: Doc, node: dict) -> None:
    """The file replaced from its lines, or the new rows appended to it."""
    from . import runner
    name = passflow.setting(node, "producer")
    if passflow.setting(node, "how") == "append":
        _append(run, doc, name)
        return
    if name and doc.position is not None:
        # Entered whether or not it earns a stamp key later, and before the
        # rows that point at it are written: a pointer into a list this
        # pass never joined reads as unknown.
        enter_producer(doc.stamp_path,
                       runner.producer(name, runner.llm_model()))
        doc.stats["documents given a producers entry"] += 1
    out = [json.dumps(row, ensure_ascii=False) if isinstance(row, dict)
           else row for row in doc.lines]
    tmp = doc.path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    archive.keep(doc.path)
    tmp.replace(doc.path)
    doc.stats["documents written"] += 1
    doc.written = True


def _append(run, doc: Doc, name: str) -> None:
    """The stored lines stay as the same bytes in the same order, and the
    rows the pass read follow them (`topup_parameter.appended_lines`)."""
    from . import runner
    from .topup_parameter import (_write_lines, appended_lines,
                                  drop_stored_repeats, point)
    extra = doc.append
    report, stored = doc.report, doc.stored
    rows, identical = drop_stored_repeats(report.tuples, stored.tuples)
    position = doc.position
    for row in rows:
        point(row, position)
    states = extra["states"]
    if extra["schema"]:
        report.tuples = rows
        runner.check_against_schema(report, doc.name, run.spec, states)
    # Entered before the rows that point at it.
    enter_producer(doc.stamp_path,
                   {**runner.producer(name, runner.llm_model()),
                    **extra["producer"]})
    _write_lines(doc.path, appended_lines(stored, doc.document_id, rows,
                                          report.refusals, states))
    doc.written = True
    stats = doc.stats
    stats["documents appended (documents)"] += 1
    stats["tuples appended (tuples)"] += len(rows)
    stats["refusals appended (refusals)"] += len(report.refusals)
    stats["tuples identical to a stored tuple, not appended (tuples)"] += \
        identical
    if extra["schema"]:
        stats["stored refusals not revisited (refusals)"] += \
            len(stored.refusals)
    for state in states:
        stats[f"parameters {state['state']} (parameters x documents)"] += 1
    for key, value in extra["counts"].items():
        stats[key] += value
    log.info("%s: %s: %s, %d tuple(s) and %d refusal(s) appended",
             extra["label"], doc.name, extra["said"], len(rows),
             len(report.refusals))


def box_carry_stamp(run, doc: Doc, node: dict) -> None:
    """The stamp keys the pass earned, written forward; and what the second
    reading says about the stamp."""
    from . import runner
    stamp = doc.stamp_path
    if doc.guard and runner.UNSERVED.of(doc.document_id) > doc.unserved:
        # A coordinate that was never read is not a coordinate re-read. The
        # stamp stays as it was, so the next top-up asks again.
        doc.stats["stamps left, a request ended on 429 or 5xx"] += 1
        return
    name = passflow.setting(node, "producer")
    if doc.settled:
        carried = stamp_forward(
            stamp, run.current, doc.settled,
            producer=runner.producer(name) if name else None)
        if carried:
            doc.stats["stamps carried forward"] += 1
        elif doc.append is not None:
            log.error("%s: %s was appended to and its stamp could not be "
                      "written; the next run completes it",
                      doc.append["label"], doc.name)
            doc.stats["documents not taken (documents)"] += 1
            doc.failed = 1
    if doc.read:
        _review_stamp(run, doc)


def _review_stamp(run, doc: Doc) -> None:
    """What the review wrote goes into the stamp of the documents it READ
    and no other: a run cut short by its limit leaves the rest without a
    review key, which is the only way a later run can tell them apart."""
    for key, value in (("review/prompt", run.prompt_sha),
                       ("review/model", run.model)):
        if not value:
            continue
        try:
            stored = json.loads(doc.stamp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stored[key] = value
        archive.keep(doc.stamp_path)
        doc.stamp_path.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2),
            encoding="utf-8")
    if doc.reviewed and run.review_producer is not None:
        if enter_producer(doc.stamp_path, run.review_producer) is not None:
            doc.stats["documents given a producers entry"] += 1


# -- a parameter the spec gained ----------------------------------------------

def box_classify(run, doc: Doc, node: dict) -> None:
    """What the pass does with one stored document, by the rules of
    `topup_parameter.classify`."""
    from . import runner
    from .topup_parameter import classify
    deps = run.deps
    stats = doc.stats
    verdict = classify(
        doc.stamp_path, {**run.current, **runner.document_current(doc.name)},
        run.spec, doc.path,
        doc_spec_of=lambda: deps["document_spec"](doc.document_id),
        frame_names=deps.get("frame_names") or (),
        dynamic_ok=deps.get("dynamic_ok", True))
    label = passflow.setting(node, "label") or "top-up-parameters"
    doc.label = label
    if verdict.kind == "none":
        stats["documents without a new parameter (documents)"] += 1
        doc.stop = True
        return
    if verdict.kind == "blocked":
        log.info("%s: %s stays stale as a whole: %s", label, doc.name,
                 verdict.why)
        stats["documents left stale as a whole (documents)"] += 1
        doc.stop = True
        return
    if verdict.kind == "failed":
        log.error("%s: %s not taken: %s", label, doc.name, verdict.why)
        stats["documents not taken (documents)"] += 1
        doc.failed = 1
        doc.stop = True
        return
    doc.settled = verdict.owned | verdict.shared
    uris = [p.uri for p in verdict.new]
    doc.stored = verdict.stored
    stats["unreadable lines kept (lines)"] += doc.stored.unreadable
    if verdict.kind == "applied":
        doc.stop = True
        if stamp_forward(doc.stamp_path, run.current, doc.settled):
            stats["stamps completed, the file already held the parameters "
                  "(documents)"] += 1
            doc.written = True
            return
        log.error("%s: %s holds %s and its stamp could not be completed",
                  label, doc.name, ", ".join(uris))
        stats["documents not taken (documents)"] += 1
        doc.failed = 1
        return
    doc.new_uris = uris
    doc.doc_spec = deps["document_spec"](doc.document_id) or run.spec


def box_read_parameters(run, doc: Doc, node: dict) -> None:
    """The whole plan read for the new parameters alone, folded and
    checked; nothing is written unless they were read completely."""
    from . import runner
    from .surveyed import FRAME_SURVEYED, STAGE
    from .pipeline import DocumentReport
    from .topup_parameter import not_read, refuses_incomplete
    from .trust import parameter_states
    label = doc.label
    uris = doc.new_uris
    before = runner.UNSERVED.of(doc.document_id)
    taken = run.take_parameters(doc.document_id, uris)
    if taken is None:
        doc.stop = True
        return
    report = DocumentReport(document_id=doc.document_id,
                            owners_harvested=taken.passages,
                            planned={STAGE: taken.passages},
                            sources_of=taken.sources_of)
    runner.fold_answers(taken.answered, report, locate=run.locate,
                        spec=doc.doc_spec)
    drop_repeats(report)
    verdict = runner.not_happened(
        report, answered=taken.replies,
        lost=runner.UNSERVED.of(doc.document_id) - before)
    if verdict is not None and refuses_incomplete():
        log.error("%s: %s: %s was not read completely, %s; nothing is "
                  "written", label, doc.name, ", ".join(uris),
                  not_read(*verdict))
        doc.stats["documents not read completely (documents)"] += 1
        doc.failed = 1
        doc.stop = True
        return
    only = runner.narrow_spec(doc.doc_spec, uris)
    states = parameter_states(only, report.tuples, report.refusals,
                              harvested=report.owners_harvested,
                              answered=taken.replies,
                              sources_of=report.sources_of)
    doc.report = report
    doc.append = {"states": states, "schema": True,
                  "producer": {"parameters": uris, "frame": FRAME_SURVEYED},
                  "counts": {}, "label": label,
                  "said": f"{', '.join(uris)} appended"}


# -- the passages nobody read -------------------------------------------------

def box_unread(run, doc: Doc, node: dict) -> None:
    """The passages no reading of the harvest answered, and the passages a
    parameter's reading came to nothing in, read now."""
    from . import runner
    from .pipeline import DocumentReport
    from .survey import Answer, Found
    from .surveyed import STAGE, holes_of, surveyed_owners
    from .topup_parameter import not_read, refuses_incomplete
    from .topup_rest import (HARVEST_TRACE_DIR, PASS, done_to_end,
                             read_owners, skips_unknown_reading)
    stats, out_dir, document_id = doc.stats, Path(run.out), doc.document_id
    label = passflow.setting(node, "label") or "top-up-rest"
    if not doc.path.is_file():
        stats["documents without a harvest (documents)"] += 1
        doc.stop = True
        return
    if done_to_end(doc.stamp_path):
        stats["documents already read to their end (documents)"] += 1
        doc.stop = True
        return
    answers, unanswered = surveyed_owners(out_dir, document_id)
    read = set(answers) | read_owners(out_dir / HARVEST_TRACE_DIR, doc.name)
    if not read and not unanswered and skips_unknown_reading():
        stats["documents without a trace of what was read (documents)"] += 1
        doc.stop = True
        return
    stored = read_harvest(doc.path)
    doc.stored = stored
    stats["unreadable lines kept (lines)"] += stored.unreadable
    passage_holes, reading_holes = holes_of(stored.refusals)
    passages = [s for s in run.passages_of(document_id)
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
        enter_producer(doc.stamp_path,
                       runner.producer(PASS, runner.llm_model()))
        stats["documents with nothing unread (documents)"] += 1
        doc.written = True
        doc.stop = True
        return
    before = runner.UNSERVED.of(document_id)
    taken = run.take_passages(document_id, passages, also)
    if taken is None:
        doc.stop = True
        return
    report = DocumentReport(document_id=document_id,
                            owners_harvested=taken.passages,
                            planned={STAGE: taken.passages},
                            sources_of=taken.sources_of)
    runner.fold_answers(taken.answered, report, locate=run.locate,
                        spec=run.spec)
    drop_repeats(report)
    verdict = runner.not_happened(
        report, answered=taken.replies,
        lost=runner.UNSERVED.of(document_id) - before)
    if verdict is not None and refuses_incomplete():
        log.error("%s: %s was not read completely, %s; nothing is written",
                  label, doc.name, not_read(*verdict))
        stats["documents not read completely (documents)"] += 1
        doc.failed = 1
        doc.stop = True
        return
    doc.report = report
    doc.append = {
        "states": [], "schema": False, "producer": {}, "label": label,
        "said": f"{len(passages)} passage(s) surveyed, "
                f"{len(also.answers)} reading(s) read again",
        "counts": {"passages read (passages)": len(passages),
                   "readings read again (passages x parameters)": sum(
                       len(a.parameters) for a in also.answers.values())}}


# -- the runs that stand once -------------------------------------------------

def box_places(run, doc, node: dict) -> None:
    """The documents start at the passages earlier harvests found
    something in."""
    name = passflow.setting(node, "archive")
    if name:
        run.begin_archive(name)
    run.found = run.make_found()


def box_main_flow(run, doc: Doc, node: dict) -> None:
    """One document read with the flow of the profile."""
    doc.written, doc.failed = run.harvest_document(doc.document_id,
                                                   doc.filename)


ACTS = {
    "stored": box_stored, "changed": box_changed, "movable": box_movable,
    "open": box_open, "take_back": box_take_back, "better": box_better,
    "derive": box_derive, "reopen_closed": box_reopen_closed,
    "demote": box_demote, "summary": box_summary, "replace": box_replace,
    "carry_stamp": box_carry_stamp, "remap": box_remap,
    "recheck": box_recheck, "review": box_review, "worklist": box_worklist,
    "clear_stamps": box_clear_stamps, "classify": box_classify,
    "read_parameters": box_read_parameters, "unread": box_unread,
    "places": box_places, "main_flow": box_main_flow,
}
