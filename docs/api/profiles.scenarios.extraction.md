# profiles.scenarios.extraction

`profiles/scenarios/extraction.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Extraction stage wiring: where the ar6 spec lives, and the lists that are
only closed once a document is named.

Two of the ar6 fields have a finite set of correct answers, but the set is not
the same for every publication, so it cannot sit in the spec file:

  scenario / scenario_label  the AR6 scenarios THIS publication documents.
                             The corpus holds 1389 of them, one publication
                             documents up to 146, and the model has to pick
                             from that publication's own list.
  scenario_region            the 249 study regions the OEKG actually uses,
                             narrowed to those the document names at all.

The narrowing is not a guess. Every claim has to quote its source verbatim, and
the sources are exactly the section, table and figure texts scanned here, so a
region whose name appears nowhere in them could never have been quoted. What is
dropped is unreachable, not merely unlikely — and dropping it keeps the prompt
at the handful of countries a paper mentions instead of all 249.

Both lists carry `out:` entries, and they are the point of this file as much as
the real entries are. A closed list without an escape hatch does not stop the
model from answering; it stops it from answering CORRECTLY, and what comes back
is the nearest entry that is not quite right. The OEKG knows 249 countries and
no aggregates, while an AR6 scenario is usually global — so without
`out:global` the honest answer to "which region" does not exist in the list,
and a paper about worldwide emissions that happens to mention Germany once
invites "Germany". The same holds for a run identifier: naming a family is not
naming a run, and the model needs a way to say so that is not silence.

Silence is the other half of the argument. An empty field already meant
"unmapped" and was already counted, but it meant three different things at
once — nothing fitted, the model did not look, the reply was cut short. A
chosen `out:` entry means exactly one of them, and it is the one worth
counting.

## Functions

### document_scenarios

```python
def document_scenarios(conn: sqlite3.Connection, document_id: int) -> dict
```

The AR6 scenarios this publication documents, as a choice list.

Keyed by the AR6 name itself rather than an invented IRI: the name is the
identity the corpus links against, and kg.py resolves it the same way.

### document_regions

```python
def document_regions(conn: sqlite3.Connection, document_id: int) -> dict
```

### document_axes

```python
def document_axes(conn: sqlite3.Connection, document_id: int) -> dict
```

Per-document choice lists, keyed by axis name and by parameter uri.

The out: entries are appended unconditionally, so every list exists even
when the narrowing finds nothing. That case is not hypothetical — a
publication with no runs in DocumentScenarios, or one that names no country
at all, used to leave the field with no list, and a field with no list is
free text again.

[Back to the index](../README.md)
