# docpipe.extraction.addressed

`docpipe/extraction/addressed.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

addressed.py: One document read in pieces of numbered lines, one question per
request, every answer an address (owner decisions 2026-11-08 evening, both
profiles).

Every request carries its instruction, the smallest part of the plan that
answers its question, and one question; every answer is an address, a
number or a few words, and code looks up what an address names
(`units.py`). Nothing is a conversation: an answer that did not hold is
asked again as a request of its own, with what did not hold (`follow`), as
often as the flow says, once by default (`flow.Numbers.follow_ups`).

The steps of a document (`Reader`):

1. Its passages as numbered lines and pieces of at most eight
   (`units.Chunk`); a figure transcribed once per run into its caption and
   its numbers and kept under the harvest (`Transcripts`); its image goes
   only to a question about a coordinate that asks for it, once a request
   (`image`, owner decision 2026-11-12). A field of numbers reads a figure
   in the pieces of its numbers, any other field in the piece of its
   caption (`units.pieces_for`).
2. What the plan settles for all its values and its own years, where the
   spec asks them (`Spec.plan_fields`). Where the spec keeps a list of
   works (`Spec.works`), every piece is asked once which of its lines
   speak of another work and which line shows the rest are this
   publication's own (`work`, owner decisions 2026-11-09): a value takes
   the work of the line it stands in only from such a line, else asks its
   own (`work_coordinate`).
3. The fields a document has once (`Parameter.once_per_document`): the
   title page and the pieces a search finds best for a sentence written
   for the field, the run's budget of them, as many a request as the flow
   says, every find kept (`docfield`); a field with a list the budget times
   the flow's factor (`flow.Numbers`).
4. Every other field in every piece, the pieces best first for the
   field's sentences (`find`): each value an address and its words, and
   where the field has a list, its entry (owner decision 2026-11-09).
5. Each coordinate of each value on its own (`coord`): the value's line
   with the head of its table or the sentences beside it, the headings up
   to it, the title page and the plan's settings; the answer an address and
   words, or 0. An entry of a list is asked once per wording (`list`), a
   name of the document's list of scenarios or works once per name
   (`names`), 0 where the words name no such thing. A 0 is asked again
   with the pieces before and after the value's, then with the pieces a
   search finds best for a sentence of how the plan would print the answer
   (HyDE, `phrase`): the run's budget of them by kind, five a request, the
   model fetching more itself (`search`); what only the value's own passage
   can say is not searched, and no work is. A find from another passage is
   asked whether it speaks about the value (`check`). A year still open is
   asked last with the plan's base and target years.
6. A value stated for a group of scenarios takes the members the document
   names, one row each, where the field takes groups
   (`Parameter.takes_group`).

The two checks are unchanged: a coordinate's quote is the line its address
names, which stands in what the request showed, and its answer stands in
that line (`pipeline.merge_field`). A value is folded as before.

Author: Felix Vossel

## Classes

### Asking

```python
@dataclass
class Asking
```

What a box of the flow asks with (`engine.Engine`): its id, which
every request it sends carries in the trace (`box`); *refused(Found)*
-> (reason, sentence) of the first own check that refuses a find, None
where every check lets it be; how often an answer that did not hold is
asked again, None for the flow's number. Whether a find of another
passage speaks about the value the question asks itself, in the own
values of the step after it that checks (`targets.keep_find`).

Fields:

- `box: Optional[str] = None`
- `refused: Optional[Callable] = None`
- `follow_ups: Optional[int] = None`
- `scope: object = None`: Where the question stands (`engine.Scope`), and the steps after it asked inside its answers, by their target (a list entry, a name; owner decision 2026-11-12 evening).
- `nested: Optional[dict] = None`

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
- `entry: Optional[int] = None`: The number of the entry of the request's list a find names, where the field has a list (owner decision 2026-11-09), 0 for none.
- `outside: bool = False`: The entry it named is none of the list's and the rule `outside_list` keeps its wording (entry 0).
- `elsewhere: bool = False`: Its quote stands in no shown line and was found in another passage of the document, which is its place (rule `check_quote_shown` off).

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

figure -> its caption and its numbers, transcribed once per run and
kept under the harvest (`transcripts/<document>.json`): a figure whose
image and prompt are those of the kept transcription is not asked again
(owner decision 2026-11-08, e); one kept in another form is (owner
decision 2026-11-09: caption and numbers apart).

*ask(source, document_id)* is the transcription request where the
step that writes out the figures gives none (`__call__`), the reply as
a dict or None; *fingerprint* says which prompt and model wrote it (a
text, or a function that tells it where it is read, in the step that
transcribes, whose model it names, `fingerprint_of`),
*image_key(source)* which image (None where the figure has none: then
nothing is asked and its description stands for it).

#### Transcripts.\_\_init\_\_

```python
def __init__(self, ask: Optional[Callable], store: Optional[Path],
             fingerprint, image_key: Callable)
