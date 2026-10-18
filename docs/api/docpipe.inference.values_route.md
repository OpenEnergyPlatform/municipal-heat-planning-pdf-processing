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
                       limit: int = DEFAULT_LIMIT,
                       parameter_question: Optional[str] = None) -> dict
```

The harvest's answer, or why there is none.

{"route": "values", "reason": None, "values": [...], "total": n,
 "parameter": uri, "coordinates": {...}} when the harvest holds values
for what the question names; otherwise route "rag" with one of REASONS.
*document* limits it to one document (its harvest name); None asks the
whole corpus. *ask(task, slot)* answers one closed question with one
label or None. *level* is the worst trust level still shown.
*parameter_question* is the question the parameter is chosen with; the
profile words one for a person's question (`chat_parameter_question`).

### used_values

```python
def used_values(values: list, statements: list) -> list
```

The values an answer stands on, each with the number of the citation
that carries it (`n`), in the order of *values*.

A value is used where a statement's quote and the value's quote hold
one another: the statement quotes the value's whole quote, or a part of
it that names the value as the plan writes it (`value_raw`). Sharing a
passage is not enough: a table of twelve carriers is one passage, and
an answer about their total uses one of its rows.

[Back to the index](../README.md)
