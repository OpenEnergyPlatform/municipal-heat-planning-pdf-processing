# docpipe.extraction.reading

`docpipe/extraction/reading.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reading.py: The values of one parameter in the passages the survey named for
it, one value per request: rounds name the values of a passage one by one,
then each value is asked its coordinates one by one, each a message of the
value's own conversation.

Step 3 of the rebuilt harvest (owner decisions 2026-11-04, 2026-11-05 and
2026-11-07). Every request has one task and reads exactly one value. A table
is read like a section: the model repeats each value as the passage prints
it, with a quote that pins it down, and code takes nothing from where it
stands (owner decision 2026-11-07: "streich diese ganze Code Logik").

A round shows the parameter in short (its `brief`), the whole passage (a table
with its title, its head and all its rows, or the survey's piece of a
section), the text around a table or figure, the line of the title page and
the table the passage may continue, and asks for the next value not yet read,
until the model says there is none. A value may stand in any passage the
round showed; it is read from the one its quote stands in, which joins the
reading's batch, so the fold checks it there (`pipeline.route_claims`). Its
quote stands in what was shown exactly once and holds the value exactly
once, each counted where it stands for itself and not as part of a longer
name or number (`verify.times_quoted`, `verify.times_stated`):
"410.662,44 | 1.109 | 6%" pins down the 1.109 of its row. A value the check
refuses (its quote in no passage shown, its number not in its quote, whatever
else the fold refuses of the value and its quote (`verify.value_refused`), a
quote that does not pin it down) is asked once more with the reason; one
named again is asked once more, and named again it ends the rounds. No
request that reads has tools.

A number a figure only draws, as a bar, a segment, an area or a point of a
curve, is a value of the plan and an estimate (owner decisions 2026-11-05 and
2026-11-07). Where a figure's image goes with the request, every value of the
round says whether the image only draws it; one no shown text states is read
off the image, its reading in place of a quote, and that reading is its
evidence (`verify.read_off`), trust level C.

Then the value's coordinates are asked one by one, in the order of the spec's
groups and of the coordinates in each (`Spec.groups`, `groups_of`), all in
one conversation (owner decision 2026-11-07: "Die Fragen A, B und C sind ja
eigentlich mehrere Fragen und sollten dann auch nacheinander gestellt
werden"): the first message shows the passage and the value, each later one
brings the words of the coordinate's group and that coordinate only, and the
model sees what it answered before. A coordinate the spec derives from the
unit is not asked where the unit question chose an entry of the parameter's
list, and is asked where it chose none (owner decision 2026-11-07: where it
does not follow by itself, the model tries). The system prompt is what every
message is told and the part of each field the first message carries; only a
frame coordinate is shown the survey's pairs, only the year the plan's base
and target years. The rounds of a passage's values are a conversation as
well: each later round asks for the next value after the answer it follows.
A correction goes after the answer it is about, in its conversation.

With a pool, the conversations of a passage's values run side by side once
its rounds have named them, as the passages do, and none waits for another
(owner decision 2026-11-07: every place stays taken to the end). A value
read as no value of its parameter is asked for once more when every value of
its passage is done, in the order of the values, so the rounds' conversation
gets the messages it got when the values went one after another. A passage
read goes to *on_read* the moment it is done, where its combing begins.

Every coordinate asked is answered: the grammar requires it, and "the
passage does not say" is one of the answers (`fields.UNSTATED`).

A coordinate whose answer is the name the document gives a thing, such as
a scenario, is read as the document prints it (`fields.Slot.merged`). A
value the passage states for several of them is one row per name, each
checked on its own (`answers_each`, owner decision 2026-11-06); names that
stand in one place may share one quote, which must hold each of them
(`spread`, owner decision 2026-11-07). What the check refuses on any of the
rows one answer made is asked once more in ONE message after that answer,
naming each refused name with its quote, and each answer of it goes to the
row of its name, a changed name to the next row still open, a further name
to a row of its own (`routed`, owner decisions 2026-11-07). Which names
mean the same thing is asked once the document is read (`naming.py`).

Nothing is checked here beyond what the harvest checks everywhere. Every
coordinate goes through `pipeline.merge_field` and every value through
`fold_batch`. What that check refuses is asked once more with its reason,
named by its coordinate; a coordinate the reply left out is asked for by
name. A frame coordinate still open takes the survey's tuple of the passage,
with its quote, where the survey named one (window `frame`). What is still
open then is asked in a conversation of its own, with the answers so far,
the sections around the value's place and the rest of the plan
(`combing.py`). A request too long for the model's window is split: a table
into halves of its rows, until a single row is a hole of its own
(`Read.lost`).

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

### Judge

```python
class Judge
```

Whether the place a find was quoted from speaks about its value
(`CHECK_PROMPT_ID`, owner decisions 2026-11-07), for one value: asked
where the quote stands in a passage the value's own request did not show
(*own*: the owners of those it did), never where the check of quote and
answer refuses the find anyway (`merge_field`). Asked once per
coordinate and quote, whatever name the find gives: the question is
about the place (owner decision 2026-11-07); a reply that names neither
answer is asked once more, told why. *check(payload, shape,
document_id, source, group, example, thread, follow)* is the request,
*shown* the value's passage and parameter as it shows them
(`check_shown`), *counts* what counts its requests (`judged`) and the
places it said do not speak about the value (`turned`).

#### Judge.\_\_init\_\_

```python
def __init__(self, check: Callable, document_id: int, shown: dict,
             own: set, source: Source, group, passages: dict,
             budget: Optional[int], counts) -> None
