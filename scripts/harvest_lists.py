#!/usr/bin/env python3
"""harvest_lists.py – Two lists a corpus run leaves for a curator to check.

A tuple's `unit` is the entry of the list the model read the passage as, and
`unit_raw` is what the passage prints. The lists in the ontology are known
to be incomplete, so the census of wordings is what a longer list is written
from: every wording a plan uses, beside the entry it was read as, and the
wordings that were read as no entry at all and refused for it ("kWh/m²a",
"kWp", "g/kWh"). A planning office's name is a second such census -- two
spellings of one office ("ecb energie.concept.bayern",
"energie.concept.bayern.") mint two different IRIs and nothing in the harvest
says so.

So: one row per unit as a plan actually writes it, with the entry it was
read as, and one row per organisation spelling, with the IRI key it
collapses onto. Neither is a filter that drops anything -- both are a
census, for a person to read once per run.

    python scripts/harvest_lists.py data/extraction/corpus_m5
    python scripts/harvest_lists.py <dir> --out-dir out --spec profiles/kwp/extraction_spec.json

No model, no database, no GPU: everything it prints was written by the run.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import csv
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe.extraction.spec import load as load_spec       # noqa: E402
from docpipe.profile import active_profile                  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = ROOT / "profiles" / "kwp" / "extraction_spec.json"

UNIT_COLUMNS = ("parameter", "unit_as_written", "unit_chosen", "chosen_factor",
                "listed", "tuples", "refusals", "plans",
                "example_plan", "example_page", "example_quote")
ORG_COLUMNS = ("name_as_written", "iri_key", "names_sharing_key",
               "related_names", "tuples", "plans", "plan_list")

# A cell has to fit a spreadsheet; the harvest keeps the whole quote.
CELL = 300


def _cell(text) -> str:
    flat = " ".join(str(text if text is not None else "").split())
    return flat if len(flat) <= CELL else flat[:CELL].rstrip() + " …"


def default_spec_path() -> Path:
    """The active profile's extraction_spec.json, else kwp's."""
    profile = active_profile()
    return (profile.package_dir / "extraction_spec.json") if profile else DEFAULT_SPEC


def organisation_normaliser(spec_path: Path):
    """The organisation-key function of the spec's own profile's `kg.py`.

    Imported, not reimplemented: `profiles/<name>/kg.py` is what mints the
    organisation IRI (`mint("organisation", normalise(name))`), so this is
    the one function that decides which spellings share a node. It is a pure
    string function with no rdflib or database import behind it.
    """
    name = spec_path.resolve().parent.name
    try:
        module = importlib.import_module(f"profiles.{name}.kg")
    except ImportError:
        return None
    fn = getattr(module, "normalise", None)
    return fn if callable(fn) else None


def harvest_files(directory: Path) -> list:
    """One file per plan, newest-glob order excluded: sorted for stable output."""
    return sorted(p for p in directory.glob("*.jsonl")
                  if not p.name.endswith(".trace.jsonl"))


def read_rows(path: Path) -> list:
    """The lines of one harvest file that parse as JSON objects. Skips the rest."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def unit_rows(files: list, spec) -> list:
    """One row per (parameter, unit as written, unit chosen), a census only.

    Counts a refusal too when its claim names a unit: a unit no list holds is
    still a unit the plans use, and it is the row the list is grown from.
    `listed` says whether the wording is itself an entry; a wording that is
    not was read onto its entry by the model, which is what `unit_raw` is
    kept for.
    """
    numeric = {p.uri: p for p in spec.parameters if p.is_numeric}
    groups: dict = {}
    for path in files:
        plan = path.stem
        for row in read_rows(path):
            kind = row.get("kind")
            if kind == "tuple":
                parameter = numeric.get(row.get("parameter"))
                if parameter is None:
                    continue
                as_written = row.get("unit_raw") or row.get("unit") or ""
                chosen = row.get("unit") or ""
                is_tuple = True
                page = (row.get("provenance") or {}).get("page")
                quote = row.get("quote") or ""
            elif kind == "refusal":
                parameter = numeric.get(row.get("parameter"))
                claim = row.get("claim")
                if parameter is None or not isinstance(claim, dict):
                    continue
                as_written = claim.get("unit_raw") or claim.get("unit") or ""
                if not as_written:
                    continue  # this claim names no unit at all
                chosen = ""
                is_tuple = False
                page = None
                quote = claim.get("quote") or ""
            else:
                continue

            key = (parameter.uri, as_written, chosen)
            acc = groups.setdefault(key, {
                "parameter": parameter, "as_written": as_written,
                "chosen": chosen, "tuples": 0, "refusals": 0,
                "plans": set(), "example": None})
            acc["tuples" if is_tuple else "refusals"] += 1
            acc["plans"].add(plan)
            if acc["example"] is None:
                acc["example"] = (plan, page, quote)

    out = []
    for acc in groups.values():
        parameter = acc["parameter"]
        chosen_factor = parameter.unit_factor(acc["chosen"])
        plan, page, quote = acc["example"]
        out.append({
            "parameter": parameter.uri,
            "unit_as_written": acc["as_written"],
            "unit_chosen": acc["chosen"],
            "chosen_factor": "" if chosen_factor is None else chosen_factor,
            "listed": "yes" if acc["as_written"] in parameter.units_accepted
                      else "no",
            "tuples": acc["tuples"],
            "refusals": acc["refusals"],
            "plans": len(acc["plans"]),
            "example_plan": plan,
            "example_page": page if page is not None else "",
            "example_quote": _cell(quote),
        })
    # The wordings no list holds first -- those are the rows a longer list is
    # written from -- then by how often a wording turns up.
    out.sort(key=lambda r: (bool(r["unit_chosen"]),
                            -(r["tuples"] + r["refusals"])))
    return out


