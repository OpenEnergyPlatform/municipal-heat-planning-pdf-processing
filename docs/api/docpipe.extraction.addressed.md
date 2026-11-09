# docpipe.extraction.addressed

`docpipe/extraction/addressed.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

addressed.py: One document read in pieces of numbered lines, one question per
request, every answer an address (owner decisions 2026-11-08 evening, both
profiles).

Every request carries its instruction, the smallest part of the plan that
answers its question, and one question; every answer is an address, a
number or a few words, and code looks up what an address names
(`units.py`). Nothing is a conversation: an answer that did not hold is
asked once more as a request of its own, with what did not hold (`follow`).

The steps of a document (`Reader`):

1. Its passages as numbered lines and pieces of at most eight
   (`units.Chunk`); a figure transcribed into lines once per run and kept
   under the harvest (`Transcripts`), its image sent to no other request.
2. What the plan settles for all its values and its own years, where the
   profile asks them (`PLAN_FIELDS`), and the fields a document has once
   (`Parameter.once_per_document`): the title page and the five pieces a
   search finds best for a sentence written for the field, then the next
   five, until an answer holds or every piece was shown (`docfield`).
3. Every other field in every piece, the pieces best first for the
   field's sentences (`find`): each value an address and its words.
4. Each coordinate of each value on its own (`coord`): the value's line
   with the head of its table or the sentences beside it, the headings up
   to it, the title page and the plan's settings; the answer an address and
   words, or 0 with a sentence of how the plan would print what is missing
   (HyDE). An entry of a list is asked once per wording (`list`), a name of
   the document's list of scenarios or works once per name (`names`). A 0
   is asked again with the pieces before and after the value's, then with
   the pieces a search with that sentence finds best, five at a time
   (`search`); what only the value's own passage can say is not searched.
   A find from another passage is asked whether it speaks about the value
   (`check`). A year still open is asked last with the plan's base and
   target years.
5. A value stated for a group of scenarios takes the members the document
   names, one row each, where the field takes groups
   (`Parameter.takes_group`).

The two checks are unchanged: a coordinate's quote is the line its address
names, which stands in what the request showed, and its answer stands in
that line (`pipeline.merge_field`). A value is folded as before.

Author: Felix Vossel

## Classes

### Found

```python
@dataclass
class Found
```

What an answer's address names: the lines, their passage, the cell
and the words, or the reason it names nothing.

Fields:

- `lines: list = field(default_factory=list)`: [(Line, Source)]
- `passage: Optional[Passage] = None`
- `cell: Optional[int] = None`
- `words: str = ""`
- `letter: str = ""`
- `why: Optional[str] = None`
- `quoted: list = field(default_factory=list)`: The lines its quote is: the named ones, and where they are too short to name a place, the shown lines around them (`Shown.around`).

#### Found.quote

```python
@property
def quote(self) -> str
```

#### Found.source

```python
@property
def source(self) -> Optional[Source]
```

### Transcripts

```python
class Transcripts
```

figure -> its lines, transcribed once per run and kept under the
harvest (`transcripts/<document>.json`): a figure whose image and prompt
are those of the kept transcription is not asked again (owner decision
2026-11-08, e).

*ask(source, document_id)* is the transcription request, the reply as
a dict or None; *fingerprint* says which prompt and model wrote it,
*image_key(source)* which image (None where the figure has none: then
nothing is asked and its description stands for it).

#### Transcripts.\_\_init\_\_

```python
def __init__(self, ask: Optional[Callable], store: Optional[Path],
             fingerprint: str, image_key: Callable)
