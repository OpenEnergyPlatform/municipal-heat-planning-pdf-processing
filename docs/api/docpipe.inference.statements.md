# docpipe.inference.statements

`docpipe/inference/statements.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

statements.py: Which of the statements a model made the reader is shown.

The answer of the chat is a list of statements, each with its own evidence
(`replies.answer`). A statement is shown only if its evidence stands, and the
reader is told how many were not (`back`). What a statement has to show is
the existing rule and nothing beyond it:

  text      its quote stands in the excerpt it cites, whole, and is at least
            as long as a quote has to be (`llm_client.grounded_quote`)
  image     the crop it reads off was attached to this call, or is one the
            model asked for and got, and it names what it read
            (`llm_client.visual_reading`)
  computed  its quote stands in the excerpt that holds the inputs AND the run
            it names is a run of this call that ran without an error

Whether a statement says what its quote says is reading, not a check (the
harvest's second half has no counterpart here). Nothing in this module asks
a model anything or reads a file.

Statements are carried forward as checked and never rewritten: what a later
batch is shown of the earlier ones is `texts`, and what it adds is appended.

Author: Felix Vossel

## Functions

### back

```python
def back(statements, *, items: dict, hits: list, attached: set,
         delivered: dict, runs: list, run_offset: int = 0,
         grounded=None, visual=None) -> tuple
```

(shown, dropped) of the statements a model made for one batch.

*items* maps the index of each excerpt of this batch to it, *hits* is the
retrieval list those indices point into, *attached* the indices whose crop
went with the call, *delivered* maps the block of each crop the model
asked for and got to {"hit": the passage it belongs to}, *runs* are the
code runs of this call ({"code", "output"}) and *run_offset* the number of
runs before them in the turn, so a shown run carries its number in the
turn.

A shown statement is {"text", "basis", "index", "block", "owner_kind",
"owner_id", "quote", "visual", "computed", "run", "hit"}; a dropped one is
what the model wrote and its `why` (one of `WHY`). Every statement is one
or the other: len(shown) + len(dropped) == len(statements).

*grounded* and *visual* are the checks (`llm_client.grounded_quote`,
`llm_client.visual_reading`), looked up when called so that nothing here
is bound to a copy of them.

### blocks_named

```python
def blocks_named(wrote) -> set
```

The crops the statements of a reply name as their `block`: the ones
whose passage has to be looked up before the statements are checked.

### texts

```python
def texts(shown: list) -> list
```

What a later batch is told was already said: the checked statements,
exactly as they were checked.

### citations_of

```python
def citations_of(shown: list) -> list
```

One citation per distinct (source, quote, run) over the shown
statements in order, numbered from 1; each statement gets the number of
its citation as `citation`.

The quote is part of the key: two statements from one table with two
quotes are two pieces of evidence, and a reader checking the first must
not be sent to the second. A calculated statement is a citation of its
own for each run it names.

### assemble

```python
def assemble(shown: list, marker: str, note: str) -> tuple
```

(answer, answer_text) of the shown statements.

One statement is a sentence, two or more are a list; each carries the
number of its citation. `answer_text` is the same statements without
list marks and numbers: what a follow-up and a comparison are given, so
a statement that was dropped can reach neither.

A statement read off a picture has to say so. Where one does not, the
profile's note is added once, under the answer and under its text.

[Back to the index](../README.md)
