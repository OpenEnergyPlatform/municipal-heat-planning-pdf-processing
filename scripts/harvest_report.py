#!/usr/bin/env python3
"""
harvest_report.py - The numbers a curator pulls by hand after every run.

Reads every plan of a harvest directory (one <plan>.jsonl per document, e.g.
data/extraction/corpus_m5; *.trace.jsonl and *.stamp.json are not a plan and
are skipped) and prints the distributions a corpus run is judged by: how many
tuples a plan carries, how many of them came off an image, how trustworthy
they are, why a claim was refused, what state every coordinate and every
parameter ended in, and what the run cost in tokens.

    python scripts/harvest_report.py data/extraction/corpus_m5
    python scripts/harvest_report.py <dir> --usage-db data/usage.db --json out.json

No model, no GPU, no document database. The token usage database is the one
optional SQLite read, and a missing one is reported, not an error.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe import usage                                     # noqa: E402
from docpipe.extraction import fields                          # noqa: E402
from docpipe.extraction.schema import REFUSAL_REASONS           # noqa: E402
from docpipe.extraction.trust import (LEVEL_A, LEVEL_B, LEVEL_C,  # noqa: E402
                                      PARAMETER_STATES)
from docpipe.extraction.verify import TIER_TEXT                 # noqa: E402

# The seven states a coordinate can end in (fields.py). A tuple carrying an
# eighth is a bug, not a finding, so it is called out rather than counted in.
KNOWN_AXIS_STATES = {fields.READ, fields.DERIVED, fields.SAID_UNSTATED,
                     fields.UNANSWERED, fields.EXHAUSTED, fields.UNBACKED,
                     fields.OUT_OF_SLICE}

# The three causes a request never came back for (schema.py's refusal.claim).
SENTINEL_WHY = ("unreachable", "no_answer", "cut_off")

TUPLE_FLOORS = (25, 10)          # "thin" thresholds a curator asked about
THIN_PLAN_COUNT = 30             # how many of the thinnest plans to break out
TOP_N = 15                       # families / reasons kept in the printed tables
UNFINISHED_PREVIEW = 10

_FAMILY_PATTERNS = [re.compile(p) for p in REFUSAL_REASONS]


def percentile(values: list, share: float):
    """The value at this share into the sorted list. Mirrors trace_report.py's
    helper so the two reports agree on what "p10" means."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def refusal_family(reason: str) -> str:
    """Which REFUSAL_REASONS pattern this reason matches, its quoted parts
    and numbers collapsed into the pattern that owns them. '(unmatched)' for
    a reason no published pattern names -- which must not happen, and is
    counted separately so a drift between verify.py and schema.py is visible."""
    for pattern in _FAMILY_PATTERNS:
        if pattern.match(reason or ""):
            return pattern.pattern.strip("^$")
    return "(unmatched)"


def harvest_files(directory: Path) -> list:
    """Every plan of the harvest, sorted; a trace file is not a plan."""
    return sorted(p for p in directory.glob("*.jsonl")
                  if not p.name.endswith(".trace.jsonl"))


