# docpipe.extraction.schema

`docpipe/extraction/schema.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

schema.py: Builds a JSON Schema for the harvest, the stamp and the trace.

The harvest is the durable artifact, and the graph is a function of
it. Until this module existed, every later question about a key (what
it means, which OEO predicate it becomes, whether it may be null,
what the closed list is) was answered by reading `runner.py`. That is
not an answer anyone outside this repository can use, and it is not
one this repository can check.

So the schema is generated from the spec, not written beside it. The
parameters, their axes, the closed lists, the questions and the `kg`
blocks all come from `profiles/<name>/extraction_spec.json`, so a
spec change that is not reflected in the schema is a failing test
rather than a stale document. Three schemas come out:

  harvest  one line of \<name>.jsonl: an accepted tuple or a refused
           claim
  stamp    \<name>.stamp.json, what produced that harvest
  trace    one line of \<name>.trace.jsonl, one event of the run

Every property carries a `description`, and every coordinate
additionally carries `x-question` (the German question the model was
asked), `x-options` (the closed list with the corpus spellings) and
`x-kg` (what it becomes in the graph). `x-kg` is the spec's own `kg`
block, the same one the serializer reads, so what a reader is told
and what is written cannot drift apart.

    python -m docpipe.extraction.schema kwp            # print
    python -m docpipe.extraction.schema kwp --write    # write into the profile

Author: Felix Vossel

## Functions

### harvest_schema

```python
def harvest_schema(spec) -> dict
```

One line of \<name>.jsonl.

### stamp_schema

```python
def stamp_schema() -> dict
```

\<name>.stamp.json: what produced the harvest beside it.

### trace_schema

```python
def trace_schema() -> dict
```

One line of \<name>.trace.jsonl: one event, never an aggregate.

### build

```python
def build(spec) -> dict
```

The three schemas of one profile's extraction output.

### serialize

```python
def serialize(schema: dict) -> str
```

One byte-stable rendering, so 'is it current' is a file comparison.

### schema_path

```python
def schema_path(profile_name: str) -> Path
```

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
