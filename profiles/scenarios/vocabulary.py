"""
vocabulary.py – This profile's half of the ontology snapshot.

The builder lives in `docpipe/ontology.py`. What is here is what is about AR6
scenario publications: which roots this profile's one static list draws from,
and the 249 study regions, which come from the OEKG rather than from an
ontology release and are therefore pinned differently.

    python -m profiles.scenarios.vocabulary --refresh   # needs OEP_API_TOKEN
    python -m profiles.scenarios.vocabulary --closure oeo-closure.owl --write
    python -m profiles.scenarios.vocabulary --check

`--refresh` is what a run calls first: the OEO closure at its latest release,
the study regions live from the OEKG, the OEKG shapes at the head of their
branch and the groups of countries a scenario may cover (IIASA, UN M49),
then the check. Without
OEP_API_TOKEN in the environment it stops, because the regions are offered to
the model and a list nobody pulled is not the OEKG's current one.

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
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from docpipe import ontology, upstream                        # noqa: E402
from docpipe.profile import load_profile                      # noqa: E402

HERE = Path(__file__).resolve().parent
VOCABULARY_PATH = HERE / "vocabulary.json"
SPEC_PATH = HERE / "extraction_spec.json"
REGIONS_PATH = HERE / "regions.json"
ALIASES_PATH = HERE / "region_aliases.json"
AGGREGATES_PATH = HERE / "region_aggregates.json"
PROFILE = HERE.name
REGION_BASE = "https://openenergyplatform.org/ontology/oekg/region/"

# Every node under region/, with whatever labels the OEKG gives it. OPTIONAL,
# because a region the graph uses without a label is still a region, and
# `merge_regions` says so instead of the query dropping it.
REGIONS_QUERY = f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?region ?label WHERE {{
  ?region ?p ?o .
  FILTER(STRSTARTS(STR(?region), "{REGION_BASE}"))
  OPTIONAL {{ ?region rdfs:label ?label }}
}}"""

# What the OEKG already says about the nodes a written graph only points at:
# the class and the label of each region and each OEO term it holds. The
# graph references them without repeating them (kg.py), and the shapes check
# both, so the graph is validated together with these (`context`).
CONTEXT_QUERY = f"""PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?p ?o WHERE {{
  VALUES ?p {{ rdf:type rdfs:label }}
  ?s ?p ?o .
  FILTER(STRSTARTS(STR(?s), "{REGION_BASE}")
         || STRSTARTS(STR(?s), "https://openenergyplatform.org/ontology/oeo/"))
}}"""

SOURCES = {
    "oeo": {"kind": "release_asset", "repo": "OpenEnergyPlatform/ontology",
            "asset": "oeo-closure.owl"},
    "regions": {"kind": "sparql",
                "endpoint": "https://openenergyplatform.org/api/v0/oekg/sparql/",
                "token_env": "OEP_API_TOKEN", "query": REGIONS_QUERY},
    "oekg_context": {"kind": "sparql",
                     "endpoint": "https://openenergyplatform.org/api/v0/oekg/sparql/",
                     "token_env": "OEP_API_TOKEN", "query": CONTEXT_QUERY},
    # The shapes the serializer reads its paths, cardinalities and classes
    # from (kg.make_serializer) and the written graph is validated against.
    # The head of the branch, which is what the next pin will be. `reviewed`
    # is the commit the platform pins its validator to today
    # (oeplatform/settings.py OEKG_SHAPES_PINNED_COMMIT): while the two are
    # the same file, the verdict here is the validator's. Every run prints
    # whether they still are.
    "oekg_shapes": {"kind": "repo_files", "repo": "OpenEnergyPlatform/oekg",
                    "ref": "production",
                    "reviewed": "b4604e02060624b381bdbe2f872df94cfd0f5630",
                    "files": ["oekg/shapes/oekg_shapes.ttl"]},
    # The groups of countries a scenario covers, with their members: the
    # regions the AR6 database itself defines (R5, R9, R10) and the UN's
    # statistical regions (M49), which carry the names a paper writes
    # ("Sub-Saharan Africa", "Western Europe"). The OEKG has countries only,
    # so a group is written as its members (`aggregates`).
    "iiasa_regions": {"kind": "repo_files",
                      "repo": "IAMconsortium/common-definitions",
                      "ref": "main",
                      "files": ["definitions/region/common.yaml"]},
    "m49": {"kind": "url",
            "url": "https://unstats.un.org/SDGAPI/v1/sdg/GeoArea/Tree",
            "file": "tree.json"},
}

# The group a worldwide scenario covers: every region the OEKG holds. Its
# spellings are the answer the list always offered for it.
WORLD = "aggregate:World"
WORLD_LABELS = ["global", "worldwide", "World",
                u"global — the whole world, not a single country"]
