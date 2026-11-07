# docpipe.extraction.survey

`docpipe/extraction/survey.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

survey.py: One pass over the whole plan before any number is read.

Every passage of the plan is a request of its own, a passage longer than the
text of one of its pages cut into pieces of a page (owner decisions
2026-11-06), and every passage is answered: the parameters whose values stand
in it, or none of them. The reply is that passage's entry alone, with no
wrapper and no id: the request shows one passage, so the model has nothing to
key its answer by (owner decision 2026-11-06). The survey only
names them, without a quote (owner decision 2026-11-06): it decides which
passages a parameter is read in, and the reading checks every value it reads
there. The same request names the tuples of the groups the spec reads here
(a scenario and its year), each coordinate with its own quote. A parameter is
then read in its own passages, and a number takes its frame from its passage,
without a search (owner decision 2026-11-04).

This replaces four steps of the harvest before it: the anchors written to
search with, the frame read from the best-ranked passages, the map of places
built at the first search, and most of the search for open coordinates. On
Rendsburg in corpus_m8_100 those were 60, 31, 112 and 833 requests, and the
frame saw 12 passages and found three pairs while the rows later carried six.

A parameter named for a passage is taken as named. A tuple is held to
`runner.frame_pairs`, the frame's own check.

The survey of a document is kept (`survey/<document>.json`) under a key over
the prompt, the parameters, the groups and the model. A survey of part of a
plan (the passages a harvest before found something in, the rest of a plan,
the parameters a spec gained) is kept beside it under its own scope
(`survey/<document>.<scope>.json`), so that neither is taken for the other.

Author: Felix Vossel

## Classes

### Answer

```python
@dataclass
class Answer
```

What the survey says of one passage.

Fields:

- `owner: tuple`
- `parameters: list`: taken, in the reply's order
- `tuples: dict = field(default_factory=dict)`: group -> [tuple]
- `dropped: list = field(default_factory=list)`: why something was not taken

### Found

```python
@dataclass
class Found
```

The survey of one document.

Fields:

- `complete: bool`
- `answers: dict = field(default_factory=dict)`: owner -> Answer
- `unanswered: list = field(default_factory=list)`
- `walked: dict = field(default_factory=dict)`: (parameter uri, owner kind, owner id) -> place from 1: each passage the walk down a search's list read a parameter in, with its place in that list, in the order read (`surveyed.sought_walk`, `walks_of`).

#### Found.passages_of

```python
def passages_of(self, parameter: str) -> list
```

The owners the survey named for *parameter*, in document order.

#### Found.tuples_at

```python
def tuples_at(self, owner: tuple, group: str) -> list
```

### Survey

```python
class Survey
```

document_id -> Found.

*ask(context, document_id, thread, follow)* is one message of a
conversation (`thread.Thread`): the reply as a dict, CUT, or None when
it could not be read. A reply with something not taken is followed by
what was wrong (`corrections_of`, owner decisions 2026-11-07), and what
either reply backs is taken. *passages_of(document_id)* is every
passage of the document in its order, *pages_of(document_id)* its page
count. *pool* runs a document's requests side by side (None: one after
another). *store* is where surveys are kept, *scope* the name of a
survey of part of a plan beside the whole one's.

#### Survey.\_\_init\_\_

```python
def __init__(self, ask: Callable, passages_of: Callable,
             pages_of: Callable, parameters: dict, slots: dict,
             pairs_of: Callable, key: str, *,
             store: Optional[Path] = None, scope: str = "",
             pool=None, trace=None)
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

### contexts_of

```python
def contexts_of(passages: list, budget: int) -> list
```

The passages in document order, each a context of its own (owner
decision 2026-11-06: one passage per request).

A passage whose text is longer than *budget* characters is cut into
pieces of the budget, each a context of its own, and every piece keeps
its passage's owner. A figure is never cut: its description is not
counted, whatever its length.

### one_passage

```python
def one_passage(context: list)
```

The one passage of a survey context (`contexts_of`); a context of any
other size is a mistake of the caller, not something to answer.

### tuple_slots

```python
def tuple_slots(spec) -> dict
```

{group name: its slots} for every group the survey reads.

### listed

```python
def listed(slot) -> Optional[dict]
```

A closed slot's list as the request shows it, without the out:
entries and without "not stated": a tuple the passages do not print is
left out, not answered.

### parameters_of

```python
def parameters_of(spec) -> dict
```

{uri: {label, definition}} of every parameter, as the survey shows
them.

### groups_shown

```python
def groups_shown(spec) -> dict
```

{group name: {where, coordinates}} of the groups the survey reads,
each coordinate with its list where it has one.

### key_of

```python
def key_of(prompt_text: str, parameters: dict, groups: dict,
           model: str) -> str
```

### payload

```python
def payload(context: list, parameters: dict, groups: dict) -> dict
```

One request: its one passage under "source", without an id, the
title and head of the table right before it, which a table may continue
("table_before", `lookup.continued`, owner decision 2026-11-06), the
parameters and the groups. What was wrong with its answer follows that
answer in the same conversation (`FOLLOWS`, owner decisions
2026-11-07).

### corrections_of

```python
def corrections_of(answers: list, unanswered: list) -> list
```

What was wrong with the reply about one passage, one sentence each,
for the request that asks it again: a tuple not taken, or no list of
parameters. Empty when nothing was.

### response_format

```python
def response_format(parameters: dict, slots: dict) -> dict
```

The reply about one passage as a server grammar: its parameters from
the list or NONE, and the tuples of each group the survey reads, at the
top with no wrapper (owner decision 2026-11-06).

### example

```python
def example(slots: dict) -> dict
```

The reply about one passage as the example of its request shows it:
exactly the keys `response_format` asks, in its order (owner decisions
2026-11-06): a parameter named, and one tuple of each group the survey
reads, every coordinate of it read (`fields.value_example`) with its
quote and its printed wording.

### read_reply

```python
def read_reply(reply: dict, context: list, parameters: dict, slots: dict,
               pairs_of: Callable) -> tuple
```

([Answer], passages unanswered) of the reply about a context's one
passage: the reply is that passage's entry itself (`response_format`).

The parameters are taken as the reply names them, those of the spec
only; NONE beside a parameter says nothing. A reply that is no object or
has no list under "parameters" leaves the passage unanswered. A tuple is
taken when *pairs_of* (`runner.frame_pairs`) takes it over the passage
shown. Nothing else is checked.

### merge

```python
def merge(found: Found, answers: list) -> None
```

Fold the answers of one context into the document's: pieces of one
passage add up, a tuple counts once.

[Back to the index](../README.md)
