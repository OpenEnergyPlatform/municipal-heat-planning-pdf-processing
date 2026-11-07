"""
stats.py: Where a harvest is hard, written beside it after every run.

    python -m docpipe.extraction.stats <harvest dir> [--trace trace ...]

The harvest says what was read; this says what was not and why, in the
numbers a report and the ontology side can act on:

- coordinates per parameter, axis and state (`read`, `unstated`,
  `exhausted`, ...), and per document the share still open, hardest first;
- the plan's wordings the model mapped onto a class although no listed
  spelling matched (`<axis>_raw_foreign`): spellings the vocabulary lacks,
  or classes it lacks;
- answers outside the closed list (`not_an_option` drops in the trace),
  with the wording given: candidates for a class the ontology does not have;
- the `out:total` readings per axis and wording, which include the numbers
  a plan does not split by that axis at all;
- per axis and search stage, the requests sent and the coordinates they
  filled, which is what a coordinate costs;
- the reasons answers were dropped, per axis;
- the open questions of the compute step, per kind and how they ended;
- the survey flow: requests, tokens and second rounds per stage, the
  survey's passages, the readings per reason unread, and the combing's
  coordinates open, filled and exhausted;
- how many requests were with the server at once, on average and at most,
  and the seconds they spent with it and waiting for a place, all and per
  stage; and per stage the requests answered with the answer of the same
  request sent before, which went out once (owner decision 2026-11-07).

Every count says what it counts. Read from the harvest files and the trace
directories named; written to `<harvest dir>/stats/<pass>-<run start>.json`.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

from . import archive, trace
from .schema import ASK_STAGES

log = logging.getLogger(__name__)

STATS = "stats"
OPEN = ("exhausted", "unanswered", "unbacked")
# Every request writes `<stage>_ask`; each such kind is counted under its
# stage, a stage no list names as well, and the known stages count even
# when they asked nothing (owner decision 2026-11-05).
ASK = "_ask"


def _int(event: dict, key: str) -> int:
    value = event.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else 0


def _at(event: dict, key: str) -> Optional[float]:
    value = event.get(key)
    return float(value) if isinstance(value, (int, float)) \
        and not isinstance(value, bool) else None


def _stage(event: dict) -> str:
    """The stage an event that reports a request speaks for: `<stage>_ask`
    names it, an error says where it was, any other event is its own."""
    kind = str(event.get("t"))
    if kind.endswith(ASK) and len(kind) > len(ASK):
        return kind[:-len(ASK)]
    if kind == "error":
        return str(event.get("where"))
    return kind


def at_once(timed: list) -> dict:
    """How many requests were with the server at once (owner decision
    2026-11-07): the mean over the time from the first one sent to the last
    answer, and the most at one moment; and the seconds they were with the
    server and waited for a place in the run's queue, all and per stage.
    *timed* is [(stage, event)] of the events that report a request sent,
    whatever their kind. One without its times (a trace from before
    2026-11-07) counts in none of these; one no queue held waited no time."""
    serving: Counter = Counter()
    waiting: Counter = Counter()
    edges = []
    for stage, event in timed:
        asked, answered = _at(event, "asked_at"), _at(event, "answered_at")
        if asked is None or answered is None:
            continue
        sent = _at(event, "sent_at")
        sent = asked if sent is None else sent
        serving[stage] += max(0.0, answered - sent)
        waiting[stage] += max(0.0, sent - asked)
        edges += [(sent, 1), (answered, -1)]
    # An answer and a sending at the same moment: the answer first.
    edges.sort()
    now = most = 0
    for _moment, step in edges:
        now += step
        most = max(most, now)
    span = (edges[-1][0] - edges[0][0]) if edges else 0.0
    served = sum(serving.values())
    return {"mean": round(served / span, 2) if span > 0 else 0.0,
            "most": most,
            "seconds_with_the_server": round(served, 1),
            "seconds_waiting_for_a_place": round(sum(waiting.values()), 1),
            "by_stage": {stage: {
                "seconds_with_the_server": round(serving[stage], 1),
                "seconds_waiting_for_a_place": round(waiting[stage], 1)}
                for stage in sorted(serving)}}


def _lines(path: Path) -> Iterable[dict]:
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def from_harvest(harvest_dir: Path, names: Optional[set] = None) -> dict:
    """The counts the harvest files carry."""
    states: dict = defaultdict(lambda: defaultdict(Counter))
    foreign: dict = defaultdict(Counter)
    totals: dict = defaultdict(Counter)
    hardest = []
    documents = tuples = 0
    for path in sorted(Path(harvest_dir).glob("*.jsonl")):
        if trace.is_trace(path) or (
                names is not None and path.stem not in names):
            continue
        documents += 1
        asked = still_open = 0
        for row in _lines(path):
            if row.get("kind") != "tuple":
                continue
            tuples += 1
            parameter = row.get("parameter") or "?"
            for key, state in row.items():
                if not key.endswith("_state") or not isinstance(state, str):
                    continue
                axis = key[:-len("_state")]
                states[parameter][axis][state] += 1
                if state in ("derived", "out_of_slice"):
                    continue
                asked += 1
                if state in OPEN:
                    still_open += 1
                if state != "read":
                    continue
                raw = row.get(f"{axis}_raw")
                if row.get(f"{axis}_raw_foreign") and isinstance(raw, str):
                    foreign[axis][(str(row.get(axis)), raw)] += 1
                if row.get(axis) == "out:total" and isinstance(raw, str):
                    totals[axis][raw] += 1
        if asked:
            hardest.append([path.stem, still_open, asked])
    hardest.sort(key=lambda d: (-d[1] / d[2], -d[2]))
    return {
        "documents": documents,
        "tuples": tuples,
        "coordinates_by_parameter_axis_state": {
            p: {a: dict(c) for a, c in axes.items()}
            for p, axes in states.items()},
        "documents_by_open_share": [
            {"document": d, "open_coordinates": o, "asked_coordinates": a}
            for d, o, a in hardest],
        "read_with_wording_off_the_list": {
            axis: [{"value": v, "wording": w, "coordinates": n}
                   for (v, w), n in c.most_common()]
            for axis, c in foreign.items()},
        "read_as_total": {
            axis: [{"wording": w, "coordinates": n}
                   for w, n in c.most_common()]
            for axis, c in totals.items()},
    }


def from_traces(trace_dirs: Iterable[Path],
                names: Optional[set] = None) -> dict:
    """The counts the traces carry: requests and fills per axis and stage,
    the reasons answers were dropped, the answers outside the list."""
    requests: dict = defaultdict(Counter)
    filled: dict = defaultdict(Counter)
    drops: dict = defaultdict(Counter)
    outside: dict = defaultdict(Counter)
    maps: Counter = Counter()
    places_by_axis: Counter = Counter()
    planned: Counter = Counter()
    withdrawn = 0
    from_table = 0
    computed: dict = defaultdict(Counter)
    completed: Counter = Counter()
    sought: Counter = Counter()
    walked: Counter = Counter()
    stages: dict = defaultdict(Counter)
    surveyed: Counter = Counter()
    survey_by_parameter: Counter = Counter()
    readings: Counter = Counter()
    unread_why: Counter = Counter()
    refused_first: Counter = Counter()
    combed: Counter = Counter()
    timed: list = []
    for directory in trace_dirs:
        for path in trace.files(directory):
            if names is not None and trace.name_of(path) not in names:
                continue
            for event in trace.lines(path):
                kind = event.get("t")
                if "asked_at" in event and event.get("once") is not True:
                    # Every event that reports a request carries its times,
                    # whatever its kind; an answer given again was not sent.
                    timed.append((_stage(event), event))
                if kind == "field":
                    axis = str(event.get("slot"))
                    stage = str(event.get("stage"))
                    requests[axis][stage] += 1
                    filled[axis][stage] += int(event.get("filled") or 0)
                elif kind == "drop":
                    axis = str(event.get("field") or event.get("slot"))
                    why = str(event.get("why") or "unbacked")
                    drops[axis][why] += 1
                    if why == "not_an_option":
                        outside[axis][(str(event.get("given")),
                                       str(event.get("raw")))] += 1
                elif kind == "places":
                    maps["documents"] += 1
                    maps["complete"] += bool(event.get("complete"))
                    for key in ("passages", "windows", "places", "dropped",
                                "unread"):
                        maps[key] += int(event.get(key) or 0)
                    places_by_axis.update(event.get("by_axis") or {})
                elif kind == "plan":
                    planned[str(event.get("origin"))] += 1
                elif kind == "sweep":
                    withdrawn += int(event.get("withdrawn") or 0)
                    from_table += int(event.get("via_table") or 0)
                elif kind == "compute":
                    computed[str(event.get("kind"))][
                        str(event.get("outcome"))] += 1
                elif kind == "completion":
                    completed[str(event.get("outcome"))] += 1
                elif kind == "seek":
                    # One event per passage the walk down a search's list
                    # read; the first of a document's is `rank` 1, and a
                    # trace from before the walk names no rank.
                    walked[str(event.get("parameter"))] += 1
                    if _int(event, "rank") <= 1:
                        sought[str(event.get("parameter"))] += 1
                elif isinstance(kind, str) and kind.endswith(ASK) \
                        and len(kind) > len(ASK):
                    stage = kind[:-len(ASK)]
                    if event.get("once") is True:
                        # The answer of the same request sent before: nothing
                        # went out and nothing was spent (owner decision
                        # 2026-11-07).
                        stages[stage]["answered_once"] += 1
                        continue
                    stages[stage]["requests"] += 1
                    stages[stage]["prompt_tokens"] += _int(event,
                                                           "prompt_tokens")
                    stages[stage]["completion_tokens"] += _int(
                        event, "completion_tokens")
                    stages[stage]["second_rounds"] += (
                        _int(event, "corrections") > 0)
                elif kind == "survey":
                    surveyed["documents"] += 1
                    surveyed["complete"] += bool(event.get("complete"))
                    for key in ("passages", "contexts", "none", "dropped",
                                "unanswered"):
                        surveyed[key] += _int(event, key)
                    survey_by_parameter.update(
                        {str(p): n for p, n in
                         (event.get("by_parameter") or {}).items()
                         if isinstance(n, int)})
                elif kind == "read":
                    readings["readings"] += 1
                    if event.get("unread"):
                        unread_why[str(event.get("why"))] += 1
                    for key in ("values", "unanswered"):
                        readings[key] += _int(event, key)
                    refused_first.update(
                        {str(w): n for w, n in
                         (event.get("failed") or {}).items()
                         if isinstance(n, int)})
                elif kind == "comb":
                    combed["passages"] += 1
                    for key in ("open", "filled", "exhausted", "hits",
                                "fetched", "searched", "missed", "listed",
                                "judged", "turned", "near", "near_read",
                                "anew"):
                        combed[key] += _int(event, key)
    return {
        # The maps of places: documents mapped and how many completely,
        # passages, requests, places taken and not, requests unread, and
        # places per axis.
        "places_maps": {**{k: maps[k] for k in (
            "documents", "complete", "passages", "windows", "places",
            "dropped", "unread")}, "places_by_axis": dict(places_by_axis)},
        "windows_withdrawn_unsent": withdrawn,
        # Rows that took the frame their table was asked for.
        "coordinates_taken_from_their_table": from_table,
        "computed_questions_by_kind_outcome": {k: dict(c)
                                               for k, c in computed.items()},
        # Documents a profile completed from outside them, by what the
        # lookup came to.
        "completions_by_outcome": dict(completed),
        # Parameters the survey named no passage for, searched for in the
        # whole plan, per parameter (documents), and the passages the walk
        # down the search's list read them in (passages).
        "parameters_sought_by_parameter": dict(sought),
        "passages_sought_by_parameter": dict(walked),
        # Where the plans' passages came from: a search or a found place.
        "passages_planned_by_origin": dict(planned),
        "requests_and_fills_by_axis_stage": {
            axis: {stage: {"requests": requests[axis][stage],
                           "coordinates_filled": filled[axis][stage]}
                   for stage in requests[axis]}
            for axis in requests},
        "dropped_answers_by_axis_reason": {a: dict(c)
                                           for a, c in drops.items()},
        "answers_outside_the_list": {
            axis: [{"given": g, "wording": w, "answers": n}
                   for (g, w), n in c.most_common()]
            for axis, c in outside.items()},
        # Per stage: requests that got a reply, their tokens, those that
        # were a second round (corrections sent), and those answered with the
        # answer of the same request sent before in the document, which were
        # not sent (owner decision 2026-11-07).
        "requests_by_stage": {
            stage: {k: stages[stage][k] for k in (
                "requests", "prompt_tokens", "completion_tokens",
                "second_rounds", "answered_once")}
            for stage in dict.fromkeys((*ASK_STAGES, *sorted(stages)))},
        # Requests with the server at once, and the seconds with it and
        # waiting for a place (`at_once`).
        "requests_at_once": at_once(timed),
        # Documents surveyed and completely, passages found, contexts sent,
        # passages carrying no parameter, passages without an answer,
        # answers not taken, and passages per parameter.
        "survey": {
            "documents": surveyed["documents"],
            "complete": surveyed["complete"],
            "passages": surveyed["passages"],
            "contexts": surveyed["contexts"],
            "passages_without_parameter": surveyed["none"],
            "passages_unanswered": surveyed["unanswered"],
            "answers_not_taken": surveyed["dropped"],
            "passages_by_parameter": dict(survey_by_parameter)},
        # Readings (one passage for one parameter), the readings that came to
        # no reply per reason, values read, coordinates left unanswered and
        # the check's refusals of the first answer per reason. A reading has
        # no tools (ticket 26), so it fetches and searches nothing, and it
        # checks no find: the second reading is the second conversation's
        # (owner decisions 2026-11-07).
        "reading": {
            "readings": readings["readings"],
            "unread_by_reason": dict(unread_why),
            "values": readings["values"],
            "coordinates_unanswered": readings["unanswered"],
            "refused_first_by_reason": dict(refused_first)},
        # Combed passages (one passage for one parameter), coordinates open
        # when combed, filled and left exhausted, hits shown, passages
        # fetched, hit lists the model asked for, lists of the next
        # passages the run added (owner decision 2026-11-06: the search runs
        # empty), asks not found, requests that checked a find quoted from
        # another passage and the finds they turned (owner decision
        # 2026-11-07).
        "combing": {
            "passages": combed["passages"],
            "coordinates_open": combed["open"],
            "coordinates_filled": combed["filled"],
            "coordinates_exhausted": combed["exhausted"],
            "hits_shown": combed["hits"],
            "passages_fetched": combed["fetched"],
            "hit_lists": combed["searched"],
            "lists_added": combed["listed"],
            "asks_not_found": combed["missed"],
            "check_requests": combed["judged"],
            "finds_turned": combed["turned"],
            # Its second reading with the sections around the value's place:
            # the messages, the coordinates they read, and the conversations
            # begun anew where one outgrew the model's window (owner
            # decisions 2026-11-07).
            "second_reading_messages": combed["near"],
            "second_reading_read": combed["near_read"],
            "begun_anew": combed["anew"]},
    }


def collect(harvest_dir: Path, trace_dirs: Iterable[Path] = (),
            names: Optional[set] = None) -> dict:
    return {**from_harvest(harvest_dir, names),
            **from_traces(trace_dirs, names)}


def write(harvest_dir: Path, trace_dirs: Iterable[Path] = (),
          names: Optional[set] = None) -> Path:
    """Collect and write; returns the file. Logs the lines a report starts
    with: the open coordinates per axis and the costliest stages."""
    harvest_dir = Path(harvest_dir)
    out = collect(harvest_dir, [Path(d) for d in trace_dirs
                                if Path(d).is_dir()], names)
    target = (harvest_dir / STATS /
              (archive.folder(harvest_dir).name + ".json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    still: Counter = Counter()
    for axes in out["coordinates_by_parameter_axis_state"].values():
        for axis, counts in axes.items():
            still[axis] += sum(counts.get(s, 0) for s in OPEN)
    log.info("stats: %d document(s), %d tuple(s), open coordinates per axis: "
             "%s -> %s", out["documents"], out["tuples"],
             ", ".join(f"{a} {n}" for a, n in still.most_common()) or "none",
             target)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("harvest", type=Path)
    parser.add_argument("--trace", type=Path, action="append", default=[],
                        help="a trace directory, relative to the harvest; "
                             "repeatable (default: trace)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    archive.begin("stats")
    traces = [args.harvest / t for t in (args.trace or [Path("trace")])]
    print(write(args.harvest, traces))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
