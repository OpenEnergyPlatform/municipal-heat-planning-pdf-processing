# docpipe.extraction.combing

`docpipe/extraction/combing.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

combing.py: The coordinates the reading left open, asked in a conversation of
their own: first with the sections around the value's place, then in the
rest of the plan. Step 4 of the rebuilt harvest (owner decisions 2026-11-04
to 2026-11-07).

The reading asks a value's coordinates in its own passage, one message each
(`reading.py`). What it leaves open (a coordinate the passage does not
state, one whose answer did not hold, one no reply answered) is asked here,
in a NEW conversation per value, not in the value's reading conversation
(owner decision 2026-11-07: „Es wird neues Gespräch, mit den bisherigen
Antworten / Ergebnissen“, to spare the context). Its first message shows the
value with its quote, its answers so far with their quotes, the title and
heading of its place, the titles of the last sections up to it
(`reading.sections_of`), the line of the title page, the table it may
continue, the plan's settings and the coordinate asked; never the passage
itself
(owner decision 2026-11-07: „Ohne die Tabelle“), which the value's quote and
answers pin down. Every request carries its document, so the run orders and
dedupes it with the document's other requests.

First the second reading (owner decision 2026-11-06): the sections before
and after the value's place (`reading.near_of`) are shown once, and each open
coordinate is asked on its own, one message after another, all but those
printed with the number itself (`Group.asked_near`). Its answer may be "not
stated", with the sentence of how the plan would print it (`probe`). A find
quoted from those sections is asked about once more: does that place speak
about the value (`reading.Judge`, owner decision 2026-11-07)?

Then the search, for each coordinate still open that another passage can
state (`Group.combed`): what a number counts and how it is aggregated says
its own passage, and a word like "ca." the number itself (owner decision
2026-11-06). One coordinate after another: its first message shows the hits
of a search with the sentence the reading wrote to it, as the plan would
print it (owner decision 2026-11-05: HyDE, `Read.probes`), as a list of titles
and first lines, without the sentence: it is the run's own writing, not the
plan's, and the model quoted it as the plan's (owner decision 2026-11-06).
That message lets the model fetch hits only; from its next message on it may
also search itself (owner decision 2026-11-07: „erst die retrievals
durchgehen und dann kann es agentisch suchen“), with the reading's own
tools: a hit by its id, the next or the previous section, a table or figure
by its placeholder, a pattern, a sentence of its own ("similar"). Where no
sentence was written, there is no list, and it searches itself at once. It
answers the coordinate where it finds it and leaves it out where it does not:
the search offers no "not stated" (owner decision 2026-11-06), and one the
model writes all the same is no answer (`found`). A round that asks for
nothing new while the coordinate is unfound gets the next passages of the
ranking, as many of each kind as the first list, or of the plan in its order
where there is no ranking, until every passage of the plan was listed (owner
decision 2026-11-06: the search runs empty). Only then is it `unstated`, a
finding about the plan; one whose request no longer fits the model's window
before that is `exhausted`, a finding about the run. A conversation that no
longer fits begins anew for the next coordinate. A find quoted from a passage
other than the value's own, its section and its heading is checked as the
second reading's are.

A year nothing found is asked once more at the end, in the same
conversation, with the plan's base and target years (`PLAN_YEARS`, owner
decision 2026-11-07: first the model looks for a year, and only where it
finds none may it choose one of them): where the value's place names only
the plan's word for its own state or its target, the year is the one of
that list it refers to (`pipeline.named_year`). Before that no answer is
taken from the list. Every value is asked for itself; none takes the
answers of another value of its table (owner decision 2026-11-07).

A value whose open coordinate may name several things, such as a scenario,
is shown every name of that kind read in the plan so far, each once, so the
model can give all of them a value holds for at once (`names_read`, owner
decision 2026-11-07); each still needs a quote that holds it, and each makes
a row of its own (`reading.answers_each`).

A passage is combed the moment its reading is done, while the rest of the
plan is still read (`Session`, owner decision 2026-11-07: every place stays
taken to the end). A value shown every name read in the plan waits until
the whole plan is read, so its list is the whole one.

Nothing is checked here beyond what the harvest checks everywhere. Every
answer goes through `merge_field`, and what it refuses is asked once more in
ONE message after that answer, with the reason; in the search, a quote that
lacks its answer is to be fixed or the coordinate left out (`NOT_IN_QUOTE`).
Its quote may stand in whatever the conversation showed of the plan (owner
decision 2026-11-05): a section around the value, a passage the model
fetched, a hit's line or title, the title or heading of the value's place,
the quote of the value or of one of its answers, the plan's settings.

A pass over a stored harvest asks with the same conversation
(`Comber.comb_groups`): the coordinates it names (*coordinates*) whatever
their state, the value's own passage and its section shown first (*own*),
since the reading that asked them there ran under an older question, the
years of the stored rows (*bases*) for the last question of a year, and the
passages a harvest before read
the coordinate in listed (*first*). A stored row carries no sentence, so the
model searches the rest of the plan itself.

Author: Felix Vossel

## Exports

What `__all__` names, and where each name is defined:

- `ABOUT` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `CHECK_FOLLOWS` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `CHECK_PROMPT_ID` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `COMB_PROMPT_ID`
- `FIRST_GETS`
- `NOT_ABOUT` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `OPEN`
- `SHOWN` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `check_example` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `check_response_format` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `place_text` from [docpipe.extraction.reading](docpipe.extraction.reading.md)
- `shown_hits` from [docpipe.extraction.reading](docpipe.extraction.reading.md)

## Classes

### Combed

```python
@dataclass
class Combed
```

What one conversation for the open coordinates of one value came
to.

Fields:

- `parameter: str`
- `owner: tuple`
- `rows: int`
- `open: int`: coordinates open before
- `filled: int = 0`: read by this step
- `asked: int = 0`
- `near: int = 0`: requests of the second reading
- `near_read: int = 0`: coordinates it read
- `hits: int = 0`: hits of the search shown
- `fetched: int = 0`
- `searched: int = 0`
- `missed: int = 0`
- `corrected: int = 0`
- `exhausted: int = 0`
- `listed: int = 0`: lists of the next passages the run added
- `made: list = field(default_factory=list)`: rows made beside the value, one per further name it was stated for and one per further year of a span
- `plan_years: int = 0`: requests for a year nothing found, with the plan's years
- `judged: int = 0`: finds quoted from a passage other than the value's own the check was asked about, and those it said do not speak about the value (owner decision 2026-11-07)
- `turned: int = 0`
- `anew: int = 0`: conversations begun anew because the one before outgrew the window

### Comber

```python
class Comber
```

(document_id, reads, passages, pairs, budget) -> [Combed], one per
read value with an open coordinate.

*ask(payload, shape, document_id, source, group, example, thread,
follow)* is one message of a conversation (`thread.Thread`): the first
shows *payload*, a later one carries *follow*, what is new since the
answer it follows (`FOLLOWS`); the reply as a dict, CUT, or None,
*group* None, *example* the reply its prompt shows.
*rank(document_id, probes, exclude)* is the plan's passages best first
for the search sentences *probes* (`runner.make_more_sources`): the
reading's sentences, and the model's own under "similar".
*known(claim, asked)* is what a row has read in the plan's words
(`runner.row_context`), which the check shows. *check(payload, shape,
document_id, source, group, example, thread, follow)*, where given, is
the request that asks of a find quoted from a passage other than the
value's own and its section whether that place speaks about the value
(`CHECK_PROMPT_ID`, owner decision 2026-11-07), a reply that names
neither answer told so after it. *span_marks* are what a value stated
for a span of years takes on each of its rows (`reading.span_rows`).

#### Comber.\_\_init\_\_

```python
def __init__(self, spec, ask: Callable, rank: Optional[Callable],
             known: Callable, *, bases: Optional[Callable] = None,
             pool=None, trace=None, check: Optional[Callable] = None,
             span_marks: Optional[dict] = None)
