# docpipe.inference.replies

`docpipe/inference/replies.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

replies.py: The reply each chat request asks for, as a JSON schema.

Every chat request names its reply as the grammar of the request (see
`docpipe.providers.grammar`). The prompts state the same shapes in words;
nothing here is a check, and what a reply says is verified afterwards.

The answer is a list of statements. Each one carries its own evidence, so
that each can be checked against the passage it cites on its own: a text
statement a `quote` and the `index` of its excerpt, a statement read off a
picture the `reading` and the `index` of the crop that was attached (or the
`block` of a crop the model asked for), a statement about a calculated value
the `run` that printed it and a `quote` of its inputs. There is no prose
answer beside them: what the reader is shown is made of the statements that
stood the check.

One request has no schema: the answer reformatted into a JSON shape the user
wrote into the task. That shape is the user's and only exists as prose.

Author: Felix Vossel

## Functions

### answer

```python
def answer(actions: bool = True) -> tuple
```

The answer, and with *actions* the two things the model may ask for
instead of statements: a calculation, or a crop it was only pointed at.

Without actions the statements are required: the last call of a turn has
to answer. With them a reply is either statements or an action, and
`needs` says which keys that is.

### needs

```python
def needs(shape) -> tuple
```

(key, kind, instead) the reader needs of a reply of this shape.

*key* has to be in the object, as an instance of *kind*; *instead* is a
key that stands in for it (the action of an answer that may ask for one),
or "". Read from the schema, so the schema is the one place that says it.
A reply with no shape has to be one object and nothing else: ("", object,
"").

[Back to the index](../README.md)