```

#### Transcripts.fingerprint

```python
@property
def fingerprint(self) -> str
```

#### Transcripts.fingerprint_of

```python
def fingerprint_of(self, told: Optional[dict] = None) -> str
```

What names the prompt and model a transcription is written with,
and *told*, the prompt, inputs and answer form of the step that
writes it where they are not its preset's (`engine.Engine.
writes_figures`): a transcription kept from another is written
again.

### Entry

```python
@dataclass
class Entry
```

One entry of a document's list of names: what it is called in
requests and in the graph, the work it belongs to, the line it was
first read at, and how the value it was first read for read its work
(its `work*` fields), which a later name of the entry whose own work
stayed open takes (owner decision 2026-11-09).

Fields:

- `label: str`
- `name: str`
- `work: int = 0`
- `quote: str = ""`
- `work_read: Optional[dict] = None`

### PieceWork

```python
@dataclass
class PieceWork
```

What a piece's work request answered (owner decisions 2026-11-09):
the finds of other works, each (the (passage, line) pairs it covers or
None for the whole piece, the number of its entry of the document's
list of works, the find), the line that shows the rest of the piece is
this publication's own (None where none does), and what the request
showed, which a work read from it is checked against.

Fields:

- `finds: list = field(default_factory=list)`
- `own: Optional["Found"] = None`
- `evidence: list = field(default_factory=list)`

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
def add(self, name: str, work: int = 0, quote: str = "",
        work_read: Optional[dict] = None) -> int
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
             chunk_units: Optional[int] = None, *, numbers=None,
             cut: Optional[Cut] = None,
             cutting: Optional[Callable] = None)
```

#### Plan.document

```python
def document(self) -> list
```

What a quote may stand in anywhere in the document, in its order
(`pipeline.place_of`): each passage as a value read from it is
checked against it, a figure as its transcription.

#### Plan.part

```python
@staticmethod
def part(numbers: bool) -> bool
```

Does a field read a figure in the pieces of its numbers? A
field of numbers does, any other field reads its caption, as the
rule `figure_part` says (by the kind of field, or always one).

#### Plan.pieces

```python
def pieces(self, numbers: bool) -> list
```

The pieces a field reads, of numbers or not (`pieces_for`).

#### Plan.places_of

```python
def places_of(self, numbers: bool) -> dict
```

{piece key: its place} among `pieces`.

#### Plan.first_request

```python
def first_request(self) -> bool
```

Is this the first request the step that runs makes in this
document? Told once per step (rule `show_title_page`, "first").

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
def chunk_of(self, owner: tuple, number: int,
             numbers: Optional[bool] = None) -> Optional[Chunk]
