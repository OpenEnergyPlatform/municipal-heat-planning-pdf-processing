# profiles.scenarios.blocks

`profiles/scenarios/blocks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

blocks.py: What only scenario papers ask (owner decisions 2026-11-12: the
plan of the general blocks, point 8, and in the evening every question is
"Ask the model" with a preset): the works a publication presents, compares
or cites, the work of a value, and the entry of a scenario's name in the
document's list. The page offers the presets beside the general ones where
this profile is open (`blocks.offered`), and a flow of another profile
cannot take them.

Author: Felix Vossel

## Functions

### works

```python
def works(ask, counts)
```

The works the document presents, compares or cites beside itself
(owner decisions 2026-11-08, h, and 2026-11-09): every piece asked once
which of its lines speak of another work and which line shows the rest
are this publication's own, kept for the values found in it
(`Plan.works_of`, `inherit_work`); each name of a work asked against
the document's list of works, piece by piece in the plan's order, and
each new work asked at its line for what the profile asks of a work
(its title, its organisation, its year, its short name), side by side:
values of that work, never of this publication, which the graph does
not take.

### work_of_value

```python
def work_of_value(ask, counts)
```

The work of one value (owner decisions 2026-11-09): the work of the
line it stands in where its piece's work request named one
(`inherit_work`), else asked as an entry of the document's list of
works with the value's line, the headings and the title page, the
answer the entry and the line that shows it; 0 leaves it `unstated`,
and it is never searched. What does not hold is asked again with its
reason (as often as the flow says), then stays `unbacked`.

### value_names

```python
def value_names(ask, counts)
```

The entry of the document's list each row of a value names, a new
one where it is not on the list yet (`addressed.Reader.named_value`),
asked as this step says.

[Back to the index](../README.md)
