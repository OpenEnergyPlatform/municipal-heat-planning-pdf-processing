#!/usr/bin/env python3
"""
probe_rows.py – The requests of the harvest over a few passages.

A corpus job is the slow way to learn whether a prompt or a reply format
works. This asks the real request over named passages against whatever
LLM_BASE_URL and LLM_MODEL say, with the prompt, the split and the reading of
the run, and needs neither a GPU job nor retrieval:

    python scripts/probe_rows.py data/scenarios/scenarios.db --out probe --survey --read --documents 4,23
    python scripts/probe_rows.py --hits passages.json --out new --compute probe

`--hits` takes the passages from a file, as `fetch_owner_content` returns them,
so a machine without the database can run the probe.

`--documents` takes every passage of these documents from the database, in
the order the run reads the rest of a document, and closes each document's
own lists from it as the run does (the profile's `document_axes`).

`--compute` takes the verified rows of a stored probe and asks only what
the compute step leaves open, so its prompt can be tried without reading the
plans again. The plans' passages come from `--hits` or, with the database,
from `--documents`. With the database and `--index` its search by a sentence ranks
the plan as a run does; without them that search finds nothing.

`--survey` with `--documents` makes only the order of each field's pieces
of each whole plan, the first step of the harvest, and keeps it in
`<out>/survey`. With `--read` each plan is then read as the run reads it
(`runner.make_harvest`): its figures transcribed once, every field in every
piece, the fields a document has once asked once, each value's coordinates
asked one by one and searched where its own place does not say them; the
values are folded as the run folds them. With `--index` the search over the
plan is the run's: the global index it names and the embedding model, on the
CPU when the machine has no GPU; without it a search shows the pieces in the
plan's order, and with RERANK_BASE_URL the reranker orders every field's
pieces.

A sandbox round needs CODE_EXEC_URL; `report.json` counts the rounds either way.
"""
import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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
    from docpipe.extraction import trace
    return [event for path in trace.files(out)
            for event in trace.lines(path)]


def source_of(hit: dict, args):
    from docpipe.extraction import runner

    source = runner._source_of(hit)
    return (replace(source, image_path=None)
            if args.image_root is None else source)


def ranking(args):
    """rank(document_id, probes, exclude): the plan ranked for sentences as a
    run ranks it, over the global index named by `--index`."""
    from docpipe.extraction import runner
    from docpipe.inference import faiss_store, query_cache
    index, id_to_pos = faiss_store.load_global_index(args.index)
    cache_path = args.out / "query_cache.db"
    query_cache.connect(cache_path).close()
    more = runner.make_more_sources(
        args.db, index, id_to_pos, cache_path,
        reranker=runner.make_search_reranker(args.image_root))

    def rank(document_id: int, probes: list, exclude: set) -> list:
        return more(document_id, probes, set(exclude), limit=0)

    return rank