```

The piece of a passage that holds its line *number*, of those a
field of numbers or another field reads where *numbers* says which;
a line every piece shows is the first piece's.

#### Plan.beside

```python
def beside(self, chunk: Chunk, numbers: bool = False) -> list
```

The pieces right before and after *chunk* among those a field of
numbers or another field reads, as many on each side as the rule
`beside_pieces` says.

### Asks

```python
@dataclass
class Asks
```

The requests of the harvest, each (payload, document_id, *, shape,
example, **noted) -> the reply as a dict, CUT or None; a request that
finds values shows two replies, *example* a pair (`find_example`).
*follow* is a request asked again with what did not hold: (kind,
payload, document_id, *, shape, example, **noted). *check*, *names*,
*work* and *phrase* are None where the profile writes no prompt for them
(`OPTIONAL`).

Fields:

- `find: Callable`
- `docfield: Callable`
- `coord: Callable`
- `list: Callable`
- `search: Callable`
- `follow: Callable`
- `names: Optional[Callable] = None`
- `check: Optional[Callable] = None`
- `work: Optional[Callable] = None`
- `phrase: Optional[Callable] = None`
- `own: Optional[Callable] = None`: A request of a general step (`general`, owner decision 2026-11-12): (prompt, payload, document_id, *, shape, example, follow, **noted), the prompt the id of a prompt file or {"text": its own}.
- `transcribe: Optional[Callable] = None`: The lines of a figure (`Transcripts`), None where the profile writes no prompt for them: the flow says so where its step is on (`flow.prompt_problems`).

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
*each(jobs, run)* runs jobs side by side. *rerank(document_id,
sentences, chunks)* orders the pieces a search shows; *budget* is how
many pieces a search shows, *shares* how many of them each kind of
passage gets first ("table", "figure", "section"), *per_request* how
many a request shows (owner decisions 2026-11-09: 50, 20/15/15, 5).
*context(document_id)* is what the document says of itself (its title,
its municipality), which a search sentence is written with. *numbers*
are the numbers of the flow the reading is bounded by (`flow.Numbers`,
the default profile's where none are given): they say *budget*, *shares*
and *per_request* where those are not given, how many times the budget
a field with a list reads, up to how many entries a list is shown with
what each means and how often an answer that did not hold is asked
again. *image_of(source)* is the picture of a figure a coordinate
request may ask for (`IMAGE`), None where the run attaches none.

#### Reader.\_\_init\_\_

```python
def __init__(self, spec, asks: Asks, order: Callable, *,
             search_order: Optional[Callable] = None,
             rerank: Optional[Callable] = None,
             probes: Optional[Callable] = None,
             known: Optional[Callable] = None,
             span_marks: Optional[dict] = None,
             plan_fields: Optional[dict] = None,
             works: Optional[dict] = None,
             frame_slots: Optional[list] = None,
             each: Optional[Callable] = None, trace=None,
             budget: Optional[int] = None,
             shares: Optional[dict] = None,
             per_request: Optional[int] = None,
             context: Optional[Callable] = None, numbers=None,
             flow: Optional[list] = None,
             image_of: Optional[Callable] = None)
```

#### Reader.span_marks

```python
@property
def span_marks(self) -> dict
```

What a value stated for a span of years marks its rows with
(rule `span_marks`), as the step that runs reads it.

#### Reader.budget

```python
@property
def budget(self) -> int
```

The chunks a search shows (`search_pieces`), as the step that
runs reads it; every chunk where the rule `search_to_end` is on.

#### Reader.shares

```python
@property
def shares(self) -> dict
```

{kind of passage: its share of a search's chunks}, as the step
that runs reads them.

#### Reader.per_request

```python
@property
def per_request(self) -> int
```

The chunks of a search one request shows (`search_per_request`),
as the step that runs reads it.

#### Reader.engine

```python
@property
def engine(self)
```

The engine that does what the drawing says with this reading.

#### Reader.follow_ups

```python
def follow_ups(self) -> int
```

How often an answer that did not hold is asked again: the box
asking's own number, else the flow's.

#### Reader.lists_of

```python
def lists_of(self, plan: Plan) -> None
```

The lists of names a document builds while it is read: its
scenarios (a field or coordinate the spec merges) and its works
(where the profile keeps them), the publication itself the first
work.

#### Reader.halves

```python
@staticmethod
def halves(piece: list, depth: int) -> Optional[list]
```

The two halves a request whose answer did not fit its room is
asked in instead (owner decision 2026-09-12: a request is split,
never its answer rescued), None where it stays a hole: the rules
`split_cut_off` (on), `split_by` (first by passages, then by lines,
or by lines only) and `split_most` (how often one request is
split, 0 until a single line is left).

#### Reader.list_of

```python
def list_of(self, options, two_step: bool = True) -> tuple
```

A list as every request of this reading shows it (`listing`):
with what each entry means up to the flow's number of entries
(`flow.Numbers.list_meanings`). Every place that shows a list or
reads a number of one goes through here, so that a number is read
against the list it was given for.

#### Reader.listed

```python
def listed(self, parameter) -> Optional[tuple]
```

The list a field's finds name their entry in (`list_of`), None
for a field without one (owner decision 2026-11-09: a field with a
list is asked with it, the answer the number of its entry).

#### Reader.claim

```python
def claim(self, plan: Plan, parameter, got: Found,
          counts: Counts) -> Optional[dict]
