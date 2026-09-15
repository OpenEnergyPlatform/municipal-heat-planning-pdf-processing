# docpipe.extraction.review

`docpipe/extraction/review.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

review.py: Reads again, under a narrower window, the values at the lowest trust
level.

The record this pass writes is read as more than it is, so what it is comes
first: the same model, over the same document, shown a window that is a strict
subset of the one the sweep already walked, the row's own passage and the
section that passage stands in. It is a self-consistency check under a narrowed
window, not an independent second reading.

What it can catch is a reading that does not hold up when the model looks
again at the two passages a row's labels, header and caption stand in. It
cannot catch the same picture misread the same way twice. An independent
second opinion would need a different model or a different window, the page
image rather than the transcription, and this pass is neither.

An agreement between the two readings never raises the trust level; it is
recorded as a mark and nothing else. A disagreement is treated as a reason,
because two readings of the same passage that do not match is a fact about the
value.

What the pass writes is one flag per reviewed row, appended to `flags`, and one
line per reviewed row in `review.csv` beside the harvest. It adds neither a new
record kind nor a new key on a tuple: the tuple branch of the published schema
stays closed, and the second reading's own content is a curation artifact
rather than evidence.

Author: Felix Vossel

## Functions

### rows_to_review

```python
def rows_to_review(tuples: list, *, force: bool = False) -> list
```

The values a second reading is worth spending a request on.

The lowest level and nothing above it: a value whose coordinates were all
read and whose quote needed no repair has nothing for a narrower window
to find. And each row once -- a row already carrying a review flag
is not asked again, because the second answer would be the second answer
to the same question and no more.

### disputed

```python
def disputed(verdict: dict) -> list
```

The coordinates this row's reasons actually name, in order, once each.

A row whose reasons name none is asked for its value alone. That is the
common case for `repaired` and `computed`, and asking such a row for all
seven of its coordinates would spend the whole review budget re-reading
what nothing is wrong with.

### review_fields

```python
def review_fields(parameter, names) -> list
```

The value slot plus the named coordinates, in spec order.

### backed

```python
def backed(target, answer, wording: Optional[str], quote: str,
           shown: list) -> bool
```

Both clauses a field answer is held to, applied to a review answer.

The quote sits verbatim in one of the two passages, AND it contains the
answer. Written here against the same two functions the harvest uses, so
the review's idea of evidence and the harvest's cannot drift apart.

### agrees

```python
def agrees(row: dict, parameter, reply: dict, slots: list,
           shown: list) -> Optional[bool]
```

True, False, or None when the second reading decided nothing.

None is the honest third answer and not a failure: an answer whose quote
is in neither passage, or whose quote does not carry it, or whose unit the
spec does not accept, says nothing about the first reading.

### review_row

```python
def review_row(row: dict, parameter, slots: list, shown: list,
               ask: Callable, captured: Optional[dict] = None) -> str
```

Read one value again. Returns the flag appended, or "".

Nothing but `flags` moves. The second reading's own value and quote are
written to the working list, never onto the row: a harvest row is what
one run read, and a pass that edits it in place destroys the thing the
disagreement is a disagreement with.

### review_file

```python
def review_file(path: Path, spec: Spec, *, ask: Callable,
                sources_for: Callable, limit: int = 0,
                working: Optional[list] = None) -> Counter
```

Review one harvest file in place. Returns what the reading came to.

The summary is recomputed rather than carried over: a disagreement is a
reason, and the summary counts reasons. A carried summary would report the
run before the review.

### run

```python
def run(harvest_dir: Path, spec: Spec, *, ask: Callable,
        sources_for: Callable, documents=None, limit: int = 0,
        prompt_sha: str = "", model: str = "") -> Counter
```

Review a whole harvest directory, or the documents named by stem.

The stamps stay, and none is created. The review changes nothing a resume
decides on -- values, coordinates and states are byte-identical, only
`flags` grows -- so dropping the stamps would make the next harvest read
the corpus again and throw the review away. Creating one where none exists
would do the opposite and skip a document that was never harvested.

What the review wrote goes into the stamps of the documents it READ and
no other: a run cut short by `limit` leaves the rest without a review
key, which is the only way a later run can tell them apart.

[Back to the index](../README.md)
