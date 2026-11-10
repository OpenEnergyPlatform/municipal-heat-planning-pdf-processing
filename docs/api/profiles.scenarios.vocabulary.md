# profiles.scenarios.vocabulary

`profiles/scenarios/vocabulary.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

vocabulary.py – This profile's half of the ontology snapshot.

The builder lives in `docpipe/ontology.py`. What is here is what is about
scenario publications: which roots this profile's one static list draws from,
and the 249 study regions, which come from the OEKG rather than from an
ontology release and are therefore pinned differently.

    python -m profiles.scenarios.vocabulary --refresh   # needs OEP_API_TOKEN
    python -m profiles.scenarios.vocabulary --closure oeo-closure.owl --write
    python -m profiles.scenarios.vocabulary --check

`--refresh` is what a run calls first: the OEO closure at its latest release,
the study regions live from the OEKG, the OEKG shapes at the head of their
branch, the groups of countries a scenario may cover (IIASA, UN M49, World
Bank) and the name LCC gives each region, then the check. Without
OEP_API_TOKEN in the environment it stops, because the regions are offered to
the model and a list nobody pulled is not the OEKG's current one.

Why this profile needed it more than the other one. Its spec names 32 ontology
identifiers and, before this, exactly zero of them were checked against
anything: the old walk looked in three named places, and this profile writes
its terms as full IRIs in vocabulary KEYS and as predicates inside `kg`
blocks. Most of them ARE predicates, so an index over classes and individuals
would have called every one of them missing.

Author: Felix Vossel

## Functions

### sources

```python
def sources() -> dict
```

### sets

```python
def sets() -> dict
```

### axis_sets

```python
def axis_sets() -> dict
```

### build

```python
def build(closure: Path, regions_path: Path = REGIONS_PATH) -> dict
```

The snapshot: the lists of the closure and the regions of
*regions_path* (the profile's own file where not given).

### load

```python
def load(path: Path = VOCABULARY_PATH) -> dict
```

### merge_regions

```python
def merge_regions(rows: list, aliases: dict) -> dict
```

{region IRI: labels} from the live rows and the hand-kept spellings.

The OEKG decides which regions exist. region_aliases.json keeps the
spellings a document writes that the graph does not carry (both "Cabo
Verde" and "Cape Verde", say); they come first, in
their order, and a live label they lack is appended. A region with no
label from either side cannot be offered to the model and raises.

### region_names

```python
def region_names(path: Path, regions: dict) -> tuple
```

({region IRI: LCC's English short name}, [regions LCC does not name]).

*path* is LCC's ISO 3166-1 file, *regions* regions.json. A region is the
LCC country of its own name (oekg/region/Germany is the individual
Germany); one whose name LCC no longer holds is the one country whose
English short name is among the region's labels (oekg/region/Macedonia is
NorthMacedonia). The name is written as LCC writes it, without its
language tag. A region neither finds, or that finds two, is returned
unnamed and never guessed.

### model_names

```python
def model_names(model: str) -> list
```

The names a paper calls a model by: its name without the version
("REMIND-MAgPIE 3.2-4.6" -> "REMIND-MAgPIE") and the first part of that
name ("REMIND"). A version is a last word that starts with a digit, or
with v and a digit.

### iiasa

```python
def iiasa(record: dict) -> tuple
```

(region definitions, {region: [codes]}) of a refreshed IIASA tree.

The definitions are what `aggregates` reads. A model's mapping file gives
each of its regions the code its own files and its papers write ("LAM:
REMIND-MAgPIE 3.2-4.6|Latin America and the Caribbean").

### sheet_rows

```python
def sheet_rows(book, name: str) -> list
```

[{column name: cell}] of the sheet *name* of an xlsx file (a path or a
file object), its first row naming the columns. An xlsx file is a zip of
XML, so the standard library reads it; a spreadsheet library would be a
dependency for one table.

### worldbank

```python
def worldbank(book) -> list
```

[(code, name, [economy])], the World Bank's groups of economies as its
classification lists them (sheet `compositions`).

### aggregates

```python
def aggregates(families: list, tree: list, regions: dict, codes=None,
               banks=()) -> tuple
```

({key: {labels, members, source}}, Counter of what could not be placed).

*families* are the parsed IIASA region files, *tree* the M49 tree,
*regions* regions.json, *codes* the codes the IIASA mappings give a
model's regions and *banks* the World Bank's groups. A member is an OEKG
region, found by one of its
labels, or by a label with the same words in another order and
punctuation ("Republic of Moldova", "Moldova (the Republic of)"), so a
country both lists spell alike needs no table. Accents do not count and
the sources' abbreviations are written out (the rule
`name_abbreviations`). A name with a
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

### refresh

```python
def refresh(cache: Path = upstream.CACHE, out: Optional[Path] = None) \
        -> dict
```

Pull the sources, write regions.json, region_names.json,
region_aggregates.json and vocabulary.json, write the lock.

The lock is what `shapes` reads: the serializer and the validation of
the written graph take the shapes this refresh pulled. *out* is the
folder the profile's files are written to, its own where not given
(`docpipe edit` fetches into a folder of its own first).

### shapes

```python
def shapes(cache: Path = upstream.CACHE) -> list
```

The OEKG shapes of the last refresh; empty if none has run.

### context

```python
def context(cache: Path = upstream.CACHE) -> list
```

[(subject, predicate, object)] the OEKG holds about the nodes it already
has, as the last refresh pulled them; empty if none has pulled them.

### spec_terms

```python
def spec_terms(spec_raw: dict) -> dict
```

### region_problems

```python
def region_problems(snapshot: dict, regions=None) -> list
```

The regions file against the snapshot it was pinned with.

`document_regions` filters this list per document, so a region that
silently disappears from it stops being offered for every publication that
names it, and nothing else would say so.

`regions` is the file's content and is read from disk when not given; a
caller passes it so the comparison can be exercised without editing the
checked-in file.

### edges

```python
def edges(spec_raw: dict) -> list
```

Every triple shape this profile emits, the spec's and the writer's.

### check

```python
def check(spec_raw: dict, snapshot: dict) -> list
```

Every complaint the pinned ontology has about this spec.

### foreign_labels

```python
def foreign_labels(spec_raw: dict, snapshot: dict) -> list
```

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