def read_plan(path: Path):
    """Stream one plan's rows. A line that is not JSON is skipped, not fatal:
    a corpus harvest is hundreds of MB and one torn line must not lose it."""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def scan(files: list) -> dict:
    """One streamed pass over every plan into the counters this report prints.

    Nothing here holds a whole file in memory: each row is folded into a
    counter and dropped. `plan_tuples` and `plan_image` are pre-seeded with
    every file so a plan that wrote no tuple still has an entry (needed for
    "n plans" and for the thinnest-N cut).
    """
    plan_tuples = {p.stem: 0 for p in files}
    plan_image = {p.stem: 0 for p in files}
    finished: set = set()

    trust_levels: collections.Counter = collections.Counter()
    trust_reasons: collections.Counter = collections.Counter()
    summary_image_total = 0

    refusal_total = 0
    refusal_families: collections.Counter = collections.Counter()
    sentinel_why: collections.Counter = collections.Counter()

    parameter_states: dict = collections.defaultdict(collections.Counter)
    axis_states: dict = collections.defaultdict(collections.Counter)

    for path in files:
        name = path.stem
        for row in read_plan(path):
            kind = row.get("kind")
            if kind == "tuple":
                plan_tuples[name] += 1
                if row.get("tier") != TIER_TEXT:
                    plan_image[name] += 1
                for key, value in row.items():
                    if key.endswith("_state"):
                        axis_states[key[:-len("_state")]][value] += 1
            elif kind == "refusal":
                refusal_total += 1
                reason = row.get("reason")
                refusal_families[refusal_family(reason)
                                  if isinstance(reason, str) else "(unmatched)"] += 1
                claim = row.get("claim")
                if isinstance(claim, dict) and claim.get("_harvest_failed"):
                    sentinel_why[claim.get("_why")] += 1
            elif kind == "parameter_state":
                parameter_states[row.get("parameter")][row.get("state")] += 1
            elif kind == "summary":
                finished.add(name)
                for level, count in (row.get("levels") or {}).items():
                    trust_levels[level] += count
                for reason, count in (row.get("reasons") or {}).items():
                    trust_reasons[reason] += count
                summary_image_total += row.get("image_origin") or 0

    return {
        "plan_tuples": plan_tuples, "plan_image": plan_image,
        "finished": finished, "trust_levels": trust_levels,
        "trust_reasons": trust_reasons,
        "summary_image_total": summary_image_total,
        "refusal_total": refusal_total, "refusal_families": refusal_families,
        "sentinel_why": sentinel_why, "parameter_states": parameter_states,
        "axis_states": axis_states,
    }


def build_stats(files: list, scanned: dict, usage_rows: list,
                usage_db: Path) -> dict:
    """`scan`'s counters, reduced to the JSON-safe numbers this report prints.

    Kept separate from `scan` so `--json` writes exactly what the terminal
    reads from, rather than a second, independently computed rendering.
    """
    tuples = list(scanned["plan_tuples"].values())
    n = len(tuples)
    distribution = ({"n": 0} if not tuples else
                    {"n": n, "min": min(tuples), "p10": percentile(tuples, .10),
                     "median": percentile(tuples, .5),
                     "p75": percentile(tuples, .75), "max": max(tuples)})
    under = {str(cap): sum(1 for t in tuples if t < cap) for cap in TUPLE_FLOORS}

    total_tuples = sum(tuples)
    total_image = sum(scanned["plan_image"].values())
    overall_share = (total_image / total_tuples) if total_tuples else None

    # Thinnest by tuple count, ties broken by name for a stable cut.
    thinnest = sorted(scanned["plan_tuples"],
                      key=lambda p: (scanned["plan_tuples"][p], p)
                      )[:THIN_PLAN_COUNT]
    thin_tuples = sum(scanned["plan_tuples"][p] for p in thinnest)
    thin_image = sum(scanned["plan_image"][p] for p in thinnest)
    thin_share = (thin_image / thin_tuples) if thin_tuples else None

    # The tuple's own `tier` is authoritative: it is what document_summary()
    # derives `image_origin` from in the first place, and it is the only one
    # of the two available for a plan that has not finished. `image_origin`
    # is kept only as a cross-check, restricted to plans that HAVE a summary
    # -- comparing it against every plan would report a mismatch on every
    # unfinished one, which is not a finding, just a run in progress.
    finished_image = sum(scanned["plan_image"][p] for p in scanned["finished"])
    consistency = {"tuple_derived_finished": finished_image,
                   "summary_total": scanned["summary_image_total"],
                   "agree": finished_image == scanned["summary_image_total"]}

    unknown_axis_states = [
        {"axis": axis, "state": state, "count": count}
        for axis, counter in sorted(scanned["axis_states"].items())
        for state, count in counter.items() if state not in KNOWN_AXIS_STATES]

    unfinished = sorted(p.stem for p in files if p.stem not in scanned["finished"])

    if usage_rows:
        tokens = {"available": True, "path": str(usage_db),
                  "rows": [{"stage": s, "model": m, "runs": r, "requests": req,
                            "input_tokens": i, "output_tokens": o,
                            "embedding_tokens": e}
                           for s, m, r, req, i, o, e in usage_rows]}
    else:
        tokens = {"available": False, "path": str(usage_db)}

    levels = {lvl: scanned["trust_levels"].get(lvl, 0)
              for lvl in (LEVEL_A, LEVEL_B, LEVEL_C)}

    return {
        "plans": {"total": n, "distribution": distribution, "under": under},
        "image_share": {
            "overall": {"tuples": total_tuples, "image": total_image,
                        "share": overall_share},
            "thinnest": {"n": len(thinnest), "tuples": thin_tuples,
                        "image": thin_image, "share": thin_share},
            "consistency": consistency},
        "trust": {"levels": levels,
                  "top_reasons": dict(scanned["trust_reasons"].most_common(TOP_N))},
        "refusals": {
            "total": scanned["refusal_total"],
            "families": dict(scanned["refusal_families"].most_common(TOP_N)),
            "unmatched": scanned["refusal_families"].get("(unmatched)", 0),
            "sentinels": dict(scanned["sentinel_why"])},
        "parameter_states": {p: dict(c) for p, c in
                             sorted(scanned["parameter_states"].items(),
                                   key=lambda kv: kv[0] or "")},
        "coordinate_states": {a: dict(c) for a, c in
                              sorted(scanned["axis_states"].items())},
        "unknown_axis_states": unknown_axis_states,
        "unfinished_plans": {"count": len(unfinished),
                             "first": unfinished[:UNFINISHED_PREVIEW]},
        "tokens": tokens,
    }


