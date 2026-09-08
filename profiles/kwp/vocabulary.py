"""
vocabulary.py – This profile's half of the ontology snapshot.

The builder, the index and the two complaints every profile shares moved to
`docpipe/ontology.py` when the second profile needed them. What stays here is
what is genuinely about heat plans: which roots this profile's lists draw
from, where its ontology files live, and the one rule that is about its own
carrier axis.

    python -m profiles.kwp.vocabulary --closure oeo-closure.owl \\
        --mhpo mhpo-edit.owl --write
    python -m profiles.kwp.vocabulary --check      # spec against the pin

The closure itself is not vendored: it is 3.9 MB, it belongs to the ontology
repository, and what this profile needs from it is a few hundred terms. The
check runs against the checked-in snapshot and needs neither the file nor
rdflib, which is what lets it run on the cluster.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from docpipe import ontology                                  # noqa: E402

HERE = Path(__file__).resolve().parent
VOCABULARY_PATH = HERE / "vocabulary.json"
SPEC_PATH = HERE / "extraction_spec.json"

OEO = "https://openenergyplatform.org/ontology/oeo/"
OBO = "http://purl.obolibrary.org/obo/"

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


def spec_terms(spec_raw: dict) -> dict:
    return ontology.spec_terms(spec_raw)


def carrier_problems(spec_raw: dict, snapshot: dict) -> list:
    """A carrier the ontology does not call a carrier, undeclared.

    This profile is allowed to offer a heat source under `carrier` -- district
    heat, geothermal, waste heat, which every plan writes in that column --
    but it has to declare it, and the serializer drops the edge for exactly
    the declared ones. Undeclared is the drift this exists to catch: a carrier
    that is not one and nobody decided.

    Stays in the profile because `no_edge_for` is this profile's answer to a
    question the other one does not have.
    """
    terms, sets = snapshot["terms"], snapshot["sets"]
    problems: list = []
    for parameter in spec_raw.get("parameters", []):
        carrier = (parameter.get("axes") or {}).get("carrier") or {}
        declared = set((carrier.get("kg") or {}).get("no_edge_for") or {})
        allowed = set(sets.get("energy_carrier") or ())
        for uri in (carrier.get("vocabulary") or {}):
            name = ontology.identifier(uri)
            if name is None or name in allowed:
                if uri in declared:
                    problems.append(
                        f"{parameter.get('uri')}.carrier: {uri} IS an energy "
                        f"carrier and does not belong in no_edge_for")
                continue
            if uri not in declared:
                label = (terms.get(name) or {}).get("label", "?")
                problems.append(
                    f"{parameter.get('uri')}.carrier: {uri} ({label}) is not "
                    f"an energy carrier and is not declared in kg.no_edge_for")
    return problems


def check(spec_raw: dict, snapshot: dict) -> list:
    """Every complaint the pinned ontology has about this spec."""
    return (ontology.term_problems(spec_raw, snapshot)
            + ontology.kind_problems(spec_raw, snapshot)
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
    parser.add_argument("--check", action="store_true",
                        help="hold the spec against the checked-in snapshot")
    args = parser.parse_args(argv)

    if args.write:
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
