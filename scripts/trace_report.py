#!/usr/bin/env python3
"""
trace_report.py – The four questions a run must be able to answer afterwards.

Reads the JSONL the harvest writes under <out>/trace and prints distributions,
not totals. Every setting this stage has is a cut through one of these, and a
cut can only be defended against the distribution it cuts.

    python scripts/trace_report.py data/extraction/corpus/trace
    python scripts/trace_report.py data/extraction/corpus/trace --top 20

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path


def percentile(values: list, share: float):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def spread(name: str, values: list, unit: str = "") -> str:
    if not values:
        return f"  {name:<28} keine"
    return ("  %-28s n=%-7d Median %s%s  90%% %s%s  99%% %s%s  max %s%s"
            % (name, len(values), percentile(values, .5), unit,
               percentile(values, .9), unit, percentile(values, .99), unit,
               max(values), unit))


def read(directory: Path):
    for path in sorted(directory.glob("*.trace.jsonl")):
        for line in path.open(encoding="utf-8"):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        print(f"kein Verzeichnis: {args.directory}", file=sys.stderr)
        return 1

    planned = collections.Counter()
    rank_of_source = {}
    rows_per_rank = collections.Counter()
    productive = collections.Counter()
    windows = collections.defaultdict(list)
    window_of_read = collections.defaultdict(list)
    stage_hits = collections.Counter()
    states = collections.Counter()
    per_axis = collections.defaultdict(collections.Counter)
    drops = collections.Counter()
    errors = collections.Counter()
    latency = collections.defaultdict(list)
    tokens = collections.defaultdict(list)
    documents = set()

    for rec in read(args.directory):
        kind = rec.get("t")
        documents.add(rec.get("doc"))
        if kind == "plan":
            planned[rec.get("origin")] += 1
            rank_of_source[(rec["doc"], rec.get("kind"), rec.get("owner"))] = \
                rec.get("rank")
        elif kind == "rows":
            latency["rows"].append(rec.get("ms") or 0)
            for value in ("prompt_tokens", "completion_tokens"):
                if isinstance(rec.get(value), int):
                    tokens[value].append(rec[value])
            for rank, owner in zip(rec.get("ranks") or [],
                                   rec.get("sources") or []):
                rows_per_rank[rank] += rec.get("rows") or 0
        elif kind == "field":
            latency["field"].append(rec.get("ms") or 0)
            stage_hits[rec.get("stage")] += rec.get("filled") or 0
            if rec.get("filled"):
                window_of_read[rec.get("slot")].append(rec.get("window") or 0)
        elif kind == "sweep":
            windows[rec.get("slot")].append(rec.get("windows") or 0)
        elif kind == "drop":
            drops[rec.get("why")] += 1
        elif kind == "error":
            errors[(rec.get("where"), rec.get("kind"))] += 1
        elif kind == "coord":
            prov = (rec["doc"], rec.get("kind"), rec.get("owner"))
            productive[rank_of_source.get(prov)] += 1
            for axis, state in (rec.get("states") or {}).items():
                states[state] += 1
                per_axis[axis][state] += 1

    print(f"{len(documents)} Dokument(e), {sum(planned.values())} geplante Quelle(n)")
    for origin, count in planned.most_common():
        print(f"  {origin or '-':<12} {count}")

    print("\n1. Bei welchem Rang wird ein Wert gefunden")
    ranks = [r for r, n in productive.items() if r is not None
             for _ in range(n)]
    unranked = productive.get(None, 0)
    print(spread("Rang der ergiebigen Quelle", ranks))
    if ranks:
        total = len(ranks) + unranked
        for cap in (10, 20, 30, 50, 75, 100, 150):
            keep = sum(1 for r in ranks if r < cap)
            print("    Deckel %4d -> %5.1f%% der Werte" % (cap, 100.0 * keep / total))
    if unranked:
        print(f"    ohne Rang (nur ueber die Struktur geplant): {unranked}")

    print("\n2. In welchem Fenster schliesst eine Koordinate")
    for axis in sorted(window_of_read):
        print(spread(axis, window_of_read[axis]))
    print("  Fenster je Sweep insgesamt:")
    for axis in sorted(windows):
        print(spread("  " + axis, windows[axis]))
    if stage_hits:
        print("  gefuellt je Stufe: " + ", ".join(
            f"{k}={v}" for k, v in stage_hits.most_common()))

    print("\n3. Zustaende und Fehler")
    total_states = sum(states.values()) or 1
    for state, count in states.most_common():
        print("  %-12s %8d  %5.1f%%" % (state, count, 100.0 * count / total_states))
    for axis in sorted(per_axis):
        counts = per_axis[axis]
        n = sum(counts.values()) or 1
        print("    %-14s %5.1f%% read  %s"
              % (axis, 100.0 * counts.get("read", 0) / n, dict(counts)))
    if drops:
        print("  verworfen: " + ", ".join(f"{k}={v}" for k, v in drops.most_common()))
    if errors:
        print("  Fehler:")
        for (where, why), count in errors.most_common(args.top):
            print(f"    {where}/{why}: {count}")

    print("\n4. Was hat es gekostet")
    for name, values in sorted(latency.items()):
        print(spread(name + " (ms)", values))
    for name, values in sorted(tokens.items()):
        print(spread(name, values))
    return 0


if __name__ == "__main__":
    sys.exit(main())
