# docpipe.extraction.compute

`docpipe/extraction/compute.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

compute.py: The numbers a plan does not print and its printed numbers yield.

The rows request copies what stands in a passage, and from where it stands
nothing is ever missing: of six cases its prompt took the sandbox in none, a
request of its own naming the number wanted in four. A tool is used where a
question stands open. So once a document is folded, its verified rows are gone
through for what they leave open, each open question gets a request of its
own, and the model works the number out in the sandbox with the tables handed
over, as in the chat (owner decision 2026-11-02).

Which questions stand open is the profile's (`compute.py` of the profile,
`questions`), because the core names no coordinate. This module holds what
every such question has: what the request shows, what the sandbox is handed,
and the row that comes of the answer. That row is a claim like any other: it
goes through `verify_tuple` under the quote of one of its numbers, and a number
that is not in the code's output is refused (`computed_in_output`), as is one
its inputs do not make (`computed_from_inputs`, owner decision 2026-11-03).

## Classes

### Number

```python
@dataclass
class Number
```

A verified row as a question shows it, in the unit the question works
in. *known* is what was read about it, in the plan's words.

Fields:

- `row: dict`
- `value: float`
- `unit: str`
- `known: dict`

### Question

```python
@dataclass
class Question
```

One number a document leaves open.

*wanted* says what is asked, in the request. *numbers* are what it may be
worked out from, named N1, N2, ... in this order. *anchor* is the number
whose quote and passage the new row stands under. *row* makes the new
row's coordinates from the rows the answer used, None where they do not
yield one. *makes* is what the numbers the answer used make, in the new
row's unit: the number the answer has to be, None where they make none.

Fields:

- `kind: str`
- `wanted: dict`
- `numbers: list`
- `anchor: dict`
- `row: Callable`
- `makes: Callable`

## Functions

### label

```python
def label(index: int) -> str
```

### labels

```python
def labels(question: Question) -> list
```

### owner_of

```python
def owner_of(row: dict) -> tuple
```

### item_of

```python
def item_of(items: dict, row: dict)
```

The work item this row stands in: a long passage is read in pieces,
and the row's quote says which.

### passages

```python
def passages(question: Question, items: dict) -> list
```

The passages the numbers stand in, each once, in the numbers' order.

### payload

```python
def payload(question: Question, shown: list) -> dict
```

The request: what is wanted, the numbers and their passages.

### context

```python
def context(question: Question, shown: list) -> dict
```

What the sandbox is handed: the numbers, every passage as the rows
request hands them, and the tables as the chat hands them.

### used_numbers

```python
def used_numbers(question: Question, answer: dict) -> list
```

The numbers the answer says it used, all of them if it names none.

### claim_of

```python
def claim_of(question: Question, value, used: list,
             runs: list) -> Optional[dict]
```

The new row: coordinates from its numbers, the code and its output as
evidence, and the numbers it was worked out from with their passages and
what they make. The last run is the one the answer stands on.

### keys_of

```python
def keys_of(row: dict, *axes: str) -> dict
```

These coordinates of a row with all their evidence.

### inherited

```python
def inherited(row: dict, *leaving: str) -> dict
```

The coordinates a row worked out from this one takes, *leaving* out
these axes.

[Back to the index](../README.md)
