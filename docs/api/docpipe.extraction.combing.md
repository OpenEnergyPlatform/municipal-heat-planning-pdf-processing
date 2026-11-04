# docpipe.extraction.combing

`docpipe/extraction/combing.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

combing.py: The coordinates the reading left open, looked for in the rest of
the plan. Step 4 of the rebuilt harvest (owner decisions 2026-11-04).

The reading asks a value's coordinates in its own passage and the text
around it, and may fetch more of the plan itself. What is still open after it
(a coordinate the passage does not state, one whose answer did not hold, one
no reply answered) is looked for here, per passage, parameter and group of
the spec that still has an open coordinate (owner decision 2026-11-04: every
request one task), the group's words for where a plan prints it shown: one
search with the passage's context (owner decision 2026-10-22: its title,
what its rows have read in the plan's words, what is asked). The best
sections, tables and figures of that search are shown as a list of titles
and first lines, and the model fetches what it wants to read with the
reading's own tools: a hit by its id, the next or the previous section, a
table or figure by its placeholder, a pattern. It answers each open
coordinate of each row with its quote, or that the plan does not state it.

Nothing is checked here. Every answer goes through `merge_field`, and what it
refuses is asked once more with the reason. A coordinate this request leaves
without an answer ends `unanswered`; one whose request no longer fits the
model's window ends `exhausted`; `unstated` is now a finding about the plan.

A pass over a stored harvest combs with the same requests
(`Comber.comb_groups`): the coordinates it names (*coordinates*) whatever
their state, one request per group, the value's own passage and its section
shown first (*own*), since the reading that asked them there ran under an
older question, the years of the stored rows
(*bases*), and the passages a harvest before read the coordinate in listed
before the search's hits (*first*).

Author: Felix Vossel

## Classes

### Combed

```python
@dataclass
class Combed
```

What combing the open coordinates of one passage came to.

Fields:

- `parameter: str`
- `owner: tuple`
- `rows: int`
- `open: int`: coordinates open before
- `filled: int = 0`: read by this step
- `asked: int = 0`
- `hits: int = 0`: hits of the search shown
- `fetched: int = 0`
- `searched: int = 0`
- `missed: int = 0`
- `corrected: int = 0`
- `exhausted: int = 0`
- `group: Optional[str] = None`: the group of the spec asked

### Comber

```python
class Comber
```

(document_id, reads, passages, pairs, budget) -> [Combed], one per
passage and parameter whose read values have an open coordinate.

*ask(payload, shape, document_id, source, group)* is one request: the
reply as a dict, CUT, or None, *group* the name of the group of the spec
it asks, for its trace. *rank(document_id, probes, exclude)* is the plan's
passages best first for the search sentences *probes*
(`runner.make_more_sources`), *probes(rows, asked, owner_of, label)* the
sentence of a passage (`runner.context_probes`), *known(claim, asked)*
what a row has read in the plan's words (`runner.row_context`).

#### Comber.\_\_init\_\_

```python
def __init__(self, spec, ask: Callable, rank: Callable,
             probes: Callable, known: Callable, *,
             bases: Optional[Callable] = None, pool=None, trace=None)
```

#### Comber.comb_groups

```python
def comb_groups(self, document_id: int, parameter, source, slots: list,
                claims: list, passages: dict, pairs: list,
                budget: Optional[int] = None, *,
                coordinates: Optional[list] = None, own: bool = False,
                bases: Optional[tuple] = None,
                first: Optional[list] = None) -> list
```

`comb` once per group of the spec that has something to ask: with
*coordinates* the group's share of them, else a coordinate open on
one of *claims*. [Combed], one per group asked.

#### Comber.comb

```python
def comb(self, document_id: int, parameter, source, slots: list,
         claims: list, passages: dict, pairs: list,
         budget: Optional[int] = None, *,
         coordinates: Optional[list] = None, own: bool = False,
         bases: Optional[tuple] = None,
         first: Optional[list] = None, group=None) -> Combed
```

The open coordinates of *claims*, values of *parameter* read in
*source*, answered in place; with *coordinates* those of every row,
open or not. *own* shows *source* and its section before the first
request, *bases* are the years a row may name by a word (instead of
those of *pairs*), *first* passages listed before the search's
hits, *group* the group of the spec *slots* belong to, whose words
for where a plan prints them the request shows.

## Functions

### open_of

```python
def open_of(claim: dict, slots: list) -> list
```

The coordinates of a value still open after its reading.

### shown_hits

```python
def shown_hits(ranked: list) -> list
```

The best of each kind of a ranked search, in its order (`SHOWN`).

### comb_response_format

```python
def comb_response_format(slots: list, labels: list) -> dict
```

Each row of *labels* with every coordinate asked, and what the reply
asks of the rest of the plan.

[Back to the index](../README.md)