```

The claim of a value found: its number or words, the line as its
quote, its address, the head of its column, and for a figure that a
model read it off a picture (`drawn`, trust level C). A value of a
list is the entry its find named, the entry of a group named asked
among the group's (`list`); one found without its entry is asked
it.

#### Reader.shown_order

```python
def shown_order(self, plan: Plan, sentences: list, pieces: list,
                budget: Optional[int] = None,
                shares: Optional[dict] = None) -> list
```

The pieces a search for *sentences* shows, in the order it shows
them (owner decisions 2026-11-09): of the pieces of the passages
the vector search finds best, the *budget* best by kind
(`budgeted`), ordered once by the reranker with the same
sentences.

#### Reader.rerank_left

```python
def rerank_left(self, plan: Plan, sentences: list, pieces: list) -> list
```

*pieces* ordered by the reranker with *sentences* again, for
the rule `rerank_when` (each round), where the rule `rerank` is on
and there are enough of them.

#### Reader.settled

```python
def settled(self, plan: Plan, counts: Counts) -> None
```

What the plan settles for all its values and its own years, as
the drawing of the flow asks them (`engine.Engine.prepare`).

#### Reader.entry

```python
def entry(self, plan: Plan, uri: str, name: str, slot, words: str,
          got: Optional[Found], counts: Counts, several: bool = False,
          group: Optional[str] = None, node: Optional[dict] = None)
```

The entry of *slot*'s list a wording means, asked once per
document, field, coordinate, wording and group (`list`, owner
decision 2026-11-08): its label, a list of labels where several may
be meant, "" where none fits (0). With *group* (a find named it,
owner decision 2026-11-09) the entries of that group are asked. It
is asked as the step after the question says that chooses list
entries, else the first of the flow (`general.nested`), or as
*node*.

#### Reader.earlier_entries

```python
@staticmethod
def earlier_entries(plan: Plan, uri: str, name: str,
                    group: Optional[str]) -> list
```

[{"words", "entry"}] the document's list of this coordinate has
already settled for other wordings, for the rule
`list_shows_earlier`.

#### Reader.name_of

```python
def name_of(self, plan: Plan, kind: str, words: str,
            got: Optional[Found], counts: Counts, work: int = 0,
            besides: tuple = (), group: bool = False,
            uri: str = "", work_read: Optional[dict] = None,
            node: Optional[dict] = None)
```

The entries of the document's list of *kind* a name means
(`names`): [(label, number)], a new entry where the name is not on
the list yet, ("out", label) for an entry *besides* the names
((label, means)); with *group* the words may name several entries;
[] where they name no such thing (0, owner decision 2026-11-09);
None where no answer came. Each name is asked once per document and
work. A new entry keeps *work_read*, how the value it is read for
read its work.

#### Reader.asked_with_fetched

```python
def asked_with_fetched(self, kind: str, plan: Plan, payload: dict, reply,
                       shape: dict, example: dict, counts: Counts,
                       noted: dict, anchor: list,
                       shown: Optional[Shown] = None) -> tuple
```

(reply, payload, shown) of a request that is no round of a
search (a name, a detail of a work) asked again with the pieces its
reply asked to see under "passages", each under a letter of its own,
as often as the rule `fetch_rounds` says (owner decision 2026-11-12:
where the document says a missing detail at another place or points
to it, the model may fetch that place itself). *anchor* is the piece
the request stands at, which "next" and "previous" go from; the
reply, payload and a copy of *shown* as they were where it asked for
nothing that could be fetched.

#### Reader.show_fetched

```python
@staticmethod
def show_fetched(plan: Plan, shown: Shown, pieces: list) -> dict
```

{letter: block} of *pieces* added to *shown*, each under a
letter of its own, as a request shows them under "passages".

#### Reader.anchor_of

```python
@staticmethod
def anchor_of(plan: Plan, got: Optional[Found]) -> list
```

[the piece] the first line of *got* stands in, [] where it stands
in none (a heading, the title page).

#### Reader.coordinate

```python
def coordinate(self, plan: Plan, read: Read, row: Row, group, slot,
               counts: Counts, clone: Callable) -> list
