# docpipe.visuals.holes

`docpipe/visuals/holes.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

holes.py: The tables and figures of a document that have no content after
Stage 5, and why (owner request 2026-11-19).

What Stage 5 could not read stood only in its own file and in one line of the
merge's log: the document went into the database, the index and the harvest
as if it were whole, and a value only such a table holds ended "not stated in
the document". Now the merge writes them into the document (document.json,
"holes"), the database keeps them beside it (Documents.holes), the harvest
reads them (a value still open in such a document is no finding about the
document, rule `state_rules`) and its stamp records them, so that a hole
filled later makes the document work again. A job counts them (`count`, the
command line's `--count-holes`) to know whether another pass of Stage 5
filled any.

Author: Felix Vossel

## Functions

### of

```python
def of(sections: list, enriched: dict) -> list
```

[{"id", "kind", "page", "why"}] of the tables and figures of
*sections* (what Stage 5 and the merge read) that have no content in
*enriched* (visuals.json as read; {} where there is none): a table
without markdown, a figure without description, in reading order. "why"
is the cause Stage 5 gave the item (`vlm_why`), else NOT_ASKED.

### of_document

```python
def of_document(output_dir) -> list
```

`of` for one document folder: the input Stage 5 reads there (the
refined sections, else the sections) against its visuals.json; [] where
it has neither input.

### count

```python
def count(root) -> tuple
```

(tables, figures, documents) without content under *root*, a document
folder or a folder of them, by `of_document`.

[Back to the index](../README.md)
