# profiles.kwp.blocks

`profiles/kwp/blocks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

blocks.py: What only heat plans ask (owner decisions 2026-11-12: the plan
of the general blocks, point 8, and in the evening every question is "Ask
the model" with a preset): what a number is, chosen from the list of
quantities, and the year of a value from the plan's base and target years.
The page offers the two presets beside the general ones where this profile
is open (`blocks.offered`), and a flow of another profile cannot take them.

Author: Felix Vossel

## Functions

### quantity

```python
def quantity(ask, counts)
```

What a number is, from the words it was read with: its own
designation, the head of its column and its unit (rule
`quantity_words`) go to the question of the list of quantities, asked
as this step says (`addressed.Reader.quantity`).

### plan_year

```python
def plan_year(ask, counts)
```

A year nothing found, asked last with the plan's base and target
years (owner decision 2026-11-07): the line of the value's place that
names the plan's word for its state, and the year of the list it
means; read where the words stand in that line and the year is one of
the plan's (`pipeline.named_year`).

[Back to the index](../README.md)