```

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
- `probes: list = field(default_factory=list)`: Per claim, in its order: the sentences its replies wrote to the coordinates they found unstated, as the plan would print them, {coordinate: sentence}, which the combing ranks with. Not on the claim: no sentence enters the harvest.

### Reader

```python
class Reader
```

(document_id, survey, passages) -> [Read], one per parameter and
passage the survey named for it.

Two kinds of request, each with one task and one value (owner
decisions 2026-11-04 and 2026-11-05), each the reply as a dict, CUT, or
None, and each a message of a conversation (`thread.Thread`, owner
decisions 2026-11-07): *ask_values(source, parameter, context, read,
thread, follow, drawn)* the first value of a passage not among *read*,
or, with *follow*, what follows the answer of *thread*: the next value,
a correction; with *drawn* the request sends the figure's image and
takes a value read off it. *ask_text(source, parameter, group, slots,
row, context, thread, follow)* one coordinate of that value (*slots*,
one): the first message of the value's conversation, the message of
its next coordinate, or, with *follow*, a correction. *context* is what
the first message shows beside its passage.
*shown_with(source)* is what a coordinate's quote may stand in besides
the passage: the heading it stands under (`heading_of`); so may what
the value has read, as its request shows it (`known_shown`).
*known(claim, asked)* is what a value has read in the plan's words
(`runner.row_context`). *drawn(source)* says whether a request about
*source* sends a figure's image, which a value only the image shows is
read off (owner decisions 2026-11-05 and 2026-11-07); None sends none.
*pool* reads passages side by side, and the values of a passage side by
side once its rounds have named them (owner decision 2026-11-07). No
request of the reading has tools (owner decision 2026-11-05, ticket 26).

#### Reader.\_\_init\_\_

```python
def __init__(self, spec, ask_values: Callable, ask_text: Callable,
             frame_slots: list, *, shown_with: Optional[Callable] = None,
             bases: Optional[Callable] = None,
             known: Optional[Callable] = None,
             drawn: Optional[Callable] = None,
             pool=None, trace=None)
```

#### Reader.context_of

```python
def context_of(self, source: Source, tuples: list, passages: dict,
               budget: Optional[int] = None,
               title_page: Optional[Source] = None) -> tuple
