# docpipe.serve.tools

`docpipe/serve/tools.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

tools.py: The questions the store answers for a program.

The HTTP API and the MCP server offer the same eight, described once here,
so a program that asks over one gets what a program that asks over the
other gets:

    list_documents, list_parameters   what the harvest has values of
    find_values, get_value            the values, each with what backs it
    get_states, get_coverage          what the harvest says about a parameter
                                      that has no value: unstated, exhausted,
                                      unbacked, never asked
    find_refusals                     the claims that were refused, and why
    search                            passages of the documents by word

A question the store cannot answer is one of three errors, so that a caller
can tell them apart: `BadRequest` (the question is malformed), `NotFound`
(a document or a parameter the harvest does not have) and `Unavailable`
(the search has no database or no word index behind it).

Author: Felix Vossel

## Classes

### BadRequest

```python
class BadRequest(ValueError)
```

A question that cannot be asked that way.

## Functions

### list_documents

```python
def list_documents(store: Values) -> dict
```

### list_parameters

```python
def list_parameters(store: Values) -> dict
```

### find_values

```python
def find_values(store: Values, arguments: dict) -> dict
```

### get_value

```python
def get_value(store: Values, name: Optional[str]) -> dict
```

### get_states

```python
def get_states(store: Values, arguments: dict) -> dict
```

### get_coverage

```python
def get_coverage(store: Values, arguments: dict) -> dict
```

### find_refusals

```python
def find_refusals(store: Values, arguments: dict) -> dict
```

### search

```python
def search(store: Values, arguments: dict) -> dict
```

### described

```python
def described(store: Values) -> dict
```

DESCRIPTIONS as this store can keep them. A search with no database
or no word index behind it says so first in its description: it is
listed, so that a caller sees that it exists, and not offered as
working.

### call

```python
def call(store: Values, name: str, arguments: Optional[dict]) -> dict
```

Answer one of the eight by name.

[Back to the index](../README.md)
