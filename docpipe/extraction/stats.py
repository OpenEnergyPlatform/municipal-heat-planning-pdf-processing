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
- the reasons answers were dropped, per axis.

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

from . import archive

log = logging.getLogger(__name__)

STATS = "stats"
OPEN = ("exhausted", "unanswered", "unbacked")


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
        if path.name.endswith(".trace.jsonl") or (
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
    for directory in trace_dirs:
        for path in sorted(Path(directory).glob("*.jsonl")):
            stem = path.name[:-len(".trace.jsonl")] \
                if path.name.endswith(".trace.jsonl") else path.stem
            if names is not None and stem not in names:
                continue
            for event in _lines(path):
                kind = event.get("t")
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
    return {
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