```

### Entry

```python
@dataclass
class Entry
```

One entry of a document's list of names: what it is called in
requests and in the graph, the work it belongs to, and the line it was
first read at.

Fields:

- `label: str`
- `name: str`
- `work: int = 0`
- `quote: str = ""`

### Names

```python
class Names
```

A document's list of scenarios or works, built piece by piece: a
name is asked against the list so far and is an entry or a new one
(`names`, owner decisions 2026-11-08: two equal names of two studies
are two entries; nothing is merged by its spelling).

#### Names.\_\_init\_\_

```python
def __init__(self, kind: str, first: Optional[Entry] = None)
```

#### Names.add

```python
def add(self, name: str, work: int = 0, quote: str = "") -> int
```

The number of a new entry for *name*, or of the entry a request
beside this one added for the same name of the same work; a label
another entry has already is told apart by its work.

#### Names.shown

```python
def shown(self, works: Optional["Names"] = None) -> list
```

[(number, text)] of the list as a request shows it, each under
its work where the entries have works, ordered by work.

### Plan

```python
class Plan
```

One document as numbered lines and pieces, and what its requests
share while it is read: its title page, its settings, its years, the
entries its wordings were read as, and its lists of names.

#### Plan.\_\_init\_\_

```python
def __init__(self, document_id: int, sources: list, transcripts: dict,
             chunk_units: int)
```

#### Plan.key_lock

```python
def key_lock(self, key) -> threading.Lock
```

#### Plan.headings

```python
def headings(self, owner: tuple) -> list
```

[(Line, Source)] of the titles of the sections up to a passage,
its own last (`lookup.sections_up_to`).

#### Plan.chunk_of

```python
def chunk_of(self, owner: tuple, number: int) -> Optional[Chunk]
```

The piece of a passage that holds its line *number*.

#### Plan.beside

```python
def beside(self, chunk: Chunk) -> list
```

The pieces right before and after *chunk* in the plan's order.

### Asks

```python
@dataclass
class Asks
```

The requests of the harvest, each (payload, document_id, *, shape,
example, **noted) -> the reply as a dict, CUT or None. *follow* is a
request asked once more with what did not hold: (kind, payload,
document_id, *, shape, example, **noted). *check* and *names* are None
where the profile writes no prompt for them (`OPTIONAL`).

Fields:

- `find: Callable`
- `docfield: Callable`
- `coord: Callable`
- `list: Callable`
- `search: Callable`
- `follow: Callable`
- `names: Optional[Callable] = None`
- `check: Optional[Callable] = None`

### Counts

```python
@dataclass
class Counts
```

What the requests of a document came to, for the trace and the
statistics: requests per kind, refusals per reason, and the search
sentences that were questions.

Fields:

- `asked: collections.Counter = field(default_factory=collections.Counter)`
- `failed: collections.Counter = field(default_factory=collections.Counter)`
- `questions: int = 0`
- `lock: threading.Lock = field(default_factory=threading.Lock)`

#### Counts.ask

```python
def ask(self, kind: str, n: int = 1) -> None
```

#### Counts.fail

```python
def fail(self, why: str, n: int = 1) -> None
```

#### Counts.question

```python
def question(self) -> None
```

### Reader

```python
class Reader
```

The reading of a document (`Plan`): what it settles and its years
(`settled`), its fields asked once (`docfield`), every other field in
its pieces (`find`) and each value's coordinates (`coordinates`).

*spec* is the document's spec, *asks* its requests (`Asks`).
*order(document_id, sentences, chunks)* is every piece best first for
search sentences (the reranker over all pieces), *search_order* the
same from the passages the vector search finds best, their pieces
reranked first (`make_order`). *probes(parameter, document_id)* is a
field's search sentences, *known(claim, asked)* what a value has read
in the plan's words (`runner.row_context`), *span_marks* what a value
stated for a span of years takes on each of its rows. *plan_fields*
are what the profile asks once of a plan ("settings", "base_year",
"target_year"; each {"name", "means", "sentence"}), *works* the field
whose finds name other works and the fields each of them is asked
({"name", "means", "fields": {uri: question}}), None where the profile
keeps no list of works. *frame_slots* date a value by the plan's years.
*each(jobs, run)* runs jobs side by side; *budget* is how many lists of
a search one coordinate walks before it is `exhausted`.

#### Reader.\_\_init\_\_

```python
def __init__(self, spec, asks: Asks, order: Callable, *,
             search_order: Optional[Callable] = None,
             probes: Optional[Callable] = None,
             known: Optional[Callable] = None,
             span_marks: Optional[dict] = None,
             plan_fields: Optional[dict] = None,
             works: Optional[dict] = None,
             frame_slots: Optional[list] = None,
             each: Optional[Callable] = None, trace=None,
             budget: int = 12)
