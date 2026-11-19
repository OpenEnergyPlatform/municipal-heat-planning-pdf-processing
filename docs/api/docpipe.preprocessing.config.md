# docpipe.preprocessing.config

`docpipe/preprocessing/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py – Central configuration of the pipeline.

Author: Felix Vossel

## Functions

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
def clean_unicode(s: str, nfkc=None) -> str
```

Remove surrogates, control chars, non-characters. The text is first
brought to the compatible normal form unless the rule
`normalize_unicode_nfkc` is off; *nfkc* says it for a caller that read
the rule once for many strings.

### clean_data

```python
def clean_data(obj, nfkc=None)
```

Recursively clean unicode in nested dicts/lists/strings. The rule
`normalize_unicode_nfkc` is read once for the whole structure.

### dump_json_atomic

```python
def dump_json_atomic(data, path) -> None
```

Serialise *data* as UTF-8 JSON to *path* atomically (write temp file in
the same directory, then os.replace), so an interrupted write can never
leave a truncated file behind.

[Back to the index](../README.md)
