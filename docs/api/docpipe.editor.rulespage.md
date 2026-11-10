# docpipe.editor.rulespage

`docpipe/editor/rulespage.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

rulespage.py: The rules of a profile as `docpipe edit` shows and sets them,
each in the tab it belongs to.

The rules themselves are the run's (`docpipe.rules`): their files, their
strict loader, what each is and where the code applies it. A tab shows the
rules of its kind (spec, prompts, flow, sources, graph) in their groups, each
with its value, the value it has where the profile says nothing (the
inherited one), who says it, the dates of the owner's decisions, and the
setting that wins over it where one is set. Saving writes the profile's own
rules.json with the rules it sets differently from what it inherits, and
every rule it declares itself (that file is where those start from); a file
with no rule left is removed. Nothing a rule says makes a harvest stale.

Author: Felix Vossel

## Functions

### sha256

```python
def sha256(data: bytes) -> str
```

### view

```python
def view(profile, tab: str, own_raw: Optional[bytes], shown) -> dict
```

The rules of *tab* of *profile* as the page shows them.

### judge

```python
def judge(profile, own_raw: Optional[bytes], values, name: str) -> dict
```

What a save of *values* ({rule: value}; those not named stay as the
files say them) would do: {"ok", "errors": [{"name", "message"}],
"changed": [{"name", "from", "to"}], "file", "writes", "diff", "says",
"text"}.

### save

```python
def save(profile, own_raw: Optional[bytes], values, base: Optional[str],
         name: str) -> tuple
```

(what the page is told, the bytes to write or None, whether the file
is to be removed); bytes only for values the rules take and where the
file is as the page loaded it (*base*).

[Back to the index](../README.md)
