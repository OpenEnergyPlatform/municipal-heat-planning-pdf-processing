# docpipe.extraction.surveyed

`docpipe/extraction/surveyed.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

surveyed.py: One document harvested piece by piece, both profiles (owner
decisions 2026-11-08 evening).

The document's passages as numbered lines in pieces of at most eight, its
figures transcribed once (`addressed.Transcripts`); what the plan settles
for all its values and its own years asked once (`addressed.Reader.settled`);
then every field read: a field the document has once asked once, every other
field in every piece, the pieces best first for its sentences
(`addressed.Orders`), and each value's coordinates asked one by one
(`addressed.Reader`). The run folds what they read, works out what the
profile computes and writes the file with its stamp, as it writes every
harvest.

What could not be read is a hole with its reason, never a plan that seems
silent: a passage a field was to be read in that came to no readable reply
goes to the fold as the harvest's sentinel (`_harvest_failed`, `_why`
cut_off or no_answer). The fold keeps it as a refusal, and a field that has
no row then ends `exhausted` and not `unstated` (`trust.parameter_states`).
The hole of a reading names its field (`_parameter`), so a pass over the
harvest knows what to read again.

The passes over a stored harvest go through the same steps. `--start-at`
reads the passages earlier harvests found something in (`take_found`);
`--top-up-parameters` reads the whole plan for the fields the spec gained
(`append_parameters`); `--top-up-open` asks every coordinate left open again
(`SurveyedHarvest.sweep` under `topup._sweep_one`) and then reads what
nothing has read yet (`append_unread`); `--top-up` asks the coordinates
whose question moved (`SurveyedHarvest.sweep`). An order of part of a plan
is kept under its own scope beside the whole one's.

Author: Felix Vossel

## Classes

### Taken

```python
@dataclass
class Taken
```

What the reading of one document came to, in the shape the fold and
the stamp read.

Fields:

- `reads: list = field(default_factory=list)`
- `answered: list = field(default_factory=list)`: (batch, reply) for the fold: every reading's values and every hole.
- `replies: int = 0`: Readings that came back with a reply: none of them means no reply at all (`runner.not_happened`).
- `passages: int = 0`
- `sources_of: dict = field(default_factory=dict)`: parameter uri -> the passages it was read in (`trust.parameter_states`).

### SurveyedHarvest

```python
class SurveyedHarvest
```

document_id -> Taken, or None when the run was halted on the way.

*make_reader(spec)* is the run's reading (`addressed.Reader`), made
once per spec; *spec_for(document_id)* the document's spec, its lists
closed (`runner.closed_spec`); *passages_of(document_id)* every passage
of the document in its order; *transcripts(document_id, figures, each)*
its figures' lines (`addressed.Transcripts`); *orders(plan, parameters,
chunk_units, scope, chunks)* the pieces of each field best first
(`addressed.Orders`); *halted()* whether the run stops. *chunk_units*
is how many lines a piece holds; *each(jobs, run)* runs jobs side by
side; *trace* writes what a document's requests came to.

#### SurveyedHarvest.\_\_init\_\_

```python
def __init__(self, spec, make_reader: Callable, passages_of: Callable,
             *, spec_for: Optional[Callable] = None,
             halted: Optional[Callable] = None,
             transcripts: Optional[Callable] = None,
             orders: Optional[Callable] = None,
             chunk_units: int = CHUNK_UNITS,
             each: Optional[Callable] = None, trace=None)
```

#### SurveyedHarvest.reader_of

```python
def reader_of(self, spec)
```

#### SurveyedHarvest.plan_of

```python
def plan_of(self, document_id: int) -> tuple
```

(the document's Plan, its Counts): its pieces, its figures'
lines, what it settles and its years. A pass over a stored harvest
asks several batches of one document and finds it made.

#### SurveyedHarvest.forget

```python
def forget(self, document_id: int) -> None
```

#### SurveyedHarvest.sweep

```python
def sweep(self, batch, rows, slots, anchor=None) -> None
```

What a pass over a stored harvest asks a coordinate again with
(`topup._sweep_one`): each row's value at the line its quote stands
in, each coordinate of *slots* asked as the harvest asks it
(`addressed.Reader.coordinate`); what it leaves open is restored by
the pass as it restores any sweep's.

### ParameterPass

```python
class ParameterPass(_counted("top-up-parameters"))
```

--top-up-parameters in a run that harvests from the survey.

#### ParameterPass.\_\_init\_\_

```python
def __init__(self, out_dir: Path, spec, current: dict, deps: dict)
```

### UnreadPass

```python
class UnreadPass(_counted("top-up-rest"))
```

The second half of --top-up-open in a run that harvests from the
survey.

#### UnreadPass.\_\_init\_\_

```python
def __init__(self, out_dir: Path, deps: dict)
```

## Functions

### hole

```python
def hole(document_id: int, source, why: str,
         parameter: Optional[str] = None) -> tuple