```

#### Reader.lists_of

```python
def lists_of(self, plan: Plan) -> None
```

The lists of names a document builds while it is read: its
scenarios (a field or coordinate the spec merges) and its works
(where the profile keeps them), the publication itself the first
work.

#### Reader.coordinates_of

```python
def coordinates_of(self, plan: Plan, reads: list,
                   counts: Counts) -> None
```

Every value of *reads* asked its coordinates, side by side;
each Read's claims become the rows they came to.

#### Reader.find

```python
def find(self, plan: Plan, parameter, chunk: Chunk,
         counts: Counts) -> dict
```

The values of *parameter* in one piece (`find`): {"claims",
"asked", "failed", "lost"}, *lost* [why] of every part that came to
nothing. A piece whose answer did not fit its room is asked in
halves of its own lines, each with the lines every piece of its
passage shows, until a single line is a hole of its own (owner
decision 2026-09-12: a request is split, never its answer
rescued).

#### Reader.claim

```python
def claim(self, plan: Plan, parameter, got: Found,
          counts: Counts) -> Optional[dict]
```

The claim of a value found: its number or words, the line as its
quote, its address, the head of its column, and for a figure that a
model read it off a picture (`drawn`, trust level C). A value of a
list is asked its entry (`list`).

#### Reader.ask_once

```python
def ask_once(self, plan: Plan, field_: dict, sentences: list,
             counts: Counts, uri: str) -> tuple
```

([Found], lost) of a field asked once of the document
(`docfield`): the title page and the `DOCFIELD_CHUNKS` pieces a
search finds best for *sentences*, then the next ones, until an
answer holds or every piece was shown. *lost* is CUT or NO_ANSWER
where a request came to nothing, else None.

#### Reader.docfield

```python
def docfield(self, plan: Plan, parameter, counts: Counts) -> list
```

[Read] of a field the document has once (owner decision
2026-11-08: asked once per document, never per piece), one per
passage a value of it was read in, each value asked its
coordinates; a field nothing came of is a Read without values,
unread with its reason where a request came to nothing.

#### Reader.settled

```python
def settled(self, plan: Plan, counts: Counts) -> None
```

What the plan settles for all its values and its own years, each
asked once in the form of a document's field (owner decision
2026-11-08): the settings' lines are shown under `F` with every
value's coordinates, the years are the plan's base and target years
(`pipeline.named_years`).

#### Reader.entry

```python
def entry(self, plan: Plan, uri: str, name: str, slot, words: str,
          got: Optional[Found], counts: Counts, several: bool = False)
```

The entry of *slot*'s list a wording means, asked once per
document, field, coordinate and wording (`list`, owner decision
2026-11-08): its label, a list of labels where several may be
meant, "" where none fits (0).

#### Reader.name_of

```python
def name_of(self, plan: Plan, kind: str, words: str,
            got: Optional[Found], counts: Counts, work: int = 0,
            besides: tuple = (), group: bool = False,
            uri: str = "") -> list
```

The entries of the document's list of *kind* a name means
(`names`): [(label, number)], a new entry where the name is not on
the list yet, ("out", label) for an entry *besides* the names
((label, means)); with *group* the words may name several entries.
Each name is asked once per document and work.

#### Reader.coordinates

```python
def coordinates(self, plan: Plan, read: Read, row: Row,
                counts: Counts) -> list