def _fmt_share(share) -> str:
    return "n/a" if share is None else f"{100.0 * share:.1f}%"


def render_report(stats: dict) -> str:
    """The whole terminal report, as one string, so a test can assert on it
    without capturing stdout and `--json` can be checked against the exact
    numbers that were printed."""
    lines = []
    plans = stats["plans"]
    lines.append(f"{plans['total']} plan(s)")

    lines.append("\n1. Tuples per plan")
    dist = plans["distribution"]
    if dist["n"] == 0:
        lines.append("  no plans")
    else:
        lines.append("  n=%d  min %d  p10 %s  median %s  p75 %s  max %d" % (
            dist["n"], dist["min"], dist["p10"], dist["median"], dist["p75"],
            dist["max"]))
        for cap in TUPLE_FLOORS:
            lines.append("  under %2d tuples: %d plan(s)"
                         % (cap, plans["under"][str(cap)]))

    lines.append(f"\n2. Image share (tier != {TIER_TEXT!r})")
    overall = stats["image_share"]["overall"]
    lines.append("  overall: %d of %d tuples (%s)" % (
        overall["image"], overall["tuples"], _fmt_share(overall["share"])))
    thin = stats["image_share"]["thinnest"]
    lines.append("  thinnest %d plans: %d of %d tuples (%s)" % (
        thin["n"], thin["image"], thin["tuples"], _fmt_share(thin["share"])))
    consistency = stats["image_share"]["consistency"]
    lines.append("  tuple-derived (finished plans) %d vs. summary image_origin "
                 "%d: %s" % (consistency["tuple_derived_finished"],
                             consistency["summary_total"],
                             "agree" if consistency["agree"] else "DISAGREE"))

    lines.append("\n3. Trust")
    levels = stats["trust"]["levels"]
    total_levels = sum(levels.values()) or 1
    lines.append("  " + ", ".join(
        "%s=%d (%.0f%%)" % (lvl, levels[lvl], 100.0 * levels[lvl] / total_levels)
        for lvl in (LEVEL_A, LEVEL_B, LEVEL_C)))
    top_reasons = stats["trust"]["top_reasons"]
    lines.append("  top reasons: " + (
        ", ".join(f"{k}={v}" for k, v in top_reasons.items()) or "none"))

    lines.append("\n4. Refusals")
    refusals = stats["refusals"]
    lines.append(f"  total {refusals['total']}")
    lines.append("  families:")
    for family, count in refusals["families"].items():
        lines.append(f"    {family}: {count}")
    if refusals["unmatched"]:
        lines.append(f"  {refusals['unmatched']} refusal(s) matched no "
                     f"published REFUSAL_REASONS pattern")
    lines.append("  harvest-failure sentinels (claim._harvest_failed):")
    if refusals["sentinels"]:
        for why, count in refusals["sentinels"].items():
            flag = "" if why in SENTINEL_WHY else "  UNKNOWN _why"
            lines.append(f"    {why}: {count}{flag}")
    else:
        lines.append("    none")

    lines.append("\n5. Parameter states")
    if stats["parameter_states"]:
        for parameter, counts in stats["parameter_states"].items():
            ordered = [(s, counts[s]) for s in PARAMETER_STATES if counts.get(s)]
            ordered += [(s, n) for s, n in counts.items()
                       if s not in PARAMETER_STATES]
            lines.append("  %-28s %s" % (
                parameter, ", ".join(f"{s}={n}" for s, n in ordered)))
    else:
        lines.append("  no parameter_state rows")

    lines.append("\n6. Coordinate states")
    for axis, counts in stats["coordinate_states"].items():
        total = sum(counts.values()) or 1
        lines.append("  %-16s %s" % (axis, ", ".join(
            f"{s}={n} ({100.0 * n / total:.0f}%)" for s, n in counts.items())))
    if stats["unknown_axis_states"]:
        lines.append("  !!! UNKNOWN STATE(S) -- THIS MUST NEVER OCCUR !!!")
        for item in stats["unknown_axis_states"]:
            lines.append("    %s = %r  x%d"
                         % (item["axis"], item["state"], item["count"]))
    else:
        lines.append("  every state is one of the known seven")

    lines.append("\n7. Tokens")
    tokens = stats["tokens"]
    if not tokens["available"]:
        lines.append(f"  no usage database at {tokens['path']}")
    else:
        header = ("stage", "model", "runs", "requests", "input", "output",
                  "embedding")
        rows = [[r["stage"], r["model"], str(r["runs"]), str(r["requests"]),
                str(r["input_tokens"]), str(r["output_tokens"]),
                str(r["embedding_tokens"])] for r in tokens["rows"]]
        table = [list(header)] + rows
        widths = [max(len(r[i]) for r in table) for i in range(len(header))]
        for row in table:
            lines.append("  " + "  ".join(
                c.ljust(w) if i < 2 else c.rjust(w)
                for i, (c, w) in enumerate(zip(row, widths))))

    lines.append("\n8. Plans without a summary row (unfinished)")
    unfinished = stats["unfinished_plans"]
    lines.append(f"  {unfinished['count']} plan(s)")
    if unfinished["first"]:
        lines.append("  first: " + ", ".join(unfinished["first"]))

    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--usage-db", type=Path, default=None,
                        help="token usage SQLite; default: "
                             "docpipe.usage.db_path()")
    parser.add_argument("--json", type=Path, dest="json_out",
                        help="also write the same numbers as JSON here")
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"not a directory: {args.directory}", file=sys.stderr)
        return 1
    files = harvest_files(args.directory)
    if not files:
        print(f"no harvest in {args.directory}", file=sys.stderr)
        return 1

    scanned = scan(files)
    usage_db = args.usage_db or usage.db_path()
    stats = build_stats(files, scanned, usage.totals(usage_db), usage_db)

    print(render_report(stats))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwritten: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
