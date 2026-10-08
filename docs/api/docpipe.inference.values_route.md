# docpipe.inference.values_route

`docpipe/inference/values_route.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

values_route.py: Answers a question for a number from the harvest, before
the documents are searched.

A question like "how much gas in 2030?" names a parameter and some of its
coordinates. The harvest has read exactly those out of the documents, each
with its quote, its page and a trust level. So the number is not looked for
a second time and not written by a model: the question is turned into the
parameter and the coordinates it names, and the values the harvest holds
for them are shown as they are (`docpipe/serve/values.py`).

The route does not guess. Which parameter and which coordinates the
question names is one closed question each over the spec's own lists (the
harvest's rule: one request per field, chosen from the list). An answer
outside the list leaves the coordinate open, and an open coordinate narrows
nothing. A question that names no parameter is not one for this route, and
the caller searches the documents as before.

Unlike `kg_route` this needs no graph and no query of the profile's: the
harvest and the spec are enough, so it works for every profile that has
both, across one document or all of them.

Author: Felix Vossel

## Functions

### answer_from_values

```python
def answer_from_values(task: str, store, *, ask,
                       document: Optional[str] = None,
                       level: Optional[str] = None,
                       limit: int = DEFAULT_LIMIT) -> dict
```

The harvest's answer, or why there is none.

{"route": "values", "reason": None, "values": [...], "total": n,
 "parameter": uri, "coordinates": {...}} when the harvest holds values
for what the question names; otherwise route "rag" with one of REASONS.
*document* limits it to one document (its harvest name); None asks the
whole corpus. *ask(task, slot)* answers one closed question with one
label or None. *level* is the worst trust level still shown.

### as_passages

```python
def as_passages(values: list) -> list
```

The values as lines a model can be shown and a reader can check:
what was read, for which coordinates, on which page, from which words.

[Back to the index](../README.md)
