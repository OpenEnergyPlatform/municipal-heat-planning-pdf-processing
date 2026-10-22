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
from docpipe.profile import load_profile                      # noqa: E402

HERE = Path(__file__).resolve().parent
VOCABULARY_PATH = HERE / "vocabulary.json"
SPEC_PATH = HERE / "extraction_spec.json"
PROFILE = HERE.name

OEO = "https://openenergyplatform.org/ontology/oeo/"
OBO = "http://purl.obolibrary.org/obo/"

# What this profile is written against, always at upstream's current version.
# MHPO attaches nothing to its releases: its mhpo.owl is in the repository,
# and is read at the tag of the latest release. The MHPKG schema is read at
# its branch's head and kept as mhpkg_schema.yaml (mhpkg.py), which kg.py
# takes its terms from; `reviewed` only names the commit the report of
# changed files starts from.
SOURCES = {
    "oeo": {"kind": "release_asset", "repo": "OpenEnergyPlatform/ontology",
            "asset": "oeo-closure.owl"},
    "mhpo": {"kind": "release_file",
             "repo": "OpenEnergyPlatform/municipal-heat-planning-ontology",
             "file": "mhpo.owl"},
    "mhpkg": {"kind": "repo_files", "repo": "OpenEnergyPlatform/oekg",
              "ref": "production",
              "reviewed": "c18860c373eefc0ff38fb7f01a6ff0a230ef1e0d",
              "files": ["mhpkg/schema/generated/mhpkg_target_scenario.shacl.ttl",
                        "mhpkg/schema/mhpkg_iri_policy.shacl.ttl",
                        "mhpkg/schema/mhpkg_context.shacl.ttl",
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
    "heat_generation_technology": ("class", OEO + "OEO_00020308"),
}

# Which axis of this spec answers from which of those roots.
AXIS_SETS = {"sector": "sector", "aggregation": "aggregation_type",
             "quantity": "quantity_value",
             "technology": "heat_generation_technology"}


def build(closure: Path, mhpo: Path = None) -> dict:
    """The snapshot: this profile's lists, every term its graph writes --
    the schema's included, so `mhpkg.missing_terms` can say which of them
    the pin lacks -- and for every value class of the schema the classes
    under it (`mhpkg:<class>`), which is what decides that a CO2-equivalent
    value IS a greenhouse gas emission value without a reasoner."""
    from profiles.kwp import mhpkg
    spec_raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    shape = mhpkg.load()
    sets = dict(SETS)
    for name in value_classes(shape):
        prefix, _, local = shape.cls(name).partition(":")
        if prefix == "oeo":
            sets[f"mhpkg:{name}"] = ("class", OEO + local)
    named = {curie.partition(":")[2] for curie in shape.curies()
             if curie.partition(":")[0] in ("oeo", "mhpo")}
    return ontology.build(
        closure, sets, spec_raw, extra=[mhpo] if mhpo else None, base=OEO,
        also=tuple(sorted(set(edge_terms(spec_raw)) | named)),
        language=load_profile(PROFILE).require("extraction",
                                               "ALT_LABEL_LANGUAGE"))


def value_classes(shape) -> list:
    """The schema classes a plan part holds values of."""
    from profiles.kwp import kg
    out = []
    for container in kg.CONTAINERS:
        for name in shape.value_classes(container, kg.CONTAINER_SLOT):
            if name not in out:
                out.append(name)
    return out


def load(path: Path = VOCABULARY_PATH) -> dict:
    return ontology.load(path)


def refresh(cache: Path = upstream.CACHE) -> dict:
    """Pull SOURCES, rebuild vocabulary.json from them, write the lock.

    Returns the records. The snapshot's pin names every source's version, so
    vocabulary.json changes exactly when something upstream did.
    """
    records = upstream.fetch(SOURCES, cache)
    from profiles.kwp import mhpkg
    schema = [path for path in upstream.files(records["mhpkg"], ".yaml")
              if Path(path).as_posix().endswith(mhpkg.SCHEMA_FILE)]
    if not schema:
        raise upstream.UpstreamError(f"{mhpkg.SCHEMA_FILE} not in the "
                                     f"MHPKG files pulled")
    text = Path(schema[0]).read_text(encoding="utf-8")
    with io.open(mhpkg.SCHEMA_PATH, "w", encoding="utf-8",
                 newline="\n") as handle:
        handle.write(text)
    mhpkg._SHAPE.clear()
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
    from profiles.kwp import kg, mhpkg   # here: kg reads the spec at import
    return (list(ontology.spec_edges(mhpkg.resolve(spec_raw, mhpkg.load())))
            + list(kg.EDGES))


def schema_predicates() -> set:
    """The predicates the MHPKG schema prescribes, bare."""
    from profiles.kwp import mhpkg
    shape = mhpkg.load()
    return {ontology.identifier(shape.slot(name).partition(":")[2])
            for name in shape.slots
            if (shape.slots.get(name) or {}).get("slot_uri")} - {None}


def schema_notes(spec_raw: dict, snapshot: dict) -> list:
    """What the pin says against the schema's own terms: the edges it
    prescribes that the ontology's domains or ranges contradict, and the
    terms the pin does not have yet. The schema is a draft with open term
    requests; these are reported with every run and stop none."""
    from profiles.kwp import mhpkg
    prescribed = schema_predicates()
    notes = ontology.edge_problems(
        [e for e in edges(spec_raw)
         if ontology.identifier(e.get("predicate")) in prescribed], snapshot)
    notes += [f"MHPKG names {curie}, which the pinned ontology does not have"
              for curie in mhpkg.missing_terms(mhpkg.load(),
                                               snapshot["terms"])]
    return notes


def edge_terms(spec_raw: dict) -> tuple:
    """Every identifier those triple shapes name, for the snapshot to carry."""
    named = {ontology.identifier(edge.get(part))
             for edge in edges(spec_raw)
             for part in ("subject", "predicate", "object") if edge.get(part)}
    return tuple(sorted(named - {None}))


def check(spec_raw: dict, snapshot: dict) -> list:
    """Every complaint the pinned ontology has about this spec; about the
    terms the MHPKG schema prescribes, `schema_notes`."""
    # The spec as written: a slot it names is the schema's term and is held
    # to the pin in `schema_notes`, not here.
    prescribed = schema_predicates()
    return (ontology.term_problems(spec_raw, snapshot)
            + ontology.kind_problems(spec_raw, snapshot)
            + ontology.edge_problems(
                [e for e in edges(spec_raw)
                 if ontology.identifier(e.get("predicate")) not in prescribed],
                snapshot)
            + carrier_problems(spec_raw, snapshot)
            + ontology.set_problems(spec_raw, snapshot, AXIS_SETS))


def foreign_labels(spec_raw: dict, snapshot: dict) -> list:
    return ontology.foreign_labels(spec_raw, snapshot)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure", type=Path,
                        help="the OEO closure (owl/ttl), for --write")
    parser.add_argument("--mhpo", type=Path, help="mhpo.owl, for --write")
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
        for note in schema_notes(spec_raw, load()):
            print(f"  note mhpkg: {note}")
        seen = set()
        for where, uri, label, own in foreign_labels(spec_raw, load()):
            if uri in seen:
                continue
            seen.add(uri)
            print(f"  note {where}: offers {label!r} for {uri} {own!r}")
        # What the pin defines differently from the spec, or defines where
        # the spec says nothing. A note and never a problem: the model reads
        # the spec's words, and they change only when somebody edits them.
        defined = ontology.definition_differences(spec_raw, load())
        for difference in defined:
            print(ontology.definition_note(difference))
        print(f"{len(spec_terms(spec_raw))} identifier(s) checked, "
              f"{len(problems)} problem(s), {len(seen)} corpus label(s), "
              f"{len(defined)} definition(s) that differ from the pin")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
