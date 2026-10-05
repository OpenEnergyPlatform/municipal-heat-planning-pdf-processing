# docpipe.compile.cli

`docpipe/compile/cli.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

cli.py: `docpipe compile`, from the shapes of a graph to an extraction spec.

    docpipe compile spec --shapes shapes.ttl --ontology onto.owl --out draft.json
    docpipe compile check draft.json
    docpipe compile examples draft.json --db corpus.db --index faiss_index.bin
    docpipe compile apply draft.json --out profiles/mine/extraction_spec.json
    docpipe compile diff --shapes shapes.ttl --profile scenarios

`spec` drafts, `check` says what the draft still lacks, `examples` proposes
the missing examples from a processed corpus into a review file, `apply`
carries the accepted ones over and writes the spec once nothing is missing.
`diff` holds a spec somebody wrote by hand against the shapes and changes
nothing.

Author: Felix Vossel

## Functions

### ask_for_example

```python
def ask_for_example(client, prompt, parameter: dict, passage: str)
```

The reply to one example request as an object, or why there is none
(a text). A reply that is not the one object that was asked for is
asked again with what was wrong with it, as the harvest does; nothing
is repaired.

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
