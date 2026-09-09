# docpipe.extraction.serialize

`docpipe/extraction/serialize.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

serialize.py: Turns a document harvest into the profile's target graph.

The module walks the JSONL harvest directory and keeps only the rows
a run accepted (kind is "tuple"), grouped by document name (collect).
run() hands each document's rows to a serializer the profile
supplies: profiles/\<name>/kg.py exposes make_serializer(db_path), and
the runner's --serialize flag calls it. What the serializer emits
(Turtle with project IRI rules, LinkML YAML, or another format) is
the profile's own decision; the module guarantees only the walk, the
per-document grouping, and that a refusal row never reaches the
serializer.

run() concatenates the output of every document whose serializer
returned something and writes it to the output path. It raises
ValueError and leaves that path untouched when no document produced
anything. The check runs unconditionally at the end of a GPU job, so
a run that ended in a counted exception still yields a graph; without
the check, an empty or unreadable harvest directory would overwrite a
valid graph from an earlier run with nothing.

Author: Felix Vossel

## Functions

### collect

```python
def collect(jsonl_dir: Path) -> dict
```

{document name: [accepted tuple rows]} from a harvest directory.

### run

```python
def run(jsonl_dir: Path, out_path: Path,
        serializer: Callable[[str, list], Optional[str]]) -> dict
```

Serialize every document's harvest; returns {name: tuple count}.

A serializer returning None skips its document (nothing to say is a
normal outcome, e.g. a plan without a single accepted tuple).

[Back to the index](../README.md)
