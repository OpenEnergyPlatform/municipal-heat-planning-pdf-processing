# docpipe.extraction.engine

`docpipe/extraction/engine.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

engine.py: The run does what the drawing of its flow says (owner decisions
2026-11-10 evening: "Freie Ablaufgrafik"; plan of 2026-11-10, sections 2,
9 and 10).

The flow (`flow.py`) is a tree of boxes and frames. This module walks it for
one document and does what each box says, in the order it stands; there is
no second order in the code. What a box does with an answer stays the
reading's (`addressed.Reader`): building a request, looking up an address,
the two checks, folding a value. The engine decides only which box runs
when, for what, how often and in which order:

- "each" iterates what the document settles, its fields, a field's pieces,
  the values read, a value's coordinates; side by side where it says so (one
  pool for a frame side by side whose only step is another side by side:
  each field and each of its pieces, as the reading always asked them), and
  only for the items its condition holds for.
- "round" runs its steps again, at most N times or until the supply its
  question shows is used up, and stops where its condition holds after a
  turn.
- "if" takes the first way whose condition holds, else the last.

Every request carries the id of the box that asked it (`box` in the trace,
owner decision 2026-11-10: the page counts requests per box); a request a
box asks while it reads an answer (the entry of a list, the name of a
scenario, a follow-up) is that box's.

A box that checks answers (`about`, an own check, `check`) stands right
after the question whose answers it checks and is applied while that
question reads them. An own check refuses an answer where its condition
holds; what it refuses is asked again with its sentence, as often as the
question's follow-ups, then stays unbacked, and is counted under
`check:<name>` (owner decision 2026-11-10: own checks are allowed in the
page; the flow the code brings has none).

Author: Felix Vossel

## Classes

### Stop

```python
class Stop(Exception)
```

The drawing holds something the run cannot do; the check of the flow
(`flow.problems`) refuses it before a run.

### Scope

```python
class Scope
```

What the run knows at one place of the drawing: the document, the
item of each frame around it, the round. An item's own values (its
answer, its supply) live in the scope of its frame's turn.

#### Scope.\_\_init\_\_

```python
def __init__(self, parent: Optional["Scope"] = None, item: bool = False,
             **values)