```

(what the requests of a passage show beside it, the section it
was cut from, the passages a coordinate may quote for what stands
beside it): the text around a table or figure (`around_of`), the
title page's line and the table the passage may continue
(`beside_of`), and the survey's pairs of the passage, which only a
group that asks a frame coordinate shows (`group_context`).

#### Reader.read

```python
def read(self, document_id: int, parameter, source: Source,
         tuples: list, pairs: list, passages: dict,
         shown: Optional[Source] = None,
         budget: Optional[int] = None, *,
         bases: Optional[list] = None,
         title_page: Optional[Source] = None,
         settings: Optional[list] = None) -> Read
```

*source* is the passage a value is verified against, *shown* the
piece of it the requests show, *budget* two pages of the plan, which
the text around a table or figure fits (`around_of`). The values in
rounds (`_values`), then each coordinate of the spec for each value,
one message each in the order of the groups (`_value_group`); what
that leaves open is asked in a conversation of its own
(`combing.Comber`). *bases* are the plan's years (else those of
*pairs*), *title_page* its title page's line (`Reader.__call__`).
The values one after another: the steps `Reader.__call__` runs side
by side with a pool.

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
every axis, one the spec derives from the unit included, which is asked
where the unit question chose no entry of the parameter's list
(`fields.derived_by_unit`).

### in_group_order

```python
def in_group_order(group, group_slots: list) -> list
```

A group's coordinates in the order its spec entry names them: the
order their questions are asked in, one message each.

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
the title page's line and the table it may continue (`beside_of`), and
the survey's pairs and the plan's years only where the group asks a
frame coordinate.

### coordinate_shown

```python
def coordinate_shown(slot, unstated: bool = True) -> dict
```

A coordinate as a request shows it: its question, and its list, or
the kind of its answer; without *unstated* a list without UNSTATED, as
the combing asks (`fields.value_schema`). A coordinate of names shows
the entries it takes beside them under its kind (`fields.beside_names`,
owner decision 2026-11-07), without UNSTATED, which a wording answers.

### several

```python
def several(slot) -> bool
```

May one value name several things for *slot*, one row each: a
coordinate whose answer is the name the document gives a thing, merged
with the document's other names for it after the reading (`naming.py`,
owner decisions 2026-11-06)?

### answer_schema

```python
def answer_schema(slot, probe: bool = False, unstated: bool = True) -> dict
```

One coordinate's answer as the grammar takes it, its printed wording
only where `fields.wording_asked`; with *probe* also the sentence a reply
writes to a coordinate its passage does not state, as the plan would
print it, which the combing searches with (owner decision 2026-11-05:
HyDE). A coordinate that may name several things (`several`) takes a
list of such answers too, and an answer that names several of them with
one quote, its names under "value" (owner decision 2026-11-07: one
quote for several names; `spread`). Without *unstated* its answer is
never UNSTATED (`fields.value_schema`).

### entry_example

```python
def entry_example(slot) -> dict
```

One coordinate's entry as the example of a request shows it: the
keys `answer_schema` asks, in its order, read (owner decisions
2026-11-06): its answer (`fields.value_example`), its printed wording
wherever the grammar asks one, so beside every entry of a list, the unit
included, and its quote. No probe: that is the sentence of an unstated
entry, which the prompt's rule line shows. A coordinate that may name
several things shows one, the form a list repeats.

### names_several

```python
def names_several(given) -> bool
```

Does a coordinate's answer name several things: a list, or an answer
whose names share one quote?

### entries_of

```python
def entries_of(given) -> list
```

A coordinate's answer as single answers: each entry of a list, and an
answer that names several things with one quote (owner decision
2026-11-07) once per name, each with that quote.

### spread

```python
def spread(reply, slots: list)
```

*reply* with each coordinate that may name several things
(`several`) and names several as a list of single answers
(`entries_of`): what follows a reply -- the check of a find, the rows of
a value -- reads one name with its quote. Anything else is left as it
is.

### answers_each

```python
def answers_each(reply, slots: list) -> list
```

The reply for one value as one reply per row (owner decision
2026-11-06): a coordinate that may name several things (`several`) and
names several of them, in a list or with one quote for several
(`entries_of`), gives one reply per name, with every other coordinate's
answer the same on each; an empty list is no answer. Any other reply is
the one reply.

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
other tables and figures of it included, when it fits *budget*, two
pages of the plan, else that many characters around the table's place
in it. The model reads from it what it needs: a cut to 200 characters on
each side would have hidden the text of 72 % of the quotes the m8 run
took from a table's section. None for a section, and for a table or
figure whose section is not among *passages*.

### near_of

```python
def near_of(source: Source, order: list,
            budget: Optional[int]) -> dict
