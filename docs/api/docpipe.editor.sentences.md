# docpipe.editor.sentences

`docpipe/editor/sentences.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

sentences.py: A text cut into sentences and the diff of two such texts.

A prompt is compared by sentence, one sentence per line, so that a changed
word shows as one changed line and not as a changed paragraph. The cut only
decides what one line of the diff is; the same rule runs on both sides, so a
wrong cut shows as two lines on each and never hides a change.

Author: Felix Vossel

## Functions

### sentences

```python
def sentences(line: str) -> list
```

One line cut where a sentence ends: a stop, a space and a capital or an
opening quote or bracket. Not after a single letter ("z. B.", "d. h.") and
not after the number that opens a list item. The cut only decides what one
line of the diff is. The same rule runs on both sides, so a wrong cut shows
as two lines on each and never hides a change.

### units

```python
def units(text: str) -> list
```

The lines of a text, each cut into its sentences. A blank line is one
unit and the end of the text is one, so a change of paragraphs or of the
last newline is a change in the list.

### unified

```python
def unified(before: list, after: list, context: int = 2) -> list
```

The unified diff of two lists of units. Not `difflib.unified_diff`: its
matcher treats an item that repeats as junk once a list reaches 200
items, and blank lines repeat.

[Back to the index](../README.md)
