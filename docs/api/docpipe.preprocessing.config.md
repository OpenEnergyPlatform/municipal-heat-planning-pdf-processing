# docpipe.preprocessing.config

`docpipe/preprocessing/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py – Central configuration of the pipeline.

Author: Felix Vossel

## Functions

### caption_max_words

```python
def caption_max_words() -> int
```

### caption_like

```python
def caption_like(text) -> bool
```

Is this short enough to be a caption rather than body prose?

### title_exclude_prefixes

```python
def title_exclude_prefixes() -> tuple
```

Caption openers that must never be promoted to a section heading.

### strip_private_use

```python
def strip_private_use(text: str) -> tuple
```

(text without private-use glyphs, how many were removed).

### clean_unicode

```python
def clean_unicode(s: str) -> str
```

Remove surrogates, control chars, non-characters.

### clean_data

```python
def clean_data(obj)
```

Recursively clean unicode in nested dicts/lists/strings.

### dump_json_atomic

```python
def dump_json_atomic(data, path) -> None
```

Serialise *data* as UTF-8 JSON to *path* atomically (write temp file in
the same directory, then os.replace), so an interrupted write can never
leave a truncated file behind.

[Back to the index](../README.md)
