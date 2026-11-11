# docpipe.editor.specs

`docpipe/editor/specs.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

specs.py: What the editor does with a profile's extraction spec.

No page and no file in here: text in, text out, so each promise the page makes
can be held to in a test without a server. The page keeps the parsed spec,
changes it and sends it back; what happens to it then is decided here.

The file is written in one fixed form (`dump`), the one `json.dumps` gives
with two spaces, in the line endings the file has. Both profile specs were
brought into that form once, so a save changes the lines an edit changed and
no others; a number the page sends back unchanged is written as the file has
it (`as_written`), because a browser does not tell `1.0` from `1`.

A spec is written only if the run's own loader takes it (`problem`,
`spec.load`). What an edit costs the next run is said with the run's own
functions and nothing else: the fingerprint of every question
(`spec.fingerprints`, in `changes`) and, where a harvest lies beside, the
documents whose stamps the edit makes stale (`runner.stale`, in `affected`).
An edit that takes something away (a field, a coordinate, an entry of a list,
a spelling) is written only after it is confirmed (`save`).

Author: Felix Vossel

## Classes

### Refused

```python
class Refused(ValueError)
```

An operation the editor does not carry out; `where` names the place.

#### Refused.\_\_init\_\_

```python
def __init__(self, where: str, message: str)
```

#### Refused.said

```python
def said(self) -> dict
```

## Functions

### newline_of

```python
def newline_of(raw: bytes) -> str
```

The line ending a file is written in.

### parse

```python
def parse(raw: bytes) -> dict
```

The spec of a file's bytes; ValueError where they are no JSON object.

### dump

```python
def dump(data: dict, newline: str = "\n") -> str
```

A spec as the editor writes it: two spaces, every character as it is
typed, one line break at the end, in the file's line endings.

### as_written

```python
def as_written(old, new)
```

*new* with every number the edit left alone as the file writes it.

A browser has one kind of number: it reads the file's `1.0` and sends
back `1`, and written like that every factor of the spec would be a
changed line. A number that equals the one at the same place of the
file is therefore written as the file has it; one the edit changed or
added is written as it was sent. Objects are matched by key, the fields
of a spec by their `uri` (a copy or a removal moves the ones after it),
any other list by position.

### problem

```python
def problem(data) -> Optional[dict]
```

{"where", "message"} of why the run would refuse this spec, None
where it loads. The loader's own words: a refusal names the field.

### changes

```python
def changes(old: dict, new: dict) -> list
```

What an edit changes for the run: one entry per question whose
fingerprint moved, [] where it moved none.

The keys are the stamp's (`spec.fingerprints`), in the order of the new
spec, a key the new spec no longer has last.

### name_of

```python
def name_of(stamp: Path) -> str
```

The document a stamp file belongs to.

### affected

```python
def affected(stamps: list, old: dict, new: dict) -> dict
```

{key: [documents]} an edit makes stale: the documents whose stamp is
current in that key under the spec on disk and not under the edited one,
asked of the run's own comparison (`runner.stale`).

### removed

```python
def removed(old: dict, new: dict) -> list
```

What the edited spec no longer has that the spec on disk has, in
words: fields, coordinates, entries of lists, names and spellings, units,
groups, and the blocks of what a document settles and of its works.

A changed text is no removal. These are the things a harvest was read
against or asked through, so taking one away is confirmed before it is
written.

### judge

```python
def judge(old_raw: bytes, data: dict, stamps: Optional[list] = None,
          snapshot: Optional[dict] = None, name: str = "extraction_spec.json"
          ) -> dict
```

Everything the page shows after "Check", for the spec *data* against
the file's bytes *old_raw*; nothing is written.

*stamps* are the stamp files of a harvest, None where the editor was
given none; *snapshot* the profile's ontology snapshot, for the notes on
definitions that differ from it.

### save

```python
def save(old_raw: bytes, data: dict, *, confirm: bool = False,
         stamps: Optional[list] = None, snapshot: Optional[dict] = None,
         name: str = "extraction_spec.json") -> tuple
```

(what the page is told, the bytes to write or None).

Bytes come back only for a spec the loader takes, and for one that takes
something away only with *confirm*. The caller writes them; this decides.

### copy_field

```python
def copy_field(data: dict, uri: str, key: str) -> dict
```

The spec with a copy of a field under a new key, right after it: all
its coordinates and lists, and no example, because an example is a
passage of a document with the values it states and a field has its
own.

### copy_coordinate

```python
def copy_coordinate(data: dict, uri: str, name: str, key: str) -> dict
```

The spec with a copy of a coordinate of a field under a new name,
right after it, in the group of its original and with what the group
says of the original.

### remove

```python
def remove(data: dict, kind: str, **named) -> dict
```

The spec without one thing: a field, a coordinate, an entry of a
list, a spelling, something a document settles, or the works block.

Nothing is written here. What follows from a removal goes with it, so
the result still loads: a coordinate no field has any more leaves its
group, and a question the works block asks of a removed field leaves the
block.

### pin

```python
def pin(data: dict, snapshot: dict) -> dict
```

{entry: the snapshot's term} for every entry of the spec's lists that
is a term of the profile's ontology snapshot.

### notes

```python
def notes(data: dict, snapshot: dict) -> list
```

Where the spec's definition of an entry is not the snapshot's, one
note per entry and list: the rule and the line of the profile check
(`ontology.definition_differences`, `ontology.definition_note`), said
for every place and not once per class, so the page can mark the row.

### terms

```python
def terms(snapshot: dict, query: str, limit: int = 50) -> dict
```

The terms of the snapshot whose identifier, label and alternative
labels together contain every word of *query*, for choosing a new
entry: {"terms", "total"}.

### kg_keys

```python
def kg_keys(profile=None) -> dict
```

{"field": [...], "axis": [...], "why": None or the reason none are
known}: the keys of a `kg` block the profile's graph writer reads, each
{"key", "kind", "help"} (`KG_KEYS` of its kg.py). A key not listed is
one the writer does not name; the page keeps it and shows it greyed.

### form

```python
def form(profile=None) -> dict
```

The form of each kind of node, {kind: [{"key", "widget", "help",
...}]}: the keys `spec.py` reads, each with the comment the code writes
at its field. A key that is not here is one the form does not know; the
page leaves it in the file as it is.

[Back to the index](../README.md)
