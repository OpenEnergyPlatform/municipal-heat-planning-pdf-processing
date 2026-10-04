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
splitting are positional. A request is retried up to MAX_RETRIES
times, except on a 4xx response, which is not retried because the
server has refused the request itself. A window that never returns a
usable reply keeps its original, unrefined text, and is recorded in
the refinement report written next to the output.

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
def __init__(self, sections: list, done: dict, lost: list, total: int)
```

## Functions

### refine_sections

```python
def refine_sections(sections: list[dict],
                    report: Optional[dict] = None,
                    done: Optional[dict] = None) -> list[dict]
```

Processes all sections through the LLM in windows of WINDOW_SIZE, dispatched
in parallel but assembled in order (merge/split semantics are positional).

Mutates *sections* in place (source_text is stripped); returns the refined
list. When *report* is given, it is filled with what this pass could not
refine — see refine_document, which writes it next to the output.

*done* resumes an unfinished pass: {window index: reply} over *sections*
as that pass cut them, so they are not cut again and only the other
windows are asked. Raises Unfinished when the server did not serve a
window; nothing is assembled then, because a window that was never
answered would go into the output as text that needed no change.

### run_refine

```python
def run_refine(output_dir: Path, data: Optional[dict] = None,
               force: bool = False) -> Optional[dict]
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

Returns:
    The refined output dict, or None on failure.

[Back to the index](../README.md)
