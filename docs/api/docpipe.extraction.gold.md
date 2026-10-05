# docpipe.extraction.gold

`docpipe/extraction/gold.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

gold.py: What a person decided about harvested values, kept beside the
harvest and never in it.

A harvest says what the run read. Whether that is right is not something
the run can say, and a second model reading the same page cannot say it
either. A person can: with the value, its quote and the page in front of
them they decide, field by field, whether the document says that. Those
decisions are the gold, and the only thing precision and recall are counted
against (`evaluate.py`).

They are one JSON line each in a file of their own, appended and never
rewritten, so two people can decide at once and a decision that was changed
is still there. The last line about one thing is the one that counts.

    verdict   one field of one harvested row is `correct` or `wrong`. The
              field is "value", "unit" or the name of a coordinate; `shown`
              is what the harvest said there when it was decided, and
              `expected` what is right, where the person gave it.
    missing   the document states a value of a parameter that the harvest
              does not carry.
    checked   somebody read the whole document for one parameter (or for
              every one): only then is what the harvest lacks there known,
              and only over such documents is recall counted.

A row is named by its document, `identity.tuple_id` (the quote and the
value as written) and its parameter. Those survive a new harvest and a new
build of the database, so a decision made once is found again by the next
run that reads the same thing.

Two rows of one document can share that name: a table row that prints the
same number under two years is one quote and one value, read twice. So a
decision also notes what the row said in its other fields when it was made
(`row`), and it is about that row. A row that reads the same finds it. A
row that reads differently takes it over only when it is the one row the
decision can be about: the same value read again with another year, and
not the row beside it.

Nothing here judges a value, drops one or writes into a harvest. What a
writer does with a decision is to keep it beside the value it concerns
(`decisions_in`): the value is the same with it and without it.

Author: Felix Vossel

## Classes

### Gold

```python
class Gold
```

The decisions of a file, as the questions an evaluation asks.

#### Gold.\_\_init\_\_

```python
def __init__(self, records: Iterable[dict] = ())
```

#### Gold.load

```python
@classmethod
def load(cls, path) -> "Gold"
```

#### Gold.settled

```python
def settled(self, document: str, row: dict, field: str,
            rows: Optional[Iterable[dict]] = None) -> Optional[tuple]
```

(`correct` or `wrong`, the decision that says so) for what *row*
says in *field* now, or None (nobody decided). *rows* are the rows
of its document, where other rows of the same name may stand;
without them the row stands alone.

A field holds one thing. So where somebody found other content
correct there, or named what is right, that settles this content
too; where the only decisions are about other content found wrong,
nothing is known about this one. What was said last counts.

#### Gold.verdict

```python
def verdict(self, document: str, row: dict, field: str,
            rows: Optional[Iterable[dict]] = None) -> Optional[str]
```

`correct`, `wrong` or None (nobody decided) for what *row* says
in *field* now; `settled` says which decision it is.

#### Gold.is_checked

```python
def is_checked(self, document: str, parameter: str) -> bool
```

#### Gold.missing_for

```python
def missing_for(self, document: str, parameter: str) -> list
```

## Functions

### same

```python
def same(left, right) -> bool
```

Whether two field contents say the same: a number as a number, a
text without regard to its spacing, and a number typed into a form as
the number it spells.

### coordinates

```python
def coordinates(row: dict) -> list
```

The names of the coordinates a row carries, in a fixed order.

### fields_of

```python
def fields_of(row: dict) -> list
```

Every field of a row a person can decide: the value, its unit where
it has one, and each coordinate.

### row_key

```python
def row_key(document: str, row: dict) -> tuple
```

What names a harvested row for a decision.

### signature

```python
def signature(row: dict) -> dict
```

What a row says beside its value: its unit and each coordinate. Two
rows of one name are told apart by it.

### same_signature

```python
def same_signature(left, right) -> bool
```

### row_name

```python
def row_name(document: str, row: dict) -> str
```

One text per row as it reads now: its name and what it says beside
its value. For an order, a key on a page, a set of rows put aside.

### read

```python
def read(path) -> list
```

Every decision in a file, in the order they were made. A file that
is not there holds none.

### decide

```python
def decide(path, document: str, row: dict, field: str, verdict: str, *,
           expected=None, by: Optional[str] = None,
           note: Optional[str] = None, at: Optional[str] = None) -> dict
```

Write down that *field* of *row* is correct or wrong.

### add_missing

```python
def add_missing(path, document: str, parameter: str, value, *,
                unit=None, quote: Optional[str] = None,
                coordinates: Optional[dict] = None, page=None,
                by: Optional[str] = None, note: Optional[str] = None,
                at: Optional[str] = None) -> dict
```

Write down a value the document states and the harvest lacks.

### mark_checked

```python
def mark_checked(path, document: str, parameter: Optional[str] = None, *,
                 by: Optional[str] = None, note: Optional[str] = None,
                 at: Optional[str] = None) -> dict
```

Write down that the whole document was read for *parameter* (None:
for every one).

### covers

```python
def covers(fact: dict, row: dict) -> bool
```

Whether a harvested row is the value a `missing` record names: the
same parameter and value, and every coordinate and the unit the record
gives.

### harvest

```python
def harvest(directory) -> dict
```

{document name: [accepted rows]} of a harvest directory.

### path_beside

```python
def path_beside(harvest_dir) -> Path
```

Where the decisions of a harvest are kept unless said otherwise: a
file of its own next to the harvest directory. `evaluate` and the review
page of the chat both find them there.

### decisions_in

```python
def decisions_in(held: Gold, harvest: dict) -> tuple
```

What people decided about the rows of a harvest, and what about rows
it does not hold.

({document: {tuple name: [decision]}}, {(document, tuple, parameter):
decisions}). A decision is the settled verdict of one field of one row
(`Gold.settled`) with who made it, when and the note; the tuple name is
the one `identity.tuple_ids` gives the row in its document, which is
what a writer's `claims` call it. The second holds the field decisions
whose row (document, `identity.tuple_id` and parameter) is in no row of
*harvest*: counted by the caller, never applied to another row.

Nothing here changes a row or leaves one out.

### queue

```python
def queue(rows_by_document: dict, gold: Gold, *,
          parameters: Optional[Iterable[str]] = None,
          limit: Optional[int] = None) -> list
```

The rows nobody has decided yet, as (document, row), in an order
that is the same every time and has nothing to do with the document or
the parameter.

The order is by a hash of the row's name. Whoever decides the first
hundred has decided a sample of the whole harvest, not the first three
documents of it, and precision counted over them holds for the rest.

[Back to the index](../README.md)
