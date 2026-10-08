# docpipe.artifacts

`docpipe/artifacts.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

artifacts.py: Names the per-document result files under `<doc>/results/`,
in the order the pipeline writes them, and finds the document directories
that hold them.

One definition serves all five pipeline modules: a filename spelled out in
four separate config.py files drifts, and the module that reads a file is
rarely the one that wrote it. The same goes for the listing: preprocessing
writes a nested folder of PDFs to a nested folder of document directories,
and a stage that lists only the first level loses every document below it,
so every stage lists through `document_dirs`.

Author: Felix Vossel

## Classes

### DuplicateDocumentName

```python
class DuplicateDocumentName(ValueError)
```

Two document directories of one name under different subfolders.

## Functions

### document_dirs

```python
def document_dirs(root, *markers: str, distinct: bool = True) -> list
```

The document directories under *root*, at any depth, in path order.

A document directory is one that holds any of *markers* (a name under it,
such as SECTIONS_JSON, which says the stage this listing is for can read
it). Nothing below a document directory is searched. A directory that
holds none of them is searched, because a subfolder of the source folder
is a directory like that, and so is a document the stage cannot read yet.
With every document directly under *root* this is what iterating *root*
and keeping the directories that hold a marker gave, in the same order.

The stages know a document by the name of its directory (the database
row is `<name>.pdf`), so two of one name under different subfolders are
one document too many: that is refused with both places named, unless
*distinct* is off for a caller that only reads the directories.

### refuse_same_names

```python
def refuse_same_names(directories, root) -> None
```

Raise DuplicateDocumentName if two of *directories* (under *root*)
have one name, with the places of each such name.

[Back to the index](../README.md)
