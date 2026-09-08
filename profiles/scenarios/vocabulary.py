"""
vocabulary.py – This profile's half of the ontology snapshot.

The builder lives in `docpipe/ontology.py`. What is here is what is about AR6
scenario publications: which roots this profile's one static list draws from,
and the 249 study regions, which come from the OEKG rather than from an
ontology release and are therefore pinned differently.

    python -m profiles.scenarios.vocabulary --closure oeo-closure.owl --write
    python -m profiles.scenarios.vocabulary --check

Why this profile needed it more than the other one. Its spec names 32 ontology
identifiers and, before this, exactly zero of them were checked against
anything: the old walk looked in three named places, and this profile writes
its terms as full IRIs in vocabulary KEYS and as predicates inside `kg`
blocks. Most of them ARE predicates, so an index over classes and individuals
would have called every one of them missing.

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
REGIONS_PATH = HERE / "regions.json"

OEO = "https://openenergyplatform.org/ontology/oeo/"

# The one static list this profile offers. `scenario_label` and
# `scenario_region` are per document, so they draw from no corpus-wide root.
SETS = {
    "scenario": ("class", OEO + "OEO_00000364"),
}

# `scenario_type` answers from the scenario tree and nothing else.
AXIS_SETS: dict = {}


def build(closure: Path) -> dict:
    spec_raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    snapshot = ontology.build(closure, SETS, spec_raw, base=OEO)
    # The regions are not in any ontology release: they are individuals the
    # OEKG mints, read off the live graph. So they are pinned by their own
    # count and digest rather than by a version IRI, and the check below can
    # still say "the spec offers a region the snapshot does not know".
    regions = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    snapshot["regions"] = sorted(regions)
    snapshot["pin"]["regions_file"] = REGIONS_PATH.name
    snapshot["pin"]["regions_count"] = len(regions)
    return snapshot


def load(path: Path = VOCABULARY_PATH) -> dict:
    return ontology.load(path)


def spec_terms(spec_raw: dict) -> dict:
    return ontology.spec_terms(spec_raw)


def region_problems(snapshot: dict, regions=None) -> list:
    """The regions file against the snapshot it was pinned with.

    `document_regions` filters this list per document, so a region that
    silently disappears from it stops being offered for every publication that
    names it, and nothing else would say so.

    `regions` is the file's content and is read from disk when not given; a
    caller passes it so the comparison can be exercised without editing the
    checked-in file.
    """
    if regions is None:
        if not REGIONS_PATH.is_file():
            return [f"{REGIONS_PATH.name} is missing"]
        regions = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    pinned = set(snapshot.get("regions") or ())
    problems = []
    for iri in sorted(pinned - set(regions)):
        problems.append(f"regions: {iri} was pinned and is gone")
    for iri in sorted(set(regions) - pinned):
        problems.append(f"regions: {iri} is new since the pin")
    return problems


def check(spec_raw: dict, snapshot: dict) -> list:
    """Every complaint the pinned ontology has about this spec."""
    return (ontology.term_problems(spec_raw, snapshot)
            + ontology.kind_problems(spec_raw, snapshot)
            + ontology.set_problems(spec_raw, snapshot, AXIS_SETS)
            + region_problems(snapshot))


def foreign_labels(spec_raw: dict, snapshot: dict) -> list:
    return ontology.foreign_labels(spec_raw, snapshot)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure", type=Path,
                        help="the OEO closure (owl/ttl), for --write")
    parser.add_argument("--write", action="store_true",
                        help="rebuild vocabulary.json from that file")
    parser.add_argument("--check", action="store_true",
                        help="hold the spec against the checked-in snapshot")
    args = parser.parse_args(argv)

    if args.write:
        if not args.closure or not args.closure.is_file():
            print("--write needs --closure <file>")
            return 2
        snapshot = build(args.closure)
        with io.open(VOCABULARY_PATH, "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write(ontology.serialize(snapshot))
        print(f"{VOCABULARY_PATH}: {len(snapshot['terms'])} terms, "
              f"{len(snapshot['regions'])} regions, "
              f"pin {snapshot['pin']['oeo_version_iri']}")
    if args.check or not args.write:
        if not VOCABULARY_PATH.is_file():
            print(f"no {VOCABULARY_PATH.name} — run --write first")
            return 1
        spec_raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        snapshot = load()
        problems = check(spec_raw, snapshot)
        for problem in problems:
            print(problem)
        for family, wheres in sorted(
                ontology.uncovered(spec_raw, snapshot).items()):
            print(f"  note: {len(wheres)} {family}_* identifier(s) are in no "
                  f"file this snapshot covers")
        seen = set()
        for where, uri, label, own in foreign_labels(spec_raw, snapshot):
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
