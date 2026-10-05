# docpipe.serve.tools

`docpipe/serve/tools.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

tools.py: The four questions the value store answers for a program.

The HTTP API and the MCP server offer the same four, described once here,
so a program that asks over one gets what a program that asks over the
other gets: which documents, which parameters, the values that match, and
one value with everything that backs it.

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

### call

```python
def call(store: Values, name: str, arguments: Optional[dict]) -> dict
```

Answer one of the four by name.

[Back to the index](../README.md)
