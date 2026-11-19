# docpipe.editor.datafiles

`docpipe/editor/datafiles.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

datafiles.py: The data files of a profile that no other tab edits.

Owner request 2026-11-19, point A2 of the review of that day ("Daten eines
Profils ohne Platz in der Seite"): the regions of the scenario profile and
their spellings, the exceptions of the KWP register. A profile names them in
its `profile.py` (`DATA_FILES`): the file in its folder, what it holds
(`about`), and whether a person keeps it (`kept`) or a fetch writes it. A
kept one also says what a key has to be (`key`, a pattern) and what an entry
has to be (`value`, a JSON schema).

Each file is one JSON object, a key -> its entry. The Sources tab lists them
and shows the entries of one; a kept one is checked and written here. A
file that changed on disk since the page read it is not overwritten, and a
written file keeps its form: the indent, the order of its keys (sorted where
the file on disk has them sorted, else as the page holds them) and its line
ends. A file a fetch writes is shown and not written: a change of it would
be gone at the next fetch.

Author: Felix Vossel

## Classes

### Refused

```python
class Refused(ValueError)
```

A data file the editor does not write, said in one sentence.

## Functions

### declared

```python
def declared(profile) -> list
```

The data files *profile* names itself, each {name, path, about,
kept, key, value}.

### find

```python
def find(profile, name: str) -> dict
```

The declared data file *name*; KeyError for one the profile does not
name.

### listing

```python
def listing(profile, read: Callable) -> list
```

What the page lists of each data file: its name, what it holds,
whether a person keeps it, whether it is there, and how many entries
it has.

### detail

```python
def detail(profile, name: str, read: Callable) -> dict
```

One data file with its entries in the order of the file, and the
sha256 of its bytes that a save names as its base.

### problems

```python
def problems(one: dict, entries) -> list
```

Why *entries* cannot be written as the data file *one*: each key that
does not match its pattern, each entry its schema does not take; [] for
entries it takes.

### kept

```python
def kept(profile, name: str) -> dict
```

The data file *name* where a person keeps it; `Refused` for one a
fetch writes.

### judge

```python
def judge(profile, name: str, entries, read: Callable) -> dict
```

Everything the page shows after "Check" for *entries*, the data file
*name* as the page holds it; nothing is written.

### current

```python
def current(profile, name: str, read: Callable) -> Optional[str]
```

The sha256 of the data file *name* on disk, None where it is not
written yet: what a save is held against (the page's `base`).

### save

```python
def save(profile, name: str, entries, read: Callable) -> tuple
```

(report, bytes to write, path) of a save of *entries* as the data
file *name*; `Refused` where they are not taken. The caller holds the
file against what the page read first (`current`).

[Back to the index](../README.md)
