# docpipe.extraction.survey

`docpipe/extraction/survey.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

survey.py: What a stored order of a plan says each field was read in.

The order of a plan's pieces for each field is made and kept by
`addressed.Orders` (`survey/<document>[.<scope>].json`, owner decisions
2026-11-08). The passes over a stored harvest read from these files which
passages each field was read in (`surveyed.surveyed_owners`), the files of
older harvests included, which also kept what their survey said of a
passage's frame.

Author: Felix Vossel

## Classes

### Answer

```python
@dataclass
class Answer
```

The fields one passage is read for. *tuples* and *dropped* are what a
stored survey of an older flow said of the passage's frame, read back by
the passes over its harvest.

Fields:

- `owner: tuple`
- `parameters: list`
- `tuples: dict = field(default_factory=dict)`: group -> [tuple]
- `dropped: list = field(default_factory=list)`

### Found

```python
@dataclass
class Found
```

The passages of one document each field is read in.

Fields:

- `complete: bool`
- `answers: dict = field(default_factory=dict)`: owner -> Answer
- `unanswered: list = field(default_factory=list)`
- `order: dict = field(default_factory=dict)`: field uri -> its owners best first; a field without one is read in the plan's order.

#### Found.passages_of

```python
def passages_of(self, parameter: str) -> list
```

The owners *parameter* is read in: best first where they were
ranked, else in the order of the document or the reverse (rule
`survey_fallback_order`).

[Back to the index](../README.md)
