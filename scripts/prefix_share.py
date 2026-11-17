#!/usr/bin/env python3
"""
prefix_share.py - How many prompt tokens the server served from its prefix
cache, per request kind (owner decision 2026-11-17, from the literature on
requests that share their beginning: BatchLLM, SGLang; rule `example_place`).

Reads the traces of a run (plain or .gz, as `stats.from_traces` does) and
prints, per request kind and step: requests, prompt tokens, cached tokens and
the share cached. A trace written before `cached_tokens` was traced says so;
with --usage-db the usage database's totals per stage and model are printed
instead, which are the run's totals and not per kind. No model, no network.

    python scripts/prefix_share.py data/extraction/corpus/trace
    python scripts/prefix_share.py trace --usage-db usage.sqlite

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe import usage  # noqa: E402
from docpipe.extraction import trace  # noqa: E402

ASK = "_ask"


def shares(trace_dirs) -> tuple:
    """({(kind, step): [requests, prompt tokens, cached tokens]}, requests
    that carry no `cached_tokens`). A request is an event `<kind>_ask` that
    reports prompt tokens and was sent (not an answer given again)."""
    rows: dict = collections.defaultdict(lambda: [0, 0, 0])
    unreported = 0
    for directory in trace_dirs:
        for path in trace.files(directory):
            for event in trace.lines(path):
                kind = str(event.get("t"))
                if not kind.endswith(ASK) or len(kind) == len(ASK) \
                        or event.get("once") is True:
                    continue
                prompt = event.get("prompt_tokens")
                if not isinstance(prompt, int):
                    continue
                cached = event.get("cached_tokens")
                if not isinstance(cached, int):
                    unreported += 1
                    cached = 0
                row = rows[(kind[:-len(ASK)], str(event.get("step") or ""))]
                row[0] += 1
                row[1] += prompt
                row[2] += cached
    return dict(rows), unreported


def report(rows: dict, unreported: int) -> str:
    lines = [f"{'kind':<16}{'step':<20}{'requests':>10}"
             f"{'prompt tokens':>15}{'cached tokens':>15}{'share':>8}"]
    total = [0, 0, 0]
    for (kind, step), (count, prompt, cached) in sorted(rows.items()):
        lines.append(f"{kind:<16}{step:<20}{count:>10}{prompt:>15}"
                     f"{cached:>15}{cached / prompt if prompt else 0:>8.1%}")
        total = [a + b for a, b in zip(total, (count, prompt, cached))]
    lines.append(f"{'all':<36}{total[0]:>10}{total[1]:>15}{total[2]:>15}"
                 f"{total[2] / total[1] if total[1] else 0:>8.1%}")
    if unreported:
        lines.append(f"{unreported} requests carry no cached_tokens (a trace "
                     f"from before it was traced); they count as 0 cached.")
    return "\n".join(lines)


def database(path: Path) -> str:
    """The usage database's totals per stage and model."""
    lines = [f"{'stage':<16}{'model':<32}{'requests':>10}"
             f"{'input tokens':>14}{'cached tokens':>15}{'share':>8}"]
    for (stage, model), one in usage.sums(path).items():
        lines.append(f"{stage:<16}{model:<32}{one.requests:>10}"
                     f"{one.input_tokens:>14}{one.cached_tokens:>15}"
                     f"{one.cached_tokens / one.input_tokens if one.input_tokens else 0:>8.1%}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Report, per request kind, how many prompt tokens the "
                    "server served from its prefix cache.")
    parser.add_argument("traces", nargs="*", type=Path,
                        help="trace directories of the run")
    parser.add_argument("--usage-db", type=Path,
                        help="usage database: print its totals per stage "
                             "and model, for traces without cached_tokens")
    args = parser.parse_args(argv)
    rows, unreported = shares(args.traces)
    if rows:
        print(report(rows, unreported))
    if args.usage_db is not None and (not rows or unreported):
        print(("\nUsage database totals (per stage and model, not per "
               "kind):\n" if rows else "No request in the traces.\n"
               "Usage database totals (per stage and model):\n")
              + database(args.usage_db))
    elif not rows:
        print("No request with prompt tokens in the traces.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
