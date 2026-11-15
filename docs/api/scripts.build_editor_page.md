# scripts.build_editor_page

`scripts/build_editor_page.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

build_editor_page.py: The page of `docpipe edit`, built from its sources.

    python scripts/build_editor_page.py [--install] [--check]

The sources of the page are docpipe/editor/ui; what the editor serves is
docpipe/editor/web, committed so that running `docpipe edit` needs no Node.
This script is the one way from the first to the second:

1. the Node on the path is held to the versions the sources name
   (`engines` of package.json);
2. the libraries are installed from package-lock.json (`npm ci`) where
   node_modules is missing, or where --install asks for it; a node_modules
   that is a link to another checkout is used as it is;
3. `npm run build` checks the types and builds into web/;
4. web/index.html is written in LF: Vite copies the line endings of the
   checked-out ui/index.html and adds its own lines in LF, and a file of
   mixed endings is one git does not normalise;
5. the fingerprint of the sources is written into web/BUILT_FROM.

--check builds nothing: it says whether web/BUILT_FROM is the fingerprint
of the sources as they stand, and exits 1 where it is not, so a change of
the sources that was not built shows in a test and in
`scripts/change_audit.py`.

The fingerprint is a SHA-256 over every file the build reads, path by path,
each with its line endings as LF, so a checkout on Windows and one on Linux
agree.

Author: Felix Vossel

## Functions

### sources

```python
def sources(ui: Path = UI) -> dict
```

{path below ui/, with /: bytes} of every file the build reads.

### fingerprint

```python
def fingerprint(files: dict) -> str
```

The fingerprint of *files* ({path: bytes}): the same for the same
paths and contents, whatever the line endings of the checkout.

### stamped

```python
def stamped(web: Path = WEB) -> Optional[str]
```

The fingerprint web/BUILT_FROM names, None where there is none.

### current

```python
def current(ui: Path = UI, web: Path = WEB) -> bool
```

Is the built page the build of the sources as they stand?

### as_lf

```python
def as_lf(path: Path) -> None
```

*path* rewritten with LF line endings only.

### node_problem

```python
def node_problem(wanted: str, found: str) -> Optional[str]
```

Why the Node *found* (`node --version`) does not meet *wanted* (the
`engines` entry, alternatives joined by ||, each `>=X.Y.Z` or `^X.Y.Z`),
None where it does.

### is_link

```python
def is_link(path: Path) -> bool
```

Is *path* a link to a folder elsewhere (a symbolic link, or a
junction on Windows, which `Path.is_symlink` does not see)?

### build

```python
def build(install: bool = False, ui: Path = UI, web: Path = WEB) -> str
```

Build the page; its fingerprint.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
