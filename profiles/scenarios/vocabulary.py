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
branch and the groups of countries a scenario may cover (IIASA, UN M49, World
Bank), then the check. Without
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
import unicodedata
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
    # regions the AR6 database itself defines (R5, R9, R10), the regions of
    # each model with the codes its mapping gives them ("LAM", "OAS"), and the
    # UN's statistical regions (M49), which carry the names a paper writes
    # ("Sub-Saharan Africa", "Western Europe"). The OEKG has countries only,
    # so a group is written as its members (`aggregates`).
    "iiasa_regions": {"kind": "repo_tree",
                      "repo": "IAMconsortium/common-definitions",
                      "ref": "main",
                      "paths": ["definitions/region/", "mappings/"],
                      "suffix": ".yaml"},
    "m49": {"kind": "url",
            "url": "https://unstats.un.org/SDGAPI/v1/sdg/GeoArea/Tree",
            "file": "tree.json"},
    # The World Bank's groups of economies with their members: the European
    # Union, the OECD members and its world regions ("Middle East & North
    # Africa"), which neither source above lists by country.
    "worldbank": {"kind": "url",
                  "url": ("https://datacatalogfiles.worldbank.org/"
                          "ddh-published/0037712/DR0090755/CLASS.xlsx"),
                  "file": "CLASS.xlsx"},
}

# The one group no source lists by country (owner, 2026-11-04): the European
# Union of 2013 to 2020, the Union of the World Bank's list and the United
# Kingdom. Its labels are the ways its name is written.
EU28 = {"key": "aggregate:EU28", "labels": ["EU28", "EU-28", "EU 28"],
        "union": "aggregate:worldbank:EUU", "joined": ["United Kingdom"]}

# The short forms a paper writes for two groups the World Bank lists under a
# longer name (owner, 2026-11-04).
SHORT_FORMS = {"EUU": ["EU"], "OED": ["OECD"]}

# How the sources abbreviate a country's name ("St. Lucia", "Congo, Dem.
# Rep.", "Lao PDR", "Hong Kong SAR, China"), written out before a member is
# looked up. SAR is a status, not part of the name.
ABBREVIATIONS = {"st.": "saint", "rep.": "republic", "dem.": "democratic",
                 "fed.": "federated", "sts.": "states",
                 "pdr": "people's democratic republic", "sar": ""}

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


def model_names(model: str) -> list:
    """The names a paper calls a model by: its name without the version
    ("REMIND-MAgPIE 3.2-4.6" -> "REMIND-MAgPIE") and the first part of that
    name ("REMIND"). A version is a last word that starts with a digit, or
    with v and a digit."""
    words = str(model).split()
    while len(words) > 1 and re.match(r"(?i)v?\d", words[-1]):
        words.pop()
    name = " ".join(words)
    first = re.split(r"[-/ ]", name, maxsplit=1)[0]
    return [name] + ([first] if first and first != name else [])


def _version_key(model: str) -> tuple:
    """A model with its version as a sort key, the numbers as numbers: 4.10
    comes after 4.9."""
    return tuple((0, int(part)) if part.isdigit() else (1, part)
                 for part in re.split(r"(\d+)", str(model)) if part)


def iiasa(record: dict) -> tuple:
    """(region definitions, {region: [codes]}) of a refreshed IIASA tree.

    The definitions are what `aggregates` reads. A model's mapping file gives
    each of its regions the code its own files and its papers write ("LAM:
    REMIND-MAgPIE 3.2-4.6|Latin America and the Caribbean").
    """
    import yaml
    families, codes = [], {}
    for entry in (record or {}).get("files") or ():
        data = yaml.safe_load(Path(entry["path"]).read_text(encoding="utf-8"))
        if entry["repo_path"].startswith("definitions/"):
            families.append(data)
            continue
        for item in (data or {}).get("native_regions") or ():
            for code, name in (item.items() if isinstance(item, dict) else ()):
                if isinstance(name, str) and str(code) not in codes.get(name, ()):
                    codes.setdefault(name, []).append(str(code))
    return families, codes


