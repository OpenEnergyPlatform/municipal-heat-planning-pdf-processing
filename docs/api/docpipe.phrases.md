# docpipe.phrases

`docpipe/phrases.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

phrases.py: The sentences a stage says to the model outside its prompts, read
from a file beside the profile's prompts.

A prompt is a file of the profile, and so is every sentence a stage writes
itself: why an answer was not taken, what was wrong with a reply that could
not be read, the heading over the user's task. They stood as tables in the
profiles' Python modules (`PHRASES`); since 2026-11-10 they are files, so
that they are edited where the prompts are (`docpipe edit`):

    profiles/<name>/prompts/<module>/phrases.json

one per module that speaks (`MODULES`). A file is one JSON object, the name
of a sentence -> its words, or a list of words where the stage takes several
(the two marks around a citation). A profile that extends another one writes
only the sentences it words differently: its file is laid over those of the
profiles it extends, entry by entry (`table`).

A file is read strictly: one object, every name once, every value a string
or a list of strings. What a sentence is filled with and which ones a stage
cannot run without is the stage's to say (`extraction.wording`,
`inference.wording`, `reading`).

Author: Felix Vossel

## Classes

### PhrasesError

```python
class PhrasesError(ValueError)
```

A sentence file a stage cannot read. It names the file.

## Functions

### path_of

```python
def path_of(profile, module: str) -> Path
```

Where *profile* writes its sentences for *module*.

### parse

```python
def parse(raw: str, where) -> dict
```

The table the text *raw* writes: name -> words, a list of words as a
tuple. *where* names the file in what is said about it.

### own

```python
def own(profile, module: str) -> Optional[dict]
```

What *profile* words itself for *module*; None where it has no file
for it, which is not an error: it takes the sentences of the profile it
extends.

### layers

```python
def layers(profile, module: str) -> list
```

[(profile, its table)] along the line of profiles, nearest first,
for those that have a file.

### table

```python
def table(profile, module: str) -> dict
```

The sentences of *module* as *profile* gets them: those of the
profiles it extends, the farthest first, and its own laid over them
entry by entry. LookupError where no profile of the line writes any.

[Back to the index](../README.md)