# The M49 code of the world, which WORLD already is.
M49_WORLD = "1"

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
    snapshot = ontology.build(
        closure, SETS, spec_raw, base=OEO,
        language=load_profile(PROFILE).require("extraction",
                                               "ALT_LABEL_LANGUAGE"))
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


def merge_regions(rows: list, aliases: dict) -> dict:
    """{region IRI: labels} from the live rows and the hand-kept spellings.

    The OEKG decides which regions exist. region_aliases.json keeps the
    spellings a document writes that the graph does not carry (both "Cabo
    Verde" and "Cape Verde", say); they come first, in
    their order, and a live label they lack is appended. A region with no
    label from either side cannot be offered to the model and raises.
    """
    live: dict = {}
    for row in rows:
        iri = row.get("region")
        if not iri:
            continue
        labels = live.setdefault(iri, [])
        # The OEKG writes most labels with a trailing space ("Austria ").
        label = (row.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    out = {}
    for iri in sorted(live):
        labels = list(aliases.get(iri) or ())
        labels += [label for label in live[iri] if label not in labels]
        if not labels:
            raise upstream.UpstreamError(f"regions: {iri} has no label")
        out[iri] = labels
    if not out:
        raise upstream.UpstreamError("regions: the OEKG returned no region")
    return out


def aggregates(families: list, tree: list, regions: dict) -> tuple:
    """({key: {labels, members, source}}, Counter of what could not be placed).

    *families* are the parsed IIASA region files, *tree* the M49 tree,
    *regions* regions.json. A member is an OEKG region, found by one of its
    labels, or by a label with the same words in another order and
    punctuation ("Republic of Moldova", "Moldova (the Republic of)"), so a
    country both lists spell alike needs no table; one no label names, or
    two regions' labels do, is counted, never guessed. A group's label that is a country's
    label is the country, and a label two groups share is the first one's:
    both would make one answer mean two things, so each is counted too.
    """
    from docpipe.extraction.spec import fold_label
    def words(name) -> frozenset:
        return frozenset(w for w in re.split(r"[^\w]+", fold_label(str(name)))
                         if w and w not in ("the", "of"))

    country, worded = {}, {}
    for iri, labels in regions.items():
        for label in labels:
            country.setdefault(fold_label(label), iri)
            worded.setdefault(words(label), set()).add(iri)
    missing: Counter = Counter()
    taken: dict = {}

    def placed(names) -> list:
        out = []
        for name in names:
            iri = country.get(fold_label(str(name)))
            if iri is None and len(worded.get(words(name), ())) == 1:
                iri = next(iter(worded[words(name)]))
            if iri is None:
                missing[f"member {name}"] += 1
            elif iri not in out:
                out.append(iri)
        return out

    out = {WORLD: {"labels": list(WORLD_LABELS), "members": sorted(regions),
                   "source": "every region of the OEKG"}}

    def add(key, labels, members, source, family=None) -> None:
        kept = []
        for label in labels:
            folded = fold_label(label)
            if folded in country:
                missing[f"label {label} is a country"] += 1
            elif taken.setdefault(folded, key) != key:
                missing[f"label {label} names two groups"] += 1
            elif label not in kept:
                kept.append(label)
        if not kept or not members:
            missing[f"group {labels[0]}"] += 1
            return
        out[key] = {"labels": kept, "members": members, "source": source}
        if family:
            out[key]["family"] = family

    for parsed in families:
        for block in parsed or ():
            for family, entries in (block or {}).items():
                for entry in entries or ():
                    # A bare name is a country or a group without members.
                    if not isinstance(entry, dict):
                        continue
                    for name, attrs in entry.items():
                        countries = (attrs or {}).get("countries")
                        if not countries:
                            continue
                        labels = [name] + ([attrs["ar6"]] if attrs.get("ar6")
                                           else [])
                        add(f"aggregate:iiasa:{name}", labels,
                            placed(countries), "iiasa", family)

    def walk(node: dict) -> list:
        # The members are the countries below a group. A leaf that is not a
        # country is a group the tree lists without its members.
        kids = node.get("children") or []
        names = ([node.get("geoAreaName")]
                 if node.get("type") == "Country" else [])
        for kid in kids:
            names += walk(kid)
        code = str(node.get("geoAreaCode"))
        if kids and code != M49_WORLD and f"aggregate:m49:{code}" not in out:
            add(f"aggregate:m49:{code}", [str(node.get("geoAreaName"))],
                placed(dict.fromkeys(names)), "m49")
        return names

    for node in tree or ():
        walk(node)
    return out, missing


def refresh(cache: Path = upstream.CACHE) -> dict:
    """Pull SOURCES, write regions.json and vocabulary.json, write the lock.

    The lock is what `shapes` reads: the serializer and the validation of
    the written graph take the shapes this refresh pulled.
    """
    records = upstream.fetch(SOURCES, cache)
    rows = json.loads(upstream.files(records["regions"])[0]
                      .read_text(encoding="utf-8"))
    aliases = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    regions = merge_regions(rows, aliases)
    with io.open(REGIONS_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(regions, ensure_ascii=False, indent=1,
                                sort_keys=True) + "\n")
    import yaml
    families = [yaml.safe_load(path.read_text(encoding="utf-8"))
                for path in upstream.files(records["iiasa_regions"])]
    tree = json.loads(upstream.files(records["m49"])[0]
                      .read_text(encoding="utf-8"))
    groups, missing = aggregates(families, tree, regions)
    with io.open(AGGREGATES_PATH, "w", encoding="utf-8",
                 newline="\n") as handle:
        handle.write(json.dumps(groups, ensure_ascii=False, indent=1,
                                sort_keys=True) + "\n")
    records["iiasa_regions"]["aggregates"] = len(groups)
    records["iiasa_regions"]["not_placed"] = dict(missing)
    snapshot = build(upstream.files(records["oeo"], ".owl")[0])
    snapshot["pin"]["sources"] = {name: record["version"]
                                  for name, record in records.items()}
    with io.open(VOCABULARY_PATH, "w", encoding="utf-8",
                 newline="\n") as handle:
        handle.write(ontology.serialize(snapshot))
    upstream.write_lock(PROFILE, records, cache)
    return records


def shapes(cache: Path = upstream.CACHE) -> list:
    """The OEKG shapes of the last refresh; empty if none has run."""
    return upstream.files((upstream.load_lock(PROFILE, cache) or {})
                          .get("sources", {}).get("oekg_shapes"), ".ttl")


def context(cache: Path = upstream.CACHE) -> list:
    """[(subject, predicate, object)] the OEKG holds about the nodes it already
    has, as the last refresh pulled them; empty if none has pulled them."""
    paths = upstream.files((upstream.load_lock(PROFILE, cache) or {})
                           .get("sources", {}).get("oekg_context"))
    if not paths:
        return []
    return [(row["s"], row["p"], row["o"])
            for row in json.loads(paths[0].read_text(encoding="utf-8"))]


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


def edges(spec_raw: dict) -> list:
    """Every triple shape this profile emits, the spec's and the writer's."""
    from profiles.scenarios import kg     # here: kg reads the spec at import
    return list(ontology.spec_edges(spec_raw)) + list(kg.edges())


def check(spec_raw: dict, snapshot: dict) -> list:
    """Every complaint the pinned ontology has about this spec."""
    return (ontology.term_problems(spec_raw, snapshot)
            + ontology.kind_problems(spec_raw, snapshot)
            + ontology.edge_problems(edges(spec_raw), snapshot)
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
    parser.add_argument("--refresh", action="store_true",
                        help="pull SOURCES at their latest version, rebuild "
                             "regions.json and vocabulary.json, then check")
    parser.add_argument("--check", action="store_true",
                        help="hold the spec against the checked-in snapshot")
    args = parser.parse_args(argv)

    if args.refresh:
        before = (set(json.loads(REGIONS_PATH.read_text(encoding="utf-8")))
                  if REGIONS_PATH.is_file() else set())
        try:
            records = refresh()
        except upstream.UpstreamError as exc:
            print(f"refresh failed: {exc}")
            return 2
        for name, record in records.items():
            print(upstream.summary(name, record))
        groups = records["iiasa_regions"]
        print(f"region groups: {groups['aggregates']} group(s), "
              f"{sum(groups['not_placed'].values())} name(s) not placed")
        for what, count in sorted(groups["not_placed"].items()):
            print(f"  not placed: {what} ({count}x)")
        after = set(json.loads(REGIONS_PATH.read_text(encoding="utf-8")))
        for iri in sorted(after - before):
            print(f"regions: new {iri}")
        for iri in sorted(before - after):
            print(f"regions: gone {iri}")
        args.check = True
    elif args.write:
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
        # What the pin defines differently from the spec, or defines where
        # the spec says nothing. A note and never a problem: the model reads
        # the spec's words, and they change only when somebody edits them.
        defined = ontology.definition_differences(spec_raw, snapshot)
        for difference in defined:
            print(ontology.definition_note(difference))
        print(f"{len(spec_terms(spec_raw))} identifier(s) checked, "
              f"{len(problems)} problem(s), {len(seen)} corpus label(s), "
              f"{len(defined)} definition(s) that differ from the pin")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