_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELATION = ("{http://schemas.openxmlformats.org/officeDocument/2006/"
             "relationships}id")


def sheet_rows(book, name: str) -> list:
    """[{column name: cell}] of the sheet *name* of an xlsx file (a path or a
    file object), its first row naming the columns. An xlsx file is a zip of
    XML, so the standard library reads it; a spreadsheet library would be a
    dependency for one table."""
    import xml.etree.ElementTree as ElementTree
    import zipfile
    with zipfile.ZipFile(book) as archive:
        def tree(member):
            return ElementTree.fromstring(archive.read(member))
        targets = {rel.get("Id"): rel.get("Target")
                   for rel in tree("xl/_rels/workbook.xml.rels")}
        sheet = next((s for s in tree("xl/workbook.xml").iter(_SHEET + "sheet")
                      if s.get("name") == name), None)
        if sheet is None:
            raise upstream.UpstreamError(f"{book}: no sheet {name!r}")
        target = targets[sheet.get(_RELATION)].lstrip("/")
        member = target if target.startswith("xl/") else "xl/" + target
        shared = ([("".join(t.text or "" for t in item.iter(_SHEET + "t")))
                   for item in tree("xl/sharedStrings.xml").iter(_SHEET + "si")]
                  if "xl/sharedStrings.xml" in archive.namelist() else [])
        rows = []
        for row in tree(member).iter(_SHEET + "row"):
            cells = {}
            for place, cell in enumerate(row.iter(_SHEET + "c")):
                column = re.match(r"[A-Z]*", cell.get("r") or "").group(0)
                if cell.get("t") == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter(_SHEET + "t"))
                else:
                    raw = cell.find(_SHEET + "v")
                    value = (None if raw is None
                             else shared[int(raw.text)] if cell.get("t") == "s"
                             else raw.text)
                cells[column or str(place)] = value
            rows.append(cells)
    header = rows[0] if rows else {}
    return [{header[column]: value for column, value in row.items()
             if header.get(column)} for row in rows[1:]]


def worldbank(book) -> list:
    """[(code, name, [economy])], the World Bank's groups of economies as its
    classification lists them (sheet `compositions`)."""
    groups: dict = {}
    for row in sheet_rows(book, "compositions"):
        code, name = row.get("WB_Group_Code"), row.get("WB_Group_Name")
        economy = row.get("WB_Country_Name")
        if code and name and economy:
            groups.setdefault((code, name), []).append(economy)
    if not groups:
        raise upstream.UpstreamError(f"{book}: no group in its compositions")
    return [(code, name, members) for (code, name), members in groups.items()]


