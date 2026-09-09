"""
serialize.py: Turns a document harvest into the profile's target graph.

The module walks the JSONL harvest directory and keeps only the rows
a run accepted (kind is "tuple"), grouped by document name (collect).
run() hands each document's rows to a serializer the profile
supplies: profiles/<name>/kg.py exposes make_serializer(db_path), and
the runner's --serialize flag calls it. What the serializer emits
(Turtle with project IRI rules, LinkML YAML, or another format) is
the profile's own decision; the module guarantees only the walk, the
per-document grouping, and that a refusal row never reaches the
serializer.

run() concatenates the output of every document whose serializer
returned something and writes it to the output path. It raises
ValueError and leaves that path untouched when no document produced
anything. The check runs unconditionally at the end of a GPU job, so
a run that ended in a counted exception still yields a graph; without
the check, an empty or unreadable harvest directory would overwrite a
valid graph from an earlier run with nothing.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


def collect(jsonl_dir: Path) -> dict:
    """{document name: [accepted tuple rows]} from a harvest directory."""
    out: dict = {}
    for path in sorted(Path(jsonl_dir).glob("*.jsonl")):
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                log.warning("serialize: %s carries an unreadable line — skipped",
                            path.name)
                continue
            if row.get("kind") == "tuple":
                rows.append(row)
        out[path.stem] = rows
    return out


def run(jsonl_dir: Path, out_path: Path,
        serializer: Callable[[str, list], Optional[str]]) -> dict:
    """Serialize every document's harvest; returns {name: tuple count}.

    A serializer returning None skips its document (nothing to say is a
    normal outcome, e.g. a plan without a single accepted tuple).
    """
    harvest = collect(jsonl_dir)
    parts: list = []
    counts: dict = {}
    for name, rows in harvest.items():
        rendered = serializer(name, rows)
        if rendered:
            parts.append(rendered)
            counts[name] = len(rows)
    out_path = Path(out_path)
    if not parts:
        # Refusing to write is the point. This runs unconditionally at the end
        # of a GPU job so that a run with a counted exception still yields its
        # graph, and the same unconditional call would otherwise truncate a
        # good TTL to nothing whenever the harvest directory was empty or
        # unreadable.
        raise ValueError(f"nothing to serialize from {jsonl_dir} — "
                         f"{out_path} left as it was")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    log.info("serialize: %d document(s) with tuples -> %s",
             len(counts), out_path)
    return counts
