# docpipe.compile.examples

`docpipe/compile/examples.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

examples.py: Proposes, from the corpus, the example a parameter still lacks.

Every parameter of a spec carries one real example: a snippet of a document
and the tuples it yields. It is the prompt's demonstration and the dry run's
test, and writing one per parameter is the heaviest part of a new spec. This
module finds candidate passages in a processed corpus, asks the model which
values of the parameter a passage states, and keeps a proposal only where
each value brings a quote that stands in the passage and contains the value.
Those are the checks every harvested value passes, and nothing else is
asked of a proposal.

A proposal is never an example. It goes into a review file beside the
draft, with the document it came from; a person reads it, sets `accept`,
and `apply` carries exactly the accepted ones into the spec. What a model
drafted becomes a demonstration only after somebody has read it.

The two things this module needs from a run are handed in: `find`, which
returns passages for a parameter, and `ask`, which returns the model's
reply for one passage. So the logic is tested without a corpus and without
a model.

Author: Felix Vossel

## Functions

### review_path

```python
def review_path(draft) -> Path
```

Where the proposals for a draft are kept: beside it and under its
name, so that two drafts in one folder do not share one file.

### reply_shape

```python
def reply_shape(numeric: bool) -> tuple
```

(name, JSON schema) of the reply to one example request.

### payload

```python
def payload(parameter: dict, passage: str) -> dict
```

What one request shows the model: the parameter as the spec writes
it, and one passage.

### checked

```python
def checked(drafted, passage: str, parameter: dict) -> tuple
```

(the tuples that carry their own evidence, [(tuple, why not)]).

The quote stands in the passage, it is long enough to name a place, and
the value stands in the quote: for a number its digits, for anything
else its wording as the document writes it (`value_raw`, else `value`).

### snippet

```python
def snippet(passage: str, quotes: list) -> str
```

The part of the passage an example shows: the quotes with what
stands around them, never more than `SNIPPET_MAX` characters. A quote
that cannot be placed letter for letter (it stands in the passage with
other spacing) is placed by nobody here: the start of the passage is
shown. Whether a quote is in what is shown is the caller's to check.

### by_rank

```python
def by_rank(ranked: list) -> list
```

Several rankings as one list: the best of each before the second
best of any. Of the passages of several documents, each document's
best is then asked about before anybody's second.

### lacking

```python
def lacking(raw_spec: dict, only: Optional[list] = None) -> list
```

The parameters a proposal is wanted for.

### propose

```python
def propose(raw_spec: dict, find: Callable, ask: Callable, *,
            only: Optional[list] = None, per_parameter: int = 2,
            passages: int = 6) -> dict
```

The review file's content: per parameter, the proposals that carry
their evidence, and a count of what was read and dropped.

### apply

```python
def apply(raw_spec: dict, review: dict) -> tuple
```

(the spec with the accepted examples, the parameters that got one,
what stands in the way). Nothing is written where something does.

### write_review

```python
def write_review(path: Path, review: dict) -> None
```

[Back to the index](../README.md)
