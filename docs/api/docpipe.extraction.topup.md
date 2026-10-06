# docpipe.extraction.topup

`docpipe/extraction/topup.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

topup.py: Re-reads the one coordinate a stamp names as moved, instead of the
whole document.

A question is reworded, or an option list gains a class the model can now
choose. The stamp knows exactly which key moved, and a
resume then does the only thing it can: it reports the document stale, and the
next run harvests it again from the first passage. For one axis of one
parameter, that is a full corpus run spent answering a question nothing else
asked.

This module instead takes the coordinate off the rows that carry it, walks the
same sweep the harvest walks (`runner.make_sweeper`, so there is one sweep and
one set of numbers), and writes the answer back. It then carries that one stamp
key forward and leaves every other key exactly as it was, so a later run still
sees what it has to redo. Who read is recorded apart from that: the pass enters
the stamp's `producers` list whether or not it earned a key, and each
coordinate it re-read points at its entry (`<axis>_producer`), so a file with
two readings of one coordinate's rows says which is which.

What the module refuses to touch matters more than what it does. A key that
decided which rows exist, which passages were planned, or which model read them
does not name a coordinate: the rows are then not this run's product at all,
and the document is skipped whole rather than half repaired. The frame is
refused for the same reason one level up, because it decides how many passes a
document gets.

A parameter the spec has gained is not a coordinate. Its keys are taken out
of the list before anything is asked (`topup_parameter.explained_keys`), so
they neither block the document nor are written by this pass, and the pass
that appends the parameter answers for them.

The old reading is restored whenever the re-sweep fails to improve on it. No
coordinate is required in either profile, so an emptied one would otherwise
pass verification in silence, with the reading gone and nothing recording the
loss. Unlike `--recheck` and `--remap`, the pass is neither model-free nor
index-free: it needs the database, the index, the embedder, and a served model,
and what it saves is the plan, the row requests, and the frame.

Author: Felix Vossel

## Classes

### Stored

```python
@dataclass
class Stored
```

A harvest file as it lies on disk, read once.

`entries` holds every line but the summary, in order, as (the line as it
stands in the file, the record it parses to or None). A pass that
rewrites a line puts its own record in the line's place and a pass that
does not writes the line back byte for byte; the summary is always built
again, so the old one is left out.

Fields:

- `entries: list = field(default_factory=list)`
- `tuples: list = field(default_factory=list)`
- `refusals: list = field(default_factory=list)`
- `states: list = field(default_factory=list)`
- `document_id: Optional[int] = None`
- `unreadable: int = 0`

#### Stored.lines

```python
@property
def lines(self) -> list
```

## Functions

### actionable

```python
def actionable(changed, spec: Spec, frame_names=(), *, dynamic_ok: bool = True,
               only=None) -> tuple
```

(keys this pass may sweep, keys that block the document).

A key blocks unless it names one coordinate of one parameter that the
profile does not put in the frame and that this run can actually close.
Anything else means the rows themselves are not what this run would
produce, and sweeping one coordinate of them would leave a file that is
half one run and half another with a stamp saying it is all one.

### slot_of

```python
def slot_of(spec: Spec, key: str)
```

"axis/\<uri>/\<name>" -> (parameter, slot), or None.

### targets_of

```python
def targets_of(spec: Spec, key: str) -> list
```

[(parameter, slot)] a stamp key names; [] when it names no coordinate.

"axis/\<uri>/\<name>" is one coordinate of one parameter. "slot/unit" is
the unit of every numeric parameter: one question in the harvest, asked
before the parameter is known, so one key -- and swept here parameter by
parameter with that parameter's own list, because a stored row already
knows its parameter.

### reopen

```python
def reopen(claim: dict, slot) -> dict
```

Take this coordinate off the claim and hand back what was taken.

A flag on `merge_field` would have been the other way, and it would have
been the wrong way: the short-circuit it would bypass is what keeps one
window from overwriting what an earlier one read, and that rule is not
this pass's to soften.

### restore

```python
def restore(claim: dict, slot, taken: dict, *, keep: tuple) -> bool
```

Put the old block back unless the new state is one of `keep`.

True when the old reading was restored, which is also what says the key
cannot be written forward: the document still holds a coordinate this
run's question never answered.

### owners_of

```python
def owners_of(row: dict, slots: list) -> list
```

The row's own passage, and every passage its coordinates were read in.

The second half is what lets the sweep offer a coordinate the passage it
was last read in: the re-entry rule works off the sources of the batch,
and a passage nobody put in the batch cannot be offered.

### pairs_of

```python
def pairs_of(tuples: list, frame_axes) -> dict
```

{index: pair} the frame wrote onto these stored rows.

The harvest wrote each pair onto its rows with the window ["frame", i],
so the pairs are recoverable from the file: one per index, from the first
row that carries it, with the wording, quote and source the pair was read
by. The indices have gaps where a pair no row carries, and the pairs come
back under the index they were stored with, never renumbered.

### base_years_of

```python
def base_years_of(tuples: list, frame_axes, base_state) -> tuple
```

The document's base years, rebuilt from the frame's own readings.

Without them a re-swept year that says "Basisjahr" and prints no number
cannot be read (`pipeline.base_year_named`): the main harvest could and
this pass could not, which would cost the full run this pass exists to
spare.

### rebuild

```python
def rebuild(rows: list, parameter, sources: dict, carry: list) -> tuple
```

(batches, {batch index: [Row]}) for a re-sweep of these stored tuples.

One work item per row's own passage, plus one per carried-over passage, so
the sweep's own window holds both. The parameter object is the same one on
every item: `group_items` groups on identity.

### reopened_by_gate

```python
def reopened_by_gate(tuples: list, spec: Spec, gate: dict,
                     frame_names=()) -> list
```

[(parameter, slot, rows)] for coordinates a re-swept gate has released.

The gate decides whether a row belongs in the slice this run serializes at
all, and a row that left it was never asked its other coordinates. If the
gate reads differently now, those questions were never put and the row
would otherwise keep a coordinate saying it left a slice it is in.

### read_harvest

```python
def read_harvest(path) -> Stored
```

The lines of one harvest file, sorted by what they are.

The file is read as bytes and split at the line feed alone, so a line is
what it was down to a carriage return (`jsonl.lines`). A line that is not
JSON, or is JSON and no record, is kept as it stands and counted. An empty
line is not a record and is not kept.

### top_up_file

```python
def top_up_file(path: Path, spec: Spec, current: dict, deps: dict, *,
                only=None) -> Counter
```

Re-sweep one harvest file's moved coordinates, then carry its stamp.

### point

```python
def point(claim: dict, slot, position: Optional[int]) -> None
```

Say that this pass wrote this coordinate: `<axis>_producer` is the
position of its entry in the stamp's list. Nothing to point at, nothing
written.

### run

```python
def run(harvest_dir: Path, spec: Spec, current: dict, deps: dict, *,
        only=None) -> Counter
```

Top up a whole harvest directory against the spec as it reads today.

[Back to the index](../README.md)
