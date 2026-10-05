# docpipe.extraction.preflight

`docpipe/extraction/preflight.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

preflight.py: A profile, everything a corpus run rests on.

Not a smoke test. Every line here failed at least once in a way that cost a
GPU run or a night: a prompt whose max_tokens was sized for a contract two
versions old, a vocabulary entry that means "I do not know" sitting where a
class belongs, an axis with no question so the field request carried no
rule.

Prints a table and exits non-zero on a hard failure, so it can stand before
a GPU run:

    docpipe preflight                   the profile in effect
    docpipe preflight kwp scenarios     these

It holds for any profile, wherever it lives. What it reads of a profile is
what the run reads: the spec the profile names (`extraction.SPEC_PATH`),
its prompts, the writer of its graph (its own `kg.make_serializer`, else
the `graph` block of the spec), its `vocabulary` module where it has one.
The keys of a request and a reply are the stage's and are checked here by
name. A wording the run depends on is the profile's, in the language of its
prompts, so the profile says which passages its prompts have to hold
(`extraction.PROMPT_CHECKS`).

Author: Felix Vossel

## Functions

### prompt_checks

```python
def prompt_checks(declared) -> tuple
```

A profile's `PROMPT_CHECKS` as (entries, what is wrong with them).

An entry is (what is checked, prompt id, passage, whether the passage
has to be there or must not be). One that is anything else is named
and not run: a check that cannot be read holds nothing.

### silent_parameters

```python
def silent_parameters(raw: dict) -> list
```

Which parameters of a raw spec say nothing about the graph.

A function rather than three lines inside `audit`, because a gate that
cannot be handed a failing input is decoration, and `audit` can only be
handed a profile's own files, which are, by the time anyone runs it, the
ones that pass.

### audit

```python
def audit(name: str) -> list
```

Every check of one profile: (profile, what, ok | warn | FAIL, detail).

Makes the profile the one in effect for this process (the environment
names it), because its prompts and its wording are read through that.

### report

```python
def report(rows: list) -> int
```

Print the table; how many checks failed hard.

### main

```python
def main(argv: Optional[list] = None) -> int
```

[Back to the index](../README.md)
