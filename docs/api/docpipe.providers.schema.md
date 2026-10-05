# docpipe.providers.schema

`docpipe/providers/schema.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

schema.py: One reply schema, in the dialect a hosted API generates in.

A stage writes the reply it asks for as plain JSON Schema: keys that may be
left out, objects keyed by a row label. An API that generates inside a schema
takes less than that, and each takes something else. `strict` rewrites a
schema into what one of them takes and hands back the way home, so the stage
reads the reply in the shape it asked for:

    an object keyed per request  a list of {"key", "value"}; read as the object
    bounds, patterns, formats    dropped: generation never checked them
    a key that may be left out   ALL_REQUIRED: required and nullable, and a
                                 null reads as left out
                                 OPTIONAL: left as it is, and a null it could
                                 also say is taken away, since leaving the key
                                 out says the same

ALL_REQUIRED is the dialect of the API that wants every property required.
OPTIONAL is for the ones that take optional properties but count them:
`budget` is (optional properties, properties with alternatives) the API
compiles, and what is over the first is moved into the second by making it
required and nullable. A schema that fits neither is refused with its counts.

The way home repairs nothing. It is applied to a reply the API generated
inside the rewritten schema and undoes the rewriting, key for key. A reply
that is not JSON is handed on as it came, and the stage that asked says what
is wrong with it.

Author: Felix Vossel

## Classes

### SchemaError

```python
class SchemaError(ValueError)
```

A reply schema this API cannot generate in.

## Functions

### strict

```python
def strict(schema: dict, dialect: str = ALL_REQUIRED,
           budget: Optional[tuple] = None) -> tuple
```

(the schema in the dialect, decode(reply) back to its shape).

### complexity

```python
def complexity(schema: dict) -> tuple
```

(optional properties, properties with alternatives) of a schema: the
two numbers an API that compiles a schema counts.

### decoder_text

```python
def decoder_text(decode: Callable, text: str) -> str
```

The reply text in the shape the stage asked for.

Text that is not one JSON value is handed on untouched: a reply the API
cut off stays cut off, and the stage that reads it names the fault.

[Back to the index](../README.md)
