"""
usage.py: Counts the tokens every run spends, into one SQLite file that
outlives the runs.

The model server reports what each request really cost: input and output
tokens on a chat reply, input tokens on an embedding. Until now those numbers
reached a log line at best and were gone with the job. Here they are summed per
stage and model and written as one row per run, so the total over every run is
a query:

    sqlite3 data/usage.db "SELECT * FROM token_totals"
    python -m docpipe.usage [--profile P]

One row per run instead of one counter that grows: a flush repeats the same
absolute numbers, so writing twice never counts twice, and a total can still be
split by stage, model or job afterwards.

Each row also says which profile the run was under and, where the provider
reports it, how many of the input tokens it served from its cache. A ledger
written before that has neither column: the first write adds them, and a read
never writes, so an older file stays readable as it is.

A process counts only after `begin(stage)`, which each stage's entry point
calls. The inference app, the tests and any library use record nothing. The
row is rewritten every FLUSH_SECONDS while requests come back and once more at
exit, so a job the scheduler kills loses at most that window. Counting must
never take a run down: a database that cannot be written is logged once and
the run goes on.

Author: Felix Vossel
"""
from __future__ import annotations

import atexit
import logging
import os
import socket
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

log = logging.getLogger(__name__)

FLUSH_SECONDS = 60.0

# Added after the table first existed: an older ledger gets them on its next
# write (see `_prepare`).
ADDED = (("profile", "TEXT"),
         ("cached_tokens", "INTEGER NOT NULL DEFAULT 0"))

TABLE = """
CREATE TABLE IF NOT EXISTS token_usage (
    run              TEXT NOT NULL,     -- one process of one stage
    job              TEXT,              -- SLURM_JOB_ID, NULL outside Slurm
    host             TEXT NOT NULL,
    stage            TEXT NOT NULL,     -- visuals | refinement | chunking | extraction
    model            TEXT NOT NULL,
    started          TEXT NOT NULL,     -- UTC, ISO 8601
    updated          TEXT NOT NULL,
    requests         INTEGER NOT NULL,  -- chat replies, or embedded inputs
    input_tokens     INTEGER NOT NULL,  -- the cached ones included
    output_tokens    INTEGER NOT NULL,
    embedding_tokens INTEGER NOT NULL,
    profile          TEXT,              -- NULL: written before this was kept
    cached_tokens    INTEGER NOT NULL DEFAULT 0,  -- of input_tokens
    PRIMARY KEY (run, stage, model)
);
"""
VIEW = """
CREATE VIEW IF NOT EXISTS token_totals AS
    SELECT stage, model,
           COUNT(DISTINCT run)   AS runs,
           SUM(requests)         AS requests,
           SUM(input_tokens)     AS input_tokens,
           SUM(output_tokens)    AS output_tokens,
           SUM(embedding_tokens) AS embedding_tokens,
           SUM(cached_tokens)    AS cached_tokens
    FROM token_usage GROUP BY stage, model;
"""
SCHEMA = TABLE + VIEW


