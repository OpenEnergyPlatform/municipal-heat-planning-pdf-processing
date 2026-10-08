# docpipe.column

`docpipe/column.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

column.py: `docpipe column`, a column of one's own for a trial harvest.

    docpipe column NAME DESCRIPTION [--dir FOLDER]

A profile asks what its spec asks, and a spec comes from an ontology. A
question of one's own, put to a few documents, has no place there. This
writes the spec of one such question into a folder of its own: one parameter,
read as text, from a name and a description in plain words ("Renovation
rate", "How many percent of the buildings are renovated each year"). It
writes no example, because the spec loader wants a real one and a person has
to read it. The rest is commands that exist, each given the folder's names:

    docpipe compile examples DRAFT --profile P   propose the example
    docpipe compile apply DRAFT --out SPEC --profile P
                                                 carry the one a person
                                                 accepted into the spec
    docpipe extract DB INDEX HARVEST --spec SPEC --document ID
    docpipe export HARVEST --out TABLE

The harvest checks every value as every harvest does: its quote stands in a
shown passage, and the answer stands in the quote. It is a trial. Nothing
here adopts the column into a profile's spec and nothing here hands the
folder to the serializer. The folder keeps itself out of version control,
because its example and its harvest are passages of the corpus.

Author: Felix Vossel

## Functions

### draft

```python
def draft(name: str, description: str) -> dict
```

The one-parameter draft: the label as the person wrote it, the
identifier made from it, the description as given and no example.

### main

```python
def main(rest: Sequence[str]) -> int
```

[Back to the index](../README.md)
