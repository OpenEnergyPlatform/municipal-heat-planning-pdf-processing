"""
cli.py: `docpipe export` and `docpipe serve`.

    docpipe export HARVEST_DIR --out values.csv
    docpipe export HARVEST_DIR --format jsonl --level B --out values.jsonl
    docpipe export HARVEST_DIR --what states --out states.csv
    docpipe export HARVEST_DIR --what refusals --out refusals.csv
    docpipe serve HARVEST_DIR --http [--port 8750]
    docpipe serve HARVEST_DIR --mcp

Both read the harvest once (`values.py`). With a profile the values carry
the labels of its spec and the transcribed mark of its database; without
one they carry what the harvest itself says.

The corpus database is named as the chat names it: `--db`, else
INFERENCE_DB_PATH, else the profile's when it is there. `serve` opens the
passage search on it (`passages.py`); without a database, or without the
word index `docpipe lexical` builds, the search says so and answers none.
`export` does not need the passages and does not open them.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..profile import add_profile_argument, program, resolve_profile
from . import export as exporting
from .values import LEVELS, NotFound, Values

DB_ENV = "INFERENCE_DB_PATH"


def _common(parser: argparse.ArgumentParser) -> None:
    add_profile_argument(parser)
    parser.add_argument("harvest", type=Path, help="harvest directory")
    parser.add_argument("--db", type=Path,
                        help="corpus database: which documents are "
                             "transcribed pages, and for `serve` the passage "
                             "search (default: INFERENCE_DB_PATH, else the "
                             "profile's, when it is there)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])


def open_store(args, search: bool = False) -> Values:
    """The value store the arguments name, with the passage search on its
    database where *search* asks for it. Opening the search checks the word
    index against the whole database, which an export has no use for."""
    logging.basicConfig(level=getattr(logging, args.log_level),
                        stream=sys.stderr,
                        format="%(asctime)s [%(levelname)s] %(name)s "
                               "%(message)s", datefmt="%H:%M:%S")
    profile = resolve_profile(args)
    spec = None
    # As the chat takes it: the option, else the setting, else the profile's.
    db = args.db or (Path(os.environ[DB_ENV]) if os.environ.get(DB_ENV)
                     else None)
    if profile is not None:
        path = profile.component("extraction", "SPEC_PATH")
        if path is not None:
            from ..extraction.spec import load
            spec = load(path)
        if db is None and Path(profile.db_path).is_file():
            db = Path(profile.db_path)
    if db is not None and not Path(db).is_file():
        raise SystemExit(f"{db} is not a file")
    try:
        store = Values.load(args.harvest, spec=spec, db=db)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    if search:
        # After the harvest: a wrong harvest directory should fail before
        # the index is checked against the whole database.
        from .passages import Passages
        store.passages = Passages(db)
    return store


def export_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.serve.export"),
        description="What a harvest holds as a table: its values (one line "
                    "each, with quote, page and trust level), the state of "
                    "each parameter in each document, or the claims it "
                    "refused.")
    _common(parser)
    parser.add_argument("--what", choices=list(exporting.TABLES),
                        default="values",
                        help="values (default), states (one line per "
                             "document and parameter: read, unstated, "
                             "exhausted, unbacked, never_asked, "
                             "not_recorded) or refusals")
    parser.add_argument("--format", choices=sorted(exporting.FORMATS),
                        help="default: by the ending of --out, else csv")
    parser.add_argument("--out", type=Path,
                        help="file to write (default: standard output)")
    parser.add_argument("--document")
    parser.add_argument("--parameter", help="parameter name or label")
    parser.add_argument("--level", choices=LEVELS,
                        help="--what values: worst trust level still wanted "
                             "(default: every value)")
    args = parser.parse_args(argv)
    if args.level and args.what != "values":
        # Not ignored: a table that quietly is not the one that was asked
        # for would pass for it.
        parser.error(f"--level grades values and does not apply to --what "
                     f"{args.what}")
    kind = args.format
    if kind is None:
        ending = args.out.suffix.lstrip(".").lower() if args.out else ""
        kind = ending if ending in exporting.FORMATS else "csv"
    store = open_store(args)
    try:
        if args.what == "values":
            found = store.find(document=args.document,
                               parameter=args.parameter, level=args.level,
                               limit=None)["values"]
        elif args.what == "states":
            found = store.states(document=args.document,
                                 parameter=args.parameter,
                                 limit=None)["states"]
        else:
            found = store.refusals(document=args.document,
                                   parameter=args.parameter,
                                   limit=None)["refusals"]
    except NotFound as exc:
        raise SystemExit(str(exc))
    writers, noun = exporting.TABLES[args.what]
    text = writers[kind](found)
    if store.unreadable:
        print(f"{store.unreadable} unreadable line(s) of the harvest were "
              f"skipped", file=sys.stderr)
    if args.out is None:
        # UTF-8 and its own line ends, whatever the terminal's code page
        # is: the text goes into a file or a pipe as often as not.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", newline="")
        sys.stdout.write(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # utf-8-sig for a CSV: a spreadsheet reads the umlauts only with it
        with open(args.out, "w", newline="", encoding="utf-8-sig"
                  if kind == "csv" else "utf-8") as handle:
            handle.write(text)
        print(f"{args.out}: {len(found)} {noun}(s)", file=sys.stderr)
    return 0


def serve_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.serve"),
        description="Answer questions about a harvest: its values, what "
                    "it says of the parameters that have none (unstated, "
                    "exhausted, ...), its refusals and, with the corpus "
                    "database and its word index, the passages. Over HTTP, "
                    "or as an MCP server for an assistant.")
    _common(parser)
    how = parser.add_mutually_exclusive_group(required=True)
    how.add_argument("--http", action="store_true",
                     help="a read-only JSON API")
    how.add_argument("--mcp", action="store_true",
                     help="a Model Context Protocol server on standard "
                          "input and output")
    parser.add_argument("--host", default="127.0.0.1",
                        help="--http: address to listen on (default: this "
                             "machine only)")
    parser.add_argument("--port", type=int, default=None,
                        help="--http: port (default: 8750)")
    args = parser.parse_args(argv)
    store = open_store(args, search=True)
    if args.mcp:
        from . import mcp
        return mcp.serve(store)
    from . import http
    return http.serve(store, args.host,
                      http.DEFAULT_PORT if args.port is None else args.port)
