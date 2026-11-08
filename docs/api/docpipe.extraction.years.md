# docpipe.extraction.years

`docpipe/extraction/years.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

years.py: A plan's own years, asked once per plan: the year it takes its own
state in and the year of its target (owner decision 2026-11-06).

A value whose passage names the plan's state by the plan's word ("Basisjahr",
"Ist-Zustand", "Zieljahr") and prints no year takes one of these years
(`pipeline.named_year`). They came from the survey's pairs of single pages,
and a profile sheet's pair "Bestand 2040" put 2030 to 2045 among the base
years. One request per plan now asks for them, each with a quote that prints
it; the pairs of single pages no longer count.

The request lists the passages the survey found a pair of either state in,
else the plan's first passages, and has the combing's tools
(`reading.Gathered`): it reads what it asks for, and a round that asks for
nothing new while a state has no year gets the next passages of the plan,
until every passage was listed. Each year is checked as any coordinate is:
its quote stands in what the request showed, is long enough, and prints the
year; what fails is told once, by its state.

Author: Felix Vossel

## Classes

### PlanYears

```python
class PlanYears
```

(document_id, passages, pairs, budget) -> the plan's base and target
years as `pipeline.named_years` gives them ({"state", "axis", "year",
"quote", "source", "index"}), [] where none holds.

*ask(payload, document_id, thread, follow)* is one message of a
conversation (`thread.Thread`): the first shows *payload*, a later one
carries *follow*, what is new since the answer it follows (`FOLLOWS`,
owner decisions 2026-11-07); the reply as a dict, CUT, or None.
*frame_slots* are the coordinates the survey reads per passage, one of
them the year; *states* what the profile says makes a pair of the survey
that state (`runner.year_states_of`), which only says where the request
starts to look. *rank(document_id, probes, exclude)* is the plan best
first for a sentence ("similar"), None where the run ranks nothing.

#### PlanYears.\_\_init\_\_

```python
def __init__(self, ask: Callable, frame_slots: list,
             states: Optional[dict], *, rank: Optional[Callable] = None,
             trace=None)
```

#### PlanYears.first

```python
def first(self, order: list, passages: dict, pairs: list) -> list
```

The passages the survey found a pair of either state in, in the
plan's order; the plan's first passages where it found none.

#### PlanYears.checked

```python
def checked(self, reply, evidence: list) -> tuple
```

([named year], [correction]) of a reply: each year whose quote
stands in what the request showed, is long enough and prints it; one
correction per year that does not, by its state.

## Functions

### response_format

```python
def response_format() -> dict
```

The years of each state, each a year and the quote that prints it,
an empty list where the plan names none, and what the reply asks of the
rest of the plan.

### example

```python
def example() -> dict
```

The reply as the prompt's example shows it: a year of each state with
its quote, and an ask for more, in the order of `response_format`. A
year is its placeholder, never a year the model could copy (owner
decision 2026-11-07: "mach das Beispiel mit YYYY").

### found_all

```python
def found_all(reply) -> bool
```

Does *reply* name a year of every state?

[Back to the index](../README.md)
