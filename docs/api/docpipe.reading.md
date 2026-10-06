# docpipe.reading

`docpipe/reading.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reading.py: The one JSON object a stage asked a model for, or why there is none.

Refinement, the visuals stage and page transcription ask for a JSON object
inside a reply schema. What comes back is read here, and read strictly: the
reply is that object and nothing else. Nothing is stripped (code fences, think
blocks), nothing is cut out of surrounding text, no bracket is closed, and
nothing is salvaged from a reply that was cut off. Every softener of that kind
turned a defective answer into content that then stood in a file as if it had
been read. A reply that is not exactly the object is classified instead, and
the stage asks again with the cause named (`say`), splits the request when the
reply was cut off, or ends the unit as a `Hole` that carries the cause.

The causes are the harvest's (`extraction.runner._reply_fault`), in its order;
a test holds the two against each other, so neither can drift. The harvest does
not call this module: it keeps its own reader and its own sentences.

The sentences the model hears are the profile's, in the language of that
profile's prompts for these stages (`profiles/<name>/reading.py: PHRASES`).

Author: Felix Vossel

## Classes

### Hole

```python
@dataclass(frozen=True)
class Hole
```

A unit (a window, a cut request, an item, a page) that has no result,
and the reason it has none. *detail* is for the log, not for a decision.

Fields:

- `cause: str`
- `detail: str = ""`

## Functions

### speaking

```python
@contextlib.contextmanager
def speaking(profile: Profile)
```

Inside the block the sentences are *profile*'s, where a caller has a
profile that is not the ambient one. A profile that is in force still
speaks for the calls that name none outside the block.

### phrases

```python
def phrases(profile: Optional[Profile] = None) -> dict
```

The profile's sentences, complete. Read once per profile.

### say

```python
def say(phrase: str, /, **values) -> str
```

One sentence of the ambient profile, with its names filled in.

### loads_object

```python
def loads_object(text) -> Optional[dict]
```

The one JSON object a reply was asked for, or None.

Whitespace around it is no text. Anything else around it, a fence, a think
block, a second object, prose, is not this object.

### first

```python
def first(response)
```

The first choice of a response; None when it carries none.

### read

```python
def read(choice, key: Optional[str] = None, of: type = list) -> tuple
```

(object, "", "") for a reply that is exactly one JSON object; else
(None, cause, sentence) for the retry.

*key*, when given, has to be in the object as an instance of *of* (a list
for a window's sections, text for a table's markdown). The sentence is
empty for a reply that was cut off: that reply is never asked again as it
stands, the stage splits the request or gives the unit more room.

*choice* is the first choice of a response (`first`), None for a response
without one, which is an empty reply.

[Back to the index](../README.md)
