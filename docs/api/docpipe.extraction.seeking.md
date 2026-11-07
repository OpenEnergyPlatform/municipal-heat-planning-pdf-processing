# docpipe.extraction.seeking

`docpipe/extraction/seeking.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

seeking.py: A parameter the survey named no passage for, and whose walk down
the ranked list found no value, searched for by the model itself (owner
decision 2026-11-07, „genau wie Nachsuche: Erst Retrieval dann Agentisch“).

The walk reads the passages a search ranks for the parameter, one a round
(`surveyed.sought_walk`). Where its list ends without a value the check
takes, one conversation with the combing's tools (`reading.Gathered`) looks
for the passages that state one: it searches by pattern or by a sentence of
its own ("similar"), fetches hits, sections, tables and figures, and names
the passages it found by their ids. The passages the walk read are not
listed again, and the conversation ends where a round asks for nothing new.
Each passage it names is then read like any other (`reading.Reader`), so a
value it found is held to the same checks; naming a passage reads nothing by
itself. An id it names that no hit and no fetched passage of the
conversation has is told once.

Author: Felix Vossel

## Classes

### FreeSearch

```python
class FreeSearch
```

(document_id, parameter, passages, walked, budget) -> [Source], the
passages the model found for *parameter*, in the order it named them.

*ask(payload, document_id, thread, follow)* is one message of a
conversation (`thread.Thread`): the first shows *payload*, a later one
carries *follow*, what is new since the answer it follows (`FOLLOWS`);
the reply as a dict, CUT, or None. *rank(document_id, probes, exclude)*
is the plan best first for a sentence ("similar"), None where the run
ranks nothing.

#### FreeSearch.\_\_init\_\_

```python
def __init__(self, ask: Callable, *, rank: Optional[Callable] = None,
             trace=None)
```

## Functions

### response_format

```python
def response_format() -> dict
```

The passages found, each by the id the conversation showed it under,
an empty list where none, and what the reply asks of the rest of the
plan.

### example

```python
def example() -> dict
```

The reply as the prompt's example shows it, in the order of
`response_format`.

### owner_of

```python
def owner_of(gathered: Gathered, ref) -> Optional[tuple]
```

The passage an id of the conversation names: a hit ("H…") or a
passage it fetched ("M…"); None for any other.

[Back to the index](../README.md)