```

#### Scope.get

```python
def get(self, key, default=None)
```

#### Scope.has

```python
def has(self, key) -> bool
```

#### Scope.owner

```python
def owner(self) -> "Scope"
```

The scope of the innermost item: where a box keeps its answer.

#### Scope.put

```python
def put(self, key, value) -> None
```

#### Scope.used_up

```python
def used_up(self) -> None
```

The question of the innermost round has nothing left to show:
that round ends.

#### Scope.drew

```python
def drew(self) -> None
```

A question of the innermost round showed pieces of its supply.

#### Scope.child

```python
def child(self, item: bool = False, **values) -> "Scope"
```

### Doc

```python
@dataclass
class Doc
```

One reading of a document.

Fields:

- `plan: Plan`
- `counts: Counts`
- `parameters: list`
- `chunks: object = None`: None, [pieces] or {uri: [...] or None}
- `order_of: dict = field(default_factory=dict)`
- `order_fields: Optional[Callable] = None`
- `reads: list = field(default_factory=list)`: works, document fields
- `field_reads: list = field(default_factory=list)`: document fields
- `find_reads: list = field(default_factory=list)`
- `by_find: dict = field(default_factory=dict)`: (uri, owner) -> Read
- `valued: dict = field(default_factory=dict)`: id(read) -> frame
- `seen_of: dict = field(default_factory=dict)`: coordinate -> seen
- `started: float = field(default_factory=time.monotonic)`
- `about: dict = field(default_factory=dict)`: facts made once
- `made: dict = field(default_factory=dict)`: The variables the page's steps made for the whole document (`general.put`, owner decision 2026-11-12).

#### Doc.whole

```python
@property
def whole(self) -> bool
```

Is the whole document read (no pass over a part of it)?

#### Doc.pieces_of

```python
def pieces_of(self, uri: str) -> list
```

### FieldItem

```python
@dataclass
class FieldItem
```

A field of the document asked once, or a thing it settles.

Fields:

- `key: str`: the field's uri or the settled key
- `shown: Optional[dict]`: as a request shows it; None for a
- `sentences: list`: parameter: built by the box that asks
- `numbers: bool = False`
- `listed: Optional[tuple] = None`
- `parameter: object = None`
- `settled: Optional[dict] = None`
- `found: list = field(default_factory=list)`
- `lost: Optional[str] = None`
- `asked_by: Optional[str] = None`: the id of the box that asked it
- `reads: Optional[list] = None`
- `first_source: Optional[Source] = None`: of the first request's chunks

### ValueItem

```python
@dataclass
class ValueItem
```

Fields:

- `read: Read`
- `row: Row`
- `rows: list`
- `clone: Callable`

### CoordItem

```python
@dataclass
class CoordItem
```

Fields:

- `read: Read`
- `row: Row`
- `slot: object`
- `group: object`
- `before: list`
- `clone: Callable`
- `made: list = field(default_factory=list)`
- `payload: Optional[dict] = None`
- `noted: Optional[dict] = None`
- `sentence: Optional[str] = None`
- `sentences: list = field(default_factory=list)`
- `seen: Optional[set] = None`
- `ordered: set = field(default_factory=set)`
- `chunk: object = None`
- `located: bool = False`
- `seen_of: Optional[dict] = None`
- `ways: list = field(default_factory=list)`: The rules whose second way the requests of this coordinate went through (`second_ways`), noted on them.
- `fetched: list = field(default_factory=list)`: The pieces the request at the value's own place asked to see, shown first by the search that follows it, and the pictures of figures its requests saw, each once (owner decision 2026-11-12).
- `pictures: set = field(default_factory=set)`

### ListSupply

```python
class ListSupply
```

The pieces a field of the document is asked over: the title page with
the first request, then the pieces in their order, a few a request. The
pieces a reply asked to see (*fetched*) come first in the next request,
beyond the pieces of the order and not counted in them; no piece is
shown twice (*seen*, owner decision 2026-11-12).

#### ListSupply.\_\_init\_\_

```python
def __init__(self, pieces: list)
```

#### ListSupply.take

```python
def take(self, size: int)
```

(first request?, pieces) of the next request, None where the
supply is used up.

#### ListSupply.left

```python
def left(self) -> int
```

### SearchSupply

```python
class SearchSupply
```

The pieces a coordinate's search shows: the pieces it was given
(*first*, shown together in the first request), then the pieces of its
order a few at a time (*ranked*, made the first time it is needed), the
pieces a reply fetched itself first in the next request; no piece twice
(`seen`, the coordinate's) unless the rule `show_twice` says it may be
shown a second time. *limit* is the most pieces the search shows (the
flow's number of chunks), *reorder* puts the pieces left in order again
with the sentence of the round (the rule `rerank_when`).

#### SearchSupply.\_\_init\_\_

```python
def __init__(self, first: list, ranked: Optional[Callable], label: str,
             limit: Optional[int] = None,
             reorder: Optional[Callable] = None)
```

#### SearchSupply.take

```python
def take(self, size: int, seen: set) -> tuple
```

(pieces, what they are: the supply's label or "fetched") of the
next request; ([], None) where nothing is left. The kinds of pieces
come in the order of the rule `supply_order`: those before the
ranked ones are shown together, the ranked ones only where none of
them is left.

#### SearchSupply.left

```python
def left(self, seen: set) -> int
```

### Answer

```python
@dataclass
class Answer
```

What the last question of an item came to.

Fields:

- `answered: bool = False`
- `finds: int = 0`
- `zero: bool = True`
- `other_passage: bool = False`
- `words: str = ""`
- `quote: str = ""`
- `follow_ups: int = 0`: follow-up questions it took
- `refusal: str = "none"`: why a find of it was refused

### Engine

```python
class Engine
```

The drawing *tree* of a flow done for documents with the reading
*reader* (`addressed.Reader`).

#### Engine.\_\_init\_\_

```python
def __init__(self, reader, tree: Optional[list] = None)
```

#### Engine.own_values

```python
@staticmethod
def own_values(node: dict) -> dict
```

What *node* sets for itself while it runs: its "rules", and a
box's own numbers ("own") under the names of the flow's numbers.

#### Engine.step

```python
def step(self, node: Optional[dict])
```

Read with *node*'s own values laid over those of the frames it
stands in, while it runs (`rules.STEP`); work it hands to other
threads takes them along (`runner.run_each` copies the context).
No node (a step of the preparation that is not drawn): the run's
values.

#### Engine.number

```python
def number(self, node: dict, key: str) -> int
```

A number setting of a box: its own value, else that of a frame
around it, else the named number of the flow as the run reads it (a
setting of the run won over the file already, `flow.in_effect`).

#### Engine.setting

```python
@staticmethod
def setting(node: Optional[dict], key: str, kind: str = "")
```

A setting of a box: its own value, else its rule's, else its
default. A box of *kind* that is not drawn (*node* None) has the
rule's or the default.

#### Engine.counted

```python
@contextlib.contextmanager
def counted(self, doc)
```

The counts of one question, apart from the counts of the other
questions asked side by side, so that what it came to (the
follow-ups it took, why its finds were refused) is its own; they
are added to the document's when it is through.

#### Engine.came_to

```python
@staticmethod
def came_to(part: Counts) -> dict
```

What a question's own counts say of its answer (`Answer`).

#### Engine.shares_of

```python
def shares_of(self, node: dict) -> dict
```

#### Engine.facts

```python
def facts(self, scope: Scope, got: Optional[Found] = None
          ) -> conditions.Facts
