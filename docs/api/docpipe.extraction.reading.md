# docpipe.extraction.reading

`docpipe/extraction/reading.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reading.py: What the reading of a plan shares with the steps around it: the
coordinates a value of a field is asked, in the order of the spec's groups;
a value stated for a span of years as one row per year; the two ends of a
range linked; what a request fetches of the rest of a plan itself
(`Gathered`, the compute step's tools); and what reading one field in one
passage came to (`Read`).

The reading itself is `addressed.py` (owner decisions 2026-11-08 evening):
pieces of numbered lines, one question per request, every answer an
address.

Author: Felix Vossel

## Classes

### Gathered

```python
@dataclass
class Gathered
```

What one read fetched of the rest of the plan, in the order the model
asked for it: the passages its request shows under "more", the hit lists
of its searches under "hits", and what could not be found, with why,
under "not_found". *seen* are the passages the request already shows,
*cursor* where "next" and "previous" go on from, *rank(probes, exclude)*
the plan's passages best first for sentences, which "similar" lists
(`runner.make_more_sources`); None where the run ranks nothing. *unfit*
is set when a request of the gathering no longer fit the model's window
or came back unread (`gather`).

Fields:

- `seen: set = field(default_factory=set)`
- `cursor: dict = field(default_factory=dict)`
- `sources: list = field(default_factory=list)`
- `shown: list = field(default_factory=list)`
- `hits: list = field(default_factory=list)`
- `missed: list = field(default_factory=list)`
- `by_hit: dict = field(default_factory=dict)`
- `rank: Optional[Callable] = None`
- `unfit: bool = False`

#### Gathered.context

```python
def context(self) -> dict
```

What a first message shows of the gathering so far: the passages
fetched under "more", the hit lists under "hits", each without what
it was searched with (`SEARCHED_WITH`), and what could not be
fetched under "not_found".

#### Gathered.mark

```python
def mark(self) -> tuple
```

Where the gathering stands: how many passages it showed, hit
lists it made and misses it noted, for what a later message brings
anew (`since`).

#### Gathered.since

```python
def since(self, mark: tuple) -> dict
```

What the gathering added after *mark*, as `context` shows it: a
later round of a search brings only what is new, after the answer
it follows (owner decisions 2026-11-07).

#### Gathered.listed

```python
def listed(self) -> set
```

The passages the request has listed as a hit or shown.

#### Gathered.evidence

```python
def evidence(self, passages: dict) -> list
```

What the request showed of the plan, as passages a quote may stand
in (owner decision 2026-11-05: whatever a request shows of a document
may be quoted): each passage it fetched as shown, then each one's
title, and the line and title of each hit, under the passage it was
shown with (`shown_as`).

#### Gathered.list_hits

```python
def list_hits(self, found: list, **about) -> int
```

Show *found*, [(owner, title, line)], as one list of hits, each
with the id a later ask names it by. Returns how many.

#### Gathered.fetch

```python
def fetch(self, asks, order: list, passages: dict,
          budget: Optional[int]) -> bool
```

The asks of one reply resolved (`lookup`), each passage cut to
*budget*, two pages of the plan. True when a passage or a hit list
came of them the request has not shown yet: an ask for something
shown already, or for nothing, ends the gathering.

### Read

```python
@dataclass
class Read
```

What reading one parameter in one passage came to.

Fields:

- `batch: Batch`
- `claims: list`
- `asked: int = 0`
- `unread: bool = False`: no readable reply
- `why: Optional[str] = None`: and why: cut_off or no_answer
- `lost: list = field(default_factory=list)`: Why each half of a table no reply answered came to nothing, the other halves read: one hole each (`surveyed.taken_of`).
- `failed: dict = field(default_factory=dict)`: what the check refused of the first replies, by reason
- `unanswered: int = 0`: coordinates no reply answered
- `uncombed: bool = False`: A field of the document that found nothing while chunks of the document were never shown to it: no reading, only the mark that its state is `parameter_uncombed` (owner decision 2026-11-13, point 3).

## Functions

### shown_counts

```python
def shown_counts() -> dict
```

### shown_hits

```python
def shown_hits(ranked: list) -> list
```

The best of each kind of a ranked search, in its order
(`shown_counts`).

### slots_of

```python
def slots_of(spec, parameter) -> list
```

The coordinates a value of *parameter* is read with: its unit, then
every axis, one the spec derives from the unit included, which is asked
where the unit question chose no entry of the parameter's list
(`fields.derived_by_unit`).

### in_group_order

```python
def in_group_order(group, group_slots: list) -> list
```

A group's coordinates in the order its spec entry names them: the
order they are asked in, one request each.

### groups_of

```python
def groups_of(spec, slots: list) -> list
```

[(group, its slots)] of *slots*, in the order of the spec's groups
(owner decision 2026-11-04). The spec puts every coordinate in exactly
one group (`spec._validate_groups`).

### shown_as

```python
def shown_as(source: Optional[Source], text) -> list
```

*text*, which a request shows with *source*, as a passage a quote may
stand in (owner decision 2026-11-05: whatever a request shows of a
document may be quoted): a hit's line, a title, a wording a value has
read. A coordinate quoting it cites *source*. Only the text shown
counts, not the rest of *source*. [] for no text.

### passage_at

```python
def passage_at(passages: dict, owner) -> Optional[Source]
```

The passage *owner*, [kind, id], names: the one among *passages*, else
a bare one of that name. None for no owner.

### more_schema

```python
def more_schema(gets: tuple = GETS) -> dict
```

The asks a reply may carry under "more": any of *gets*, by default
every one.

### first_line

```python
def first_line(source: Source) -> str
```

The first line of a passage under its title: what a hit list shows
of it.

### passage_of

```python
def passage_of(claim: dict, shown: list,
               document: Sequence = ()) -> Optional[Source]
```

The first passage of *shown* whose text carries the claim's quote:
the one its value is read from; where the rule `check_quote_shown` is
off and none does, the first passage of *document*, the document's
passages in its order, that does (`pipeline.place_of`). None where the
quote stands in none.

### span_rows

```python
def span_rows(row: Row, slot, until: Optional[int], marks: dict,
              clone: Callable) -> list
```

A value the plan states for a span of years as one row per year of
it (owner decision 2026-11-07: "als ca. für jedes distinkte Jahr
erfassen"): *row*, read with the span's first year, and a copy of it
(*clone(row)*) for each year after, the last read as the first is, those
between derived from the span, which the quote prints and names neither
of. Each takes *marks* ({coordinate: entry}, the rule `span_marks`)
where it read nothing, derived from the span. Only where the year read
holds and the last year stands in its quote as well, as any year must;
[the copies].

### link_ranges

```python
def link_ranges(rows: list, slots: list) -> int
```

The two ends of each range a passage prints, linked (owner decision
2026-11-06): a value read as the lower end of a range
(`fields.RANGE_LOW`) and the next one read as the upper end
(`fields.RANGE_HIGH`), under the same quote and with the same answer to
every other coordinate, both carry [lower, upper] under `fields.RANGE`.
Only a list that has both entries marks ends. Returns how many ranges
were linked.

[Back to the index](../README.md)