def db_path() -> Path:
    """Where the counts go. Read at flush time, so a test can redirect it."""
    from docpipe.profile import shared_file
    return Path(os.environ.get("DOCPIPE_USAGE_DB")
                or shared_file("usage.db", "data/usage.db"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_lock = threading.Lock()
_flush_lock = threading.Lock()
_stage: Optional[str] = None
_profile: Optional[str] = None
_run = ""
_started = ""
_counts: dict = {}      # model -> [requests, input, output, embedding, cached]
_last_flush = 0.0
_warned = False


def begin(stage: str) -> None:
    """Count this process's requests under `stage` from here on.

    The profile in effect is read here: a stage settles it before it begins.
    """
    from docpipe.profile import ENV_VAR
    global _stage, _profile, _run, _started, _last_flush
    with _lock:
        if _stage is not None:
            return
        _stage = stage
        _profile = os.environ.get(ENV_VAR) or None
        _run = uuid.uuid4().hex
        _started = _now()
        _last_flush = time.monotonic()
    atexit.register(flush)


def add(model: str, input_tokens: int = 0, output_tokens: int = 0,
        embedding_tokens: int = 0, requests: int = 1,
        cached_tokens: int = 0) -> None:
    """Count one request (or `requests` embedded inputs) against `model`.

    `cached_tokens` are the part of `input_tokens` the provider served from
    its cache: they are counted beside them, never instead.
    """
    if _stage is None:
        return
    due = False
    with _lock:
        row = _counts.setdefault(str(model), [0, 0, 0, 0, 0])
        row[0] += requests
        row[1] += input_tokens
        row[2] += output_tokens
        row[3] += embedding_tokens
        row[4] += cached_tokens
        due = time.monotonic() - _last_flush >= FLUSH_SECONDS
    if due:
        flush(wait=False)


def _whole(value) -> Optional[int]:
    """A token count the provider reported: a whole number from 0 up, else
    None."""
    return value if (isinstance(value, int) and not isinstance(value, bool)
                     and value >= 0) else None


def cached_of(usage) -> int:
    """The input tokens a reply's usage block says came from the provider's
    cache. 0 where it says nothing, which is what a server without a cache,
    or one that does not report it, comes to.

    The adapters of the hosted providers put it on `cached_tokens`; the
    OpenAI client of a server of one's own carries it under
    `prompt_tokens_details`.
    """
    direct = _whole(getattr(usage, "cached_tokens", None))
    if direct is not None:
        return direct
    nested = getattr(getattr(usage, "prompt_tokens_details", None),
                     "cached_tokens", None)
    return _whole(nested) or 0


def reply(response, model: str) -> None:
    """Count a chat completion by what the server says it cost.

    A reply without a usage block (a stub, a server that omits it) counts
    nothing rather than a guess.
    """
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if not isinstance(prompt, int):
        return
    add(model, input_tokens=prompt,
        output_tokens=completion if isinstance(completion, int) else 0,
        cached_tokens=cached_of(usage))


def _columns(conn: sqlite3.Connection) -> set:
    return {row[1] for row in conn.execute("PRAGMA table_info(token_usage)")}


def _prepare(conn: sqlite3.Connection) -> None:
    """The ledger as this version writes it: what is missing is made, and a
    ledger from before the profile and the cached tokens gets those columns.
    Only the writer does this; a reader of a file it cannot write still reads.
    """
    conn.executescript(SCHEMA)
    have = _columns(conn)
    added = False
    for column, kind in ADDED:
        if column in have:
            continue
        try:
            conn.execute(f"ALTER TABLE token_usage ADD COLUMN {column} {kind}")
        except sqlite3.OperationalError as exc:
            # another process added it between the look and the statement
            if "duplicate column" not in str(exc).lower():
                raise
        added = True
    if added:
        # an older file's view does not sum the new columns
        conn.executescript("DROP VIEW IF EXISTS token_totals;" + VIEW)


def flush(wait: bool = True) -> None:
    """Write this run's rows. Never raises."""
    global _last_flush, _warned
    if _stage is None:
        return
    if not _flush_lock.acquire(blocking=wait):
        return                      # another thread is writing the same rows
    try:
        with _lock:
            _last_flush = time.monotonic()
            rows = [(model, *counts) for model, counts in _counts.items()]
        if not rows:
            return
        path = db_path()
        updated = _now()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(path), timeout=30) as conn:
                _prepare(conn)
                conn.executemany(
                    "INSERT INTO token_usage (run, job, host, stage, model, "
                    "started, updated, requests, input_tokens, output_tokens, "
                    "embedding_tokens, profile, cached_tokens) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(run, stage, model) DO UPDATE SET "
                    "updated=excluded.updated, requests=excluded.requests, "
                    "input_tokens=excluded.input_tokens, "
                    "output_tokens=excluded.output_tokens, "
                    "embedding_tokens=excluded.embedding_tokens, "
                    "profile=excluded.profile, "
                    "cached_tokens=excluded.cached_tokens",
                    [(_run, os.environ.get("SLURM_JOB_ID"),
                      socket.gethostname(), _stage, model, _started, updated,
                      requests, inp, out, emb, _profile, cached)
                     for model, requests, inp, out, emb, cached in rows])
            conn.close()
        except Exception as exc:
            if not _warned:
                _warned = True
                log.warning("usage: could not write token counts to %s: %s",
                            path, exc)
    finally:
        _flush_lock.release()


class Sum(NamedTuple):
    """What the ledger holds for one stage and model, over its runs."""
    runs: int
    requests: int
    input_tokens: int       # the cached ones included
    output_tokens: int
    embedding_tokens: int
    cached_tokens: int


def sums(path: Optional[Path] = None,
         profile: Optional[str] = None) -> dict:
    """{(stage, model): Sum}, over the runs of one profile when it is named.

    A read never writes: a ledger from before the profile and the cached
    tokens were kept is read as it is, its rows carrying no profile and no
    cached tokens, so none of them is any profile's.
    """
    path = Path(path) if path else db_path()
    if not path.exists():
        return {}
    conn = sqlite3.connect(str(path))
    try:
        have = _columns(conn)
        if not have or (profile is not None and "profile" not in have):
            return {}
        cached = "cached_tokens" if "cached_tokens" in have else "0"
        where, given = ((" WHERE profile = ?", (profile,))
                        if profile is not None else ("", ()))
        rows = conn.execute(
            "SELECT stage, model, COUNT(DISTINCT run), SUM(requests), "
            "SUM(input_tokens), SUM(output_tokens), SUM(embedding_tokens), "
            f"SUM({cached}) FROM token_usage{where} "
            "GROUP BY stage, model ORDER BY stage, model", given).fetchall()
    finally:
        conn.close()
    return {(stage, model): Sum(*counted) for stage, model, *counted in rows}


def unattributed(path: Optional[Path] = None) -> int:
    """How many rows of the ledger carry no profile: the runs from before it
    was kept."""
    path = Path(path) if path else db_path()
    if not path.exists():
        return 0
    conn = sqlite3.connect(str(path))
    try:
        have = _columns(conn)
        if not have:
            return 0
        if "profile" not in have:
            return conn.execute(
                "SELECT COUNT(*) FROM token_usage").fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM token_usage "
                            "WHERE profile IS NULL").fetchone()[0]
    finally:
        conn.close()