```

[*row* and the rows made beside it], each coordinate of the
spec asked on its own in the order of the groups (owner decision
2026-11-07); a coordinate that reads the value as no value of its
field (`fields.kept`) closes those after it (`out_of_slice`). A
value that is a name of the document's list is that entry
(`named_value`).

#### Reader.coordinate

```python
def coordinate(self, plan: Plan, read: Read, row: Row, group, slot,
               counts: Counts, clone: Callable) -> list
```

One coordinate of one value (`coord`), [the rows made beside
it]: its own place first; a 0 then, unless only its own passage can
say it, the pieces beside it and a search with the sentence of how
the plan would print it; a year still open the plan's years.

#### Reader.several

```python
@staticmethod
def several(slot) -> bool
```

#### Reader.coord_example

```python
@staticmethod
def coord_example(shown: Shown, several: bool) -> dict
```

#### Reader.coord_finds

```python
@staticmethod
def coord_finds(reply) -> list
```

#### Reader.take

```python
def take(self, plan: Plan, read: Read, row: Row, slot, shown: Shown,
         reply: dict, payload: dict, kind: str, example: dict,
         counts: Counts, clone: Callable, window: tuple,
         noted: dict) -> tuple
```

(rows made, held, hyde) of a coordinate's answer: its finds each
read onto the row, one row per entry where several are named, and
checked (`merge_field`); what does not hold is asked once more with
its reason (`follow`), then stays `unbacked`. *hyde* is the
answer's sentence where it found nothing.

#### Reader.settle

```python
def settle(self, plan: Plan, read: Read, row: Row, slot, shown: Shown,
           finds: list, counts: Counts, clone: Callable,
           window: tuple) -> tuple
```

(rows made, held, [what failed]) of a coordinate's finds read
onto *row*: each entry they name is a row of its own.

#### Reader.answers

```python
def answers(self, plan: Plan, parameter, row: Row, slot, got: Found,
            counts: Counts) -> list
```

[(answer for `merge_field`, names it means or None)] of one find
of a coordinate: a year from its words, an entry of its list, a name
of the document's list, or the words themselves.

#### Reader.work_of

```python
@staticmethod
def work_of(plan: Plan, row: Row) -> int
```

The number of the work a value was read for in the document's
list of works, 0 where none.

#### Reader.quantity

```python
def quantity(self, plan: Plan, parameter, row: Row, slot,
             counts: Counts) -> None
```

What a number is, by the words it was read with: its own
designation, the head of its column and its unit go to the list
(`list`), and the line that holds the designation, else the value's
own, is its quote (owner decision 2026-11-08: "quantity geht mit den
Worten von what, Kopf und Einheit direkt in die Listenfrage").

#### Reader.plan_year

```python
def plan_year(self, plan: Plan, parameter, slot, got: Found,
              counts: Counts) -> dict
```

The year a find names by the plan's word for its state
("Basisjahr", "Zieljahr"), asked among the plan's base and target
years (`list`, owner decision 2026-11-07): the answer for
`merge_field`, which reads it where the words stand in the line and
the year is one of the plan's (`pipeline.named_year`).

#### Reader.last_year

```python
def last_year(self, plan: Plan, parameter, row: Row, slot,
              counts: Counts, noted: dict) -> None
```

A year nothing found, asked last with the plan's base and target
years (owner decision 2026-11-07): the line of the value's place
that names the plan's word for its state, and the year of the list
it means; read where the words stand in that line and the year is
one of the plan's (`pipeline.named_year`).

#### Reader.search

```python
def search(self, plan: Plan, read: Read, row: Row, slot, payload: dict,
           hyde: str, counts: Counts, clone: Callable,
           noted: dict) -> list
