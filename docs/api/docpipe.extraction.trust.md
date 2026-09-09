# docpipe.extraction.trust

`docpipe/extraction/trust.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

trust.py: Grades every harvested value by how far the run can stand
behind it.

Every accepted tuple is verified: its number is in its quote, its
quote is in a shown source, and every coordinate names the passage it
was read in. That is a floor, not a grade. Two values that both clear
it can still differ by a lot:

  one has every coordinate read off its own table, in the document's
  own text
  one has its year read off the caption of a different table three
  pages away

The second case is the failure this module addresses, and before this
module existed nothing downstream could tell the two apart. A reader
of the graph saw two numbers with no way to compare their reliability.

The module computes a deterministic level per value, from what the
harvest already records: no model call, no second opinion, no
threshold anybody tuned.

  A  the document's own text states it, every coordinate read, every
     passage local
  B  the same, but read out of a table transcription or a figure
     description (a model's reading of a picture), or out of a
     document whose pages had no text layer and were transcribed page
     by page
  C  something is off: a passage that belongs to another row, a
     coordinate the run gave up on, a repaired quote, a computed
     number, a contested identity

The reasons form a closed list, because a reason nobody can enumerate
is a reason nobody can count. What makes a value a C is what a curator
should examine.

A value can be read a second time (`review.py`), and what that reading
came to is recorded here as a mark. It never raises a level: the
second reading uses the same model over a narrower window, so an
agreement states that the reading is self-consistent, not that the
passage it cites belongs to the row.

Measured on Kassel's 559 tuples, which is why the levels are cut at
this point and not elsewhere: 527 of 559 tuples came out of a table or
figure image, so image origin alone separates nothing and is not by
itself a warning. What did separate, on that run: 370 of 455 year
readings cited a passage outside the row's own table and its section,
as did 87 percent of the area readings, 47 percent of the scenarios,
49 percent of the sectors, and 13 percent of the carriers, the one
coordinate the row itself carries directly.

That run had no evidence rule at all, so reading those numbers
requires care. The spec now sets the rule per axis (own, local or
any), and the harvest enforces it: a coordinate that breaks its own
rule comes out `unbacked`, never `read`. On a harvest written under
the rule, a passage outside the row's own source is a finding only
for an axis whose rule is `own`; for the others it is the rule
working as written. Judging all seven axes by the strictest rule
would report every legal reading as a doubt, a signal that fires
across the whole corpus and separates nothing, the same mistake image
origin was kept out of the reasons for.

Hence `own`: the set of axes a reader may hold to the row's own
source. It is a property of the spec, so the caller passes it in;
without it, every read coordinate is judged, matching the treatment
of a harvest written before the rule existed.

Author: Felix Vossel

## Functions

### reasons

```python
def reasons(row: dict, *, conflict: bool = False, transcribed: bool = False,
            own: Optional[frozenset] = None) -> list
```

Every reason this value is not an A, in a fixed order.

An empty list means the harvest sees nothing wrong with the value.

`own` is (parameter uri, axis name) for the axes whose evidence
rule is `own` (`spec.own_evidence`). Only those axes are held to
the row's own source; an axis the spec lets read a page away was
already judged where the pages were, and reporting it here would
mark a legal reading as a doubt. A value of None judges every
axis, matching the treatment of a harvest written before the rule
existed.

### trust

```python
def trust(row: dict, *, conflict: bool = False, transcribed: bool = False,
          corroborated: bool = False, own: Optional[frozenset] = None) -> dict
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
def document_summary(document_id, tuples, refusals,
                     *, own: Optional[frozenset] = None) -> dict
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

`own` is passed straight to `trust`; see there for why an axis the spec
lets read a page away is not held to the row's own source.

### parameter_states

```python
def parameter_states(spec, tuples: list, refusals: list, *,
                     harvested: int = 0,
                     answered: Optional[int] = None) -> list
```

One state per parameter of the spec, in spec order.

Every state this pipeline writes is a state of a ROW: `apply_derived`,
`merge_field`, `apply_frame` and `mark_unanswered` all loop over rows. So a
parameter that produced no row leaves no byte anywhere, and "the document
does not name its planning office" and "we never got round to asking" are
the same empty file. Measured on Kassel: `planning_organisation` came back
with 0 tuples and no state at all.

`exhausted` is the one that is a fact about the RUN and not about the
document, and it is document-wide rather than per parameter: under the
document-level plan there is no per-parameter run signal to read, the
report keys its rounds by the literal string "document". So a truncated
run marks every unanswered parameter exhausted together, which is the
honest reading of "we stopped before the end".

[Back to the index](../README.md)