```

#### Comber.session

```python
def session(self, document_id: int, passages: dict, pairs: list,
            budget: Optional[int] = None,
            bases: Optional[list] = None, *, title_page=None,
            settings: Optional[list] = None) -> "Session"
```

The combing of one document, begun before its reading
(`Session`).

#### Comber.plan

```python
def plan(self, read) -> list
```

[value jobs] of one Read: a job per value with a coordinate still
open, each value asked for itself (owner decision 2026-11-07).

#### Comber.shows_names

```python
@staticmethod
def shows_names(job) -> bool
```

Is *job* a value's whose open coordinate is shown every name of
its kind read in the plan (`names_read`)?

#### Comber.comb_job

```python
def comb_job(self, job, session: "Session",
             read_so_far: Optional[dict] = None)
```

The Combed of one job of `plan` in *session*'s document: the
conversation of its value, shown the names *read_so_far* where its
open coordinate is a coordinate of names.

#### Comber.comb_groups

```python
def comb_groups(self, document_id: int, parameter, source, slots: list,
                claims: list, passages: dict, pairs: list,
                budget: Optional[int] = None, *,
                coordinates: Optional[list] = None, own: bool = False,
                bases: Optional[tuple] = None,
                first: Optional[list] = None) -> list
```

`comb` once per value of *claims* that has something to ask: with
*coordinates* those of them *slots* has, whatever their state, else
a coordinate open on the value. [Combed], one per value asked.

#### Comber.comb

```python
def comb(self, document_id: int, parameter, source, slots: list,
         claims: list, passages: dict, pairs: list,
         budget: Optional[int] = None, *,
         coordinates: Optional[list] = None, own: bool = False,
         bases: Optional[tuple] = None,
         first: Optional[list] = None,
         probes: Optional[dict] = None, split: bool = False,
         names_so_far: Optional[list] = None,
         title_page=None, settings: Optional[list] = None) -> Combed