```

One coordinate of one value as the drawing's frame of
coordinates asks it (`engine.Engine.coordinate`): [the rows made
beside it].

#### Reader.pictures

```python
def pictures(self, shown: Shown, seen: set) -> dict
```

{letter: picture} of the figures *shown* shows whose picture the
run attaches and this coordinate has not seen yet ("" the value's
own place), where the step allows a request to ask for it (rule
`fetches`, `IMAGE`).

#### Reader.with_picture

```python
def with_picture(self, kind: str, payload: dict, document_id: int,
                 several: bool, example: dict, counts: Counts, reply,
                 pictures: dict, seen: set, noted: dict)
```

A coordinate request's reply, where it asked for the picture of a
figure it shows (`IMAGE`, owner decision 2026-11-12: the picture as
a tool) the reply of the same request asked again with that picture
beside it, which may ask for no picture: one picture a request, each
once a coordinate (*seen*). The answer is a shown line as always;
the picture helps to read what the figure's lines do not say. The
reply itself where it asked for none it may see.

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

(rows made, held, what its replies ask to fetch) of a
coordinate's answer: its finds each read onto the row, one row per
entry where several are named, and checked (`merge_field`); what
does not hold is asked again with its reason (`follow`, as often as
the flow says), then stays `unbacked`. A follow-up may fetch as its
request may (owner decision 2026-11-12).

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
             counts: Counts, node: Optional[dict] = None) -> None
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

#### Reader.field_sentence

```python
def field_sentence(self, plan: Plan, read: Read, slot) -> str
```

What a search goes with where no sentence was written for it
(rule `search_fallback`): the field's own search sentence, else its
question or name; or its question, or its name, or none.

#### Reader.fallback

```python
def fallback(self, plan: Plan, parameter, slot) -> str
```

#### Reader.fetch

```python
def fetch(self, plan: Plan, more, batch: list, seen: set,
          numbers: bool = False) -> list
```

The pieces a reply asks for itself (`more`), those not shown
yet, of the pieces its field reads: the piece before or after a
shown one, a table or figure by its placeholder, the pieces a
pattern stands in, the pieces best for a sentence of its own.

#### Reader.matching

```python
def matching(self, wanted, pieces: list, seen: set) -> list
```

The pieces a pattern the model wrote stands in, not shown yet,
as many as a request shows. The pattern runs for the rule
`pattern_timeout_s` seconds at most over all the pieces; one that
does not finish stands in none (it is a pattern of the model's,
which can backtrack without end).

#### Reader.named_value

```python
def named_value(self, plan: Plan, parameter, row: Row,
                counts: Counts, node: Optional[dict] = None) -> None
```

A value that is the name the document gives a thing (a
scenario): the entry of the document's list it is, a new one where
it is not on it yet, under `value_means` (owner decisions
2026-11-08: the list is built piece by piece).

#### Reader.own_line

```python
@staticmethod
def own_line(plan: Plan, shown: Shown, chunk: Chunk, raw) -> tuple
```

(Found or None, why or None) of the line a piece's work request
names as showing the rest of the piece is this publication's own:
it counts where it stands among the piece's lines or headings, or
on the title page in the piece itself; 0 names none.

#### Reader.covered

```python
@staticmethod
def covered(chunk: Chunk, found: Found) -> Optional[set]
```

The (passage, line) places a find of a piece's work request
speaks for: the whole piece (None) where it stands in a heading or
in what every piece of its passage shows (a table's title and head,
a figure's caption), else its own lines.

#### Reader.read_work

```python
def read_work(self, plan: Plan, row: Row, slot, shown: Shown,
              reply: dict) -> list
```

[what did not hold] of an answer to a value's work, [] where it
read the work or said none (0, `unstated`).

#### Reader.take_work

```python
@staticmethod
def take_work(row: Row, slot, number: int, got: Found, evidence: list,
              window: tuple, works: "Names",
              document: Sequence = ()) -> list
