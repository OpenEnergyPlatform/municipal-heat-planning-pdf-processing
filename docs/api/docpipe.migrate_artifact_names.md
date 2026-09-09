# docpipe.migrate_artifact_names

`docpipe/migrate_artifact_names.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

migrate_artifact_names.py – Rename the per-document artefacts of an already
processed tree to the names in ``docpipe.artifacts``.

The old names lied about their place in the pipeline: ``structured_output_final``
was followed by two more stages, ``structured_output_images`` holds no images,
and ``output.json`` — the one the database reads — was the vaguest of the five.

Renaming costs nothing (the files are keyed by name only, never by path stored
elsewhere), so a processed tree does not have to be rebuilt:

    python -m docpipe.migrate_artifact_names data/pdf/processed
    python -m docpipe.migrate_artifact_names data/pdf/processed --apply

Author: Felix Vossel

## Functions

### pending

```python
def pending(root: Path) -> list[tuple[Path, Path]]
```

(old, new) for every artefact still carrying its old name.

### migrate

```python
def migrate(root: Path, apply: bool = False) -> int
```

Renames what `pending` finds. Returns the number of files renamed.

### main

```python
def main() -> None
```

[Back to the index](../README.md)
