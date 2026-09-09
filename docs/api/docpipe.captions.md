# docpipe.captions

`docpipe/captions.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

captions.py: Defines what a caption looks like, and finds where a table's
title really sits.

Stage 2 links a caption block to a table by distance, and in a plan whose
tables carry a rounding footnote it links the footnote instead. The
sentence that names the table then stands unlinked in the section text, a
few words before the table's own placeholder. Measured over Kassel, 15 of
89 tables were captioned with the rounding footnote's own sentence rather
than their real title.

Both ends of the pipeline need the same rule about that: Stage 3, which
assembles the section text when the placeholder is written, and the read
side, which has only the finished database. A second copy of the rule is
how the section text and the stored title start disagreeing, the defect
this module exists to fix. So the rule lives above both.

Author: Felix Vossel

## Functions

### looks_like_a_caption

```python
def looks_like_a_caption(text) -> bool
```

Does this text open the way a caption opens?

### resolve_title

```python
def resolve_title(caption, content, block_id) -> str
```

The caption of one table or figure, from the section that holds it.

Stage 2 links a caption block to an item by distance, and in a plan whose
tables carry a rounding footnote it links the footnote: measured over
Kassel, 15 of 89 tables were captioned "Hinweis: Wegen der Rundung von
Zahlenwerten ..." while the sentence that names them stood unlinked in the
section text, three words before their own placeholder. The consequence
was not cosmetic. The caption is the only line of a table a model can
quote for the table's own year, so 240 of 379 tuples from the twelve
titled target tables carried a year read off another table's caption, and
88 of Kassel's 100 contested value identities were that.

The sentence is taken from between the PREVIOUS item's placeholder and
this one's, because that is where a caption sits and everything before
the previous placeholder belongs to the previous item. A stored caption
that already opens like a caption is never replaced: it was linked, and a
link beats a guess.

[Back to the index](../README.md)