```

The work *number* of the document's list read onto a value with
the line *got* names as its quote (`merge_field`): [] where it holds,
[what did not hold] else.

#### Reader.inherit_work

```python
def inherit_work(self, plan: Plan, row: Row, slot) -> bool
```

Does the value take the work of the line it stands in (owner
decisions 2026-11-09: nothing without a line)? The work its piece's
work request named for that line, read with that find as its
quote: a find of the line itself before one of the whole piece,
the line of this publication's own after both; a line two works
are named for, or none, is the value's own to ask.

#### Reader.work_by_piece

```python
def work_by_piece(self, plan: Plan, row: Row, slot) -> bool
```

Does the value take the work its piece names, or this
publication where it names none, with no line that names it (rule
`work_without_line`)? The value's own line is its quote. A piece
that names two works leaves the value to ask.

#### Reader.piece_work

```python
@staticmethod
def piece_work(plan: Plan, claim: dict) -> Optional[tuple]
```

(number of the work, the find, what its request showed) a
value's piece names for the line it stands in, None where it names
none or two.

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
[piece key]}: the pieces each field reads (`Plan.pieces`) best first
for its sentences, kept under the harvest
(`survey/<document>[.<scope>].json`) with the passages each field was
read in, which the passes over a stored harvest read
(`surveyed.surveyed_owners`).

#### Orders.\_\_init\_\_

```python
def __init__(self, order: Callable, probes: Callable,
             store: Optional[Path], trace=None, written: str = "")
```

## Functions

### asking

```python
@contextlib.contextmanager
def asking(what: Asking)
```

### asking_box

```python
def asking_box() -> Optional[str]
```

The id of the box asking now, None outside a box.

### prompting

```python
@contextlib.contextmanager
def prompting(kind: str, prompt)
```

The requests of *kind* asked with *prompt* while the block runs; with
None, with the prompt of their kind.

### own_prompt

```python
def own_prompt(kind: str)
```

The prompt the step asking now asks requests of *kind* with, None
for the prompt of the kind.

### years_in

```python
def years_in(text: str) -> list
```

The years *text* names, as their four digits, in order.

### span

```python
def span()
```

What makes a span of years between two of them (rules `span_words`,
`span_dashes`).

### told

```python
def told(why: str, entry) -> str
```

Why a find or an answer did not hold, in the profile's words, with
the address and the words it gave; where the rule `answer_with` has the
answer name its line by its words, in the sentence that asks for them
and not for an address (`<why>_quote`, owner decision 2026-11-12).

### refusals

```python
def refusals(refused: list) -> list
```

What a follow-up tells of the finds that did not hold: each as it
was given, and why in the profile's words.

### joined

```python
def joined(held: list, more: list) -> list
```

*held* and those finds of *more* that are not among them: what the
rule `same_find_by` names (a line, its cell, its words) once.

### work_read

```python
def work_read(claim: dict) -> Optional[dict]
```

How a value read its work, its `work` fields, None where it read
none.

### number_of

```python
def number_of(words: str) -> Optional[str]
```

The number the words of a find print, with its sign (owner decision
2026-11-01), in `canonical_number`'s spelling: the words themselves
where they are a number, else the one number they print ("750.940
kWh", "ca. 8,8 GWh"); None where they print none or more than one
("800 / 750", "2019 bis 2021"). A signed number and its magnitude are
one number ("-1.155"). Where the rule `sign_belongs` is off the sign
stays outside the number: its magnitude.

### is_question

```python
def is_question(sentence: str) -> bool
```

Is a search sentence a question rather than a sentence of the
plan?

### reply_format

```python
def reply_format(schema: dict) -> dict
```

The form of the answer of a general step's request (`general`):
its own JSON schema as the grammar.

### address_key

```python
def address_key() -> str
```

How an answer names its line: "at", the number of the line, or
"quote", the words of the line (rule `answer_with`).

### fetches

```python
def fetches(image: bool = False) -> list
```

What a reply may fetch itself (rule `fetches` of the step that
asks), in the order of `GETS`; with *image* the picture of a shown
figure too, where the rule allows it.

### more_schema

```python
def more_schema(image: bool = False) -> dict
```

### with_more

```python
def with_more(properties: dict, more: bool, image: bool = False) -> dict
```

*properties* of a reply with "more" beside them where *more* and the
step allows a way of fetching (rule `fetches`).

### asked_more

```python
def asked_more(reply) -> list
```

What a reply asks to fetch ("more"), [] where it asks nothing.

### found_format

```python
def found_format(closed: bool = False, more: bool = False) -> dict
```

The finds of a request: each an address and the words of the value,
and where the field has a list the number of its entry (*closed*); an
empty list where nothing shown holds one. With *more* the pieces it
asks to see besides (`fetches`).

### work_format

```python
def work_format() -> dict
```

The answer of a piece's work request: the lines of other works, each
an address and the name as a line prints it, and the line that shows
the rest are this publication's own (`own`), 0 where none does.

### work_choice_format

```python
def work_choice_format() -> dict
```

The work of one value, asked as an entry of the document's list of
works: its number, 0 for none, and the line that shows it.

### phrase_format

```python
def phrase_format() -> dict
```

A sentence as the plan would print what a search looks for.

### coord_format

```python
def coord_format(several: bool, more: bool = False,
                 image: bool = False) -> dict