```

{"before": Source, "after": Source}: the sections before and after a
value's place, which is the section a table or figure stands in, as the
second reading shows them (owner decision 2026-11-06: where the reading
said a coordinate is not stated, it is asked once more with the plan
around it). Together at most *budget*, two pages of the plan, each side
the part nearest the place. A side without a section is left out; {}
where the plan has neither.

### table_before_of

```python
def table_before_of(source: Source) -> Optional[Source]
```

The title and head of the table right before *source*, on its page
or the page before, which *source* may continue (`lookup.continued`), as
a passage a quote may stand in; whether the table continues it is the
model's reading (owner decisions 2026-11-06 and 2026-11-07). None for
any other passage.

### settings_shown

```python
def settings_shown(settings: list) -> list
```

The plan's settings as a request shows them: what each is about, what
it settles and its quote (`settings.PlanSettings`, owner decision
2026-11-07).

### settings_evidence

```python
def settings_evidence(settings: list, passages: dict) -> list
```

The quotes of the plan's settings, each a passage a quote may stand
in under the passage it was read from.

### beside_of

```python
def beside_of(source: Source, title_page: Optional[Source]) -> tuple
```

({key: text} a reading request shows beside *source*, [the passages
a coordinate's quote may stand in for them]): the line of the title page
that names the plan's own place (owner decision 2026-11-06) and the
title and head of the table *source* may continue (`table_before_of`).

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

### gather

```python
def gather(ask: Callable, reply: dict, gathered: Gathered, order: list,
           passages: dict, budget: Optional[int],
           then: Optional[Callable] = None) -> tuple
```

(the reply that stands, the requests made): what each reply asks of
the rest of the plan is fetched and *ask()* sends the next round, a
message after that reply bringing what is new (owner decisions
2026-11-07: the rounds are one conversation), until a round asks for
nothing the conversation has not shown or it no longer fits the model's
window (`Gathered.unfit`). The reply before such a round stands.
*then(reply)*, where given, is asked when a round asks for nothing new:
True when it showed the request something new, which sends it again
(the combing lists the next passages of its ranking, owner decision
2026-11-06).

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
passage does not state is no value. Empty for a parameter with no
list.

### source_shown

```python
def source_shown(source: Source) -> dict
```

### shown_value

```python
def shown_value(claim: dict) -> dict
```

A value as a request shows it: its value, wording and quote, or for
one read off a figure the sentence of what was read.

### values_payload

```python
def values_payload(source: Source, parameter, context: dict,
                   read: list = (), drawn: bool = False) -> dict
