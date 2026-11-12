# profiles.kwp.blocks

`profiles/kwp/blocks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

blocks.py: The steps of a flow that only heat plans need (owner decision
2026-11-12, plan of the general blocks, point 8): what a number is, chosen
from the list of quantities, and the year of a value from the plan's base
and target years. The page offers them beside the general steps where this
profile is open (`blocks.offered`), and a flow of another profile cannot
take them.

Author: Felix Vossel

## Functions

### quantity

```python
def quantity(engine, node, scope) -> None
```

What a number is, from the words it was read with
(`addressed.Reader.quantity`).

### last_year

```python
def last_year(engine, node, scope) -> None
```

The year a value's line means, from the plan's base and target
years (`addressed.Reader.last_year`).

[Back to the index](../README.md)
