"""
usage.py: Counts the tokens every run spends, into one SQLite file that
outlives the runs.

The model server reports what each request really cost: input and output
tokens on a chat reply, input tokens on an embedding. Until now those numbers
reached a log line at best and were gone with the job. Here they are summed per
stage and model and written as one row per run, so the total over every run is
a query:

    sqlite3 data/usage.db "SELECT * FROM token_totals"
    python -m docpipe.usage

One row per run instead of one counter that grows: a flush repeats the same
absolute numbers, so writing twice never counts twice, and a total can still be
split by stage, model or job afterwards.

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
from typing import Optional

log = logging.getLogger(__name__)

FLUSH_SECONDS = 60.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS token_usage (
    run              TEXT NOT NULL,     -- one process of one stage
    job              TEXT,              -- SLURM_JOB_ID, NULL outside Slurm
    host             TEXT NOT NULL,
    stage            TEXT NOT NULL,     -- visuals | refinement | chunking | extraction
    model            TEXT NOT NULL,
    started          TEXT NOT NULL,     -- UTC, ISO 8601
    updated          TEXT NOT NULL,
    requests         INTEGER NOT NULL,  -- chat replies, or embedded inputs
    input_tokens     INTEGER NOT NULL,
    output_tokens    INTEGER NOT NULL,
    embedding_tokens INTEGER NOT NULL,
    PRIMARY KEY (run, stage, model)
);
CREATE VIEW IF NOT EXISTS token_totals AS
    SELECT stage, model,
           COUNT(DISTINCT run)   AS runs,
           SUM(requests)         AS requests,
           SUM(input_tokens)     AS input_tokens,
           SUM(output_tokens)    AS output_tokens,
           SUM(embedding_tokens) AS embedding_tokens
    FROM token_usage GROUP BY stage, model;
"""


def db_path() -> Path:
    """Where the counts go. Read at flush time, so a test can redirect it."""
    return Path(os.environ.get("DOCPIPE_USAGE_DB", "data/usage.db"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_lock = threading.Lock()
_flush_lock = threading.Lock()
_stage: Optional[str] = None
_run = ""
_started = ""
_counts: dict = {}          # model -> [requests, input, output, embedding]
_last_flush = 0.0
_warned = False


def begin(stage: str) -> None:
    """Count this process's requests under `stage` from here on."""
    global _stage, _run, _started, _last_flush
    with _lock:
        if _stage is not None:
            return
        _stage = stage
        _run = uuid.uuid4().hex
        _started = _now()
        _last_flush = time.monotonic()
    atexit.register(flush)


def add(model: str, input_tokens: int = 0, output_tokens: int = 0,
        embedding_tokens: int = 0, requests: int = 1) -> None:
    """Count one request (or `requests` embedded inputs) against `model`."""
    if _stage is None:
        return
    due = False
    with _lock:
        row = _counts.setdefault(str(model), [0, 0, 0, 0])
        row[0] += requests
        row[1] += input_tokens
        row[2] += output_tokens
        row[3] += embedding_tokens
        due = time.monotonic() - _last_flush >= FLUSH_SECONDS
    if due:
        flush(wait=False)


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
        output_tokens=completion if isinstance(completion, int) else 0)


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
                conn.executescript(SCHEMA)
                conn.executemany(
                    "INSERT INTO token_usage VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(run, stage, model) DO UPDATE SET "
                    "updated=excluded.updated, requests=excluded.requests, "
                    "input_tokens=excluded.input_tokens, "
                    "output_tokens=excluded.output_tokens, "
                    "embedding_tokens=excluded.embedding_tokens",
                    [(_run, os.environ.get("SLURM_JOB_ID"),
                      socket.gethostname(), _stage, model, _started, updated,
                      requests, inp, out, emb)
                     for model, requests, inp, out, emb in rows])
            conn.close()
        except Exception as exc:
            if not _warned:
                _warned = True
                log.warning("usage: could not write token counts to %s: %s",
                            path, exc)
    finally:
        _flush_lock.release()


def totals(path: Optional[Path] = None) -> list:
    """(stage, model, runs, requests, input, output, embedding) per stage and model."""
    path = path or db_path()
    if not path.exists():
        return []
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute("SELECT * FROM token_totals "
                            "ORDER BY stage, model").fetchall()
    conn.close()
    return rows


def main(argv=None) -> int:
    rows = totals(Path(argv[0]) if argv else None)
    if not rows:
        print(f"no token counts in {argv[0] if argv else db_path()}")
        return 0
    header = ("stage", "model", "runs", "requests", "input", "output",
              "embedding")
    table = [header] + [tuple(f"{v:,}" if isinstance(v, int) else str(v)
                              for v in row) for row in rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    for r in table:
        print("  ".join(c.ljust(w) if i < 2 else c.rjust(w)
                        for i, (c, w) in enumerate(zip(r, widths))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