```

The first message of the values of a passage: the parameter in
short, a category parameter with its entries (`value_classes`), first,
the same in every conversation of the parameter; then the passage and
the text around a table or figure (ticket 26: what requests share
stands first). Nothing of the value's coordinates. The line of the
title page that names the plan's own place stands before the passage,
the same in a plan; the title and head of the table the passage may
continue after it (`beside_of`). The next value, and a value the check
refused, are asked after the answer in the same conversation (owner
decisions 2026-11-07); *read*, the values named so far, stands only in
a conversation begun anew because the old one no longer fit the
model's window (`Reader._rounds`). With *drawn*, a figure whose image
goes with the request says so ("image"), and the system prompt tells how
a number only the image shows is read off it.

### values_response_format

```python
def values_response_format(parameter, drawn: bool = False) -> dict
```

The next value of the passage as the reply itself, with no wrapper
(owner decision 2026-11-06): its value and quote, its printed wording
only where the value is an entry of a list or a number (a free text value
is its own wording, `verify.wording_of`); {"value": null} where no
further value stands in it. A category value is one of its entries, or
"" where the model is unsure of them. With *drawn*, a figure whose image
goes with the request: always whether the image only draws the number
(`drawn`), and in place of a quote the sentence of what was read off the
image where no shown text states it (`reading`, owner decisions
2026-11-05 and 2026-11-07).

### values_example

```python
def values_example(parameter, drawn: bool = False) -> dict
```

The reply of a value request as its example shows it: a value read,
with exactly the keys `values_response_format` asks for this parameter
and this passage, in its order (owner decision 2026-11-06): a printed
value, so with *drawn* one the image does not only draw. The reply that
names no further value stays in the prompt's rule line, and one read off
an image in the part about the image.

### claim_of

```python
def claim_of(reply, drawn: bool = False) -> Optional[dict]
```

The value a round's reply names, as a row's claim, or None where it
names none: {"value": null}, or no object. Where the request sent the
image (*drawn*), whether the image only draws the number, and a reading
in place of a missing quote, which the switch `read_off` makes the
value's evidence (`verify.read_off`).

### same_value

```python
def same_value(a: dict, b: dict) -> bool
```

Do two claims name the same value: the same number or wording, in the
same quote, read off the same way?

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
                  parameter, kind: str = "section") -> Optional[tuple]
```

(kind, reason) of what the check refuses of a round's value of
*parameter*, or None: a value already read (`REPEATED`), the value
itself (`VALUE`: its quote in no passage of *shown*, its number not in
its quote, what the fold refuses of the value and its quote,
`verify.value_refused`), or a quote that does not pin the value down
(`UNIQUE`, owner decision 2026-11-07: it stands in what *shown* holds
more than once, or holds the value more than once). Of a value read off
a figure of *kind*, the passage the round reads, only the value itself
(`verify.read_off`). The fold's refusal is told in its own words: what
the fold refuses, the model hears while it can still answer (owner
decision 2026-11-05).

### text_payload

```python
def text_payload(source: Source, parameter, slots: list, row: Row,
                 where: str, context: dict, full: bool = False) -> dict
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
words. The line of the title page stands with the plan's years, the
table the passage may continue after it (`beside_of`). It is the first
message of the value's conversation: its next coordinate and a
correction follow the answer (`group_payload`, owner decisions
2026-11-07).

### group_payload

```python
def group_payload(parameter, slots: list, where: str, context: dict,
                  full: bool = False) -> dict
```

The message that asks the next group of a value in its conversation
(owner decision 2026-11-07: one conversation per value, each group a
message of its own): the group's coordinates and the spec's words for
where a plan prints them, the parameter's full definition where the
group classifies (*full*) and the conversation has not shown it, and for
a frame group the plan's base and target years and the survey's pairs of
the passage (`group_context`). The passage and the value stand in the
first message; a row the conversation goes on for that its answers do
not show, a further name a reply gave (`_Job.clone`), is shown again
with what it has read ("value").

### text_response_format

```python
def text_response_format(slots: list) -> dict
```

Every coordinate of the group for the one value the request shows,
each with the sentence of one the passage does not state (`probe`).

### text_example

```python
def text_example(slots: list) -> dict
```

The reply of one group's request as its example shows it: exactly
the coordinates this request asks, in its order, each read
(`entry_example`). The model writes the keys its example shows: with one
example per prompt, 183 of 184 heat load requests left out the
"aggregation" it did not show (owner decision 2026-11-06).

### answer_of

```python
def answer_of(entry: dict) -> dict
```

### value_replies

```python
def value_replies(reply: dict, slot, label: str,
                  window: tuple = ("own", 1)) -> list
