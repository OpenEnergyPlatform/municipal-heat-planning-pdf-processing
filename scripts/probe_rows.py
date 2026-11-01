#!/usr/bin/env python3
"""
probe_rows.py – The rows request of the harvest over a few passages.

A corpus job is the slow way to learn whether a prompt or a reply format
works. This asks the real request over named passages against whatever
LLM_BASE_URL and LLM_MODEL say, with the prompt, the split and the reading of
the run, and needs neither a GPU job nor retrieval:

    python scripts/probe_rows.py data/KWP.db --out probe --owner table/89205
    python scripts/probe_rows.py data/KWP.db --out probe --document 1021 --largest 5
    python scripts/probe_rows.py --hits passages.json --out probe

`--hits` takes the passages from a file, as `fetch_owner_content` returns them,
so a machine without the database can run the probe.

For each passage it reports the tokens and seconds of its requests, the values
read, how many share a quote, and how many stand the two checks of the harvest:
the quote stands in the passage and the number in the quote.
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
    harvest = runner.make_harvester(args.image_root, spec=spec)

    def probe(hit: dict) -> dict:
        source = runner._source_of(hit)
        if args.image_root is None:
            source = replace(source, image_path=None)
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
    for path in args.out.glob("*.trace.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("t") == "rows":
                for kind, number in event.get("sources") or ():
                    key = f"{kind}/{number}"
                    tokens[key] = (tokens.get(key, 0)
                                   + (event.get("completion_tokens") or 0))
    for row in report:
        row["completion_tokens"] = tokens.get(row["owner"], 0)
        print(json.dumps({k: v for k, v in row.items() if k != "tuples"},
                         ensure_ascii=False))
    (args.out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
