# docpipe.editor.flowtry

`docpipe/editor/flowtry.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

flowtry.py: A drawing of the flow tried on one document with made-up
answers: what each box would ask, nothing sent (owner decisions 2026-11-10
evening, section 12 of the plan).

"Try" reads a document as a run reads it, by the drawing on the page
(`extraction.engine`), with every request built in full, as it would go out
(its prompt, the parts of it the payload carries, its message), and kept
instead of sent. The answer comes from here, in one of two ways:

- "nothing": a find, and the question of a field the document has once,
  names the first number its piece prints where the field is a number
  (nothing where the piece prints none), else the piece's first word, so
  that there are values; every other answer is the empty answer of its
  request's own form (0, an empty list, an empty text, "no"): each
  coordinate goes through its whole search. It shows how far rounds and searches go at
  most. (Were the finds empty too, there would be no value to search for.)
- "first_line": every answer names the first line the request showed (its
  first number where it prints one, else its first word). It shows the
  shortest way.

No embedder and no reranker are asked either: a search orders the pieces
in the document's order, which a run never does instead of a search (owner
decision 2026-11-09); the page says so. The document is one of the corpus
database (its passages, some pages of them where asked) or, without one, a
plan made up from the examples of the profile's spec.

What comes back: per box the requests it asked and the first one in full,
the states the coordinates of the values ended in, and the pieces the
document was cut into.

Author: Felix Vossel

## Exports

What `__all__` names, and where each name is defined:

- `MODES`

## Classes

### Refused

```python
class Refused(ValueError)
```

What cannot be tried, said.

## Functions

### example_sources

```python
def example_sources(spec) -> list
```

A plan made up from the examples of *spec*: a title page and one
section per field's example.

### empty

```python
def empty(schema: dict)
```

The answer of the form *schema* that names nothing: every key the
form requires, each empty: an empty list, 0 for a number or an address,
an empty text, the last of a choice of words (a check's "no"), the
first of several forms (the number, not "new").

### answer

```python
def answer(kind: str, payload: dict, shape: dict, mode: str,
           numeric: bool = False)
```

The made-up answer of one request, in the request's own form; a find
of a *numeric* field names a number.

### run

```python
def run(profile, spec, tree: list, numbers, sources: list,
        mode: str = "nothing") -> dict
```

What the drawing *tree* asks of the document *sources* with the
made-up answers of *mode*, nothing sent (see the module's head).

### sources_of

```python
def sources_of(db_path, document_id: int,
               pages: Optional[tuple] = None) -> list
```

The passages of a document of the corpus database, those of the
pages *pages* (first, last) where given.

### documents

```python
def documents(db_path, limit: int = 200) -> list
```

[{"id", "title"}] of the documents of the corpus database, for the
page's choice.

[Back to the index](../README.md)