```

The coordinates of the one value *claims* holds, read from
*source*, that its reading left open, asked in one conversation of
their own: with *coordinates* those of *slots* whatever their state,
else those still open. First each that the second reading asks once
more with the sections around the value's place, then each that the
rest of the plan can state, searched for one after another (module
docstring). *own* shows *source* and its section in the first
message, *bases* are the years a row may name by a word (instead of
those of *pairs*), asked only once nothing found the year
(`PLAN_YEARS`), *first* passages listed before the hits of the
first coordinate searched, *probes* the sentences the reading wrote
to coordinates it found unstated ({coordinate: sentence}), which the
search ranks with. *names_so_far* are the names
read in the plan so far for a coordinate asked that may name several
things (`names_read`). With *split*, a value the reply states for
several names of such a coordinate is one row per name
(`reading.answers_each`, owner decision 2026-11-06), and a value of
a span of years one per year (`reading.span_rows`), each a copy of
the value's row in `Combed.made`; without it, as in a pass over a
stored harvest that re-reads each stored row in place, the first
name and the first year. *title_page* and *settings* are shown in
the first message.

## Functions

### open_of

```python
def open_of(claim: dict, slots: list) -> list
```

The coordinates of a value still open after its reading.

### comb_response_format

```python
def comb_response_format(slots: list, gets: tuple = GETS) -> dict
```

The coordinates a search message asks of the one value it is about,
as far as the reply found them, at the top of the reply with no wrapper
and no row label (owner decision 2026-11-06), none required and none
UNSTATED, and what the reply asks of the rest of the plan: any of
*gets* (`FIRST_GETS` in the first message of a coordinate's search).

### near_response_format

```python
def near_response_format(slots: list) -> dict
```

The coordinate a message of the second reading asks of its value:
required, "not stated" one of its answers, with the sentence of how the
plan would print it (`probe`), which the search ranks with.

### found

```python
def found(answer) -> bool
```

Does *answer*, a reply's entry for one coordinate, name something: an
answer that is not UNSTATED, alone or in a list? An entry the reply left
out, one without a value, and UNSTATED name nothing: the search does
not offer it, and one the model writes all the same is no answer (owner
decision 2026-11-06). A name in another form than asked names something,
and is asked for once more in the form asked.

### finds

```python
def finds(reply, slots: list)
```

*reply* (`as_rows`) as the search reads it: each row's entries that
name nothing (`found`) taken out, and each list without its entries
that name nothing. Anything but an object is left as it is.

### comb_example

```python
def comb_example(slots: list) -> dict
```

The reply of a search message as its example shows it: exactly the
coordinates it asks, in its order, each read (`reading.entry_example`),
then what it asks of the rest of the plan, as `comb_response_format`
has them (owner decision 2026-11-06).

### near_example

```python
def near_example(slots: list) -> dict
```

The reply of a message of the second reading as its example shows
it: exactly the coordinate it asks, read.

### as_rows

```python
def as_rows(reply, label: str)
```

A reply about the one row a request showed (`comb_response_format`)
as the rows the step folds: its answers under that row's *label*, its
requests for more beside them. Anything but an object is left as it
is.

### names_read

```python
def names_read(spec, reads: list) -> dict
```

{kind: [name]}: every name read in the plan so far for a kind of
thing the spec merges (`naming.merged_slots`), as a value or as a
coordinate, each once, in the order the reading read them (owner
decision 2026-11-07: "Alle gelesenen Namen").

### answers_shown

```python
def answers_shown(claim: dict) -> dict
```

{coordinate: {"value", "quote"}}: what a value has read so far, each
coordinate the plan's wording (or the answer itself where it has none)
with the quote it was read from, the unit included; what the spec
derived is its decision and says nothing the plan printed (owner
decision 2026-11-07: the conversation for what is open begins with the
answers so far).

[Back to the index](../README.md)
