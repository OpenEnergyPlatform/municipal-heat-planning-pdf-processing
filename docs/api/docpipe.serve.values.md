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

The same files say more than their values. A harvest file holds, per
parameter, a state line (`kind: parameter_state`) and the claims that were
refused (`kind: refusal`), and these are read here too, once, with the
values. A missing value is then an answer and not a silence:

    read          values of the parameter were read and accepted
    unstated      the document was read and does not carry it
    exhausted     the run ended before the document was read through
    unbacked      values were offered and refused (`refusals` says why)
    never_asked   the file has state lines, and none for this parameter
    not_recorded  the file has no state line at all: it was written before
                  states were kept

The first four are the harvest's words, as it wrote them. The last two are
not a state of the document: they say that the harvest holds none, and are
kept apart from `unstated` because "the plan does not say it" is a finding
and "nobody asked" is not. A document or a parameter the harvest does not
have at all is an error (`NotFound`), never an empty answer.

Beware the name: a tuple's own `parameter_state` key is the state of its
`parameter` coordinate, which is another thing (`coordinates`, below).

Author: Felix Vossel

## Classes

### NotFound

```python
class NotFound(LookupError)
```

A document or a parameter the harvest does not have.

### Harvest

```python
@dataclass
class Harvest
```

What a harvest directory holds, by document name (the file's name
without its ending).

Fields:

- `tuples: dict = field(default_factory=dict)`: accepted rows
- `refusals: dict = field(default_factory=dict)`: refused claims
- `states: dict = field(default_factory=dict)`: {parameter: state line}
- `unreadable: int = 0`: lines that could not be used, counted not hidden

### Values

```python
class Values
```

Every accepted value of a harvest, and what the harvest says about
the parameters that have none.

*rows_by_document* are the accepted rows; *refusals* and *states* are
what `read_harvest` found beside them. Without them every document
reads as `not_recorded` and has no refusal. *passages* is the handle of
the passage search (`passages.py`), which reads the corpus database and
not the harvest; None where there is no database.

#### Values.\_\_init\_\_

```python
def __init__(self, rows_by_document: dict, *, spec=None,
             transcribed: Iterable[str] = (),
             refusals: Optional[dict] = None,
             states: Optional[dict] = None, passages=None,
             unreadable: int = 0)
```

#### Values.load

```python
@classmethod
def load(cls, harvest_dir, *, spec=None, db=None,
         passages=None) -> "Values"
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

#### Values.states

```python
def states(self, *, document: Optional[str] = None,
           parameter: Optional[str] = None, state: Optional[str] = None,
           limit: Optional[int] = 50, offset: int = 0) -> dict
```

What the harvest says about parameters of documents, one cell
per pair, as {total, offset, states, meanings}.

With a *document* the cells are its parameters, with a *parameter*
(a name or a label) its documents, with both one cell, with neither
all of them. *state* keeps the cells in that state. `meanings` says
what each state of the page is. A document or parameter the harvest
does not have raises `NotFound`; *limit* is as in `find`.

#### Values.coverage

```python
def coverage(self, *, document: Optional[str] = None,
             parameter: Optional[str] = None,
             limit: Optional[int] = 50, offset: int = 0) -> dict
```

Documents by parameters, each cell the state of that pair:
{parameters, total, offset, documents, tally, meanings}.

`documents` is the page asked for, each as {document, states:
{parameter: state}}. `tally` counts, per parameter, the documents
in each state over all `total` documents and not only the page, so
a page of fifty still says how the whole corpus stands.

#### Values.refusals

```python
def refusals(self, *, document: Optional[str] = None,
             parameter: Optional[str] = None,
             limit: Optional[int] = 50, offset: int = 0) -> dict
```

The claims the harvest refused, as {total, offset, refusals}:
why, from which passage, and the claim as the model returned it.
`failed` is set where the claim is no claim but a request that was
not served (`unreachable`, `unserved`, `no_answer`, `cut_off`).
This is the reason behind an `unbacked` state. *parameter* may name
what only a refusal names (a claim for no parameter of the spec).

## Functions

### read_harvest

```python
def read_harvest(harvest_dir) -> Harvest
```

Read every document file of a harvest directory once.

The one place that reads the files: the values, the states and the
refusals served from here come out of the same pass, so they cannot
describe two different states of the directory. A line that is not a
JSON object, or a state line that names no parameter or no state, is
skipped, said in the log and counted in `unreadable`. Where a file
carries two state lines for one parameter the later one stands.

[Back to the index](../README.md)
