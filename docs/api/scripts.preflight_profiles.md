# scripts.preflight_profiles

`scripts/preflight_profiles.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

preflight_profiles.py – Both profiles, everything a corpus run rests on.

Not a smoke test. Every line here failed at least once in a way that cost a
GPU run or a night: a prompt whose max_tokens was sized for a contract two
versions old, a vocabulary entry that means "I do not know" sitting where a
class belongs, a job script pointing at an index file that is not there, an
axis with no question so the field request carried no rule.

Prints a table and exits non-zero on the first hard failure, so it can stand
before a GPU run. Run it for one profile or both:

    python scripts/preflight_profiles.py
    python scripts/preflight_profiles.py kwp

Author: Felix Vossel

## Functions

### check

```python
def check(profile: str, what: str, ok: bool, detail: str = "", fatal=True)
```

### audit

```python
def audit(profile: str) -> None
```

### silent_parameters

```python
def silent_parameters(raw: dict) -> list
```

Which parameters of a raw spec say nothing about the graph.

A function rather than three lines inside `audit`, because a gate that
cannot be handed a failing input is decoration, and `audit` can only be
handed the repository's own files -- which are, by the time anyone runs
it, the ones that pass.

### main

```python
def main(argv: list) -> int
```

[Back to the index](../README.md)