```

A coordinate its value's own place does not state (owner
decisions 2026-11-08): the pieces right before and after the
value's, then the pieces a search finds best for the answer's
sentence of how the plan would print it (HyDE; the field's own
sentence where it wrote none), `SEARCH_CHUNKS` at a time, until a
find holds, one does not hold after its follow-up (`unbacked`),
the ranking ends (`unstated`) or the budget does (`exhausted`). What
a request asks to fetch itself (`more`) is shown in the next. [the
rows made].

#### Reader.search_round

```python
def search_round(self, plan: Plan, read: Read, row: Row, slot,
                 payload: dict, batch: list, counts: Counts,
                 clone: Callable, window: tuple, noted: dict) -> tuple
```

(rows made, held, what it asks to fetch) of one request of a
search: the value's place and the pieces *batch* under letters of
their own.

#### Reader.about

```python
def about(self, plan: Plan, row: Row, slot, got: Found, counts: Counts,
          noted: dict) -> bool
```

Does the place a find of another passage stands in speak about
this value (`check`, owner decision 2026-11-07)?

#### Reader.fetch

```python
def fetch(self, plan: Plan, more, batch: list, seen: set) -> list
```

The pieces a reply asks for itself (`more`), those not shown
yet: the piece before or after a shown one, a table or figure by
its placeholder, the pieces a pattern stands in, the pieces best
for a sentence of its own.

#### Reader.named_value

```python
def named_value(self, plan: Plan, parameter, row: Row,
                counts: Counts) -> None
```

A value that is the name the document gives a thing (a
scenario): the entry of the document's list it is, a new one where
it is not on it yet, under `value_means` (owner decisions
2026-11-08: the list is built piece by piece).

#### Reader.works

```python
def works(self, plan: Plan, chunks: list, counts: Counts) -> list
```

The works the document presents, compares or cites beside itself
(owner decision 2026-11-08, h): found piece by piece (the profile's
`WORKS` field), each asked against the document's list of works,
and each new one asked at its line for what the profile asks of a
work (its title, its organisation, its year, its short name):
values of that work, never of this publication, which the graph
does not take. [Read] of those values.

#### Reader.work_finds

```python
def work_finds(self, plan: Plan, shown_field: dict, chunk: Chunk,
               counts: Counts) -> list
```

[Found] of the names of other works in one piece (`find`).

#### Reader.work_value

```python
def work_value(self, plan: Plan, parameter, question: str, one: Found,
               label: str, counts: Counts) -> Optional[dict]
```

One detail of a work, asked at its line (`coord`): the claim of
a value of *parameter* whose work is that work, with the line as its
quote; None where the line does not give it.

### ChunkDoc

```python
@dataclass
class ChunkDoc
```

A piece as the reranker reads it.

Fields:

- `owner_kind: str`
- `owner_id: tuple`
- `text: str`
- `image_path: Optional[str] = None`

### Orders

```python
class Orders
```

(plan, parameters, chunk_units, scope, chunks) -> {field uri:
[piece key]}: the pieces of each field best first for its sentences,
kept under the harvest (`survey/<document>[.<scope>].json`) with the
passages each field was read in, which the passes over a stored harvest
read (`surveyed.surveyed_owners`).

#### Orders.\_\_init\_\_

```python
def __init__(self, order: Callable, probes: Callable,
             store: Optional[Path], trace=None, written: str = "")
