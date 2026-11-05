# docpipe.extraction.reading

`docpipe/extraction/reading.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reading.py: The values of one parameter in the passages the survey named for
it, one value per request: rounds name the values of a passage one by one,
then each value is asked once per group of the spec for that group's
coordinates.

Step 3 of the rebuilt harvest (owner decisions 2026-11-04 and 2026-11-05).
Every request has one task and reads exactly one value. A table is read like
a section: the model repeats each value as the passage prints it, quoted by
its sentence or its table row, and for a number in a table also the head of
its column as printed, which tells two equal numbers of one row apart. Code
reads no number by its place.

A round shows the parameter in short (its `brief`), the whole passage (a table
with its title, its head and all its rows, or the survey's piece of a
section), the text around a table or figure and the values already read, and
asks for the next value not yet read, until the model says there is none. A
value may stand in any passage the round showed: the passage, its heading or
the text around it; it is read from the one its quote stands in, which joins
the reading's batch, so the fold checks it there (`pipeline.route_claims`).
The requests that read have no tools; only the combing has (owner decision
2026-11-05, ticket 26: no reading of 2,231 in an eight-plan probe used them). A value the check refuses (its quote in no passage
shown, its number not in its quote, whatever else the fold refuses of the
value and its quote, such as an answer its quote does not hold or one off
its closed list (`verify.value_refused`), a quote over several table rows
that print it, a head no head line prints) is asked once more with the
reason; one named again is asked once more, and named again it ends the
rounds.

A number in a table takes its column from its head, else from the one cell of
its row that prints it, and a head that prints exactly one year of the
document's pairs is its year, read off the head line and not asked
(`pipeline.with_head`, owner decision 2026-11-03); where exactly one pair has
that year, the pair's scenario is the value's too (`pipeline.head_pair`).
Then every group of the spec (`Spec.groups`, `groups_of`) is asked for this
one value, its coordinates still open only. A request begins with what is the
same for every request of its parameter and group (the parameter, in full
only where the group classifies, its questions with their lists), then what
is the same in a plan (its base and target years), then the passage, and the
value comes last, marked, with what is already read of it, so a server reads
each shared beginning once (owner decision 2026-11-05, ticket 26). Each group
has its own system prompt, its section of the prompt (`group_prompts`), and
its own correction round, and only a group that asks a frame coordinate is
shown the pairs and the plan's base and target years.

Every coordinate asked is answered: the grammar of a group request requires
each of them, and "the passage does not say" is one of the answers
(`fields.UNSTATED`).

Nothing is checked here beyond what the harvest checks everywhere. Every
coordinate goes through `pipeline.merge_field` and every value through
`fold_batch`. What that check refuses is asked once more with its reason,
named by its coordinate; a coordinate the reply left out is asked for by
name. A frame coordinate still open takes the survey's tuple of the passage,
with its quote, where the survey named one (window `frame`). A coordinate no
reply answered ends `unanswered`. A request too long for the model's window
is split: a table into halves of its rows, until a single row is a hole of
its own (`Read.lost`).

Author: Felix Vossel

## Classes

### Grid

```python
@dataclass
class Grid
```

A transcribed table: its head lines and its body rows, cell by cell.

Fields:

- `text: str`
- `heads: list`: the lines above the rule
- `body: list`: [(line, [cells])] below it
- `columns: int`

#### Grid.row_numbers

```python
def row_numbers(self) -> list
```

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
(`runner.make_more_sources`); None where the run ranks nothing.

Fields:

- `seen: set = field(default_factory=set)`
- `cursor: dict = field(default_factory=dict)`
- `sources: list = field(default_factory=list)`
- `shown: list = field(default_factory=list)`
- `hits: list = field(default_factory=list)`
- `missed: list = field(default_factory=list)`
- `by_hit: dict = field(default_factory=dict)`
- `rank: Optional[Callable] = None`

#### Gathered.context

```python
def context(self) -> dict
```

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
*budget*, the survey's two pages. True when a passage or a hit list
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
- `corrected: int = 0`: corrections asked
- `failed: dict = field(default_factory=dict)`: what the check refused of the first replies, by reason
- `unanswered: int = 0`: coordinates no reply answered
- `probes: list = field(default_factory=list)`: Per claim, in its order: the sentences its group replies wrote to the coordinates they found unstated, as the plan would print them, {coordinate: sentence}, which the combing ranks with. Not on the claim: no sentence enters the harvest.

### Reader

```python
class Reader
```

(document_id, survey, passages) -> [Read], one per parameter and
passage the survey named for it.

Two requests, each with one task and one value (owner decisions
2026-11-04 and 2026-11-05), each the reply as a dict, CUT, or None:
*ask_values(source, parameter, context, read, corrections)* the next
value of a passage not among *read*; *ask_text(source, parameter, group,
slots, row, context, corrections)* one group's coordinates of that
value. *context* is what the request shows beside its passage,
*corrections* None the first time and what was wrong the second.
*shown_with(source)* is what a coordinate's quote may stand in besides
the passage: the heading it stands under (`heading_of`); so may what
the value has read, as its request shows it (`known_shown`).
*known(claim, asked)* is what a value has read in the plan's words
(`runner.row_context`). *pool* reads passages side by side. No request
of the reading has tools (owner decision 2026-11-05, ticket 26).

#### Reader.\_\_init\_\_

```python
def __init__(self, spec, ask_values: Callable, ask_text: Callable,
             frame_slots: list, *, shown_with: Optional[Callable] = None,
             bases: Optional[Callable] = None,
             known: Optional[Callable] = None,
             pool=None, trace=None)
