# docpipe.inference.wording

`docpipe/inference/wording.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

wording.py: What the answer loop says around the prompts.

The prompts belong to the profile; so does everything the loop wraps around
them: the heading over the user's task, the labels inside the history block,
the sentence that tells the model to answer NOW. The core assembles those
pieces and does not write them: it cannot know whether the reader is holding a
German heat plan or an English scenario study.

A profile contributes them in `profiles/<name>/inference.py`. A profile that
extends another one writes only the pieces it words differently: its PHRASES
are laid over those of the profile it extends.

The words of the app's pages come the same way and from the same file: the
profile's `UI` table, which a person reads where a model reads PHRASES. Both
are checked for the entries the core asks for (`REQUIRED`, `UI_REQUIRED`).

Author: Felix Vossel

## Functions

### phrases

```python
def phrases(profile: Optional[Profile] = None) -> dict
```

The profile's labels and guides, complete.

Cached: citation_label asks once per retrieval hit, and the completeness
check has nothing new to say the second time.

### ui

```python
def ui(profile: Optional[Profile] = None) -> dict
```

The words of the app's pages, complete. Without a profile they are
those of the profile the package brings itself: the app starts on any
corpus, and what it shows then is in English.

### readoff

```python
def readoff(profile: Optional[Profile] = None) -> tuple
```

(marker, note) for values the model read off a figure.

The note is appended unless the answer already says so itself, and the
marker is how that is recognised — both in the answer's own language.

[Back to the index](../README.md)
