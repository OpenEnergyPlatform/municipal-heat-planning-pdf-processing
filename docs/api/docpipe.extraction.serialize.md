# docpipe.extraction.serialize

`docpipe/extraction/serialize.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

serialize.py: Turns a document harvest into the profile's target graph.

The module walks the JSONL harvest directory and keeps only the rows
a run accepted (kind is "tuple"), grouped by document name (collect).
run() hands each document's rows to a serializer, and the runner's
--serialize flag chooses it: profiles/\<name>/kg.py exposes
make_serializer(db_path) where the profile writes its graph itself,
and a profile without one gets the generic writer of graph.py, which
writes what the `graph` block of the spec describes. What a profile's
own serializer emits (Turtle with project IRI rules, LinkML YAML, or
another format) is the profile's decision; the module guarantees only
the walk, the per-document grouping, and that a refusal row never
reaches the serializer.

A serializer may leave, per document, which values it wrote
(`claims`). run() then hands them to the provenance writer it was
given (provenance.py), and the provenance of the written values goes
to a file of its own beside the graph.

What people decided about the rows of the harvest (gold.py) is read
here, after the harvest is, and kept beside the value each decision
concerns: the provenance writer records it with the value's provenance,
and a serializer that declares a `decisions` dict gets it as
{document: {tuple name: [decision]}} to write itself. No row changes and
none is left out because of it. A decision about a row the harvest does
not hold is counted and named in the log.

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

### count_decisions

```python
def count_decisions(decided: dict) -> int
```

How many field decisions {document: {tuple name: [decision]}} holds.

### read_decisions

```python
def read_decisions(held, harvest: dict, source=None) -> dict
```

What *held* decided about the rows of *harvest*, counted in the log.

{document: {tuple name: [decision]}}. A decision about a row the harvest
does not hold is named, up to `NAMED` of them, and applied to nothing.

### run

```python
def run(jsonl_dir: Path, out_path: Path,
        serializer: Callable[[str, list], Optional[str]],
        provenance=None, gold=None, gold_source=None) -> dict
```

Serialize every document's harvest; returns {name: tuple count}.

A serializer returning None skips its document (nothing to say is a
normal outcome, e.g. a plan without a single accepted tuple).

*provenance* is a `provenance.Writer`. A serializer that leaves what it
wrote per document in its `claims` gets the provenance of those values
written beside the graph; one that leaves nothing gets none.

*gold* is the decisions of people (`gold.Gold`); *gold_source* says
where they were read from, for the log. They are looked up after the
harvest is collected and not in `collect`, which the review page and
`evaluate` read their rows from: counting a decision against a harvest
that already held it would hide the row it was made on.

### validate

```python
def validate(out_path: Path, shapes: list, top: int = 12) -> dict
```

Hold the written graph against the profile's SHACL shapes.

A report, not a gate: the full text goes next to the graph as
`<name>.shacl.txt` and the most frequent kinds of violation go to the
log. The graph stays written either way. The harvest is the durable
artifact and a graph the shapes reject is still the one to look at.

[Back to the index](../README.md)