```

## Functions

### told

```python
def told(why: str, entry) -> str
```

Why a find or an answer did not hold, in the profile's words, with
the address and the words it gave.

### number_of

```python
def number_of(words: str) -> Optional[str]
```

The number the words of a find print, with its sign (owner decision
2026-11-01), in `canonical_number`'s spelling: the words themselves
where they are a number, else the one number they print ("750.940
kWh", "ca. 8,8 GWh"); None where they print none or more than one
("800 / 750", "2019 bis 2021"). A signed number and its magnitude are
one number ("-1.155").

### is_question

```python
def is_question(sentence: str) -> bool
```

Is a search sentence a question rather than a sentence of the
plan?

### more_schema

```python
def more_schema() -> dict
```

### found_format

```python
def found_format() -> dict
```

The finds of a request: each an address and the words of the value,
an empty list where nothing shown holds one.

### coord_format

```python
def coord_format(several: bool, more: bool = False) -> dict
```

A coordinate's answer: an address and its words, or 0 and the
sentence of how the plan would print it (`hyde`); one that may name
several entries lists its finds.

### entry_format

```python
def entry_format(several: bool = False, new: bool = False) -> dict
```

The number of a list's entry, 0 for none; a list of them where
several may be meant; "new" for a name not on the document's list.

### year_format

```python
def year_format() -> dict
```

The last question of a year: the line that names the plan's state,
its words and the entry of the plan's years it means, 0 for none.

### lines_format

```python
def lines_format() -> dict
```

### about_format

```python
def about_format() -> dict
```

### nothing_found

```python
def nothing_found(reply) -> bool
```

Does a coordinate's answer say nothing shown states it?

### hyde_missing

```python
def hyde_missing(reply) -> Optional[str]
```

"hyde" where a coordinate's answer says nothing shown states it and
gives no sentence and fetches nothing: such a reply is asked again
(owner decision 2026-11-08, test 6); None where it holds.

### field_shown

```python
def field_shown(parameter, full: bool = False) -> dict
```

A field as a request shows it: its name and what a value of it is,
in short where the spec writes that (`brief`).

### block_payload

```python
def block_payload(passage: Optional[Passage], shown: Shown,
                  letter: str = "") -> dict
```

A block of lines as a request shows it: its passage's kind, page and
title, and the lines with their addresses.

### first_address

```python
def first_address(shown: Shown, table: bool, letter: str = "") -> str
```

An address for a request's example: the first of its own lines that
is no title or head, a cell of it in a table.

### resolve

```python
def resolve(shown: Shown, entry, passages: dict) -> Found
```

The lines an answer's address names in what *shown* showed, its
words checked against them: `NOT_AN_ADDRESS` where it names no shown
line or cell, `WORDS_NOT_IN_LINE` where its words do not stand in what
it names. Words left empty are the cell's, or the lines' of a stretch;
a single line without a cell needs words.

### image_key

```python
def image_key(path: Optional[str]) -> Optional[str]
```

What names an image for its kept transcription: its bytes' hash.

### show_value

```python
def show_value(plan: Plan, claim: dict, headings: bool = True) -> tuple
```

(Shown, payload) of what every request about a value's coordinates
shows: its line with its table's title and head, or the sentences
before and after it; the headings up to it, the title page and the
plan's settings; the value as its words and its address.

### settings_of

```python
def settings_of(plan: Plan) -> dict
```

{"settings": lines} of what the plan settles for all its values,
shown beside a list's entries, {} where it settles nothing: they hold
for every value, also where the entry of a wording depends on them
(emissions given in CO2 equivalents).

### field_shown_of

```python
def field_shown_of(field_: dict) -> dict
```

A field the profile asks of a plan as a request shows it.

### make_order

```python
def make_order(reranker: Optional[Callable], rank: Optional[Callable]
               ) -> tuple
```

(order, search_order), each (document_id, sentences, chunks) -> the
pieces best first. *order* has the reranker score every piece with
every sentence, keeping each piece's best (owner decisions 2026-11-08:
all pieces, best first); *search_order* takes the passages the vector
search finds best (*rank*, with its reranker over passages), has the
reranker order the pieces of the first `SEARCH_PASSAGES` and puts the
rest after them in the plan's order (owner decision 2026-11-08: "Treffer
werden in ihre Stücke zerlegt und vom Reranker mit demselben Satz
geordnet"). Without a reranker the pieces keep their passages' order;
without either, the plan's.

### order_key

```python
def order_key(parameters: list, chunk_units: int, written: str = "") -> str
```

The key an order of the pieces is kept under: the fields it ranked,
each with the words its search sentences are written from, what writes
them (*written*) and the size of the pieces.

[Back to the index](../README.md)
