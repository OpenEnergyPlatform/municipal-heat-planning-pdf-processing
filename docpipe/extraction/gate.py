"""
gate.py: Whether the graph of a run can still be written, before the run.

    python -m docpipe.extraction.gate HARVEST DB TTL --against REPORT.shacl.json

A corpus run spends its GPU hours on a harvest that ends in a graph. The
graph is written last, and every reason it could not be (a serializer that
no longer builds against the shapes the run just pulled, a Turtle no parser
reads, a validator that does not run, a kind of violation the shapes newly
ask for) showed only then. This writes the graph of the harvest that is
already there, with the code and the shapes the run will use, and exits
non-zero for any of those, so a job stops before it starts its model.

Violations are compared by kind (constraint, path, collection: the keys of
`<ttl>.shacl.json`) with the report of the graph the last run wrote. Counts
move with the harvest and are not compared; a kind that was not there
before is the shapes asking for something the serializer does not write.
Without an earlier report there is nothing to compare, and the gate says
so and stays open.

Exit 0: written, parsed, validated, no new kind. Exit 3: shut, the reasons
are in the log.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SHUT = 3


def _serializer(profile, db: Path):
    factory = profile.component("kg", "make_serializer")
    if factory is not None:
        return factory(db)
    from . import graph
    spec_path = profile.component("extraction", "SPEC_PATH")
    if spec_path is None:
        raise ValueError(f"profile {profile.name!r} has no extraction spec "
                         f"and no kg.make_serializer")
    return graph.make_serializer(json.loads(
        Path(spec_path).read_text(encoding="utf-8")))


def new_kinds(report: dict, against: dict) -> list:
    """The kinds of violation in *report* that *against* does not have."""
    return sorted(set(report.get("kinds") or {})
                  - set(against.get("kinds") or {}))


def check(harvest: Path, db: Path, out: Path,
          against: Optional[Path] = None, profile=None) -> list:
    """Why the graph of *harvest* cannot be written as the run would write
    it; empty when it can."""
    from docpipe.profile import load_profile
    from .serialize import run as serialize_run, validate
    profile = profile or load_profile()
    try:
        serializer = _serializer(profile, db)
    except Exception as exc:          # what building it raises is the reason
        return [f"the serializer does not build: {exc}"]
    try:
        counts = serialize_run(harvest, out, serializer)
    except Exception as exc:
        return [f"the graph is not written: {exc}"]
    if not counts:
        return [f"no document of {harvest} reaches the graph"]
    try:
        from rdflib import Graph
        Graph().parse(str(out), format="turtle")
    except Exception as exc:
        return [f"{out} is no Turtle a parser reads: {exc}"]
    shapes = profile.component("vocabulary", "shapes")
    paths = [p for p in (shapes() if shapes else []) if Path(p).is_file()]
    if not paths:
        return [f"no shapes from a refresh to hold the graph against "
                f"(python -m profiles.{profile.name}.vocabulary --refresh)"]
    try:
        validate(out, paths)
    except Exception as exc:
        return [f"the validator does not run: {exc}"]
    written = json.loads(out.with_name(out.name + ".shacl.json")
                         .read_text(encoding="utf-8"))
    if against is None or not Path(against).is_file():
        log.warning("gate: no earlier report to compare with (%s), so no "
                    "kind of violation counts as new", against)
        return []
    fresh = new_kinds(written, json.loads(
        Path(against).read_text(encoding="utf-8")))
    return [f"a kind of violation the last graph did not have: {kind}"
            for kind in fresh]


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("harvest", type=Path, help="the harvest directory")
    parser.add_argument("db", type=Path, help="the corpus database")
    parser.add_argument("ttl", type=Path, help="where the trial graph goes")
    parser.add_argument("--against", type=Path, default=None,
                        metavar="REPORT",
                        help="the .shacl.json of the graph the last run wrote")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    reasons = check(args.harvest, args.db, args.ttl, args.against)
    for reason in reasons:
        log.error("gate: %s", reason)
    if reasons:
        print(f"RESULT|graph_gate=shut|reasons={len(reasons)}")
        return SHUT
    print("RESULT|graph_gate=open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
