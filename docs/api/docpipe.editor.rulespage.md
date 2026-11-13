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

### masked

```python
def masked(value)
```

What the page is sent of a value: an address keeps its host, port
and path but not the user and password before its host, in a list or
a map as well.

### value_shown

```python
def value_shown(rule, value)
```

What the page is sent of *rule*'s value: nothing for a key
(`secret`), else the value `masked`.

### unmasked

```python
def unmasked(value, real)
```

The value the page sends back for one it was sent `masked`: the real
one while it is still the mask, else what the page says.

### sha256

```python
def sha256(data: bytes) -> str
```

### view

```python
def view(profile, tab: str, own_raw: Optional[bytes], shown,
         own_at: Optional[dict] = None) -> dict
```

The rules of *tab* of *profile* as the page shows them. *own_at* is
{rule: [{"id", "kind"} of the steps of the saved flow that give it a
value of their own]}; a key's value is never sent.

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

### machine_rows

```python
def machine_rows(profile) -> list
```

The rules that are values of this machine, each with its value, where
it comes from and the key of the project file it is written under. A key
(`secret`) is left out: it is never shown and never written here.

### project_state

```python
def project_state(path, shown: Callable) -> dict
```

What the page is told of the project file: where it is, whether it
exists, and why a value may not be written there (None where it may).

### machine_save

```python
def machine_save(profile, values, path, shown: Callable) -> dict
```

Write {rule: value} of the machine's rules into the project file
*path* (never a rule that is no value of the machine, never a key; never
a file git would commit). What the page is told: {"saved", "reason",
"errors", "message", "file", "writes", "changed"}.

[Back to the index](../README.md)
