#!/usr/bin/env python3
"""
probe_rows.py – The requests of the harvest over a few passages.

A corpus job is the slow way to learn whether a prompt or a reply format
works. This asks the real request over named passages against whatever
LLM_BASE_URL and LLM_MODEL say, with the prompt, the split and the reading of
the run, and needs neither a GPU job nor retrieval:

    python scripts/probe_rows.py data/KWP.db --out probe --owner table/89205
    python scripts/probe_rows.py data/KWP.db --out probe --document 1021 --largest 5
    python scripts/probe_rows.py --hits passages.json --out probe
    python scripts/probe_rows.py --hits passages.json --out probe --whole
    python scripts/probe_rows.py --hits passages.json --out new --compute probe
    python scripts/probe_rows.py data/ar6/ar6.db --out probe --whole --documents 4,23

`--hits` takes the passages from a file, as `fetch_owner_content` returns them,
so a machine without the database can run the probe.

For each passage it reports the tokens and seconds of its requests, the values
read, how many share a quote, and how many stand the two checks of the harvest:
the quote stands in the passage and the number in the quote.

`--whole` asks what a run asks of these passages: the frame, the rows of each
pair and every coordinate of them, with the prompts and the checks of the run.
There is no search: a coordinate is looked for in the other passages given,
in their order, and a list a document closes from the database stays empty.
With `--places` the coordinates are searched over the map of the run instead,
and `--every-row` asks each of its windows for every open row. It writes each
document's report when it is done, and reports the pairs and each coordinate's
states. Several agents share the work through LLM_MODELS and
LLM_SLOTS_PER_MODEL, as in the chat.

`--documents` takes every passage of these documents from the database, in
the order the run reads the rest of a document, and closes each document's
own lists from it as the run does (the profile's `document_axes`).

`--compute` takes the verified rows of such a stored probe and asks only what
the compute step leaves open, so its prompt can be tried without reading the
plans again.

`--survey` with `--documents` asks only the survey of each whole plan, the
first pass of the rebuilt harvest, and keeps it in `<out>/survey`.

A sandbox round needs CODE_EXEC_URL; `report.json` counts the rounds either way.
"""
import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def owners_of(args, conn) -> list:
    owners = [(kind, int(number)) for kind, number
              in (text.split("/") for text in args.owner or ())]
    if args.document:
        rows = conn.execute(
            "select t.id from Tables t join Sections s on s.id = t.section "
            "where s.document = ? "
            "order by length(t.markdown) - length(replace(t.markdown, '|', '')) desc "
            "limit ?", (args.document, args.largest)).fetchall()
        owners += [("table", row[0]) for row in rows]
    return owners


def tally(tuples: list, text: str) -> dict:
    """What came back for one passage, by the harvest's two checks."""
    from docpipe.extraction.verify import (canonical_number, numbers_in,
                                           quote_in)

    read = [t for t in tuples if isinstance(t, dict)
            and not t.get("_harvest_failed")]
    backed = 0
    for claim in read:
        quote = claim.get("quote") or ""
        number = canonical_number(claim.get("value"))
        backed += bool(quote_in(text, quote) and number
                       and number in numbers_in(quote))
    return {"values": len(read), "quotes": len({t.get("quote") for t in read}),
            "backed": backed,
            "failed": [t.get("_why") for t in tuples
                       if isinstance(t, dict) and t.get("_harvest_failed")]}


def states_of(tuples: list, names) -> dict:
    """{coordinate: {state: tuples}} over the rows that came back."""
    states: dict = {}
    for claim in tuples:
        if not isinstance(claim, dict) or claim.get("_harvest_failed"):
            continue
        for name in names:
            state = claim.get(f"{name}_state") or "none"
            counts = states.setdefault(name, {})
            counts[state] = counts.get(state, 0) + 1
    return states


