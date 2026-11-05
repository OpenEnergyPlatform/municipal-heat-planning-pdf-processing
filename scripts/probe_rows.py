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
plans again. With the database and `--index` its search by a sentence ranks
the plan as a run does; without them that search finds nothing.

`--survey --read` runs the rebuilt harvest's survey and its reading of each
parameter; `--comb` adds the search for what the reading left open, ranked as
a run ranks it: the global index named by `--index` and the embedding model,
on the CPU when the machine has no GPU.

`--survey` with `--documents` asks only the survey of each whole plan, the
first pass of the rebuilt harvest, and keeps it in `<out>/survey`. With
`--read` each parameter is then read in the passages the survey named for it,
and the values are folded as the run folds them.

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
    from docpipe.extraction import trace
    return [event for path in trace.files(out)
            for event in trace.lines(path)]


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
    completer = runner.make_completer(profile, args.db)
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
        completion = completer(report, own) if completer else None
        row = {
            "document": document, "passages": len(sources),
            "completion": completion,
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


def ranking(args):
    """rank(document_id, probes, exclude): the plan ranked for sentences as a
    run ranks it, over the global index named by `--index`."""
    from docpipe.extraction import runner
    from docpipe.inference import faiss_store, query_cache
    index, id_to_pos = faiss_store.load_global_index(args.index)
    cache_path = args.out / "query_cache.db"
    query_cache.connect(cache_path).close()
    more = runner.make_more_sources(args.db, index, id_to_pos, cache_path)

    def rank(document_id: int, probes: list, exclude: set) -> list:
        return more(document_id, probes, set(exclude), limit=0)

    return rank


def survey_over(passages: dict, spec, args, document_spec=None) -> list:
    """The survey of each document's whole plan, as the run asks it, and
    with --read the reading of each parameter after it and with --comb the
    combing, through the run's own steps (`surveyed.SurveyedHarvest`). Each
    document is asked with the lists it closes (*document_spec*), made once
    per document, as the run makes them."""
    from docpipe.extraction import fields, runner, surveyed
    from docpipe.extraction.pipeline import DocumentReport
    from docpipe.profile import active_profile

    specs = {document: (document_spec(document) if document_spec else None)
             or spec for document in passages}
    completer = runner.make_completer(active_profile(), args.db)

    def every(document: int, exclude: set) -> list:
        return [source for source in passages.get(document, ())
                if (source.owner_kind, source.owner_id) not in exclude]

    pool = ThreadPoolExecutor(args.parallel)
    rank = seek = None
    profile = active_profile()
    own = profile.component("extraction", "FRONT_PAGE_PARAMETERS") or ()
    if args.comb:
        if not args.read or args.index is None:
            raise SystemExit("--comb needs --read and --index")
        rank = ranking(args)
        seek = runner.make_seek_probes(
            own, runner.document_context_of(
                args.db, profile.component("extraction", "document_context")))

    def made_survey(doc_spec, only, scope):
        made = runner.make_survey(args.db, runner.narrow_spec(doc_spec, only),
                                  args.out, every=every,
                                  image_root=args.image_root, scope=scope)
        if made is None:
            raise SystemExit("no survey: the profile writes no survey prompt "
                             "or its spec names no groups")
        made.pool = pool
        return made

    def made_reader(doc_spec):
        made = runner.make_reader(doc_spec, args.image_root)
        if made is None:
            raise SystemExit("no reading: the profile writes no read prompts")
        made.pool = pool
        return made

    def made_comber(doc_spec):
        if rank is None:
            return None
        made = runner.make_comber(doc_spec, rank, seek)
        if made is None:
            raise SystemExit("no combing: the profile writes no comb prompt")
        made.pool = pool
        return made

    whole = surveyed.SurveyedHarvest(
        spec, made_survey, made_reader, made_comber,
        lambda document: every(document, set()),
        runner.make_page_count(args.db), spec_for=specs.__getitem__,
        front=own,
        title=profile.component("extraction", "FRONT_PAGE_TITLE"))
    names = sorted({slot.name for parameter in spec.parameters
                    for slot in fields.axis_slots(parameter)}
                   | {"unit", "parameter", "value"})

    def one(document: int) -> dict:
        started = time.time()
        survey = whole.survey_of(specs[document])
        found = survey(document, passages[document])
        answers = list(found.answers.values())
        own = specs[document]
        row = {"document": document, "passages": len(passages[document]),
               "seconds": round(time.time() - started, 1),
               # The lists this document closes, entries per list: 0 is a
               # list the run would close and this probe did not.
               "lists": {**{p.uri: len(p.vocabulary or ())
                            for p in own.parameters if p.vocabulary_dynamic},
                         **{f"{p.uri}.{name}": len(axis.vocabulary or ())
                            for p in own.parameters
                            for name, axis in p.axes.items()
                            if axis.dynamic}},
               "complete": found.complete,
               "by_parameter": {p: len(found.passages_of(p))
                                for p in survey.parameters},
               "none": sum(1 for a in answers if not a.parameters),
               "dropped": sum(len(a.dropped) for a in answers),
               "unanswered": len(found.unanswered),
               "tuples": {name: sum(len(a.tuples.get(name, ()))
                                    for a in answers)
                          for name in survey.slots}}
        if not args.read:
            return row
        read_started = time.time()
        taken = whole(document)
        reads, combed = taken.reads, taken.combed
        # The parameters the survey named no passage for, each with every
        # passage the walk down its search's list read it in, in rank order.
        row["sought"] = {uri: [list(owner) for owner in owners]
                         for uri, owners
                         in surveyed.walks_of(taken.sought).items()}
        # What a publication says of itself, each with the passages of its
        # first pages read for it besides those the survey named, page by
        # page.
        row["front"] = {uri: [list(owner) for owner
                              in taken.front.passages_of(uri)]
                        for uri in whole.front
                        if taken.front.passages_of(uri)}
        report = DocumentReport(document_id=document,
                                owners_harvested=taken.passages,
                                planned={surveyed.STAGE: taken.passages},
                                sources_of=taken.sources_of)
        runner.fold_answers(taken.answered, report, locate=None, spec=spec)
        # What the run completes from outside the document, as it does
        # after the fold.
        row["completion"] = completer(report, own) if completer else None
        if args.comb:
            row.update({
                "combed": len(combed),
                "comb_requests": sum(c.asked for c in combed),
                "comb_open": sum(c.open for c in combed),
                "comb_filled": sum(c.filled for c in combed),
                "comb_hits": sum(c.hits for c in combed),
                "comb_fetched": sum(c.fetched for c in combed),
                "comb_searched": sum(c.searched for c in combed),
                "comb_exhausted": sum(c.exhausted for c in combed)})
        row.update({
            # Reading and combing together, as the run does them.
            "read_seconds": round(time.time() - read_started, 1),
            "read_requests": sum(r.asked for r in reads),
            "asked_again": sum(1 for r in reads if r.asked > 1),
            "corrections": sum(r.corrected for r in reads),
            "refused_first": dict(sum((Counter(r.failed) for r in reads),
                                      Counter())),
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
        return list(documents.map(one, passages))


def compute_over(stored: Path, hits: list, spec, args) -> list:
    """The compute step over the verified rows of a stored `--whole` probe.
    The raw claims cannot be folded again: their source is a label of the batch
    they were read in, and the batches are not stored."""
    from docpipe.extraction import runner
    from docpipe.extraction.pipeline import Batch, DocumentReport, WorkItem
    from docpipe.profile import active_profile

    documents: dict = {}
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
    parser.add_argument("--read", action="store_true",
                        help="with --survey: read each parameter after it")
    parser.add_argument("--comb", action="store_true",
                        help="with --read: search for what the reading left "
                             "open (needs --index)")
    parser.add_argument("--index", type=Path, default=None,
                        help="with --comb or --compute: the global FAISS "
                             "index")
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
        report = survey_over(passages, spec, args, document_spec)
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
