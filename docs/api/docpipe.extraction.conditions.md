# docpipe.extraction.conditions

`docpipe/extraction/conditions.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

conditions.py: The conditions a flow's boxes and frames are set with, as
`docpipe edit` writes them (owner decisions 2026-11-10 evening: the flow is
a free drawing, its conditions written in the page, no JSON typed).

A condition is one row or several; each row says [what it is about] [which
of its properties] [a comparison] [a value], and may be negated ("not").
All rows are joined by "and", or all by "or":

    {"all": [{"of": "quote", "is": "length", "op": "less", "value": 20}]}
    {"any": [{"of": "coordinate", "is": "state", "op": "one_of",
              "value": ["read"]},
             {"of": "coordinate", "is": "state", "op": "one_of",
              "value": ["unbacked"]}]}

What a row can be about, and each thing's properties, the code provides
(`SUBJECTS`); the page offers only what there is at a box's place (`where`
of the flow). A property is a yes or no (`yes`, no comparison), a number
(`is`, `is_not`, `less`, `more`, `at_least`, `at_most`), a text (`is`,
`contains`, `empty`) or one of a list (`one_of`).

`problems` says why a condition cannot be evaluated where it stands: a row
about something there is not yet at that place (a quote before the first
question), a comparison its property does not take, a value of the wrong
kind, a value missing. `holds` evaluates a condition against what the run
knows at that place (`Facts`), and `sentence` says it as the page shows it
at its box ("when the quote is shorter than 20 characters").

"open" as a state of a coordinate means what `--top-up-open` reads again:
the states of the rule `open_states` (exhausted, unanswered, unbacked
unless a step says otherwise); "none" that it has no state yet.

Author: Felix Vossel

## Classes

### ConditionError

```python
class ConditionError(ValueError)
```

A condition that cannot be evaluated where it stands.

### Prop

```python
@dataclass(frozen=True)
class Prop
```

One property of a thing a condition can be about.

Fields:

- `name: str`
- `kind: str`
- `label: str`
- `choices: tuple = ()`
- `words: Optional[dict] = None`: choice -> what the page shows

### Subject

```python
@dataclass(frozen=True)
class Subject
```

A thing a condition can be about, and its properties.

Fields:

- `name: str`
- `label: str`
- `props: tuple`

#### Subject.prop

```python
def prop(self, name: str) -> Optional[Prop]
```

### Facts

```python
class Facts
```

What the run knows at one place: *get(subject, property)* -> the
value, a LookupError where the place does not know it.

#### Facts.\_\_init\_\_

```python
def __init__(self, get: Callable)
```

## Functions

### open_states

```python
def open_states() -> tuple
```

The states "open" stands for (rule `open_states`), as the step that
runs reads it.

### row_problem

```python
def row_problem(row, where) -> Optional[str]
```

Why one row cannot be evaluated at a place that knows the things
*where* (names of `SUBJECTS`), None where it can.

### problems

```python
def problems(condition, where=None) -> list
```

Why *condition* cannot be evaluated at a place that knows the things
*where* (None: anywhere), [] where it can.

### subjects_of

```python
def subjects_of(condition) -> set
```

The things a condition is about.

### holds

```python
def holds(condition, facts: Facts) -> bool
```

Does *condition* hold for what *facts* know? ConditionError where it
cannot be evaluated (`problems`).

### row_sentence

```python
def row_sentence(row: dict) -> str
```

### sentence

```python
def sentence(condition) -> str
```

The condition as a box shows it: "when the quote's length is less
than 20".

### one

```python
def one(of: str, is_: str, op: Optional[str] = None, value=None,
        no: bool = False) -> dict
```

One row, for the code that writes a condition.

### catalogue

```python
def catalogue() -> list
```

Every thing a condition can be about with its properties, as the
page offers them.

[Back to the index](../README.md)
