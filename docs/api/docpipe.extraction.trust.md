# docpipe.extraction.trust

`docpipe/extraction/trust.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

trust.py: Grades every harvested value by how far the run can stand
behind it.

Every accepted tuple is verified: its number is in its quote, its
quote is in a shown source, and every coordinate names the passage it
was read in, and that passage carries its answer. That is a floor, not
a grade. Two values that both clear it can still differ: one was read
out of the document's own text with every coordinate read, the other
out of a picture, with a coordinate the run gave up on.

The module computes a deterministic level per value, from what the
harvest already records: no model call, no second opinion, no
threshold anybody tuned.

  A  the document's own text states it, every coordinate read
  B  the same, but read out of a table transcription or a figure
     description (a model's reading of a picture), or out of a
     document whose pages had no text layer and were transcribed page
     by page
  C  something is off: a coordinate the run gave up on or could not
     back, a repaired quote, a computed number, a contested identity

The reasons form a closed list, because a reason nobody can enumerate
is a reason nobody can count. What makes a value a C is what a curator
should examine.

Where in the document a coordinate's passage stands is not a reason.
The harvest takes a reading whose quote stands in a shown passage and
carries the answer, and grading it again by that passage's distance
from the row would be a check the harvest does not make.

A value can be read a second time (`review.py`), and what that reading
came to is recorded here as a mark. It never raises a level: the
second reading uses the same model over a narrower window, so an
agreement states that the reading is self-consistent, not that it is
right.

Measured on Kassel's 559 tuples, 527 came out of a table or figure
image, so image origin alone separates nothing and is not by itself a
warning.

Author: Felix Vossel

## Functions

### reasons

```python
def reasons(row: dict, *, conflict: bool = False,
            transcribed: bool = False) -> list
```

Every reason this value is not an A, in a fixed order.

An empty list means the harvest sees nothing wrong with the value.

### trust

```python
def trust(row: dict, *, conflict: bool = False, transcribed: bool = False,
          corroborated: bool = False) -> dict
```

{level, reasons, image_origin, corroborated} for one accepted tuple.

### marks

```python
def marks(verdict: dict, row: Optional[dict] = None) -> tuple
```

The verdict as ordered (mark, arguments) pairs, only those that apply.

The arguments come out already rendered to strings, because the profile's
half is a table of format strings and a table cannot join a list.

`row` carries the one thing the verdict does not: the image the value was
read out of. Without it the line says a picture was involved but not which
picture, which is the difference between a warning and a lead.

### check_prose

```python
def check_prose(prose: dict, where: str) -> dict
```

`prose` back, or raise if it does not word every mark exactly once.

Checked when the serializer is imported and not at the first C of a corpus
run: a mark nobody worded is one missing piece of one comment line in one
document out of a thousand, and nothing reads that.

### render

```python
def render(verdict: dict, prose: dict, *, join: str,
           row: Optional[dict] = None) -> str
```

One line a reader of the graph can act on, in the profile's words.

The pieces and their order are the core's, every character is the
profile's. `row` is keyword-only although the sentence it replaces took it
second: a call site left over from then raises rather than quietly losing
the image name.

### document_summary

```python
def document_summary(document_id, tuples, refusals) -> dict
```

One `kind: summary` line per document: the harvest's view of its run.

A corpus of 1.082 plans cannot be read tuple by tuple, and the question a
reader actually has, "how much of this plan can I use", has no answer
in a file of 559 rows. So every harvest file ends with the distribution
over its own values.

Called a summary and not a plan line because the trace schema already
has a `plan` kind, and there it means a planned source. Two files, two
meanings, one word is how a reader ends up counting the wrong thing.

What it cannot say is in here by its absence. A contested identity is
decided by the serializer, when two tuples turn out to mint the same
value IRI, and a second reading is a later pass: neither exists yet when
this line is written, so neither is counted. `trust` takes them as
arguments for exactly that reason, and the graph side recomputes the
levels with them. The levels here are the floor: a value that is a C
already will not become an A later.

### parameter_states

```python
def parameter_states(spec, tuples: list, refusals: list, *,
                     harvested: int = 0,
                     answered: Optional[int] = None,
                     sources_of: Optional[dict] = None) -> list
```

One state per parameter of the spec, in spec order.

Every state this pipeline writes is a state of a ROW: `apply_derived`,
`merge_field`, `apply_frame` and `mark_unanswered` all loop over rows. So a
parameter that produced no row leaves no byte anywhere, and "the document
does not name its planning office" and "we never got round to asking" are
the same empty file. Measured on Kassel: `planning_organisation` came back
with 0 tuples and no state at all.

`exhausted` is the one that is a fact about the RUN and not about the
document. A parameter is exhausted when nothing of the document was
answered, or when a request that never came back held one of the
parameter's own sources, the passages its own anchors ranked
(`sources_of`, from `plan_document`). Kassel's `planning_organisation`
was once marked exhausted by a cut-off table request while its one
candidate passage had been read in full, and its answer is "the plan
does not say". Without `sources_of` for a parameter, or for a failed
request that names no source, a cut anywhere counts for every parameter.

[Back to the index](../README.md)
