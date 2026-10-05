"""
cli.py: `docpipe export` and `docpipe serve`.

    docpipe export HARVEST_DIR --out values.csv
    docpipe export HARVEST_DIR --format jsonl --level B --out values.jsonl
    docpipe serve HARVEST_DIR --http [--port 8750]
    docpipe serve HARVEST_DIR --mcp

Both read the harvest once (`values.py`). With a profile the values carry
the labels of its spec and the transcribed mark of its database; without
one they carry what the harvest itself says.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..profile import add_profile_argument, program, resolve_profile
from . import export as exporting
from .values import LEVELS, Values


def _common(parser: argparse.ArgumentParser) -> None:
    add_profile_argument(parser)
    parser.add_argument("harvest", type=Path, help="harvest directory")
    parser.add_argument("--db", type=Path,
                        help="corpus database (default: the profile's, "
                             "when it is there)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])


def open_store(args) -> Values:
    """The value store the arguments name."""
    logging.basicConfig(level=getattr(logging, args.log_level),
                        stream=sys.stderr,
                        format="%(asctime)s [%(levelname)s] %(name)s "
                               "%(message)s", datefmt="%H:%M:%S")
    profile = resolve_profile(args)
    spec = None
    db = args.db
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
        return Values.load(args.harvest, spec=spec, db=db)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))


def export_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.serve.export"),
        description="The harvested values as a table, one line per value, "
                    "each with its quote, page and trust level.")
    _common(parser)
    parser.add_argument("--format", choices=sorted(exporting.FORMATS),
                        help="default: by the ending of --out, else csv")
    parser.add_argument("--out", type=Path,
                        help="file to write (default: standard output)")
    parser.add_argument("--document")
    parser.add_argument("--parameter", help="parameter name or label")
    parser.add_argument("--level", choices=LEVELS,
                        help="worst trust level still wanted (default: "
                             "every value)")
    args = parser.parse_args(argv)
    kind = args.format
    if kind is None:
        ending = args.out.suffix.lstrip(".").lower() if args.out else ""
        kind = ending if ending in exporting.FORMATS else "csv"
    store = open_store(args)
    found = store.find(document=args.document, parameter=args.parameter,
                       level=args.level, limit=None)
    text = exporting.FORMATS[kind](found["values"])
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
        print(f"{args.out}: {len(found['values'])} value(s)",
              file=sys.stderr)
    return 0


def serve_main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.serve"),
        description="Answer questions about the harvested values: over "
                    "HTTP, or as an MCP server for an assistant.")
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
    store = open_store(args)
    if args.mcp:
        from . import mcp
        return mcp.serve(store)
    from . import http
    return http.serve(store, args.host,
                      http.DEFAULT_PORT if args.port is None else args.port)
