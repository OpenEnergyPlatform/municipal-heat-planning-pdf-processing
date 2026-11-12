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

This module instead takes the coordinate off the rows that carry it, asks it
as the harvest asks it (`surveyed.SurveyedHarvest.sweep`, so there is one
question and one set of numbers), and writes the answer back. It then carries that one stamp
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

### Sweep

```python
@dataclass
class Sweep
```

One dimension asked again, between asking and deciding: the rows,
their batches, and what each row's entry held before it was taken
off.

Fields:

- `rows: list`
- `parameter: object`
- `slot: object`
- `usable: list = field(default_factory=list)`
- `batches: list = field(default_factory=list)`
- `by_batch: dict = field(default_factory=dict)`
- `taken: dict = field(default_factory=dict)`: batch index -> {label: block}
- `settled: bool = True`
- `ended: bool = False`: no row had a passage to be read in
- `locate: Optional[Callable] = None`

## Functions

### keep_read

```python
def keep_read() -> tuple
```

A coordinate that was read stays read unless the sweep reads it
again: the states of a new reading that replace it (rule
`reread_keep_states`).

### keep_asked

```python
def keep_asked() -> tuple
```

A coordinate that was not read is bettered by any answer, "the
passages do not say it" included -- that is an answer. Running out of
budget is not (rule `reread_improves_states`).

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

### in_order

```python
def in_order(keys: list, spec: Spec) -> list
```

[(key, parameter, slot)] of the moved coordinates in the order they
are read again (rule `reread_order`): by the key of the stamp, each
with its parameters in the spec's order, or by the order of the
parameters in the spec.

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

### named_years_of

```python
def named_years_of(tuples: list, frame_axes, year_states) -> tuple
```

The document's base years and target years, rebuilt from the frame's
own readings.

Without them a re-swept year that says "Basisjahr" or "Zieljahr" and
prints no number cannot be read (`pipeline.named_year`): the main harvest
could and this pass could not, which would cost the full run this pass
exists to spare.

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

### open_coordinates

```python
def open_coordinates(tuples: list, spec: Spec) -> list
```

[(parameter, slot, rows)] of every asked coordinate some row left open.

The frame's coordinates are among them: a row whose year is open was not
under a pair, and its year is asked per row like any other coordinate.

### point

```python
def point(claim: dict, slot, position: Optional[int]) -> None
```

Say that this pass wrote this coordinate: `<axis>_producer` is the
position of its entry in the stamp's list. Nothing to point at, nothing
written.

### sweep_ask

```python
def sweep_ask(rows: list, parameter, slot, doc_spec: Spec, deps: dict,
              stats: Counter, bases: tuple = ()) -> Sweep
```

Take one coordinate off these rows and ask it again.

The coordinate is asked as the harvest asks it (`deps["sweep"]`), over
the passages its rows were read in. What the rows held is kept in the
returned `Sweep` for `sweep_decide`, which keeps it or the new answer.

### sweep_decide

```python
def sweep_decide(sweep: Sweep, stats: Counter,
                 position: Optional[int] = None) -> tuple
```

Keep what the coordinate was asked again, or what it held.

(every row settled, the rows the verifier refused afterwards). A refused
row was rewritten in place as the refusal it now is: the re-read said the
coordinate is not what the tuple carried -- a unit no list holds, a
required axis the passages do not state -- and that is the finding, with
the claim kept beside the reason for the audit. Keeping the old tuple
instead would leave in the graph exactly the reading the re-read was
asked to check.

A coordinate whose new reading stands points at `position`, this pass's
entry in the stamp's list (`point`). One whose old block was put back
keeps the pointer that block had, or none.

[Back to the index](../README.md)