```

(batch, reply) the fold turns into the refusal of a passage nothing
could read: the sentinel claim with its reason, filed under no parameter
as every sentinel is, the parameter it was read for beside it.

### derive_left

```python
def derive_left(reads: list) -> int
```

What the spec derives from the unit, on every value no request read
it for once its coordinates are asked (owner decision 2026-11-07: asked
first, and only where no answer is read taken from the unit,
`fields.derives`). Returns how many coordinates.

### taken_of

```python
def taken_of(document_id: int, spec, reads: list) -> Taken
```

The fold's view of one document's reading, holes included. A field's
sources are the passages it was read in.

### locate_value

```python
def locate_value(plan: Plan, source, claim: dict) -> Optional[dict]
```

The address of a stored value in its passage (`at`): the line its
quote stands in, the cell of a table row that alone holds its number or
words; None where no line of the passage holds the quote. A value read
with its address keeps it.

### take_found

```python
def take_found(whole: SurveyedHarvest, document_id: int, kept: list,
               gained: list) -> Optional[Taken]
```

--start-at: the passages earlier harvests found something in, and
for a field none of them was asked (*gained*) the rest of the plan as
well, so that it is read over the whole plan as in any run (owner
decision 2026-11-03).

### append_parameters

```python
def append_parameters(document_id: int, filename: str, out_dir: Path,
                      spec, current: dict, deps: dict) -> tuple
```

(written, failures, stats) of --top-up-parameters for one stored
document, in a run that harvests from the survey.

The rules of `topup_parameter.append_document`, which this is for such a
run: only the addition may have moved, the stored lines stay as they
are, and nothing is written, neither file nor stamp, unless the new
parameters were read. They are read by a survey of the whole plan for
them alone (*deps["take"](document_id, uris)*), read piece by piece
with their coordinates asked and searched for; the frame of their rows
comes from that survey.

*deps* holds "document_spec" (id -> the document's spec, None when its
lists cannot be closed), "take", "locate", "frame_names" and
"dynamic_ok".

### surveyed_owners

```python
def surveyed_owners(out_dir: Path, document_id: int) -> tuple
```

({owner: Answer} every stored survey of the document answered, and
the owners none of them could) from `survey/<document>[.<scope>].json`.
What was surveyed is read from the files whatever key they were kept
under: a pass reads what the harvest covered, not what it would ask
today.

### holes_of

```python
def holes_of(refusals: list) -> tuple
```

({owner} of passages nothing read, {owner: {parameter}} of passages a
parameter's reading came to nothing in) among a harvest's refusals.

### append_unread

```python
def append_unread(document_id: int, filename: str, out_dir: Path,
                  deps: dict) -> tuple
```

(written, failures, stats) of the second half of --top-up-open for
one stored document, in a run that harvests from the survey: what
nothing has read yet, read now and appended after the stored lines.

Unread is a passage no survey of the harvest answered (one it left
unanswered, or one outside the found places of a harvest read in part),
and a passage a parameter's reading came to nothing in (a hole that
names its parameter, `_parameter`), which is read again for that
parameter alone with what its survey said of the passage. A harvest of
the old flow has no surveys: what its rows requests were shown counts as
read (`topup_rest.read_owners`). A document with neither is skipped, as
in that flow. A document this pass has read to its end says so in its
stamp (`topup_rest.PASS`) and is not read again.

*deps* holds "take" (document_id, passages, also -> Taken), "passages_of"
(document_id -> every passage), "locate" and "spec".

[Back to the index](../README.md)
