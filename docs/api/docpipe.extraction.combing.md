# docpipe.extraction.combing

`docpipe/extraction/combing.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

combing.py: The coordinates the reading left open, looked for in the rest of
the plan. Step 4 of the rebuilt harvest (owner decisions 2026-11-04).

The reading asks a value's coordinates in its own passage and the text
around it, and may fetch more of the plan itself. What is still open after it
(a coordinate the passage does not state, one whose answer did not hold, one
no reply answered) is looked for here, per value and group of the spec that
still has an open coordinate (owner decisions 2026-11-04 and 2026-11-05:
every request one task and one value), the group's words for where a plan
prints it shown. The search ranks the plan with the sentences the reading
wrote to the coordinates it found unstated, as the plan would print them
(owner decision 2026-11-05: HyDE, `Read.probes`), those of the coordinates
asked here; the best sections, tables and figures of that ranking are shown
as a list of titles and first lines. Where no coordinate asked has a
sentence, one whose answer did not hold or that no reply answered, the
request shows no list and the model searches itself (owner decision
2026-11-05), with the reading's own tools: a hit by its id, the next or the
previous section, a table or figure by its placeholder, a pattern, a
sentence of its own ("similar"). It answers each open coordinate of the
value with its quote, or that the plan does not state it.

Nothing is checked here. Every answer goes through `merge_field`, and what it
refuses is asked once more with the reason. Its quote may stand in whatever
the request showed of the plan (owner decision 2026-11-05): a passage the
model fetched, a hit's line or title, the title or heading of a passage, the
value's passage and its section, a wording the value has read. The
coordinate then cites the passage that piece was shown with. A coordinate
this request leaves
without an answer ends `unanswered`; one whose request no longer fits the
model's window ends `exhausted`; `unstated` is now a finding about the plan.

A pass over a stored harvest combs with the same requests
(`Comber.comb_groups`): the coordinates it names (*coordinates*) whatever
their state, one request per value and group, the value's own passage and
its section
shown first (*own*), since the reading that asked them there ran under an
older question, the years of the stored rows
(*bases*), and the passages a harvest before read the coordinate in listed
(*first*). A stored row carries no sentence, so the model searches the rest
of the plan itself.

Author: Felix Vossel

## Exports

What `__all__` names, and where each name is defined:

- `COMB_PROMPT_ID`
- `OPEN`
- `SHOWN` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `shown_hits` from [docpipe.extraction.reading](docpipe.extraction.reading.md)

## Classes

### Combed

```python
@dataclass
class Combed
```

What combing the open coordinates of one value came to.

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
- `made: list = field(default_factory=list)`: rows made beside the value, one per further wording it was stated for

### Comber

```python
class Comber
```

(document_id, reads, passages, pairs, budget) -> [Combed], one per
read value and group of the spec with an open coordinate.

*ask(payload, shape, document_id, source, group)* is one request: the
reply as a dict, CUT, or None, *group* the name of the group of the spec
it asks, for its trace. *rank(document_id, probes, exclude)* is the plan's
passages best first for the search sentences *probes*
(`runner.make_more_sources`): the reading's sentences, and the model's
own under "similar". *known(claim, asked)* is what a row has read in the
plan's words (`runner.row_context`). *match* chooses the entry of a list
matched apart that a wording answered is (`matching.Matcher`), shown
the passage its quote stands in.

#### Comber.\_\_init\_\_

```python
def __init__(self, spec, ask: Callable, rank: Optional[Callable],
             known: Callable, *, bases: Optional[Callable] = None,
             match: Optional[Callable] = None, pool=None, trace=None)
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

`comb` once per value of *claims* and group of the spec that has
something to ask of it: with *coordinates* the group's share of
them, else a coordinate open on the value. [Combed], one per value
and group asked.

#### Comber.comb

```python
def comb(self, document_id: int, parameter, source, slots: list,
         claims: list, passages: dict, pairs: list,
         budget: Optional[int] = None, *,
         coordinates: Optional[list] = None, own: bool = False,
         bases: Optional[tuple] = None,
         first: Optional[list] = None, group=None,
         probes: Optional[dict] = None, split: bool = False) -> Combed
```

The open coordinates of *claims*, values of *parameter* read in
*source*, answered in place; with *coordinates* those of every row,
open or not. *own* shows *source* and its section before the first
request, *bases* are the years a row may name by a word (instead of
those of *pairs*), *first* passages listed before the search's
hits, *group* the group of the spec *slots* belong to, whose words
for where a plan prints them the request shows, *probes* the
sentences the reading wrote to coordinates it found unstated
({coordinate: sentence}), which the search ranks with. With
*split*, a value the reply states for several wordings of a list
matched apart is one row per wording (`reading.answers_each`, owner
decision 2026-11-06), each a copy of the value's row in
`Combed.made` and asked again on its own; without it, as in a pass
over a stored harvest that re-reads each stored row in place, the
first wording.

## Functions

### open_of

```python
def open_of(claim: dict, slots: list) -> list
```

The coordinates of a value still open after its reading.

### comb_response_format

```python
def comb_response_format(slots: list, labels: list) -> dict
```

Each row of *labels* with every coordinate asked, and what the reply
asks of the rest of the plan.

[Back to the index](../README.md)