```

A coordinate's answer: an address and its words, or 0 (owner
decision 2026-11-09: the sentence a search goes with is a request of
its own, `phrase`); one that may name several entries lists its
finds. With *more* the pieces it asks to see besides (`fetches`), with
*image* the picture of a figure it shows among them.

### entry_format

```python
def entry_format(several: bool = False, new: bool = False,
                 more: bool = False) -> dict
```

The number of a list's entry, 0 for none; a list of them where
several may be meant; "new" for a name not on the document's list.
With *more* the pieces it asks to see besides (`fetches`).

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

A figure transcribed: its caption (title, axes, legend) and its
numbers, each a line (owner decision 2026-11-09).

### about_format

```python
def about_format() -> dict
```

### field_shown

```python
def field_shown(parameter, full: Optional[bool] = None) -> dict
```

A field as a request shows it: its name and what a value of it is,
in short where the spec writes that (`brief`) or whole as the rule
`field_text` says (*full* says it for the caller).

### block_payload

```python
def block_payload(passage: Optional[Passage], shown: Shown,
                  letter: str = "") -> dict
```

A block of lines as a request shows it: its passage's kind, page and
title, and the lines with their addresses.

### first_address

```python
def first_address(shown: Shown, cells: bool, letter: str = "") -> str
```

An address for a request's example: the first of its own lines that
is no title or head, with *cells* a cell of it where it has cells.

### shown_example

```python
def shown_example(example)
```

The reply a request shows as its example, as the rules say
(`show_example`: none at all, `show_empty_example`: of the two a request
that finds values shows, only the one with a find); None stays None,
and no example at all is the empty tuple.

### point

```python
def point(shown: Shown, cells: bool = False, letter: str = "",
          at: Optional[str] = None) -> dict
```

What an example answer names its line with: the address of the
request's first line of its own (or *at*), or, where the rule
`answer_with` has the answer quote, the words of that line.

### find_example

```python
def find_example(shown: Shown, closed: bool = False,
                 letter: str = "") -> tuple
