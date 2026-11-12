# profiles.scenarios.blocks

`profiles/scenarios/blocks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

blocks.py: The steps of a flow that only scenario papers need (owner
decision 2026-11-12, plan of the general blocks, point 8): the works a
publication presents, compares or cites, the work of a value, and the entry
of a scenario's name in the document's list. The page offers them beside the
general steps where this profile is open (`blocks.offered`), and a flow of
another profile cannot take them.

Author: Felix Vossel

## Functions

### works

```python
def works(engine, node, scope) -> None
```

The works each chunk names, matched against the document's list of
works, and the details of each new one (`addressed.Reader.works`).

### names

```python
def names(engine, node, scope) -> None
```

The entry of the document's list each row of a value names
(`addressed.Reader.named_value`).

### work_coordinate

```python
def work_coordinate(engine, node, scope) -> None
```

The work a value belongs to (`addressed.Reader.work_coordinate`).

[Back to the index](../README.md)
