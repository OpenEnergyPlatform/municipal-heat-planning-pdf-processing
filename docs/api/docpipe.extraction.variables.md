# docpipe.extraction.variables

`docpipe/extraction/variables.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

variables.py: What the steps of a flow pass on to each other (owner
decision 2026-11-12, plan of the general blocks, points 2 and 9).

Every step of a flow takes named inputs and gives named outputs. An input
is a variable a step before it gave, or one the run starts with (the
document and the fields of the Spec); what may stand where follows from
this alone (`flow.problems`). Each variable has a JSON schema, which the
page shows and a step that asks the model fills (`ask`), and says whether
it lasts for the whole document (a list of values, the document's facts)
or only for the item it was made for (the answer to one question, the
search hits of one dimension).

A frame gives its item: "for each field" the field, "for each chunk" the
chunk, and so on (`ITEMS`). A variable a step of the page makes itself
(the output of an own question, of a Python step, of "set") is named by
that step; it lasts where the step says so ("for the whole document").

Author: Felix Vossel

## Classes

### Var

```python
@dataclass(frozen=True)
class Var
```

One variable: its *name* in the flow, what the page calls it, what
it holds (*says*), its JSON *schema*, and whether it lasts for the whole
document after the step that made it (*lasting*).

Fields:

- `name: str`
- `label: str`
- `says: str`
- `schema: dict = field(default_factory=dict)`
- `lasting: bool = False`

## Functions

### var

```python
def var(name: str) -> Optional[Var]
```

### label

```python
def label(name: str) -> str
```

### lasting

```python
def lasting(name: str, made: Optional[dict] = None) -> bool
```

Does *name* last for the whole document once a step made it? A
variable of the page lasts where its step says so (*made*: name ->
lasting).

### wanted

```python
def wanted(spec: str) -> tuple
```

(names, optional) of an input written as "a|b" (one of them) with
"?" at its end where the step does without it.

### catalogue

```python
def catalogue() -> dict
```

The variables as the page shows them.

[Back to the index](../README.md)
