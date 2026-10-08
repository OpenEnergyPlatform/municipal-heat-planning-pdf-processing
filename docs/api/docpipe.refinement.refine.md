# docpipe.refinement.refine

`docpipe/refinement/refine.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

refine.py: Runs Stage 4, the LLM-based refinement of Stage 3
sections.

The LLM is asked, per window of sections, to clean extraction
artefacts and titles, drop directory sections, convert bibliographies
to BibTeX, and merge or split sections; each returned action is
applied by refine_sections. A section longer than the split threshold
is cut before windowing (see split.py), since a window has to echo
every section it carries, and an oversized section could never be
echoed.

Windows are dispatched in parallel, up to LLM_NUM_PARALLEL requests
at once, then assembled in the original order, since merging and
splitting are positional. Every request sends its reply schema as the
grammar, and a reply is read as exactly one JSON object (see
docpipe/reading.py): nothing is stripped, cut out or closed. A reply
that is not that object is asked again with its cause named, up to
MAX_RETRIES times, except on a 4xx response, which is not retried
because the server has refused the request itself. A reply that was
cut off at its token limit is never asked again as it stands: the
window is asked in halves by sections, and a lone section gets more
room once (twice what it asked, or as much as the window the server
reported leaves, whichever is smaller; a window that leaves none makes
it a hole at once). What is still unread is a hole with its cause: the
window keeps its original, unrefined text and is recorded in the
refinement report written next to the output, and the next plain run
asks exactly those windows again.

Page provenance travels with the rewritten text: an unchanged window
reattaches its segments one to one, and a window that split, merged
or dropped sections is redistributed by which output section's
tokens a segment's text is found in, or by which output claims a
table's or figure's block id. A "remove" action is refused when the
section still carries a table or figure, since those are Stage 2
artefacts with their own transcriptions and not the model's to
discard; a section made of nothing but reference markers can
otherwise look empty to a reader of the text alone.

Author: Felix Vossel

## Classes

### Halved

```python
class Halved
```

A window that was asked in halves, of which at least one part is a Hole.

*parts* are (offset of the part in the window, the part's sections, its
reply: a list of sections or a Hole). A window whose parts were all read
is not one of these: its replies are laid end to end into one list, and
the window is assembled like one that was never cut.

#### Halved.\_\_init\_\_

```python
def __init__(self, parts: list)
```

### Unfinished

```python
class Unfinished(Exception)
```

Windows the model server did not serve, so the document is not refined.

*sections* are the sections the windows were cut from (after the split),
*done* the usable replies by window index, *lost* the indices that were
not served. A later run over the same sections asks only for the rest.
Without *sections* it was the cut of an oversized section that was not
served, and there is nothing to keep: the next run starts with the cut.

#### Unfinished.\_\_init\_\_

```python
def __init__(self, sections: list, done: dict, lost: list, total: int,
             mechanical: Optional[list] = None)
```

## Functions

### reply_shapes

```python
def reply_shapes() -> dict
```

{name: schema} of what this stage sends as the grammar of its requests,
for the preflight to put to the server before the first document.

The window schema is built per window from the keys it carries, so the
probe's is built from a section of the shape stage 3 writes: text, a table
and a figure, one of them with a caption the model may leave null.

### refine_sections

```python
def refine_sections(sections: list[dict],
                    report: Optional[dict] = None,
                    done: Optional[dict] = None,
                    left: Optional[dict] = None) -> list[dict]
```

Processes all sections through the LLM in windows of WINDOW_SIZE, dispatched
in parallel but assembled in order (merge/split semantics are positional).

Mutates *sections* in place (source_text is stripped); returns the refined
list. When *report* is given, it is filled with what this pass could not
refine: the windows (or the parts of a window) that ended as a hole, each
with its cause, and the sections whose cut the model did not place. See
run_refine, which writes it next to the output. A report that already
holds `mechanical_cuts` (from the pass that cut the sections, on a resume)
keeps them.

*done* resumes an unfinished pass: {window index: reply} over *sections*
as that pass cut them, so they are not cut again and only the other
windows are asked. Raises Unfinished when the server did not serve a
window; nothing is assembled then, because a window that was never
answered would go into the output as text that needed no change.

*left*, when given, is filled with what the next pass over the same input
needs to ask only the windows that ended as a hole: the sections as this
pass cut them, and the reply of every window that was read.

### run_refine

```python
def run_refine(output_dir: Path, data: Optional[dict] = None,
               force: bool = False,
               holes: Optional[list] = None) -> Optional[dict]
```

Refines the Stage-3 sections and writes sections_refined.json under
*output_dir*. An existing final output is returned from cache without
re-running the LLM; *force* ignores it and runs the LLM again.

*data* is the Stage-3 result dict; when None, sections.json is read
from *output_dir* instead.

Forcing must not delete the old output first. dump_json_atomic replaces it
in one step at the end, so a run killed part-way — a batch timeout, a job
hitting its wall clock — leaves the previous refinement rather than nothing
at all. A document with no refined output is left out by the merge, and
would vanish from the database.

A pass the server did not serve every window of writes no refined output.
What it did get is kept beside it (REFINEMENT_PARTIAL_JSON), and the next
run, forced or not, asks only for the windows that are missing.

*holes*, when given, gets one entry (`_hole_entry`) for a document this
pass wrote with windows that kept their original text, or sections cut
mechanically: what a caller counts to say what a run left unread.

A pass that was served every window and could not read some of them (a
hole, with its cause) writes the refined output with those windows in
their original text, names them in the report, and keeps the other
windows' replies in REFINEMENT_PARTIAL_JSON as well: the next plain run
asks exactly the windows the report lists, and the file goes when none is
left.

Returns:
    The refined output dict, or None on failure.

[Back to the index](../README.md)