```

The two replies a request that finds values shows (owner decision
2026-11-09: "immer ein Positiv und ein Negativbeispiel"): one find at
the request's own first line, and where the field has a list with the
number of its entry; and the empty one, where no shown line prints a
value.

### second_ways

```python
def second_ways(ways: list) -> dict
```

The note a request carries that went through the second way of the
rules *ways* (owner decision 2026-11-11): their names, so that
a run shows what it used. Nothing where it went through none.

### said_none

```python
def said_none(reply) -> bool
```

Does the answer of a names request name 0, none of its list?

### listing

```python
def listing(options, meanings: int, two_step: bool = True) -> tuple
```

(lines, choices, grouped) of a list as a request shows it (owner
decisions 2026-11-08): a list longer than *meanings* entries
(`flow.Numbers.list_meanings`) whose entries name groups is shown by
its groups, each a choice; a shorter one with what each entry means, a
longer one by its names. *choices* are what a number picks, labels or
group names. The rule `two_step_list` says whether a long list of groups
is asked in two steps, *two_step* that this list is the first of them:
the entries of the groups chosen are never shown as groups.

### picked_entry

```python
def picked_entry(entry, size: int) -> Optional[int]
```

The number a find names of a list of *size*, 0 for none; None where
it names no number of the list.

### share_of

```python
def share_of(chunk: Chunk) -> str
```

The kind of passage a piece counts under in a search's shares: a
table, a figure, else text ("section").

### shares_problem

```python
def shares_problem(shares: dict) -> Optional[str]
```

Why *shares* (the shares of tables, figures and text of a search)
cannot be scaled, None where they can: for the check of the values of
the flow. Three shares of 0 are honoured by `budgeted` (no kind first),
never counted as 1.

### budgeted

```python
def budgeted(ranked: list, budget: int, shares: dict) -> list
```

The pieces a search shows of *ranked*, best first (owner decisions
2026-11-09: 50 pieces, 20 of tables, 15 of figures, 15 of text, filled
up): the best of each kind of passage up to its share, the shares
scaled to *budget*, then the best of the rest up to *budget*; in the
order of *ranked*.

### quoted_address

```python
def quoted_address(shown: Shown, quote: str) -> Optional[str]
```

The address of the shown lines that hold *quote*, characters that
count as the same compared as the same (rule `same_characters`): the
lines of the request's own passage first, one line or a stretch of
consecutive ones; None where no shown line holds it.

### has_address

```python
def has_address(reply) -> bool
```

Does the answer name a line: an address, or, where the rule
`answer_with` has it quote, a quote?

### quoted_elsewhere

```python
def quoted_elsewhere(passages: dict, quote: str) -> tuple
```

(the passage shown alone, the address of its lines that hold
*quote*) of the first of *passages*, in the document's order, whose
lines hold it (`quoted_address`); (None, None) where none does.

### resolve

```python
def resolve(shown: Shown, entry, passages: dict) -> Found
```

The lines an answer's address names in what *shown* showed, its
words checked against them: `NOT_AN_ADDRESS` where it names no shown
line or cell, `WORDS_NOT_IN_LINE` where its words do not stand in what
it names. Words left empty are the cell's, or the lines' of a stretch;
a single line without a cell needs words. An answer that names its line
by its words (rule `answer_with`) whose words stand in no shown line is
looked for in every passage of *passages*, the document's, where the
rule `check_quote_shown` is off (owner decision 2026-11-12); an address
is never: the rule is about the quote.

### image_key

```python
def image_key(path: Optional[str]) -> Optional[str]
```

What names an image for its kept transcription: its bytes' hash.

### title_page_shown

```python
def title_page_shown(plan: Plan) -> bool
```

Does the request that is built now show the title page (rule
`show_title_page`)? "first" shows it in the first request the step
makes in the document only.

### show_value

```python
def show_value(plan: Plan, claim: dict, headings: Optional[bool] = None,
               plain: bool = False) -> tuple
```

(Shown, payload) of a value's place as the requests about its
coordinates show it (they are built from their step's inputs,
`shows`): its line with its table's title and head, or the sentences
before and after it; the headings up to it, the title page and the
plan's settings, as the step that asks says (rules `show_headings`,
`show_title_page`, `show_settled`); the value as its words and its
address. *headings* False shows none whatever the rules say, *plain*
asks only for the lines of the place: the title page and the settings
stand in what a quote may cite, as the rules `show_*` do not touch
them.

### own_check

```python
def own_check(got: Found) -> Optional[tuple]
```

(reason, sentence) of the own check of the box asking now that
refuses *got*, None where none does (owner decision 2026-11-10: an own
check only refuses; its reason is check:\<name>).

### years_listed

```python
def years_listed(listed: list) -> list
```

The plan's years as a request lists them, each with the state it is
the year of and, where the rule `year_list_quote` says so, the line that
says it.

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

(order, search_order, rerank), each (document_id, sentences, chunks)
-> the pieces best first. *order* has the reranker score every piece
with every sentence, keeping each piece's best (owner decisions
2026-11-08: all pieces, best first); *search_order* takes the passages
the vector search finds best (*rank*, with its reranker over passages,
100 of each kind) and gives their pieces in that order, the rest of the
plan after them; *rerank* orders the pieces a search shows with the
same sentences (owner decisions 2026-11-09: "der Reranker ordnet diese
höchstens 50 Stücke einmal mit demselben Satz"). Without a reranker the
pieces keep their passages' order; without either, the plan's. A
reranker or a search that fails raises: what is handed in asks again
until it answers (`runner.persistently`, owner decision 2026-11-09:
nothing is read in another order instead), and one the server refuses
as often as the flow's `replies` says fails its document, which stays
unfinished.

### order_key

```python
def order_key(parameters: list, chunk_units: int, written: str = "") -> str
```

The key an order of the pieces is kept under: the fields it ranked,
each with the words its search sentences are written from, what writes
them (*written*) and the size of the pieces.

[Back to the index](../README.md)