def survey_over(passages: dict, spec, args, document_spec=None) -> list:
    """Each document as the run harvests it (`runner.make_harvest`), with
    the lists it closes (*document_spec*), made once per document: without
    --read the order of each field's pieces, with it the whole reading and
    the fold."""
    from docpipe.extraction import fields, runner, throttle
    from docpipe.extraction.pipeline import DocumentReport
    from docpipe.profile import active_profile

    specs = {document: (document_spec(document) if document_spec else None)
             or spec for document in passages}
    profile = active_profile()
    completer = runner.make_completer(profile, args.db)

    def every(document: int, exclude: set) -> list:
        return [source for source in passages.get(document, ())
                if (source.owner_kind, source.owner_id) not in exclude]

    # --parallel requests with the model at once, held by the run's queue,
    # and the run's threads that ask a document's requests side by side.
    runner.start_fixed_limit(args.parallel)
    runner.AHEAD = ThreadPoolExecutor(max(args.parallel, throttle.MAXIMUM),
                                      thread_name_prefix="ahead")
    whole = runner.make_harvest(
        spec, db_path=args.db, out=args.out, image_root=args.image_root,
        profile=profile, every=every, spec_for=specs.__getitem__,
        rank=ranking(args) if args.index is not None else None,
        reranker=runner.make_chunk_reranker())
    names = sorted({slot.name for parameter in spec.parameters
                    for slot in fields.axis_slots(parameter)}
                   | {"unit", "parameter", "value"})

    def one(document: int) -> dict:
        started = time.time()
        own = specs[document]
        row = {"document": document, "passages": len(passages[document]),
               # The lists this document closes, entries per list: 0 is a
               # list the run would close and this probe did not.
               "lists": {**{p.uri: len(p.vocabulary or ())
                            for p in own.parameters if p.vocabulary_dynamic},
                         **{f"{p.uri}.{name}": len(axis.vocabulary or ())
                            for p in own.parameters
                            for name, axis in p.axes.items()
                            if axis.dynamic}}}
        if not args.read:
            plan, _counts = whole.plan_of(document)
            located = [p for p in own.parameters
                       if not p.once_per_document]
            order = whole.orders(plan, located, whole.chunk_units)
            row.update({
                "seconds": round(time.time() - started, 1),
                "chunks": len(plan.chunks),
                # Each field's first pieces, best first.
                "first": {uri: [list(key) for key in keys[:5]]
                          for uri, keys in order.items()}})
            return row
        taken = whole(document)
        if taken is None:
            row["halted"] = True
            return row
        report = DocumentReport(document_id=document,
                                owners_harvested=taken.passages,
                                planned={"survey": taken.passages},
                                sources_of=taken.sources_of)
        runner.fold_answers(taken.answered, report, locate=None, spec=spec)
        # What the run completes from outside the document, as it does
        # after the fold.
        row["completion"] = completer(report, own) if completer else None
        reads = taken.reads
        row.update({
            "seconds": round(time.time() - started, 1),
            "coordinates_unanswered": sum(r.unanswered for r in reads),
            "unread": sum(1 for r in reads if r.unread),
            "holes": sum(1 for _batch, reply in taken.answered
                         for claim in reply.get("tuples") or ()
                         if claim.get("_harvest_failed")),
            "claims": sum(len(r.claims) for r in reads),
            "verified": report.tuples, "refusals": len(report.refusals),
            "refused_for": dict(Counter(refusal.get("reason")
                                        for refusal in report.refusals)),
            "states": states_of(report.tuples, names)})
        (args.out / f"doc{document}.json").write_text(
            json.dumps(row, ensure_ascii=False, default=str),
            encoding="utf-8")
        return {k: v for k, v in row.items() if k != "verified"}

    with ThreadPoolExecutor(len(passages) or 1) as documents:
        rows = list(documents.map(one, passages))
    # The requests each document came to, per kind, from the trace
    # (`surveyed.SurveyedHarvest`, event "asked"), written out first: the
    # trace is still open.
    from docpipe.extraction import trace
    trace.flush()
    asked = {}
    for event in trace_events(args.out):
        if event.get("t") == "asked":
            asked[event.get("doc")] = event
    for row in rows:
        event = asked.get(row["document"]) or asked.get(
            f"doc{row['document']}") or {}
        row.update({"requests": event.get("requests"),
                    "refused_first": event.get("refused"),
                    "question_queries": event.get("question_queries")})
    return rows


def compute_over(stored: Path, hits: list, spec, args, passages=None) -> list:
    """The compute step over the verified rows of a stored `--whole` probe.
    The raw claims cannot be folded again: their source is a label of the batch
    they were read in, and the batches are not stored."""
    from docpipe.extraction import runner
    from docpipe.extraction.pipeline import Batch, DocumentReport, WorkItem
    from docpipe.profile import active_profile

    documents: dict = {
        document: [WorkItem(document, None, source) for source in sources]
        for document, sources in (passages or {}).items()}
    for hit in hits:
        documents.setdefault(hit.get("document_id") or 0, []).append(
            WorkItem(hit.get("document_id") or 0, None, source_of(hit, args)))
    # The passages given are the plan the request's tools read, in their
    # order, as a run's are, and with an index it ranks the plan as one.
    computer = runner.make_computer(
        active_profile(), lambda document: [item.source for item in
                                            documents.get(document, ())],
        rank=ranking(args) if args.index is not None else None)
    if computer is None:
        raise SystemExit("no compute step: is CODE_EXEC_URL set?")
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
    parser.add_argument("--documents",
                        help="every passage of these documents, "
                             "comma-separated ids")
    parser.add_argument("--parallel", type=int, default=2,
                        help="requests with the model at once")
    parser.add_argument("--image-root", type=Path, default=None)
    parser.add_argument("--compute", type=Path,
                        help="the compute step over this stored probe")
    parser.add_argument("--survey", action="store_true",
                        help="with --documents: only the order of each "
                             "field's pieces")
    parser.add_argument("--read", action="store_true",
                        help="with --survey: read each plan as the run "
                             "reads it")
    parser.add_argument("--index", type=Path, default=None,
                        help="the global FAISS index: the search over a "
                             "plan, and needed by --compute")
    args = parser.parse_args()

    from docpipe.extraction import runner, trace
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
        parser.error("give --hits or --documents")

    args.out.mkdir(parents=True, exist_ok=True)
    trace.open_trace(args.out, lambda document_id: f"doc{document_id}")
    if args.survey:
        if not passages:
            parser.error("--survey reads whole plans: give --documents")
        report = survey_over(passages, spec, args, document_spec)
        trace.close()
        for row in report:
            print(json.dumps(row, ensure_ascii=False))
        return write_report(args.out, report)
    if args.compute:
        report = compute_over(args.compute, hits, spec, args, passages)
        trace.close()
        for row in report:
            print(json.dumps({k: v for k, v in row.items() if k != "tuples"}))
        return write_report(args.out, report)
    parser.error("give --survey or --compute")


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