```

[(level, window, field reply)] of one coordinate of a group's reply
for the value *label*; *window* is ("near", 1) in a second reading.

### is_open

```python
def is_open(claim: dict, slot) -> bool
```

Is a coordinate still open on a value after its reading: said not
stated, answered without backing, or not answered at all?

### refused_of

```python
def refused_of(failed: list) -> collections.Counter
```

What the check refused of a reply, by reason.

### unanswered_what

```python
def unanswered_what(entry, name: str) -> str
```

What a correction says of the coordinate *name* that a reply about
one value (*entry*) gave no answer for: that the reply lacked it, or,
where it stands there in another form than the one asked (a bare word
where an object with "value" is asked), that the reply did not have the
form asked for (owner decision 2026-11-06: a correction names the
fault).

### value_corrections

```python
def value_corrections(row: Row, failed: list, slots: list,
                      reply: Optional[dict] = None) -> list
```

What the check refused of a group's reply for one value, each named
by its coordinate: [{coordinate, what}]. A coordinate *reply* left out
is named as missing, one it gave in another form than asked as given in
the wrong form (`unanswered_what`).

### named_corrections

```python
def named_corrections(corrections: list, reply: dict, slots: list) -> list
```

*corrections* for one of several rows a reply made of one value
(`answers_each`): each correction of a coordinate that named several
things names the name this row was given, and its quote, so the request
asks again for that one.

### told_once

```python
def told_once(corrections: dict, given: dict, slots: list,
              named: bool) -> list
```

What ONE message after an answer tells of the rows it made (owner
decision 2026-11-07: one follow-up per reply): each row's corrections
(*corrections*, {row label: [{coordinate, what}]}) in the order of the
rows, with *named* those of a coordinate that named several things
naming the name and quote that row was given (*given*, {row label: its
answer}; `named_corrections`), each correction told once.

### routed

```python
def routed(answers: list, rows: list, corrections: dict, given: dict,
           slots: list) -> list
```

[(row or None, answer, {coordinate})]: where each answer of a
follow-up (`answers_each`) goes, and which of its coordinates (owner
decisions 2026-11-07). An answer for a coordinate that may name several
things goes to the row its name was refused on, a changed name to the
next such row still open (they differ only in the name refused), and a
name for none of them to a row of its own (None); one that repeats
another row's answer unchanged corrects nothing. A row corrected on the
other coordinates takes them from the first answer, which holds them
for every name. *corrections* is {row label: [{coordinate, ...}]},
*given* {row label: the answer it got before}.

### cleared

```python
def cleared(claim: dict, names: list) -> dict
```

*claim* with the coordinates *names* open again: a row of its own
for a further name starts from a copy of its value.

### check_response_format

```python
def check_response_format() -> dict
```

What the check of a find answers: whether the place it was quoted
from speaks about the value, one of `ABOUT`.

### check_example

```python
def check_example() -> dict
```

The reply of a check as its example shows it.

### place_text

```python
def place_text(text: str, quote: str, budget: Optional[int]) -> str
```

The text of the place a check shows: whole where it fits *budget*
characters, else the stretch of *budget* around *quote*, so the quote
stands in what is shown.

### check_shown

```python
def check_shown(source: Source, parameter) -> dict
```

The value's passage and parameter as the check shows them.

### turned_out

```python
def turned_out(reply, slots: list, judge: Optional[Judge], evidence: list,
               row: dict) -> tuple
```

(*reply* without each find whose place the check says does not speak
about the value (`Judge`), {coordinate: [the answers taken out]}).

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
