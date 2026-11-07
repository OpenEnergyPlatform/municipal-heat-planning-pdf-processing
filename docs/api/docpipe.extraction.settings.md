# docpipe.extraction.settings

`docpipe/extraction/settings.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

settings.py: What a plan settles for all its values, asked once per plan:
its settings, each in the plan's own words and with its quote (owner
decisions 2026-11-07, „Ja, je Plan (Empfohlen)“, both profiles).

A plan says once what holds for all its numbers: "Das Basisjahr ist das Jahr
2022.", that "CO2-Emissionen" include the CO2 equivalents, the unit of the
consumptions in a table. Asked of every value on its own, such a sentence
pages away was not shown, and the coordinate stayed open. One request per
plan now reads them, free settings in the plan's words, each {about, value,
quote}, without a list and without saying which coordinate one belongs to:
that is the reading's to decide, by meaning, where it is shown the settings
beside a value (`reading.text_payload`, `combing.Comber`), and an answer may
quote one.

The request lists the plan's passages in its order, a page of each kind at a
time, and has the combing's tools (`reading.Gathered`): it reads what it asks
for, and a round that asks for nothing new gets the next passages of the
plan, until every passage was listed. Each setting is checked as any answer
is: its quote stands in what the request showed, is long enough, and holds
what it is about and what it settles; what fails is told once.

Author: Felix Vossel

## Classes

### PlanSettings

```python
class PlanSettings
```

(document_id, passages, budget) -> the plan's settings, each
{"about", "value", "quote", "source"}, [] where none holds.

*ask(payload, document_id, thread, follow)* is one message of a
conversation (`thread.Thread`): the first shows *payload*, a later one
carries *follow*, what is new since the answer it follows (`FOLLOWS`);
the reply as a dict, CUT, or None. *rank(document_id, probes, exclude)*
is the plan best first for a sentence ("similar"), None where the run
ranks nothing.

#### PlanSettings.\_\_init\_\_

```python
def __init__(self, ask: Callable, *, rank: Optional[Callable] = None,
             trace=None)
```

#### PlanSettings.checked

```python
@staticmethod
def checked(reply, evidence: list) -> tuple
```

([setting], [correction]) of a reply: each setting whose quote
stands in what the request showed, is long enough and holds what it
is about and what it settles; one correction per setting that does
not.

## Functions

### response_format

```python
def response_format() -> dict
```

The plan's settings, each what it is about, what it settles and its
quote, an empty list where the plan settles nothing for all its values,
and what the reply asks of the rest of the plan.

### example

```python
def example() -> dict
```

The reply as the prompt's example shows it: one setting with its
quote, and an ask for more, in the order of `response_format`.

[Back to the index](../README.md)