```

#### Reader.context_of

```python
def context_of(self, source: Source, tuples: list, passages: dict,
               budget: Optional[int] = None) -> tuple
```

(what the requests of a passage show beside it, the section it
was cut from): the text around a table or figure (`around_of`) and
the survey's pairs of the passage, which only a group that asks a
frame coordinate shows (`group_context`).

#### Reader.read

```python
def read(self, document_id: int, parameter, source: Source,
         tuples: list, pairs: list, passages: dict,
         shown: Optional[Source] = None,
         budget: Optional[int] = None) -> Read
```

*source* is the passage a value is verified against, *shown* the
piece of it the requests show, *budget* the survey's two pages, which
the text around a table or figure fits (`around_of`). The values in
rounds (`_values`), each placed in its table (`_placed`), then each
group of the spec for each value (`_value_group`).

## Functions

### shown_hits

```python
def shown_hits(ranked: list) -> list
```

The best of each kind of a ranked search, in its order (`SHOWN`).

### cells_of

```python
def cells_of(line: str) -> list
```

### grid_of

```python
def grid_of(text: str) -> Optional[Grid]
```

The table of *text*, or None when it has no Markdown table.

### part_text

```python
def part_text(grid: Grid, shown) -> str
```

The table's text with only the body rows *shown*, as the table numbers
them: its title, its head lines and every line that is no body row stay
where they stand.

### halves

```python
def halves(view: Source) -> list
```

A table too long for one request as two, each with half its rows and
all its title and head lines; [] for anything else, or a single row.

### slots_of

```python
def slots_of(spec, parameter) -> list
```

The coordinates a value of *parameter* is read with: its unit, then
every axis the spec does not decide.

### groups_of

```python
def groups_of(spec, slots: list) -> list
```

[(group, its slots)] of *slots*, in the order of the spec's groups:
one request each (owner decision 2026-11-04). The spec puts every
coordinate in exactly one group (`spec._validate_groups`).

### group_context

```python
def group_context(context: dict, group_slots: list, frame_slots: list,
                  bases: list) -> dict
