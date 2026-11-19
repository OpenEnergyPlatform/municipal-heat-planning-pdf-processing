# docpipe.newprofile

`docpipe/newprofile.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

newprofile.py: A new profile, as `docpipe init` and the editor make it
(owner request 2026-11-14, wish 5: "Es wäre cool, wenn es auch die Option
gäbe über den Editor ein Profil anzulegen").

A new profile lies in the profile folder of the project (`profiles/<name>`)
beside a folder for its PDFs (`data/<name>/pdf`). It starts empty, extending
the profile docpipe brings itself, or as a copy of a profile the installation
finds: then it extends that one and has a copy of each of its files a page
edits (the spec, the flow, the graph, the chat, the rules, the sources), so
editing them leaves the other profile as it was; the flow's copy leaves out
the changes the profile makes in the drawing it inherits, which the copy
inherits with them. Where it is given the
addresses of an ontology, shapes or a graph, they are its sources; a draft of
its spec is made from shapes with the same code `docpipe init --shapes` uses.
Everything is read before anything is written: a name taken, a file that
cannot be used or a source that cannot be fetched leaves nothing behind.

Author: Felix Vossel

## Classes

### ProfileError

```python
class ProfileError(ValueError)
```

A profile that cannot be made. It says why; nothing was written.

## Functions

### check_name

```python
def check_name(name: str) -> None
```

Refuses a name that cannot name a profile or names one there is.

### draft_from_shapes

```python
def draft_from_shapes(given)
```

(the draft of a spec, the shapes file it is from). *given* is a file
of the user's, or True for the one the package brings.

### addressed_sources

```python
def addressed_sources(addresses: Optional[dict]) -> dict
```

{name: source} of the addresses given (`ADDRESSED`), each the file at
its address (the kind `url` of `sources.KEYS`).

### write_profile

```python
def write_profile(home: Path, name: str, *, copy_of: Optional[str] = None,
                  draft: Optional[dict] = None,
                  sources: Optional[dict] = None) -> list
```

Makes profile *name* in the project at *home* and the folder of its
PDFs; returns the files written. *copy_of*: the profile it is a copy
of, else it extends the one docpipe brings; *draft*: the draft of its
spec; *sources*: sources laid over those it has.

### write_project

```python
def write_project(home: Path, name: str) -> list
```

The project's file, and an example of its .env and a .gitignore
where there are none yet; returns the files written.

### missing

```python
def missing(draft: Optional[dict]) -> list
```

What still stands between a draft and a spec, one line each (a real
example per field before the strict check takes it, and whatever else
`compile.draft.todo` names); [] without a draft.

[Back to the index](../README.md)
