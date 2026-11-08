# docpipe.extraction.survey

`docpipe/extraction/survey.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

survey.py: The passages each parameter of a plan is read in, best first.

Every passage of the plan is read for every parameter (owner decisions
2026-11-08). The survey this replaces asked the model, per passage, which
parameters stand in it, and read a parameter only where it was named: on
one plan it named none for 34 of the 207 passages two runs both surveyed
where the run before had named one, and about 120 values were never asked.
What is left is the order: for each parameter the reranker ranks the whole
plan with the parameter's search sentences (its HyDE sentences,
`runner.make_seek_probes`), and its passages are read in that order, a
passage the search did not return after them in the plan's order. Nothing
is left out for its rank.

The order of a document is kept (`survey/<document>.json`) under a key over
the parameters, with the passages it ranked. An order of part of a plan (the
passages a harvest before found something in, the rest of a plan, the
parameters a spec gained) is kept beside it under its own scope
(`survey/<document>.<scope>.json`), so that neither is taken for the other;
the passes over a stored harvest read from these files what was read
(`surveyed.surveyed_owners`).

Author: Felix Vossel

## Classes

### Answer

```python
@dataclass
class Answer
```

The parameters one passage is read for. *tuples* and *dropped* are
what a stored survey of the flow before this one said of the passage's
frame, read back by the passes over its harvest.

Fields:

- `owner: tuple`
- `parameters: list`
- `tuples: dict = field(default_factory=dict)`: group -> [tuple]
- `dropped: list = field(default_factory=list)`

### Found

```python
@dataclass
class Found
```

The passages of one document each parameter is read in.

Fields:

- `complete: bool`
- `answers: dict = field(default_factory=dict)`: owner -> Answer
- `unanswered: list = field(default_factory=list)`
- `order: dict = field(default_factory=dict)`: parameter uri -> its owners best first (`Ranking`); a parameter without one is read in the plan's order.

#### Found.passages_of

```python
def passages_of(self, parameter: str) -> list
```

The owners *parameter* is read in: best first where they were
ranked, else in document order.

#### Found.tuples_at

```python
def tuples_at(self, owner: tuple, group: str) -> list
```

### Ranking

```python
class Ranking
```

document_id -> Found: every passage of the document for every
parameter of *parameters*, each parameter's passages best first.

*rank(document_id, sentences, exclude)* is the whole plan best first
for search sentences (the run's search with its reranker), *probes(
parameter, document_id)* the parameter's sentences, its label where it
has none. *passages_of(document_id)* is every passage of the document in
its order. *store* is where orders are kept, *scope* the name of an
order of part of a plan beside the whole one's.

#### Ranking.\_\_init\_\_

```python
def __init__(self, rank: Optional[Callable], passages_of: Callable,
             parameters: list, *, probes: Optional[Callable] = None,
             store: Optional[Path] = None, scope: str = "", trace=None)
```

## Functions

### budget_of

```python
def budget_of(passages: list, pages: Optional[int], span: int = 2) -> int
```

The text of *span* pages of this plan, in characters: *span* times
its mean; two pages unless said otherwise.

A figure's description is not counted: a figure is never cut, whatever
its description's length.

### pieces

```python
def pieces(text: str, budget: int) -> list
```

*text* in pieces of at most *budget* characters, cut at a line end
where one stands in the second half of the piece.

### key_of

```python
def key_of(parameters: list) -> str
```

The key an order is kept under: the parameters it ranked, each with
the words its search sentences are written from.

### merge

```python
def merge(found: Found, answers: list) -> None
```

Fold *answers* into the document's: the parameters of one passage
add up, a tuple counts once.

### ranked_owners

```python
def ranked_owners(ranked: list, passages: list) -> list
```

The owners of *passages*, those *ranked* returned first in its order,
the rest after them in the order of *passages*: every passage once.

[Back to the index](../README.md)