```

What a group's request shows beside the passage: the text around it,
and the survey's pairs and the plan's years only where the group asks a
frame coordinate.

### coordinate_shown

```python
def coordinate_shown(slot) -> dict
```

### answer_schema

```python
def answer_schema(slot, probe: bool = False) -> dict
```

One coordinate's answer as the grammar takes it; with *probe* also
the sentence a reply writes to a coordinate its passage does not state,
as the plan would print it, which the combing searches with (owner
decision 2026-11-05: HyDE).

### known_of

```python
def known_of(tuples: list, frame_slots: list) -> list
```

### years_of

```python
def years_of(bases: list, slots: list) -> dict
```

The plan's base years and target years, numbers only, where a
coordinate asked is the one they date: what the field request shows
(`runner._field_payload`), so a value whose passage names its state by
the plan's word and prints no year can answer one of them
(`pipeline.named_year`).

### heading_of

```python
def heading_of(source: Source) -> list
```

The heading a request shows with *source* under "section", as a
passage a quote may stand in (owner decision 2026-11-05): a table's or
figure's the heading of its section, a section's its own. None where the
passage's text carries it already or no section holds it.

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

### known_shown

```python
def known_shown(claim: dict, known: dict, passages: dict) -> list
```

What a request shows of what a value has read (*known*, {coordinate:
the plan's wording}, `runner.row_context`), each wording a passage a
quote may stand in under the passage its coordinate was read in
(`shown_as`).

### around_of

```python
def around_of(source: Source, passages: dict,
              budget: Optional[int]) -> Optional[Source]
```

The text of the section a table or figure stands in, as its request
shows it (owner decisions 2026-11-04 and 2026-11-05): the whole section,
other tables and figures of it included, when it fits *budget*, the
survey's two pages, else that many characters around the table's place
in it. The model reads from it what it needs: a cut to 200 characters on
each side would have hidden the text of 72 % of the quotes the m8 run
took from a table's section. None for a section, and for a table or
figure whose section is not among *passages*.

### more_schema

```python
def more_schema() -> dict
```

The asks a reply may carry under "more".

### first_line

```python
def first_line(source: Source) -> str
```

The first line of a passage under its title: what a hit list shows
of it.

### gather

```python
def gather(ask: Callable, reply: dict, gathered: Gathered, order: list,
           passages: dict, budget: Optional[int]) -> tuple
```

(the reply that stands, the requests made): what each reply asks of
the rest of the plan is fetched and the request sent again, until a round
asks for nothing the request has not shown or the request no longer fits
the model's window. The reply before such a round stands.

### parameter_shown

```python
def parameter_shown(parameter, full: bool = True) -> dict
```

The parameter as a request shows it: with its full definition, or,
without *full*, with its `brief` where the spec writes one (owner
decision 2026-11-05, ticket 26).

### value_classes

```python
def value_classes(parameter) -> dict
```

The entries a category parameter's value is one of, as a request shows
a closed list (`fields.Slot.answerable`), without UNSTATED: a value the
passage does not state is no value. Empty for a parameter with no list.

### source_shown

```python
def source_shown(source: Source) -> dict
```

### with_head_asked

```python
def with_head_asked(parameter, source: Source) -> bool
```

Does a value of *parameter* in *source* name the head of its column?
A number in a table: the head tells two equal numbers of one row apart
and dates the number (owner decision 2026-11-05).

### shown_value

```python
def shown_value(claim: dict) -> dict
```

A value as a request shows it: its value, wording, quote and head.

### values_payload

```python
def values_payload(source: Source, parameter, context: dict, read: list,
                   corrections: Optional[list] = None) -> dict
```

One round of the values of a passage: the parameter in short, a
category parameter with its entries (`value_classes`), first, the same
in every round of the parameter; then the passage and the text around a
table or figure, the same in every round of the passage; the values
already read (*read*) last; with *corrections* the value of the round
the check refused, asked once more (ticket 26: what requests share
stands first). Nothing of the value's coordinates.

### values_response_format

```python
def values_response_format(parameter, head: bool = False) -> dict
```

The next value of the passage, with its wording, its quote and, with
*head*, the head of its column; null where no further value stands in it.
A category value is one of its entries, or "" where the model is unsure
of them.

### claim_of

```python
def claim_of(reply, head: bool = False) -> Optional[dict]
```

The value a round's reply names, as a row's claim, or None where it
names none. A table row quoted with others is cut to the one row that
prints the number (`narrow_quote`).

### same_value

```python
def same_value(a: dict, b: dict) -> bool
```

Do two claims name the same value: the same number or wording, in the
same quote, under the same head?

### head_matches

```python
def head_matches(table: str, cell: int, cells: int, head: str) -> bool
```

Does *head* name the head of this column: its words on one head line,
or all of them as `column_head` joins them?

### column_of

```python
def column_of(source: Source, claim: dict) -> Optional[tuple]
```

(column, cells of its row) of a number in a table, 1-based, or None:
the one column whose head is the head the model wrote and whose cell in
the quoted row prints the number, else the one cell of the row that
prints it (`pipeline.cell_index`). None where neither is certain: a
wrong column is worse than none.

### head_in_table

```python
def head_in_table(source: Source, head: str) -> bool
```

Does any head line of the table print *head* over one of its
columns?

### passage_of

```python
def passage_of(claim: dict, shown: list) -> Optional[Source]
```

The first passage of *shown* whose text carries the claim's quote:
the one its value is read from. None where the quote stands in none.

### source_of

```python
def source_of(batch: Batch, claim: dict) -> Source
```

The passage of *batch* a claim is read from, by the label it carries
(`Batch.label`), else the passage the batch was made for.

### value_failure

```python
def value_failure(claim: dict, source: Source) -> Optional[str]
```

Why the check of a value refuses it, or None: a quote not in its
passage, a number its quote does not print (the harvest's own
`number_outside_quote`). Said as the harvest says it.

### round_failure

```python
def round_failure(claim: dict, shown: list, read: list,
                  parameter) -> Optional[tuple]
