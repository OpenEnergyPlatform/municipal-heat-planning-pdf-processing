# docpipe.serve.values

`docpipe/serve/values.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

values.py: The harvested values of a corpus, as something that can be asked.

A harvest is one JSONL file per document, written for the run that made it.
Whoever wants a number out of it (a table, another program, an assistant,
the chat) wants the same few things: which documents, which parameters,
the values that match, and for each one what backs it. This module is that
one reading of a harvest, and the export, the HTTP API, the MCP server and
the chat all answer from it, so they cannot say different things.

A value is served as the harvest holds it, with what the harvest knows
about it and nothing added:

    id            its name (`identity.tuple_ids`): the document, the quote
                  and the value as written. The same after a new build of
                  the database and after a new harvest that reads the same.
    value, unit   as read, and converted into the parameter's unit where
                  the harvest did that
    coordinates   each with what was read, the wording it was read from and
                  how the reading ended (`fields.py`)
    quote, page   the words of the document the value stands in, and where
    level         A, B or C with the reasons (`trust.py`)

Nothing is filtered: a value of level C is served like one of level A, and
says that it is one. Leaving a level out is the asker's decision
(`level="B"` asks for B and better).

Author: Felix Vossel

## Classes

### Values

```python
class Values
```

Every accepted value of a harvest.

#### Values.\_\_init\_\_

```python
def __init__(self, rows_by_document: dict, *, spec=None,
             transcribed: Iterable[str] = ())
```

#### Values.load

```python
@classmethod
def load(cls, harvest_dir, *, spec=None, db=None) -> "Values"
```

#### Values.get

```python
def get(self, name: str) -> Optional[dict]
```

#### Values.documents

```python
def documents(self) -> list
```

Every document with a value, and how many it has.

#### Values.parameters

```python
def parameters(self) -> list
```

Every parameter the harvest has a value of: how many, in how
many documents, in which units and with which coordinates. Under
`coordinates` each one lists what was read there and how often, so
an asker sees what can be asked for before asking.

#### Values.find

```python
def find(self, *, document: Optional[str] = None,
         parameter: Optional[str] = None, level: Optional[str] = None,
         coordinates: Optional[dict] = None, text: Optional[str] = None,
         limit: Optional[int] = 50, offset: int = 0) -> dict
```

The values that match everything asked for, as {total, values}.
*limit* None is every one of them, for a caller that writes a
file; a number is held to `MAX_LIMIT`, which is what one answer of
a server carries.

*parameter* is a parameter's name or its label. *level* is the
worst level still wanted. A coordinate is asked for by what was
read there or by its label. *text* is looked for in the quote, the
label and the wordings, without regard to case.

[Back to the index](../README.md)