```

What a condition can know at *scope*; *got* is the find an own
check is looking at.

#### Engine.rows_read

```python
def rows_read(self, doc, parameter) -> int
```

How many values of the field the document's reads hold so far.

#### Engine.about_document

```python
def about_document(self, doc, plan: Plan) -> dict
```

What the document says of itself, made once per reading: its
language, its pages and its title.

#### Engine.holds

```python
def holds(self, condition, scope: Scope) -> bool
```

#### Engine.figure_facts

```python
@staticmethod
def figure_facts(source: Source) -> conditions.Facts
```

What a condition of the transcribe box knows of a figure.

#### Engine.included

```python
def included(self, sources: list) -> list
```

The sources the document step reads: the kinds of passages of
the rule `include_kinds`, on the pages of the rule `pages`.

#### Engine.cut

```python
def cut(self) -> addressed.Cut
```

How the drawing cuts a document into pieces (its split box).

#### Engine.number_of_split

```python
def number_of_split(self, key: str) -> int
```

#### Engine.plan

```python
def plan(self, document_id: int, sources: list, transcripts=None,
         each=None, numbers=None) -> tuple
```

(Plan, Counts) of a document: its figures transcribed
(*transcripts*), its pieces cut as the split box says, then the
lists and what it settles (`prepare`).

#### Engine.prepare

```python
def prepare(self, plan: Plan, counts: Counts) -> None
```

The lists of the document and what it settles, as the drawing
says.

#### Engine.read

```python
def read(self, plan: Plan, parameters: list, chunks=None,
         counts: Optional[Counts] = None,
         order_of: Optional[dict] = None,
         order_fields: Optional[Callable] = None) -> list
```

[Read] of *parameters* in *plan*: one per field and passage it
was read in. *chunks* are the pieces read: all where None, else a
list, or {uri: list or None} per field; *order_of* {uri: [piece
key]} the order each field reads them in, or *order_fields(located
fields)* makes it where the drawing orders them (`sentences`).

#### Engine.coordinate

```python
def coordinate(self, plan: Plan, read: Read, row: Row, group, slot,
               counts: Counts, clone: Callable) -> list
