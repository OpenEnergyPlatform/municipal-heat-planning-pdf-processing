# profiles.scenarios.extraction

`profiles/scenarios/extraction.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Extraction stage wiring: where the scenarios spec lives, and the list that
is only closed once a document is named.

One of the fields has a finite set of correct answers, but the set is not
the same for every publication, so it cannot sit in the spec file:

  scenario_region            the 249 study regions the OEKG actually uses,
                             narrowed to those the document names at all.

A scenario is read as the publication names it, and which entry of the
publication's list of scenarios a name is, a new one or one read before, is
asked while the publication is read (`docpipe/extraction/addressed.py`,
owner decisions 2026-11-08).

The narrowing is not a guess. Every claim has to quote its source verbatim, and
the sources are exactly the section, table and figure texts scanned here, so a
region whose name appears nowhere in them could never have been quoted. What is
dropped is unreachable, not merely unlikely — and dropping it keeps the prompt
at the handful of countries a paper mentions instead of all 249.

The list carries `out:` entries, and they are the point of this file as much
as the real entries are. A closed list without an escape hatch does not stop the
model from answering; it stops it from answering CORRECTLY, and what comes back
is the nearest entry that is not quite right. The OEKG knows 249 countries and
no aggregates, while a scenario is usually global — so without a world entry
the honest answer to "which region" does not exist in the list, and a paper
about worldwide emissions that happens to mention Germany once invites
"Germany". The world and the groups of countries are entries of the list now
and are written as their member countries.

Silence is the other half of the argument. An empty field already meant
"unmapped" and was already counted, but it meant three different things at
once — nothing fitted, the model did not look, the reply was cut short. A
chosen `out:` entry means exactly one of them, and it is the one worth
counting.

## Functions

### aggregates

```python
def aggregates() -> dict
```

{key: {labels, members, ...}}, the groups of countries of the last
refresh; empty before one has written them.

### spellings

```python
def spellings(labels: list, joined: bool = False) -> list
```

An entry's labels and the ways a paper writes them.

"&" and "and" stand for each other. Where *joined*, a group's code and
its name are joined as a paper joins them ("LAM (Latin America)",
"Latin America (LAM)", "LAM - Latin America"): a wording made of two
names of one entry names that entry, and `_one_meaning` keeps one two
entries share from naming either.

### document_regions

```python
def document_regions(conn: sqlite3.Connection, document_id: int) -> dict
```

The countries and groups of countries this document names.

The world is always offered, as `global` was. A group of the IAM
regions is also offered by its bare name where the document names its
family: a paper writes "the R10 regions" and then "Europe". A model's
own region is offered where the paper names the model and the region,
and keeps a label it shares with another group (`_one_meaning`). Every
entry is offered with the ways a paper writes its labels (`spellings`).

### document_axes

```python
def document_axes(conn: sqlite3.Connection, document_id: int) -> dict
```

Per-document choice lists, keyed by axis name and by parameter uri.

The regions this document names, possibly none. The run appends the
out: entries the spec lists beside them (`beside` of scenario_region,
`runner.fill_dynamic_axes`), so the list exists even when the narrowing
finds nothing. That case is not hypothetical — a publication that names
no country at all used to leave the field with no list, and a field with
no list is free text again.

### shapes_files

```python
def shapes_files() -> list
```

The OEKG shapes of the last `vocabulary --refresh`, or none.

Where the preflight finds the file `NOT_EXTRACTED` is held against: the
same one the serializer reads its paths from.

### document_context

```python
def document_context(conn, document_id: int) -> dict
```

What a publication says of itself, for the sentence it is searched
with: its title as the corpus index holds it (`DocumentMeta.title`).
Missing metadata is no error: the sentence is then written from the
parameter alone.

[Back to the index](../README.md)
