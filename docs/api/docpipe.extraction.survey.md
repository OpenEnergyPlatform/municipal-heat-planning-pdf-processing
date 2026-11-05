# docpipe.extraction.survey

`docpipe/extraction/survey.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

survey.py: One pass over the whole plan before any number is read.

The plan is cut into small contexts, at most one figure and at most the text
of two of its pages each, and every passage of every context is answered:
the parameters whose numbers stand in it, with a quote, or none of them.
The same request names the tuples of the groups the spec reads here (a
scenario and its year), each coordinate with its own quote. A parameter is
then read in its own passages, and a number takes its frame from its passage,
without a search (owner decision 2026-11-04).

This replaces four steps of the harvest before it: the anchors written to
search with, the frame read from the best-ranked passages, the map of places
built at the first search, and most of the search for open coordinates. On
Rendsburg in corpus_m8_100 those were 60, 31, 112 and 833 requests, and the
frame saw 12 passages and found three pairs while the rows later carried six.

Checked is what every reading is checked for: an assignment's quote stands
in its own passage and is long enough to name a place there; a tuple is held
to `runner.frame_pairs`, the frame's own check.

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
- `quote: Optional[str] = None`
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
- `hits: dict = field(default_factory=dict)`: (parameter uri, owner kind, owner id) -> [Source]: the ranked list a search of the whole plan for that parameter named the passage from, which every request of the passage's reading for it shows first (`reading._Job.gathered`). A list belongs to the question it was searched for: another parameter read in the same passage shows none.

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

*ask(context, document_id, corrections)* is one request: the reply as a
dict, CUT, or None when it could not be read. A reply with something not
taken is asked once more with what was wrong (`corrections_of`), and
what either reply backs is taken. *passages_of(document_id)* is every
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
def budget_of(passages: list, pages: Optional[int]) -> int
```

The text of two pages of this plan, in characters: twice its mean.

A figure's description is not counted: a context holds one figure,
whatever its description's length.

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

The passages in document order, packed into contexts of at most one
figure and at most *budget* characters of text.

A passage longer than the budget is cut into pieces of the budget, each
a context of its own, and every piece keeps its passage's owner.

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
def payload(context: list, parameters: dict, groups: dict,
            corrections: Optional[list] = None) -> dict
```

### corrections_of

```python
def corrections_of(answers: list, unanswered: list, context: list) -> list
```

What was wrong with a reply over *context*, one sentence each, for
the request that asks it again: a quote not in its passage or too short,
a tuple not taken, a passage not answered. Empty when nothing was.

### response_format

```python
def response_format(context: list, parameters: dict, slots: dict) -> dict
```

The reply as a server grammar: one entry for EVERY passage of the
context, its parameters from the list or NONE, a quote, and the tuples
of each group the survey reads.

### read_reply

```python
def read_reply(reply: dict, context: list, parameters: dict, slots: dict,
               pairs_of: Callable) -> tuple
```

([Answer], passages unanswered) of one context's reply.

A passage's parameters are taken when their quote stands in that passage
and is long enough to name a place there; NONE beside a parameter says
nothing. A tuple is taken when *pairs_of* (`runner.frame_pairs`) takes
it over the passages shown. Nothing else is checked.

### merge

```python
def merge(found: Found, answers: list) -> None
```

Fold the answers of one context into the document's: pieces of one
passage add up, a tuple counts once.

[Back to the index](../README.md)