def aggregates(families: list, tree: list, regions: dict, codes=None,
               banks=()) -> tuple:
    """({key: {labels, members, source}}, Counter of what could not be placed).

    *families* are the parsed IIASA region files, *tree* the M49 tree,
    *regions* regions.json, *codes* the codes the IIASA mappings give a
    model's regions and *banks* the World Bank's groups. A member is an OEKG
    region, found by one of its
    labels, or by a label with the same words in another order and
    punctuation ("Republic of Moldova", "Moldova (the Republic of)"), so a
    country both lists spell alike needs no table. Accents do not count and
    the sources' abbreviations are written out (ABBREVIATIONS). A name with a
    comma whose whole words find no label is found by the words before the
    comma ("Egypt, Arab Rep.", "Taiwan, China") where exactly one region's
    labels hold them all: "Congo, Dem. Rep." is found by its whole words, and
    the words before its comma are two regions'. One no label names, or two
    regions' labels do, is counted, never guessed. A group's label that is a country's
    label is the country, and a label two groups share is the first one's:
    both would make one answer mean two things, so each is counted too.

    A model's region ("REMIND-MAgPIE 3.2-4.6|Other Asia") is a group of that
    model, labelled with its name and its codes ("Other Asia", "OAS"). Its
    labels need to be its own only among the regions of models of one name
    (`model_names`), since a paper is offered them where it names the model;
    every version defines its regions again, and the newest is kept. EU28 is
    the World Bank's European Union and the United Kingdom.
    """
    from docpipe.extraction.spec import fold_label

    def plain(name) -> str:
        spelt = unicodedata.normalize("NFKD", fold_label(str(name)))
        return "".join(c for c in spelt if not unicodedata.combining(c))

    def words(name) -> frozenset:
        spelt = " ".join(ABBREVIATIONS.get(w, w) for w in plain(name).split())
        return frozenset(w for w in re.split(r"[^\w]+", spelt)
                         if w and w not in ("the", "of"))

    country, worded = {}, {}
    for iri, labels in regions.items():
        for label in labels:
            country.setdefault(fold_label(label), iri)
            country.setdefault(plain(label), iri)
            worded.setdefault(words(label), set()).add(iri)
    missing: Counter = Counter()
    taken: dict = {}

    def found(name):
        iri = country.get(fold_label(str(name))) or country.get(plain(name))
        if iri is None and len(worded.get(words(name), ())) == 1:
            iri = next(iter(worded[words(name)]))
        if iri is None and "," in str(name):
            head = words(str(name).split(",", 1)[0])
            holders = {region for held, regions_ in worded.items()
                       if head and head <= held for region in regions_}
            if len(holders) == 1:
                iri = next(iter(holders))
        return iri

    def placed(names) -> list:
        out = []
        for name in names:
            iri = found(name)
            if iri is None:
                missing[f"member {name}"] += 1
            elif iri not in out:
                out.append(iri)
        return out

    out = {WORLD: {"labels": list(WORLD_LABELS), "members": sorted(regions),
                   "source": "every region of the OEKG"}}
    for label in WORLD_LABELS:
        taken[(None, fold_label(label))] = WORLD

    def add(key, labels, members, source, family=None, model=None) -> None:
        # A model's labels need to be its own among its namesakes only.
        scope = model_names(model)[-1] if model else None
        kept = []
        for label in labels:
            folded = fold_label(label)
            if folded in country:
                missing[f"label {label} is a country"] += 1
            elif taken.setdefault((scope, folded), key) != key:
                missing[f"label {label} names two groups"] += 1
            elif label not in kept:
                kept.append(label)
        if not kept or not members:
            missing[f"group {labels[0]}"] += 1
            return
        out[key] = {"labels": kept, "members": members, "source": source}
        if family:
            out[key]["family"] = family
        if model:
            out[key]["model"] = model
            out[key]["named_by"] = model_names(model)

    natives = []
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
                        if isinstance(countries, str):
                            countries = [countries]
                        if "|" in name:
                            natives.append((family, name, countries))
                            continue
                        labels = [name] + ([attrs["ar6"]] if attrs.get("ar6")
                                           else [])
                        add(f"aggregate:iiasa:{name}", labels,
                            placed(countries), "iiasa", family)

    # The newest version first: the regions of a model of one name are
    # defined again in each of its versions, and only one of them is kept.
    defined = set()
    for model, name, countries in sorted(
            natives, key=lambda native: (model_names(native[0])[-1],
                                         _version_key(native[0])),
            reverse=True):
        region = name.split("|", 1)[1]
        held = (model_names(model)[-1], fold_label(region))
        if held in defined:
            continue
        defined.add(held)
        add(f"aggregate:iiasa:{name}",
            [region] + list((codes or {}).get(name, ())), placed(countries),
            "iiasa", model=model)

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
    for code, name, members in banks or ():
        add(f"aggregate:worldbank:{code}", [name] + SHORT_FORMS.get(code, []),
            placed(members), "worldbank")
    union = out.get(EU28["union"])
    if union is None:
        missing[f"group {EU28['labels'][0]}"] += 1
    else:
        add(EU28["key"], EU28["labels"],
            list(dict.fromkeys(union["members"] + placed(EU28["joined"]))),
            "worldbank and the United Kingdom")
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
    families, codes = iiasa(records["iiasa_regions"])
    tree = json.loads(upstream.files(records["m49"])[0]
                      .read_text(encoding="utf-8"))
    banks = worldbank(upstream.files(records["worldbank"])[0])
    groups, missing = aggregates(families, tree, regions, codes, banks)
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
