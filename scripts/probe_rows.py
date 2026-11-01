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

`--hits` takes the passages from a file, as `fetch_owner_content` returns them,
so a machine without the database can run the probe.

For each passage it reports the tokens and seconds of its requests, the values
read, how many share a quote, and how many stand the two checks of the harvest:
the quote stands in the passage and the number in the quote.

`--whole` asks what a run asks of these passages: the frame, the rows of each
pair and every coordinate of them, with the prompts and the checks of the run.
There is no search: a coordinate is looked for in the other passages given,
in their order, and a list a document closes from the database stays empty.
It writes each document's report when it is done, and reports the pairs and
each coordinate's states. Several agents share the work through LLM_MODELS and
LLM_SLOTS_PER_MODEL, as in the chat.

A sandbox round needs CODE_EXEC_URL; `report.json` counts the rounds either way.
"""
import argparse
import json
import sqlite3
import sys
import time
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


def states_of(tuples: list, slots: list) -> dict:
    """{coordinate: {state: tuples}} over the rows that came back."""
    states: dict = {}
    for claim in tuples:
        if not isinstance(claim, dict) or claim.get("_harvest_failed"):
            continue
        for slot in slots:
            state = claim.get(f"{slot.name}_state") or "none"
            counts = states.setdefault(slot.name, {})
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


def whole(hits: list, spec, args) -> list:
    """The frame, the rows and the coordinates of each document's passages."""
    from docpipe.extraction import fields, runner
    from docpipe.extraction.pipeline import WorkItem, group_items
    from docpipe.profile import active_profile

    profile = active_profile()
    frame_axes = fields.frame_slots(spec, profile.component("extraction", "FRAME") or ())
    gate = profile.component("extraction", "SLICE") or {}
    ask_frame = runner.make_frame_asker(args.image_root)
    documents: dict = {}
    for hit in hits:
        documents.setdefault(hit.get("document_id") or 0, []).append(
            source_of(hit, args))

    def rest_of_document(document: int, exclude: set,
                         start=None) -> list:
        return [replace(source, provenance={**source.provenance, "via": "comb"})
                for source in documents.get(document, ())
                if (source.owner_kind, source.owner_id) not in exclude]

    harvest = runner.make_fieldwise_harvester(
        args.image_root, rest_of_document=rest_of_document, spec=spec,
        slice_gate=gate, frame_axes=frame_axes)
    slots = {slot.name: slot for parameter in spec.parameters
             for slot in fields.axis_slots(parameter)}

    def one(document: int) -> dict:
        sources = documents[document]
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
        with ThreadPoolExecutor(args.parallel) as pool:
            replies = list(pool.map(lambda batch: harvest(batch, []), batches))
        tuples = [claim for got in replies for claim in got.get("tuples") or ()]
        row = {
            "document": document, "passages": len(sources),
            "seconds": round(time.time() - started, 1),
            "pairs": [{s.name: pair.get(s.name) for s in frame_axes}
                      for pair in pairs],
            "frame_status": status, "years_not_named": missed,
            "batches": len(batches), "tuples": tuples,
            "states": states_of(tuples, slots.values())}
        (args.out / f"doc{document}.json").write_text(
            json.dumps(row, ensure_ascii=False, default=str), encoding="utf-8")
        return row

    with ThreadPoolExecutor(len(documents) or 1) as pool:
        return list(pool.map(one, documents))


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
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--image-root", type=Path, default=None)
    parser.add_argument("--whole", action="store_true",
                        help="also the frame and every coordinate")
    args = parser.parse_args()

    from docpipe.extraction import runner, trace
    from docpipe.extraction.pipeline import Batch, WorkItem
    from docpipe.inference import db as inference_db
    from docpipe.profile import active_profile

    spec = runner.load_spec(json.loads(Path(active_profile().component(
        "extraction", "SPEC_PATH")).read_text(encoding="utf-8")))
    if args.hits:
        hits = json.loads(args.hits.read_text(encoding="utf-8"))
    else:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        hits = [dict(inference_db.fetch_owner_content(conn, kind, number))
                for kind, number in owners_of(args, conn)]
        conn.close()

    args.out.mkdir(parents=True, exist_ok=True)
    trace.open_trace(args.out, lambda document_id: f"doc{document_id}")
    if args.whole:
        report = whole(hits, spec, args)
        trace.close()
        for row in report:
            print(json.dumps({k: v for k, v in row.items() if k != "tuples"},
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
