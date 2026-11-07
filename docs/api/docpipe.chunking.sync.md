# docpipe.chunking.sync

`docpipe/chunking/sync.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

sync.py: Writes documents processed again into the database under the
numbers their entries already have, and takes out of every index the
vectors whose input changed.

A plan whose tables were transcribed again, or whose sections were refined
again, used to go back into the database with --force: its sections, tables
and figures were deleted and inserted under new numbers, and all its vectors
were embedded again. A harvest, its found places and an index built under
the database's ids then no longer fit it. Here (owner decision 2026-11-07,
"Nur Geändertes neu") an entry keeps its number:

- a section keeps its row where the new document has a section with the
  same title and text, in the order of the sections; where a stretch of
  sections changed, its new sections take the rows of the old ones of that
  stretch in their order, and the rest are new or gone;
- a table or a figure keeps its row by its block id, in order where one id
  stands more than once, and moves with it to the section it now stands in;
- a table part the merge joined to the table it continues is gone.

A vector stays where its input is unchanged: the text, and the picture, that
`chunking.build_embedding_inputs` makes of the entry, from the database
before and from the document now, each with the caption the database holds
(`captions.resolve_title`, which `enrich_caption` applies). Every other
vector goes: its Embeddings row is deleted and its id taken out of every
index named. The embed step then embeds each input that has no row, and a
re-embedding (chunking/reembed.py) fills each further index, built under the
same ids, with the ids it lacks.

The indexes are written first and the database after, document by document.
A run that dies in between leaves rows whose vector is gone, which the embed
step drops and embeds again; a second run finds the changes still to be
written and writes them.

Author: Felix Vossel

## Classes

### Plan

```python
@dataclass
class Plan
```

What writing one document again changes, before anything is written.

Fields:

- `name: str`
- `doc_id: int`
- `new: dict`
- `rows: list`: per new section: the row it keeps, or None
- `gone_sections: list`
- `tables: list`: [(section index, item, old row or None)]
- `gone_tables: list`
- `figures: list`
- `gone_figures: list`
- `provenance: set`: new sections whose pages or segments are written
- `renumbered: bool`
- `drop: dict`: faiss id -> embedding type, of every vector that goes
- `kept: int`
- `counts: dict`

#### Plan.writes

```python
@property
def writes(self) -> bool
```

### SyncReport

```python
@dataclass
class SyncReport
```

What a sync found, counted over its documents.

Fields:

- `documents: int = 0`
- `changed: list = field(default_factory=list)`
- `unregistered: list = field(default_factory=list)`
- `sections: Counter = field(default_factory=Counter)`
- `tables: Counter = field(default_factory=Counter)`
- `figures: Counter = field(default_factory=Counter)`
- `kept: int = 0`
- `dropped: Counter = field(default_factory=Counter)`
- `removed: dict = field(default_factory=dict)`

#### SyncReport.add

```python
def add(self, plan: Plan) -> None
```

#### SyncReport.sentence

```python
def sentence(self) -> str
```

## Functions

### align

```python
def align(old: list, new: list) -> list
```

For each entry of *new*, the index of the entry of *old* whose row it
takes, or None: equal entries in order keep theirs, and in a stretch where
the two differ the new ones take the old ones' rows in their order.

### pair

```python
def pair(old_rows: list, new_items: list) -> tuple
```

([(section index, item, old row or None)], [old rows no item takes]):
each new item takes the next old row of its block id.

### plan_document

```python
def plan_document(conn, doc_id: int, name: str, merged: dict, pdf_dir: Path,
                  resolve: Resolve = resolve_title) -> Plan
```

What writing *merged* over the rows of document *doc_id* changes.

### apply_plan

```python
def apply_plan(conn, plan: Plan) -> None
```

Write *plan* into the database; the caller commits.

### drop_from_index

```python
def drop_from_index(path: Path, ids) -> int
```

Take *ids* out of the index file *path*, written whole under a new name
first; a re-embedding's record beside it then says it is incomplete.
Returns how many vectors went.

### run_sync

```python
def run_sync(data_dir: Path, db_path: Path, index_paths, *,
             dry_run: bool = False, resolve: Resolve = resolve_title) -> SyncReport
```

Write every document under *data_dir* into *db_path* under the numbers
its entries have, taking each vector whose input changed out of every
file of *index_paths* first. *dry_run* counts and writes nothing.

[Back to the index](../README.md)