def organisation_parameters(spec) -> list:
    """The spec's parameters that mint an organisation node, by `kg.node`."""
    return [p for p in spec.parameters if (p.kg or {}).get("node") == "organisation"]


def organisation_rows(files: list, spec, normalise=None) -> list:
    """One row per organisation name as a plan writes it.

    `normalise` is the profile's own `kg.py` function; two names share
    `iri_key` exactly when the profile's serializer would mint them the same
    node. `related_names` catches the case that does not: two keys that do
    not match but one contains the other, which is a spelling the profile
    still mints as two organisations.
    """
    org_params = {p.uri for p in organisation_parameters(spec)}
    if not org_params:
        return []
    keyer = normalise or (lambda s: " ".join(str(s).split()).casefold())

    groups: dict = {}
    for path in files:
        plan = path.stem
        for row in read_rows(path):
            if row.get("kind") != "tuple" or row.get("parameter") not in org_params:
                continue
            name = row.get("value_raw") or row.get("value")
            if not isinstance(name, str) or not name.strip():
                continue
            acc = groups.setdefault(name, {"tuples": 0, "plans": set()})
            acc["tuples"] += 1
            acc["plans"].add(plan)
    if not groups:
        return []

    keyed = {name: keyer(name) for name in groups}
    by_key: dict = collections.defaultdict(list)
    for name, key in keyed.items():
        by_key[key].append(name)

    # Which OTHER keys relate to this one by containment. Quadratic in the
    # number of distinct keys, which the docstring already promises is at
    # most a few hundred.
    unique_keys = [k for k in sorted(set(keyed.values())) if k]
    related_keys: dict = collections.defaultdict(set)
    for i, k1 in enumerate(unique_keys):
        for k2 in unique_keys[i + 1:]:
            if k1 in k2 or k2 in k1:
                related_keys[k1].add(k2)
                related_keys[k2].add(k1)

    out = []
    for name, acc in groups.items():
        key = keyed[name]
        related_names = sorted(
            n for other in related_keys.get(key, ()) for n in by_key[other])
        out.append({
            "name_as_written": name,
            "iri_key": key,
            "names_sharing_key": len(by_key[key]),
            "related_names": "; ".join(related_names),
            "tuples": acc["tuples"],
            "plans": len(acc["plans"]),
            "plan_list": "; ".join(sorted(acc["plans"])),
        })
    out.sort(key=lambda r: (r["iri_key"], r["name_as_written"]))
    return out


def _write_csv(path: Path, columns: tuple, rows: list) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path,
                        help="harvest dir, one <plan>.jsonl per plan")
    parser.add_argument("--out-dir", type=Path, default=Path("."),
                        help="where units.csv and organisations.csv are "
                             "written (default: the current directory)")
    parser.add_argument("--spec", type=Path, default=None,
                        help="extraction_spec.json to read parameters from "
                             "(default: the active profile's, "
                             "$DOCPIPE_PROFILE, else profiles/kwp/"
                             "extraction_spec.json)")
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"not a directory: {args.directory}", file=sys.stderr)
        return 1
    files = harvest_files(args.directory)
    if not files:
        print(f"no harvest in {args.directory}", file=sys.stderr)
        return 1

    spec_path = args.spec or default_spec_path()
    if not spec_path.is_file():
        print(f"no spec: {spec_path}", file=sys.stderr)
        return 1
    spec = load_spec(spec_path)

    normalise = organisation_normaliser(spec_path)
    if normalise is None and organisation_parameters(spec):
        print(f"warning: profiles/{spec_path.resolve().parent.name}/kg.py "
              f"has no normalise(); iri_key falls back to a plain casefold",
              file=sys.stderr)

    units = unit_rows(files, spec)
    organisations = organisation_rows(files, spec, normalise)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    units_path = args.out_dir / "units.csv"
    org_path = args.out_dir / "organisations.csv"
    _write_csv(units_path, UNIT_COLUMNS, units)
    _write_csv(org_path, ORG_COLUMNS, organisations)

    unlisted = sum(1 for r in units if not r["unit_chosen"])
    print(f"{len(files)} plan(s): {len(units)} unit row(s) "
          f"({unlisted} read as no entry) -> {units_path}")
    print(f"{len(organisations)} organisation spelling(s) -> {org_path}")

    print("\nTop unit rows (no entry first, then most-used):")
    for row in units[:10]:
        print("  %-20s %-16r -> %-12r listed=%-3s tuples=%-4d refusals=%d"
              % (row["parameter"], row["unit_as_written"], row["unit_chosen"],
                 row["listed"], row["tuples"], row["refusals"]))

    print("\nTop organisation rows (by iri_key):")
    for row in organisations[:10]:
        print("  %-45s key=%-30r sharing=%-3d tuples=%d"
              % (row["name_as_written"], row["iri_key"],
                 row["names_sharing_key"], row["tuples"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