```

One coordinate of one value asked as the drawing's frame of
coordinates asks it (a pass over a stored harvest,
`surveyed.SurveyedHarvest.sweep`): [the rows made beside it].

#### Engine.run_steps

```python
def run_steps(self, steps: list, scope: Scope) -> None
```

#### Engine.run_node

```python
def run_node(self, node: dict, scope: Scope) -> None
```

#### Engine.round

```python
def round(self, node: dict, scope: Scope) -> None
```

#### Engine.items

```python
def items(self, node: dict, scope: Scope) -> list
```

[(child scope values)] of the items *node* iterates at *scope*.

#### Engine.each

```python
def each(self, node: dict, scope: Scope) -> None
```

#### Engine.after_items

```python
def after_items(self, node: dict, done: list, scope: Scope) -> None
```

What a frame does once its items are through: the finds of each
piece become the reads of their field and passage, a field of the
document its reads, what the document settles its trace.

#### Engine.hole_source

```python
@staticmethod
def hole_source(plan: Plan, item: FieldItem) -> Source
```

The passage the hole of a field read nothing of names (rule
`hole_passage`).

#### Engine.field_reads

```python
def field_reads(self, item: FieldItem, scope: Scope) -> list
```

The reads of a field of the document: one per passage a value of
it was found in, made once from what its questions found.

#### Engine.each_value

```python
def each_value(self, node: dict, scope: Scope) -> None
```

Every value of the reads at *scope* (a field's, else the finds of
the document) through the frame's steps; each read's claims become
the rows its values came to.

#### Engine.value_scope

```python
def value_scope(self, scope: Scope, read: Read, row: Row) -> Scope
```

#### Engine.each_coordinate

```python
def each_coordinate(self, node: dict, scope: Scope) -> None
```

Each coordinate of the value, in the order of the spec's groups,
for the value's row and every row made beside it.

#### Engine.box_settle

```python
def box_settle(self, node: dict, scope: Scope) -> None
```

What a thing the document settles came to, kept for every
request after it.

#### Engine.box_order

```python
def box_order(self, node: dict, scope: Scope) -> None
```

The supply of the item: its pieces best first for its sentence,
the budget of them by kind, those already shown left out.

#### Engine.box_beside

```python
def box_beside(self, node: dict, scope: Scope) -> None
```

#### Engine.locate

```python
@staticmethod
def locate(coord: CoordItem, plan: Plan) -> None
```

The piece the value stands in, shown first so that no search
shows it again.

#### Engine.asking_of

```python
def asking_of(self, node: dict, scope: Scope, steps_after: list
              ) -> Asking
```

What a question asks with: its box, the boxes after it that check
its answers (the place of a find, own checks).

#### Engine.own_checks

```python
def own_checks(self, node: dict) -> list
```

[(name, condition, sentence, id)] of the own checks that stand
right after *node* and are on.

#### Engine.keep

```python
def keep(self, doc: Doc, parameter, claims: list) -> None
```

Each value a general step read of *parameter* in the read of its
field and passage, as a find's are (`after_items`).

#### Engine.follow_ups_of

```python
def follow_ups_of(self, node: dict) -> Optional[int]
```

The box's own number of follow-ups, None for the flow's.

#### Engine.box_docfield

```python
def box_docfield(self, node: dict, scope: Scope) -> None
```

#### Engine.after

```python
def after(self, node: dict) -> list
```

The steps after *node* in its list of steps.

#### Engine.box_find

```python
def box_find(self, node: dict, scope: Scope) -> None
```

#### Engine.box_sentences

```python
def box_sentences(self, node: dict, scope: Scope) -> None
```

#### Engine.coord_base

```python
def coord_base(self, coord: CoordItem, plan: Plan) -> None
```

What every request about the coordinate shows, made once.

#### Engine.box_coord

```python
def box_coord(self, node: dict, scope: Scope) -> None
```

#### Engine.box_phrase

```python
def box_phrase(self, node: dict, scope: Scope) -> None
```

#### Engine.box_search

```python
def box_search(self, node: dict, scope: Scope) -> None
```

#### Engine.box_state

```python
def box_state(self, node: dict, scope: Scope) -> None
```

#### Engine.box_ask

```python
def box_ask(self, node: dict, scope: Scope) -> None
```

#### Engine.box_retrieve

```python
def box_retrieve(self, node: dict, scope: Scope) -> None
```

#### Engine.box_rerank

```python
def box_rerank(self, node: dict, scope: Scope) -> None
```

#### Engine.box_set

```python
def box_set(self, node: dict, scope: Scope) -> None
```

#### Engine.box_filter

```python
def box_filter(self, node: dict, scope: Scope) -> None
```

#### Engine.box_merge

```python
def box_merge(self, node: dict, scope: Scope) -> None
```

#### Engine.box_python

```python
def box_python(self, node: dict, scope: Scope) -> None
```

#### Engine.step_of

```python
def step_of(self, kind: str)
```

The values of the top box of *kind* (one of `AFTER`), for
the run that does it outside the engine (`runner`); no values where
the drawing has none.

#### Engine.box_document

```python
def box_document(self, node, scope)
```

## Functions

### language_of

```python
def language_of(texts) -> str
```

"de", "en" or "other": which of two languages the *texts* are
written in, by the words each has more of.

### refusal_of

```python
def refusal_of(failed) -> str
```

The reason most of the refusals of a question came to, as a
condition names it (`conditions.REFUSALS`).

### compute_on

```python
def compute_on(profile=None) -> bool
```

Is the calculation after the reading on in the drawing of
*profile*?

[Back to the index](../README.md)
