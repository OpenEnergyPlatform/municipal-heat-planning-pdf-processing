# docpipe.refinement.corrections

`docpipe/refinement/corrections.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

corrections.py: Applies a model's edit list to a section and refuses
the edits that do not hold up.

Refinement used to have the model return the whole section, which is
mostly retyping: measured over 60 ar6 documents, 28% of sections came
back byte-identical, the median similarity was 99%, and only 166 of
4887 sections were real conversions, so the stage spent the expensive
part of the call, the tokens it writes, on copying its own input.

Asking for the changes instead is cheap, and unsafe unless every one
of them is checked against the original first: a find or replace the
model half-remembered would otherwise rewrite a sentence nobody asked
it to touch, or match in two places and change the wrong one. Nothing
here is applied on trust. The text to find must be present, exactly
once, in the section as the model received it, the only text it can
honestly be quoting. Where two corrections cover the same passage,
the longer one wins and the other is reported as overlapping. An
edit may not add, drop or alter a [pN_tblM] or [pN_imgM] placeholder.
The edits together may not remove more than MAX_SHRINK of the
section.

The first two rules used to be one: each find was looked up in the
text left by its predecessors. That punished the model for following
the instruction to quote whole sentences, since two fixes to one
sentence then overlap by construction, and the second was reported as
quoting text absent from the document when the text had in fact been
edited away moments earlier by the first. Of 4828 corrections checked
this way on one book, 1144 were refused for that reason.

A rejected edit is dropped and reported, never guessed at. If the
caller finds anything in the returned report, keeping the original
section is the safe choice, since the model's picture of it evidently
did not match.

Author: Felix Vossel

## Classes

### CorrectionReport

```python
@dataclass
class CorrectionReport
```

Fields:

- `applied: int = 0`
- `rejected: list = field(default_factory=list)`: (find, reason)

#### CorrectionReport.ok

```python
@property
def ok(self) -> bool
```

## Functions

### apply_corrections

```python
def apply_corrections(original: str, edits) -> tuple
```

(text, CorrectionReport). *original* is returned unchanged for any edit that
fails its check — the caller decides what to do about a non-empty report.

[Back to the index](../README.md)
