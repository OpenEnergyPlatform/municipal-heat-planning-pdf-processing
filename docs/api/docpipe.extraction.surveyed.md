# docpipe.extraction.surveyed

`docpipe/extraction/surveyed.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

surveyed.py: One document harvested passage by passage.

Every passage of the plan for every parameter, best first (survey.py, owner
decisions 2026-11-08), the plan's years and settings (years.py,
settings.py), the reading of every parameter in every passage (reading.py)
and the conversation for what the reading left open (combing.py). The run
folds what they read, works out what the profile computes and writes the
file with its stamp, as it writes every harvest.

Since every passage is read for every parameter, nothing is searched for a
parameter before it can count as not stated: the walk down a search's list
for a parameter the survey named no passage for, the model's own search for
it and the read of a publication's first pages for what it says of itself
went with the survey (owner decisions 2026-11-08). What a passage leaves
open of a value is still searched for in the rest of the plan (combing.py).
Every passage a parameter was read in is one of its sources, so a request
that came to nothing there leaves a hole and not a silent plan.

What could not be read is a hole with its reason, never a plan that seems
silent: a passage a parameter was to be read in that came to no readable
reply goes to the fold as the harvest's sentinel (`_harvest_failed`, `_why`
cut_off or no_answer). The fold keeps it as a refusal, and a parameter that
has no row then ends `exhausted` and not `unstated`
(`trust.parameter_states`). The hole of a reading names its parameter
(`_parameter`), so a pass over the harvest knows what to read again.

The passes over a stored harvest go through the same steps. `--start-at`
reads the passages earlier harvests found something in (`take_found`);
`--top-up-parameters` reads the whole plan for the parameters the spec
gained (`append_parameters`); `--top-up-open` combs every coordinate left
open (`comb_sweep` under `topup._sweep_one`) and then reads what nothing has
read yet (`append_unread`); `--top-up` combs the coordinates whose question
moved (`comb_sweep`). An order of part of a plan is kept under its own scope
beside the whole one's.

Author: Felix Vossel

## Classes

### Taken

```python
@dataclass
class Taken
```

What the reading and the combing of one document came to, in the
shape the fold and the stamp read.

Fields:

- `found: Found`
- `reads: list = field(default_factory=list)`
- `combed: list = field(default_factory=list)`
- `answered: list = field(default_factory=list)`: (batch, reply) for the fold: every reading's values and every hole.
- `replies: int = 0`: Readings that came back with a reply: none of them means no reply at all (`runner.not_happened`).
- `passages: int = 0`
- `sources_of: dict = field(default_factory=dict)`: parameter uri -> the passages it was read in (`trust.parameter_states`).

### SurveyedHarvest

```python
class SurveyedHarvest
```

document_id -> Taken, or None when the run was halted on the way.

*make_survey(spec, only, scope)* is the run's order of the passages
for the parameters *only* (all when empty) under *scope*
(`survey.Ranking`), *make_reader(spec)* and
*make_comber(spec)* its reading and combing (the comber None where
nothing is combed), each made once per spec. *spec_for(document_id)* is
the document's spec, its lists closed (`runner.closed_spec`),
*passages_of(document_id)* every passage of the document in its order,
*pages_of(document_id)* its page count, *halted()* whether the run stops.
*make_years(spec)* is the request for the plan's base
and target years (`years.PlanYears`), None where the spec dates nothing
by them; *title_page_of(document_id, passages)* the line of the title
page that names the plan's own place, None where the profile shows none
(owner decisions 2026-11-06). *make_settings(spec)* is the request for
what the plan settles for all its values (`settings.PlanSettings`),
None where the profile writes no prompt for it (owner decision
2026-11-07).

#### SurveyedHarvest.\_\_init\_\_

```python
def __init__(self, spec, make_survey: Callable, make_reader: Callable,
             make_comber: Callable, passages_of: Callable,
             pages_of: Callable, *, spec_for: Optional[Callable] = None,
             halted: Optional[Callable] = None,
             make_years: Optional[Callable] = None,
             title_page_of: Optional[Callable] = None,
             make_settings: Optional[Callable] = None)
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

#### SurveyedHarvest.years_of

```python
def years_of(self, spec)
```

#### SurveyedHarvest.settings_of

```python
def settings_of(self, spec)
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

### derive_left

```python
def derive_left(reads: list) -> int
```

What the spec derives from the unit, on every value no request read
it for once the reading and the combing are done (owner decision
2026-11-07: asked first, and only where no answer is read taken from the
unit, `fields.derives`). Returns how many coordinates.

### joined

```python
def joined(found: Found, also: Found) -> Found
```

One order of both: what *also* names is read beside what *found*
names, a passage both name with the parameters of both, each parameter
in the order its own ranking gave.

### taken_of

```python
def taken_of(document_id: int, spec, found: Found, reads: list,
             combed: list, shown: dict) -> Taken
```

The fold's view of one document's reading, holes included. A
parameter's sources are the passages it was read in.

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
coordinates the pass re-reads are combed per passage of the rows and
group of the spec (`combing.Comber.comb_groups`), their own passage
and its section shown first, since the reading that asked them there
ran under an older question, and with the years the stored rows give
(`batch.bases`). What it leaves open is restored by the pass as it
restores any sweep's.

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
