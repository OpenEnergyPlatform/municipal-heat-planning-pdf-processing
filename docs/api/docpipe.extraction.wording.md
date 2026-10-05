# docpipe.extraction.wording

`docpipe/extraction/wording.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

wording.py: What the extraction stage says to the model outside its prompts.

The prompts belong to the profile, and so does every sentence the stage
writes itself: why an answer was not taken, what was wrong with a reply
that could not be read, what stands beside an image, how the closed list
names a meaning. These go back to the model in the next request, so they
are in the language of the prompts, and the core does not know which that
is. They stood in the core as German sentences, which nobody saw until a
profile wrote its prompts in another language.

A profile contributes them in `profiles/<name>/extraction.py: PHRASES`. A
profile that extends another one writes only the ones it words differently.
A phrase is a template for `str.format`: the names in braces are filled by
the stage, `!r` shows a value the way the model wrote it, and a brace that
is meant as a brace is doubled.

Author: Felix Vossel

## Functions

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

[Back to the index](../README.md)
