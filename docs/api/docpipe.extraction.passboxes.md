# docpipe.extraction.passboxes

`docpipe/extraction/passboxes.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

passboxes.py: What each box of a follow-up pass does (`passflow`, library
entries with `flow == "pass"` in `blocks`).

A box works on one document: its harvest file, as it lies on disk and as the
boxes before it have changed it (`Doc`). The logic of each box is that of the
pass it was cut out of, at the step boundaries the pass had:

- `topup.py`: the questions that moved, the dimensions read again and kept
  or put back;
- `topup_parameter.py`, `surveyed.py`: a parameter the spec gained, the
  passages nobody read;
- `remap.py`, `recheck.py`: the lists mapped again, the quotes checked again,
  no model;
- `review.py`: the second reading of the rows nobody can stand behind.

A box leaves `doc.stop` where the document is done or left alone, and the
chain goes no further for it. What a box counts goes in `doc.stats`; the
stamp keys a pass may carry forward in `doc.settled`.

Author: Felix Vossel

## Classes

### Unit

```python
class Unit
```

One dimension a pass reads again: the stamp key it came from (None
where the dimension was open), its parameter and slot, its rows where
they are known, and what asking it left for the step that decides it.

#### Unit.\_\_init\_\_

```python
def __init__(self, key, parameter, slot, rows=None)
```

### Doc

```python
class Doc
```

One document of a pass: its harvest file, and what the boxes before
have made of it.

#### Doc.\_\_init\_\_

```python
def __init__(self, run, path, document_id: Optional[int] = None,
             filename: Optional[str] = None)
```

#### Doc.tuples

```python
@property
def tuples(self) -> list
```

#### Doc.refusals

```python
@property
def refusals(self) -> list
```

#### Doc.bases

```python
@property
def bases(self) -> tuple
```

The document's base and target years, rebuilt from the frame's
own readings of the stored rows.

#### Doc.position

```python
@property
def position(self) -> Optional[int]
```

Where this pass will stand in the stamp's list. What it writes
points at that position and the rows are written before the list
is, so it is asked for before anything is entered.

## Functions

### files_of

```python
def files_of(run, which: str) -> list
```

The harvest files a chain takes: those of the folder, or of the
documents the run names, or of those it would harvest.

### box_stored

```python
def box_stored(run, doc: Doc, node: dict) -> None
```

The file as it lies on disk, and the lists its document closed.

### box_changed

```python
def box_changed(run, doc: Doc, node: dict) -> None
```

The questions the stamp says moved, but for those only a gained
parameter moved.

### box_movable

```python
def box_movable(run, doc: Doc, node: dict) -> None
```

Which of the moved questions may be read again; one that blocks
leaves the file as it is.

### box_open

```python
def box_open(run, doc: Doc, node: dict) -> None
```

Every dimension some row left open, each read to the end of the
plan.

### box_take_back

```python
def box_take_back(run, doc: Doc, node: dict) -> None
```

The dimension taken off its rows and asked again.

### box_better

```python
def box_better(run, doc: Doc, node: dict) -> None
```

The new answer where it is better, else the old one.

### box_derive

```python
def box_derive(run, doc: Doc, node: dict) -> None
```

The dimension the spec decides from the unit, taken from it.

### box_reopen_closed

```python
def box_reopen_closed(run, doc: Doc, node: dict) -> None
```

Rows a moved gate released are asked the dimensions they never were
asked. They carry `out_of_slice`, which is not a reading and not a
finding about the plan: it says the row left before the question.

### box_demote

```python
def box_demote(run, doc: Doc, node: dict) -> None
```

A refused row is a refusal now, in the file and in the summary. The
line keeps its place: the dict was rewritten where it stands.

### box_summary

```python
def box_summary(run, doc: Doc, node: dict) -> None
```

### box_remap

```python
def box_remap(run, doc: Doc, node: dict) -> None
```

The recorded wording of each row mapped onto the lists as the spec
reads them today. The stamp keys that stay settled are the answer spaces
every row could be mapped in.

### box_recheck

```python
def box_recheck(run, doc: Doc, node: dict) -> None
```

Every coordinate of every row held to the rule that its answer
stands in its quote.

### box_review

```python
def box_review(run, doc: Doc, node: dict) -> None
```

Each row of the trust levels in the rule read a second time.

### box_worklist

```python
def box_worklist(run, doc, node: dict) -> None
```

What the second reading said, beside the harvest.

### box_clear_stamps

```python
def box_clear_stamps(run, doc, node: dict) -> None
```

The stamps of the files a pass rewrote, kept in the archive and
deleted, so that the next run reads those documents again.

### box_replace

```python
def box_replace(run, doc: Doc, node: dict) -> None
```

The file replaced from its lines, or the new rows appended to it.

### box_carry_stamp

```python
def box_carry_stamp(run, doc: Doc, node: dict) -> None
```

The stamp keys the pass earned, written forward; and what the second
reading says about the stamp.

### box_classify

```python
def box_classify(run, doc: Doc, node: dict) -> None
```

What the pass does with one stored document, by the rules of
`topup_parameter.classify`.

### box_read_parameters

```python
def box_read_parameters(run, doc: Doc, node: dict) -> None
```

The whole plan read for the new parameters alone, folded and
checked; nothing is written unless they were read completely.

### box_unread

```python
def box_unread(run, doc: Doc, node: dict) -> None
```

The passages no reading of the harvest answered, and the passages a
parameter's reading came to nothing in, read now.

### box_places

```python
def box_places(run, doc, node: dict) -> None
```

The documents start at the passages earlier harvests found
something in.

### box_main_flow

```python
def box_main_flow(run, doc: Doc, node: dict) -> None
```

One document read with the flow of the profile.

[Back to the index](../README.md)
