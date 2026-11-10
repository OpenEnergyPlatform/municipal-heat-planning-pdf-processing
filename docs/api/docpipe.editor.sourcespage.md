# docpipe.editor.sourcespage

`docpipe/editor/sourcespage.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

sourcespage.py: Where a profile's ontology, shapes and graph come from, as
`docpipe edit` shows, fetches and applies them, and what they say differently
from the spec.

The sources themselves are the run's (`docpipe.sources`, `docpipe.upstream`):
the profile's sources.json, the fetch of each kind, the lock that names what
the last refresh took. This module turns them into what the page shows and
decides what each button does (owner, 2026-11-10: "einfach die URLs angeben
für Ontologie und KG und dann eben die auch die Felder auswählen und
zusammenlegen"):

- `view`: every source with its address, the kind of version it stands at
  (a release, the head of a branch, a live query) and the version the lock
  holds; a token only as set or not set, never its value; the lists and
  which coordinate answers from which.
- `judge` and `save`: an edited sources.json, read strictly by the run's own
  parser before it is written.
- `fetch`: the profile's own refresh into a folder of the temp directory,
  never into the profile or the cache: which source moved, what that does
  to each list (entries added, gone, renamed, redefined) and to the other
  files the refresh writes.
- `apply`: a fetch made the profile's: the files the refresh writes into the
  profile's folder, the fetched files into the cache and the lock beside
  them, its paths moved from the temp folder to the cache. The spec never.
- `differences`: per field, what the shapes and the ontology say otherwise
  than the spec (`draft.differences`, held to the shapes as the profile names
  its properties; `ontology.definition_differences`), each row the page can
  act on with an id.
- `take`: the chosen rows applied to the spec, for the Spec tab to check and
  save with what it costs: a new entry of a list with the ontology's name
  and definition, a definition replaced by the ontology's, a property no
  field asks as a new field (a draft: it needs an example before the strict
  check takes it), or merged into an existing field as one more property it
  writes (`also`).

Author: Felix Vossel

## Functions

### sha256

```python
def sha256(data: bytes) -> str
```

### fetch_root

```python
def fetch_root() -> Path
```

### lock_name

```python
def lock_name(profile) -> str
```

The name the profile's refresh writes its lock under.

### view

```python
def view(profile, own_raw: Optional[bytes], shown,
         cache: Path = upstream.CACHE, snapshot: Optional[dict] = None,
         spec_raw: Optional[dict] = None) -> dict
```

The sources of *profile* as the page shows them.

### judge

```python
def judge(profile, own_raw: Optional[bytes], data, name: str) -> dict
```

What a save of *data* ({"sources", "lists", "axis_lists"}) would do:
{"ok", "errors", "file", "writes", "diff", "says", "text"}.

### save

```python
def save(profile, own_raw: Optional[bytes], data, base: Optional[str],
         name: str) -> tuple
```

(what the page is told, the bytes to write or None).

### shape_files

```python
def shape_files(profile, cache: Path = upstream.CACHE) -> list
```

The shapes the profile's spec is held against, as the lock in *cache*
names them.

### list_changes

```python
def list_changes(before: Optional[dict], after: Optional[dict]) -> list
```

Per list of the snapshot: the entries a fetch adds, takes away,
renames or defines anew, each with its name.

### fetch

```python
def fetch(profile, root: Optional[Path] = None,
          cache: Path = upstream.CACHE, spec_raw: Optional[dict] = None,
          now: Optional[datetime.datetime] = None) -> dict
```

The profile's refresh into a folder of *root* (the temp directory's
where not given): nothing is written into the profile or the cache.
Returns what moved, with the id `apply` takes.

### compare

```python
def compare(profile, where: Path, cache: Path = upstream.CACHE,
            spec_raw: Optional[dict] = None) -> dict
```

What the fetch in *where* would change against what the profile and
the cache hold now.

### fetched

```python
def fetched(root: Path, fetch_id: str) -> Path
```

### apply

```python
def apply(profile, where: Path, write_profile, write_cache,
          cache: Path = upstream.CACHE) -> dict
```

The fetch in *where* made the profile's: every file its refresh
writes into the profile's folder (through *write_profile*, the editor's
guard), every fetched file into the cache and the lock with its paths in
the cache (through *write_cache*). The spec is no file a refresh writes,
so it is never touched.

### differences

```python
def differences(profile, spec_raw: Optional[dict], snapshot: Optional[dict],
                files: list) -> dict
```

{"fields": [{"field", "rows"}], "unasked": [rows], "skipped": why}:
what the shapes in *files* and the ontology in *snapshot* say otherwise
than *spec_raw*, per field.

### take

```python
def take(spec_raw: dict, chosen: list, snapshot: Optional[dict],
         profile=None, files: Optional[list] = None) -> dict
```

{"data": the spec with the chosen rows applied, "done": [...],
"refused": [{"id", "why"}]}. *chosen* is [{"id", "action", "into"?}];
`into` names the field a property is merged into.

### merge_targets

```python
def merge_targets(spec_raw: Optional[dict]) -> list
```

[{"into", "label"}]: every predicate of every field a property of the
shapes can be merged into (`draft.predicate_places`): the value itself,
its unit, an edge of one of its axes. *into* is "field|key.key...", the
place `_merge` writes `also` to.

[Back to the index](../README.md)
