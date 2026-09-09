# docpipe.inference.wording

`docpipe/inference/wording.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

wording.py – What the answer loop says around the prompts.

The prompts belong to the profile; so does everything the loop wraps around
them — the heading over the user's task, the labels inside the history block,
the sentence that tells the model to answer NOW. The core assembles those
pieces and does not write them: it cannot know whether the reader is holding a
German heat plan or an English scenario study.

A profile contributes them in `profiles/<name>/inference.py`.

Author: Felix Vossel

## Functions

### phrases

```python
def phrases(profile: Optional[Profile] = None) -> dict
```

The profile's labels and guides, complete.

Cached: citation_label asks once per retrieval hit, and the completeness
check has nothing new to say the second time.

### non_anchor

```python
def non_anchor(profile: Optional[Profile] = None)
```

Pattern matching a search anchor that turned into a refusal.

Which words those are is a property of the language the model answers in,
so the core cannot hold the list — with the wrong one the check silently
never fires and every refusal is used as a retrieval probe.

### readoff

```python
def readoff(profile: Optional[Profile] = None) -> tuple
```

(marker, note) for values the model read off a figure.

The note is appended unless the answer already says so itself, and the
marker is how that is recognised — both in the answer's own language.

[Back to the index](../README.md)