```

(kind, reason) of what the check refuses of a round's value of
*parameter*, or None: a value already read (`REPEATED`), the value
itself (`VALUE`: its quote in no passage of *shown*, its number not in
its quote, what the fold refuses of the value and its quote
(`verify.value_refused`), a number quoted over several rows of its
table that print it), or a head no head line of its table prints
(`HEAD`). The fold's refusal is told in its own words: what the fold
refuses, the model hears while it can still answer (owner decision
2026-11-05).

### text_payload

```python
def text_payload(source: Source, parameter, slots: list, row: Row,
                 where: str, context: dict,
                 corrections: Optional[list] = None,
                 full: bool = False) -> dict
```

One group's request for one value, what its requests share first
(ticket 26): the parameter, with its full definition only where *full*
(the group that classifies, `Group.full_definition`), and the group's
coordinates with the spec's words for where a plan prints them
(*where*), the same for every value of the parameter; then, for a frame
group, the plan's base and target years, the same in a plan; then the
passage, the text around a table or figure and, for a frame group, the
survey's pairs of the passage (`group_context`); the value last, with
its quote and, under "read", what is already read of it in the plan's
words; with *corrections* the same request asked once more.

### text_response_format

```python
def text_response_format(slots: list) -> dict
```

Every coordinate of the group for the one value the request shows,
each with the sentence of one the passage does not state (`probe`).

### group_prompts

```python
def group_prompts(prompt, groups) -> dict
```

{group name: the prompt its requests send}: what stands before the
first section (`GROUP_SECTION`) is every group's, then the group's own
section (owner decision 2026-11-05, ticket 26: one system prompt per kind
of request, with only its rules). A prompt without sections is every
group's as it is, the one prompt of a profile with one group. A prompt
with sections has one for each of *groups* and none for any other group:
a group without its rules, or rules no group reads, raises LookupError,
which the run raises at its start (`runner.surveyed_flow`).

### answer_of

```python
def answer_of(entry: dict) -> dict
```

### value_replies

```python
def value_replies(reply: dict, slot, label: str) -> list
```

[(level, window, field reply)] of one coordinate of a group's reply
for the value *label*.

### refused_of

```python
def refused_of(failed: list) -> collections.Counter
```

What the check refused of a reply, by reason.

### value_corrections

```python
def value_corrections(row: Row, failed: list, slots: list) -> list
```

What the check refused of a group's reply for one value, each named
by its coordinate: [{coordinate, what}]. A coordinate the reply left out
is named as missing.

### same

```python
def same(slot, a, b) -> bool
```

### inherit

```python
def inherit(rows: list, slots: list, tuples: list, pairs: list,
            shown: list) -> int
```

A frame coordinate still open on a row takes the survey's tuple of
the passage, when the survey named exactly one, through the field check
with the tuple's own quote. Not on a row that read a frame coordinate of
its own the tuple contradicts: a year under its column head is not the
year of the table's title. Returns the coordinates taken.

[Back to the index](../README.md)
