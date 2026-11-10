# docpipe.editor.graphprobe

`docpipe/editor/graphprobe.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

graphprobe.py: The graph of a local harvest as a profile's graph file has
it written, into a folder of the temp directory, for the Graph tab of
`docpipe edit` ("Write probe"). A process of its own, because a writer reads
its rules when it is imported:

    python -m docpipe.editor.graphprobe PROFILE HARVEST DB OUT

with `DOCPIPE_GRAPH_FILE` naming the graph file to write with (the page's,
unsaved) or unset for the profile's own. Writes OUT/graph.ttl and
OUT/probe.json: per document the nodes it has in the graph and what left it
with which constraint, the nodes of each class, the violations of each
constraint and how many nodes were named anew. Nothing is written but into
OUT; no model is asked.

Author: Felix Vossel

## Functions

### probe

```python
def probe(profile_name: str, harvest: Path, db: Path, out: Path) -> dict
```

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
