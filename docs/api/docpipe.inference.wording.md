# docpipe.inference.wording

`docpipe/inference/wording.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

wording.py: What the answer loop says around the prompts.

The prompts belong to the profile; so does everything the loop wraps around
them: the heading over the user's task, the labels inside the history block,
the sentence that tells the model to answer NOW. The core assembles those
pieces and does not write them: it cannot know whether the reader is holding a
German heat plan or an English scenario study.

A profile writes them in `profiles/<name>/prompts/inference/phrases.json`
(`docpipe/phrases.py`; a table in its `inference.py` until 2026-11-10). A
profile that extends another one writes only the pieces it words
differently: its file is laid over those of the profile it extends.

The words of the app's pages come the same way, from the profile's
`prompts/chat/phrases.json` (`CHAT`; its `inference.py` until 2026-11-19,
owner request A2: so that they have a place in the page and are edited
where the other sentences are). A person reads them where a model reads the
sentences: the labels of the pages and of the picker, the tag after a
document's name and the noun for one (`UI_REQUIRED`), the name of each axis
of the spec where the chat shows a value's coordinates (`axis_<axis>`), why
the graph route did not answer (`graph_note_<reason>`), and the marker and
note of a value read off a figure (`readoff_marker`, `readoff_note`). Both
tables are checked for the entries the core asks for (`REQUIRED`,
`CHAT_REQUIRED`).

Author: Felix Vossel

## Functions

### chat_profile

```python
def chat_profile(profile: Optional[Profile] = None) -> Profile
```

The profile the answer loop reads from: the one given, else the one
in force, else the built-in one.

The chat starts on any corpus, and its pages already take their words
from the built-in profile when none is named; its prompts and phrases
follow, so the first question is answered in English instead of stopping.
The fallback is here and not in `prompts.load` or `require_profile`: the
stages that write a corpus keep their stop without a profile, because a
forgotten flag there would start a real run on the wrong prompts. Said
once per process, since the loop asks for a profile on every hit.

### phrases

```python
def phrases(profile: Optional[Profile] = None) -> dict
```

The profile's labels and guides, complete.

Cached: citation_label asks once per retrieval hit, and the completeness
check has nothing new to say the second time.

### chat_words

```python
def chat_words(profile: Optional[Profile] = None) -> dict
```

Every word of the chat a person reads (`CHAT`), complete: the
profile's file laid over those of the profiles it extends. Without a
profile they are those of the profile the package brings itself: the app
starts on any corpus, and what it shows then is in English. A name of
none of its families is refused: no page would show it.

### ui

```python
def ui(profile: Optional[Profile] = None) -> dict
```

The words of the app's pages and of the picker, complete
(`chat_words`, those of `UI_REQUIRED`).

### axis_names

```python
def axis_names(profile: Optional[Profile] = None) -> dict
```

{axis: its name in the profile's words} where the chat shows a
value's coordinates; an axis the profile does not name is shown by its
key.

### graph_notes

```python
def graph_notes(profile: Optional[Profile] = None) -> Optional[dict]
```

{reason of kg_route.REASONS: why the graph route did not answer, in
the profile's words}; None where the profile words none.

### readoff

```python
def readoff(profile: Optional[Profile] = None) -> tuple
```

(marker, note) for values the model read off a figure.

The note is appended unless the answer already says so itself, and the
marker is how that is recognised — both in the answer's own language.

[Back to the index](../README.md)