def totals(path: Optional[Path] = None,
           profile: Optional[str] = None) -> list:
    """(stage, model, runs, requests, input, output, embedding) per stage and
    model, over one profile's runs when it is named."""
    return [(stage, model, *counted[:5])
            for (stage, model), counted in sums(path, profile).items()]


def cost(row, prices: dict, cached: int = 0) -> Optional[float]:
    """What one row of `totals` cost, or None when its model has no price.

    *prices* is the project file's table: per model what a million input,
    output, embedding and cached input tokens cost. A kind the table leaves
    out costs nothing, which is right for a model that is only ever used for
    the other.

    *cached* is how many of the row's input tokens the provider served from
    its cache. They cost the model's `cached` price where the table has one;
    without it they cost what any input token does, so a cache the table says
    nothing about never makes the bill smaller than it was.
    """
    price = prices.get(row[1])
    if price is None:
        return None
    _, _, _, _, tokens_in, tokens_out, tokens_embedded = row
    cached = min(max(cached, 0), tokens_in) if "cached" in price else 0
    return ((tokens_in - cached) * price.get("input", 0.0)
            + cached * price.get("cached", 0.0)
            + tokens_out * price.get("output", 0.0)
            + tokens_embedded * price.get("embedding", 0.0)) / 1_000_000


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m docpipe.usage",
        description="Tokens and cost of every run in the ledger.")
    parser.add_argument("db", nargs="?", type=Path, default=None,
                        help="the ledger (default: the project's usage.db)")
    parser.add_argument("--profile", default=None,
                        help="only the runs made under this profile: a name, "
                             "or the directory of one")
    args = parser.parse_args(argv)
    if args.profile:
        # the ledger keeps the name a run was started under, never a path
        from docpipe.profile import name_profile
        args.profile = name_profile(args.profile)
    path = args.db or db_path()
    found = sums(path, args.profile)
    if not found:
        where = f" for profile {args.profile}" if args.profile else ""
        print(f"no token counts{where} in {path}")
        older = unattributed(path) if args.profile else 0
        if older:
            print(f"{older:,} row(s) of runs from before the ledger kept the "
                  f"profile belong to none")
        return 0
    from docpipe import settings
    prices = settings.prices()
    shown_cached = any(counted.cached_tokens for counted in found.values())
    header = (("stage", "model", "runs", "requests", "input")
              + (("cached",) if shown_cached else ())
              + ("output", "embedding") + (("cost",) if prices else ()))
    table = [header]
    costs = []
    for (stage, model), counted in found.items():
        line = ((stage, model, f"{counted.runs:,}", f"{counted.requests:,}",
                 f"{counted.input_tokens:,}")
                + ((f"{counted.cached_tokens:,}",) if shown_cached else ())
                + (f"{counted.output_tokens:,}",
                   f"{counted.embedding_tokens:,}"))
        if prices:
            spent = cost((stage, model, *counted[:5]), prices,
                         counted.cached_tokens)
            costs.append(spent)
            line += ("-" if spent is None else f"{spent:,.2f}",)
        table.append(line)
    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    if args.profile:
        print(f"profile {args.profile}")
    for r in table:
        print("  ".join(c.ljust(w) if i < 2 else c.rjust(w)
                        for i, (c, w) in enumerate(zip(r, widths))))
    if prices:
        priced = [spent for spent in costs if spent is not None]
        print(f"cost: {sum(priced):,.2f} over {len(priced)} of {len(costs)} "
              f"rows; prices per million tokens from "
              f"{settings.project_file().name}, a model without one is not "
              f"counted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
