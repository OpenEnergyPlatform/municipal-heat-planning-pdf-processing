# docpipe.extraction.surveyed

`docpipe/extraction/surveyed.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

surveyed.py: One document harvested from its survey.

The survey of the whole plan (survey.py), the reading of every parameter in
the passages it named (reading.py) and the combing for what the reading left
open (combing.py). The run folds what they read, works out what the profile
computes and writes the file with its stamp, as it writes every harvest.

What none of them could read is a hole with its reason, never a plan that
seems silent: a passage the survey left unanswered, and a passage a parameter
was to be read in that came to no readable reply, each go to the fold as the
harvest's sentinel (`_harvest_failed`, `_why` cut_off or no_answer). The fold
keeps it as a refusal, and a parameter that has no row then ends `exhausted`
and not `unstated`: `trust.parameter_states` looks for its holes among the
passages the survey named for it, and a passage the survey could not answer
counts for every parameter. The hole of a reading names its parameter
(`_parameter`), so a pass over the harvest knows what to read again.

The passes over a stored harvest go through the same steps. `--start-at`
surveys the passages earlier harvests found something in (`take_found`);
`--top-up-parameters` surveys the whole plan for the parameters the spec
gained (`append_parameters`); `--top-up-open` combs every coordinate left
open (`comb_sweep` under `topup._sweep_one`) and then reads what nothing has
read yet (`append_unread`); `--top-up` combs the coordinates whose question
moved (`comb_sweep`). A survey of part of a plan is kept under its own scope
beside the whole one's.

Author: Felix Vossel

## Classes

### Taken

```python
@dataclass
class Taken
```

What the survey, the reading and the combing of one document came to,
in the shape the fold and the stamp read.

Fields:

- `found: Found`
- `reads: list = field(default_factory=list)`
- `combed: list = field(default_factory=list)`
- `answered: list = field(default_factory=list)`: (batch, reply) for the fold: every reading's values and every hole.
- `replies: int = 0`: Passages the survey answered: none of them means no reply at all.
- `passages: int = 0`
- `sources_of: dict = field(default_factory=dict)`: parameter uri -> the passages the survey named for it, and every passage it could not answer (`trust.parameter_states`).

### SurveyedHarvest

```python
class SurveyedHarvest
```

document_id -> Taken, or None when the run was halted on the way.

*make_survey(spec, only, scope)* is the run's survey of the parameters
*only* (all when empty) under *scope*, *make_reader(spec)* and
*make_comber(spec)* its reading and combing (the comber None where
nothing is combed), each made once per spec. *spec_for(document_id)* is
the document's spec, its lists closed (`runner.closed_spec`),
*passages_of(document_id)* every passage of the document in its order,
*pages_of(document_id)* its page count, *halted()* whether the run stops.

#### SurveyedHarvest.\_\_init\_\_

```python
def __init__(self, spec, make_survey: Callable, make_reader: Callable,
             make_comber: Callable, passages_of: Callable,
             pages_of: Callable, *, spec_for: Optional[Callable] = None,
             halted: Optional[Callable] = None)
```

#### SurveyedHarvest.survey_of

```python
def survey_of(self, spec, only=(), scope: str = "")
```

#### SurveyedHarvest.reader_of

```python
def reader_of(self, spec)
```

#### SurveyedHarvest.comber_of

```python
def comber_of(self, spec)
```

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

### frame_pairs

```python
def frame_pairs(found: Found) -> list
```

The frame tuples of a survey, each once, in the order of the plan.

### joined

```python
def joined(found: Found, also: Found) -> Found
```

One survey of both: what *also* names is read beside what *found*
names, a passage both answer with the parameters of both.

### taken_of

```python
def taken_of(document_id: int, spec, found: Found, reads: list,
             combed: list, shown: dict) -> Taken
```

The fold's view of one document's reading, holes included.

### take_found

```python
def take_found(whole: SurveyedHarvest, document_id: int, kept: list,
               gained: list) -> Optional[Taken]
```

--start-at: the survey of the passages earlier harvests found
something in, and for a parameter none of them was asked (*gained*) the
survey of the rest of the plan as well, so that it is surveyed over the
whole plan as in any run (owner decision 2026-11-03).

### comb_sweep

```python
def comb_sweep(comber_of: Callable, spec_for: Callable, every: Callable,
               pages_of: Callable) -> Callable
```

sweep(batch, rows, slots, anchor) of a pass over a stored harvest
(`topup._sweep_one`) in a run that harvests from the survey: the
coordinates the pass re-reads are combed per passage of the rows
(`combing.Comber.comb`), their own passage and its section shown first,
since the reading that asked them there ran under an older question, and
with the years the stored rows give (`batch.bases`). What it leaves open
is restored by the pass as it restores any sweep's.

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
them alone (*deps["take"](document_id, uris)*), their reading and their
combing; the frame of their rows comes from that survey.

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