def trace_events(out: Path) -> list:
    return [json.loads(line) for path in out.glob("*.trace.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]


def source_of(hit: dict, args):
    from docpipe.extraction import runner

    source = runner._source_of(hit)
    return (replace(source, image_path=None)
            if args.image_root is None else source)


def whole(hits: list, spec, args, passages=None, document_spec=None) -> list:
    """The frame, the rows and the coordinates of each document's passages.

    *passages* are {document: sources} in place of *hits*, and
    *document_spec* gives each document the spec its own lists close."""
    from docpipe.extraction import fields, runner
    from docpipe.extraction.pipeline import (DocumentReport, WorkItem,
                                             group_items)
    from docpipe.profile import active_profile

    profile = active_profile()
    frame_axes = fields.frame_slots(spec, profile.component("extraction", "FRAME") or ())
    gate = profile.component("extraction", "SLICE") or {}
    ask_frame = runner.make_frame_asker(args.image_root)
    documents: dict = dict(passages or {})
    for hit in hits:
        documents.setdefault(hit.get("document_id") or 0, []).append(
            source_of(hit, args))

    def rest_of_document(document: int, exclude: set,
                         start=None) -> list:
        return [replace(source, provenance={**source.provenance, "via": "comb"})
                for source in documents.get(document, ())
                if (source.owner_kind, source.owner_id) not in exclude]

    places = (runner.make_places(None, spec, args.out, every=rest_of_document)
              if args.places else None)
    if places is not None:
        places.pool = ThreadPoolExecutor(args.parallel)
        if args.every_row:
            places.rows_for = None
    harvest = runner.make_fieldwise_harvester(
        args.image_root, rest_of_document=rest_of_document, spec=spec,
        slice_gate=gate, frame_axes=frame_axes, places=places)
    computer = runner.make_computer(profile)
    names = sorted({slot.name for parameter in spec.parameters
                    for slot in fields.axis_slots(parameter)}
                   | {"parameter", "value"})

    def one(document: int) -> dict:
        sources = documents[document]
        own = (document_spec(document) if document_spec else None) or spec
        items = [WorkItem(document, None, source) for source in sources]
        started = time.time()
        pairs, status, missed = runner.find_frame(
            sources, frame_axes, document, ask_frame)
        batches, rest, _added = runner.pair_batches(
            items, pairs, [], frame_axes, [])
        batches += group_items(rest)
        bases = tuple(runner.named_years(pairs, frame_axes,
                                         runner.year_states_of(profile)))
        for batch in batches:
            batch.bases = bases
            batch.pairs = tuple(pairs)
            batch.spec = own
        with ThreadPoolExecutor(args.parallel) as pool:
            replies = list(pool.map(lambda batch: harvest(batch, []), batches))
        tuples = [claim for got in replies for claim in got.get("tuples") or ()]
        answered = list(zip(batches, replies))
        report = DocumentReport(document_id=document)
        runner.fold_answers(answered, report, locate=None, spec=own)
        if computer is not None:
            computer(answered, report, spec=spec)
        row = {
            "document": document, "passages": len(sources),
            "seconds": round(time.time() - started, 1),
            "pairs": [{s.name: pair.get(s.name) for s in frame_axes}
                      for pair in pairs],
            "frame_status": status, "years_not_named": missed,
            "batches": len(batches), "tuples": tuples,
            "verified": report.tuples, "refusals": len(report.refusals),
            "refused_for": dict(Counter(refusal.get("reason")
                                        for refusal in report.refusals)),
            "states": states_of(tuples, names)}
        (args.out / f"doc{document}.json").write_text(
            json.dumps(row, ensure_ascii=False, default=str), encoding="utf-8")
        return row

    with ThreadPoolExecutor(len(documents) or 1) as pool:
        return list(pool.map(one, documents))


def survey_over(passages: dict, spec, args) -> list:
    """The survey of each document's whole plan, as the run asks it."""
    from docpipe.extraction import runner

    def every(document: int, exclude: set) -> list:
        return [source for source in passages.get(document, ())
                if (source.owner_kind, source.owner_id) not in exclude]

    surveyed = runner.make_survey(args.db, spec, args.out, every=every,
                                  image_root=args.image_root)
    if surveyed is None:
        raise SystemExit("no survey: the profile writes no survey prompt or "
                         "its spec names no groups")
    surveyed.pool = ThreadPoolExecutor(args.parallel)

    def one(document: int) -> dict:
        started = time.time()
        found = surveyed(document)
        answers = list(found.answers.values())
        return {"document": document, "passages": len(passages[document]),
                "seconds": round(time.time() - started, 1),
                "complete": found.complete,
                "by_parameter": {p: len(found.passages_of(p))
                                 for p in surveyed.parameters},
                "none": sum(1 for a in answers if not a.parameters),
                "dropped": sum(len(a.dropped) for a in answers),
                "unanswered": len(found.unanswered),
                "tuples": {name: sum(len(a.tuples.get(name, ()))
                                     for a in answers)
                           for name in surveyed.slots}}

    with ThreadPoolExecutor(len(passages) or 1) as pool:
        return list(pool.map(one, passages))


def compute_over(stored: Path, hits: list, spec, args) -> list:
    """The compute step over the verified rows of a stored `--whole` probe.
    The raw claims cannot be folded again: their source is a label of the batch
    they were read in, and the batches are not stored."""
    from docpipe.extraction import runner
    from docpipe.extraction.pipeline import Batch, DocumentReport, WorkItem
    from docpipe.profile import active_profile

    computer = runner.make_computer(active_profile())
    if computer is None:
        raise SystemExit("no compute step: is CODE_EXEC_URL set?")
    documents: dict = {}
    for hit in hits:
        documents.setdefault(hit.get("document_id") or 0, []).append(
            WorkItem(hit.get("document_id") or 0, None, source_of(hit, args)))
    rows = []
    for path in sorted(stored.glob("doc*.json")):
        probe = json.loads(path.read_text(encoding="utf-8"))
        document = probe["document"]
        if "verified" not in probe:
            raise SystemExit(f"{path} is older than its verified rows")
        started = time.time()
        report = DocumentReport(document_id=document)
        report.tuples.extend(row for row in probe["verified"]
                             if not row.get("computed"))
        before = len(report.tuples)
        computer([(Batch(document, None, documents[document]), {})], report,
                 spec=spec)
        row = {"document": document, "seconds": round(time.time() - started, 1),
               "verified": before, "tuples": report.tuples[before:]}
        (args.out / f"doc{document}.json").write_text(
            json.dumps(row, ensure_ascii=False, default=str), encoding="utf-8")
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path, nargs="?")
    parser.add_argument("--hits", type=Path,
                        help="the passages as a JSON list, no database needed")
    parser.add_argument("--out", type=Path, required=True,
                        help="folder for the trace and report.json")
    parser.add_argument("--owner", action="append",
                        help="a passage as kind/id, repeatable")
    parser.add_argument("--document", type=int,
                        help="take the widest tables of this document")
    parser.add_argument("--largest", type=int, default=5)
    parser.add_argument("--documents",
                        help="with --whole: every passage of these "
                             "documents, comma-separated ids")
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--image-root", type=Path, default=None)
    parser.add_argument("--whole", action="store_true",
                        help="also the frame and every coordinate")
    parser.add_argument("--places", action="store_true",
                        help="with --whole: search over the map of places")
    parser.add_argument("--every-row", action="store_true",
                        help="with --places: no window narrows its rows")
    parser.add_argument("--compute", type=Path,
                        help="the compute step over this stored --whole probe")
    parser.add_argument("--survey", action="store_true",
                        help="with --documents: only the survey of each plan")
    args = parser.parse_args()

    from docpipe.extraction import runner, trace
    from docpipe.extraction.pipeline import Batch, WorkItem
    from docpipe.inference import db as inference_db
    from docpipe.profile import active_profile

    spec = runner.load_spec(json.loads(Path(active_profile().component(
        "extraction", "SPEC_PATH")).read_text(encoding="utf-8")))
    passages, document_spec = None, None
    if args.hits:
        hits = json.loads(args.hits.read_text(encoding="utf-8"))
    elif args.documents:
        hits = []
        every = runner.make_rest_of_document(args.db)
        passages = {}
        for number in args.documents.split(","):
            document = int(number)
            passages[document] = [
                replace(source, image_path=None)
                if args.image_root is None else source
                for source in every(document, set())]
        document_spec = runner.document_spec_per_call(
            args.db, spec, active_profile().component("extraction",
                                                      "document_axes"))
    else:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        hits = [dict(inference_db.fetch_owner_content(conn, kind, number))
                for kind, number in owners_of(args, conn)]
        conn.close()

    args.out.mkdir(parents=True, exist_ok=True)
    trace.open_trace(args.out, lambda document_id: f"doc{document_id}")
    if args.survey:
        if not passages:
            parser.error("--survey reads whole plans: give --documents")
        report = survey_over(passages, spec, args)
        trace.close()
        for row in report:
            print(json.dumps(row, ensure_ascii=False))
        return write_report(args.out, report)
    if args.compute:
        report = compute_over(args.compute, hits, spec, args)
        trace.close()
        for row in report:
            print(json.dumps({k: v for k, v in row.items() if k != "tuples"}))
        return write_report(args.out, report)
    if args.whole:
        report = whole(hits, spec, args, passages, document_spec)
        trace.close()
        for row in report:
            print(json.dumps({k: v for k, v in row.items()
                              if k not in ("tuples", "verified")},
                             ensure_ascii=False))
        return write_report(args.out, report)
    harvest = runner.make_harvester(args.image_root, spec=spec)

    def probe(hit: dict) -> dict:
        source = source_of(hit, args)
        document = hit.get("document_id") or 0
        batch = Batch(document, None, [WorkItem(document, None, source)])
        started = time.time()
        got = harvest(batch, [])
        return {"owner": f"{source.owner_kind}/{source.owner_id}",
                "chars": len(source.text or ""),
                "seconds": round(time.time() - started, 1),
                "status": got.get("status"), "tuples": got.get("tuples"),
                **tally(got.get("tuples") or [], source.text or "")}

    with ThreadPoolExecutor(args.parallel) as pool:
        report = list(pool.map(probe, hits))
    trace.close()

    tokens: dict = {}
    for event in trace_events(args.out):
        if event.get("t") == "rows":
            for kind, number in event.get("sources") or ():
                key = f"{kind}/{number}"
                tokens[key] = (tokens.get(key, 0)
                               + (event.get("completion_tokens") or 0))
    for row in report:
        row["completion_tokens"] = tokens.get(row["owner"], 0)
        print(json.dumps({k: v for k, v in row.items() if k != "tuples"},
                         ensure_ascii=False))
    return write_report(args.out, report)


def write_report(out: Path, report: list) -> int:
    rounds = [event for event in trace_events(out) if event.get("t") == "code"]
    print(json.dumps({"sandbox_rounds": len(rounds),
                      "sandbox_ok": sum(1 for r in rounds if r.get("ok"))}))
    (out / "report.json").write_text(json.dumps(
        {"passages": report, "sandbox": rounds}, ensure_ascii=False, indent=1,
        default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
