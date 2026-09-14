"""
vocabulary.py – This profile's half of the ontology snapshot.

The builder, the index and the two complaints every profile shares moved to
`docpipe/ontology.py` when the second profile needed them. What stays here is
what is genuinely about heat plans: which roots this profile's lists draw
from, where its ontology files live, and the one rule that is about its own
carrier axis.

    python -m profiles.kwp.vocabulary --refresh    # SOURCES, latest, then check
    python -m profiles.kwp.vocabulary --closure oeo-closure.owl --write
    python -m profiles.kwp.vocabulary --check      # spec against the pin

`--refresh` is what a run calls first. It pulls every source in SOURCES at
the version upstream currently calls its own, rebuilds vocabulary.json from
it, writes the lock under data/upstream, and then holds the spec against the
new snapshot. A spec the current ontology no longer agrees with stops the run.
The closure itself is not vendored: it is 3.9 MB, it belongs to the ontology
repository, and what this profile needs from it is a few hundred terms. The
check runs against the checked-in snapshot and needs neither the file nor
rdflib.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from docpipe import ontology, upstream                        # noqa: E402

HERE = Path(__file__).resolve().parent
VOCABULARY_PATH = HERE / "vocabulary.json"
SPEC_PATH = HERE / "extraction_spec.json"
PROFILE = HERE.name

OEO = "https://openenergyplatform.org/ontology/oeo/"
OBO = "http://purl.obolibrary.org/obo/"

# What this profile is written against, always at upstream's current version.
# MHPO has no release yet (its VERSION reads 0.0.0 and its only file is OWL
# functional syntax, which rdflib does not read), so it is declared as the
# release it will be and skipped until it exists. `reviewed` is the MHPKG
# commit kg.py was last read against: a newer schema is reported with the
# files that changed, because kg.py mirrors it by hand.
SOURCES = {
    "oeo": {"kind": "release_asset", "repo": "OpenEnergyPlatform/ontology",
            "asset": "oeo-closure.owl"},
    "mhpo": {"kind": "release_asset",
             "repo": "OpenEnergyPlatform/municipal-heat-planning-ontology",
             "asset": "mhpo.owl", "until_released": True},
    "mhpkg": {"kind": "repo_files", "repo": "OpenEnergyPlatform/oekg",
              "ref": "production",
              "reviewed": "c18860c373eefc0ff38fb7f01a6ff0a230ef1e0d",
              "files": ["mhpkg/schema/generated/mhpkg_target_scenario.shacl.ttl",
                        "mhpkg/schema/mhpkg_iri_policy.shacl.ttl",
                        "mhpkg/schema/mhpkg_target_scenario.yaml",
                        "mhpkg/schema/mint_slice.py"]},
}

# The roots each list draws from. A list is only checkable against a set, and
# a set is only honest if it is the ontology's own: "OEO_00000132 district
# heat is not an energy carrier" is a fact of the closure, not an opinion.
SETS = {
    "energy_carrier": ("class", OEO + "OEO_00020039"),
    "sector": ("class", OEO + "OEO_00000367"),
    "quantity_value": ("class", OEO + "OEO_00000350"),
    "energy_unit": ("class", OBO + "UO_0000111"),
    "mass_unit": ("class", OBO + "UO_0000002"),
    "aggregation_type": ("individual", OEO + "OEO_00140068"),
}

# Which axis of this spec answers from which of those roots.
AXIS_SETS = {"sector": "sector", "aggregation": "aggregation_type",
             "quantity": "quantity_value"}


def build(closure: Path, mhpo: Path = None) -> dict:
    spec_raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return ontology.build(closure, SETS, spec_raw,
                          extra=[mhpo] if mhpo else None, base=OEO)


def load(path: Path = VOCABULARY_PATH) -> dict:
    return ontology.load(path)


def refresh(cache: Path = upstream.CACHE) -> dict:
    """Pull SOURCES, rebuild vocabulary.json from them, write the lock.

    Returns the records. The snapshot's pin names every source's version, so
    vocabulary.json changes exactly when something upstream did.
    """
    records = upstream.fetch(SOURCES, cache)
    closure = upstream.files(records["oeo"], ".owl")[0]
    mhpo = next(iter(upstream.files(records["mhpo"])), None)
    snapshot = build(closure, mhpo)
    snapshot["pin"]["sources"] = {name: record["version"]
                                  for name, record in records.items()}
    with io.open(VOCABULARY_PATH, "w", encoding="utf-8",
                 newline="\n") as handle:
        handle.write(ontology.serialize(snapshot))
    upstream.write_lock(PROFILE, records, cache)
    return records


def shapes(cache: Path = upstream.CACHE) -> list:
    """The MHPKG shapes of the last refresh; empty if none has run."""
    return upstream.files((upstream.load_lock(PROFILE, cache) or {})
                          .get("sources", {}).get("mhpkg"), ".shacl.ttl")


def spec_terms(spec_raw: dict) -> dict:
    return ontology.spec_terms(spec_raw)


def carrier_problems(spec_raw: dict, snapshot: dict) -> list:
    """A carrier the ontology does not call a carrier, undeclared.

    This profile is allowed to offer a heat source under `carrier` -- district
    heat, geothermal, waste heat, which every plan writes in that column --
    but it has to declare it, and the serializer drops the edge for exactly
    the declared ones. Undeclared is the drift this exists to catch: a carrier
    that is not one and nobody decided.

    Stays in the profile because `outside_root` is this profile's answer to a
    question the other one does not have.
    """
    terms, sets = snapshot["terms"], snapshot["sets"]
    problems: list = []
    for parameter in spec_raw.get("parameters", []):
        carrier = (parameter.get("axes") or {}).get("carrier") or {}
        declared = set((carrier.get("kg") or {}).get("outside_root") or {})
        allowed = set(sets.get("energy_carrier") or ())
        for uri in (carrier.get("vocabulary") or {}):
            name = ontology.identifier(uri)
            if name is None or name in allowed:
                if uri in declared:
                    problems.append(
                        f"{parameter.get('uri')}.carrier: {uri} IS an energy "
                        f"carrier and does not belong in outside_root")
                continue
            if uri not in declared:
                label = (terms.get(name) or {}).get("label", "?")
                problems.append(
                    f"{parameter.get('uri')}.carrier: {uri} ({label}) is not "
                    f"an energy carrier and is not declared in kg.outside_root")
    return problems


def edges(spec_raw: dict) -> list:
    """Every triple shape this profile emits, the spec's and the writer's.

    The `kg` blocks carry most of them and `kg.py` declares the handful that
    sit behind no parameter, so the two together are the whole output and the
    pin can be asked about all of it.
    """
    from profiles.kwp import kg          # here: kg reads the spec at import
    return list(ontology.spec_edges(spec_raw)) + list(kg.EDGES)


def check(spec_raw: dict, snapshot: dict) -> list:
    """Every complaint the pinned ontology has about this spec."""
    return (ontology.term_problems(spec_raw, snapshot)
            + ontology.kind_problems(spec_raw, snapshot)
            + ontology.edge_problems(edges(spec_raw), snapshot)
            + carrier_problems(spec_raw, snapshot)
            + ontology.set_problems(spec_raw, snapshot, AXIS_SETS))


def foreign_labels(spec_raw: dict, snapshot: dict) -> list:
    return ontology.foreign_labels(spec_raw, snapshot)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure", type=Path,
                        help="the OEO closure (owl/ttl), for --write")
    parser.add_argument("--mhpo", type=Path, help="mhpo-edit.owl, for --write")
    parser.add_argument("--write", action="store_true",
                        help="rebuild vocabulary.json from those files")
    parser.add_argument("--refresh", action="store_true",
                        help="pull SOURCES at their latest version, rebuild "
                             "vocabulary.json, then check")
    parser.add_argument("--check", action="store_true",
                        help="hold the spec against the checked-in snapshot")
    args = parser.parse_args(argv)

    if args.refresh:
        before = (load()["pin"] if VOCABULARY_PATH.is_file() else {})
        try:
            records = refresh()
        except upstream.UpstreamError as exc:
            print(f"refresh failed: {exc}")
            return 2
        for name, record in records.items():
            print(upstream.summary(name, record))
        after = load()["pin"]
        if before.get("oeo_version_iri") != after.get("oeo_version_iri"):
            print(f"oeo: {before.get('oeo_version_iri')} -> "
                  f"{after.get('oeo_version_iri')}")
        args.check = True
    elif args.write:
        if not args.closure or not args.closure.is_file():
            print("--write needs --closure <file>")
            return 2
        snapshot = build(args.closure, args.mhpo)
        with io.open(VOCABULARY_PATH, "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write(ontology.serialize(snapshot))
        print(f"{VOCABULARY_PATH}: {len(snapshot['terms'])} terms, "
              f"{sum(len(v) for v in snapshot['sets'].values())} set members, "
              f"pin {snapshot['pin']['oeo_version_iri']}")
    if args.check or not args.write:
        if not VOCABULARY_PATH.is_file():
            print(f"no {VOCABULARY_PATH.name} — run --write first")
            return 1
        spec_raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        problems = check(spec_raw, load())
        for problem in problems:
            print(problem)
        seen = set()
        for where, uri, label, own in foreign_labels(spec_raw, load()):
            if uri in seen:
                continue
            seen.add(uri)
            print(f"  note {where}: offers {label!r} for {uri} {own!r}")
        print(f"{len(spec_terms(spec_raw))} identifier(s) checked, "
              f"{len(problems)} problem(s), {len(seen)} corpus label(s)")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
