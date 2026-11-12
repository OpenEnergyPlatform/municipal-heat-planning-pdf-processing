# docpipe.extraction.passflow

`docpipe/extraction/passflow.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

passflow.py: The follow-up passes as flows of their own (owner decision
2026-11-11).

A follow-up pass reads a harvest that is already written: it reads the
questions that moved again, the dimensions that stayed open, the parameters
the spec gained, the lists a grown vocabulary moves, the quotes, the rows
nobody can stand behind. Each is a file `flows/<name>.json` of boxes, shipped
with the default profile and overridden by a profile's own file of the same
name, as the main flow is (`flow.line`). The call switch of a pass only
chooses its flow, and `--flow NAME` starts any flow by name.

A flow of a pass is a list of boxes (`blocks.LIBRARY`, those that say
`flow == "pass"`) and, around the boxes that read one dimension, frames "each
dimension". Its boxes run in the order the file gives. What a box leaves for
the next is held for one harvest file or document (`passboxes.Doc`), so a
box says in the library which boxes stand before it. A box that starts the
chain (the stored harvest, the classification of a new parameter, the
unread passages, the main flow) takes the documents; the boxes after it run
for each document, in order; a box that runs once (the working list, the
clearing of the stamps) runs after them. A box that is off does not run, and
the values a box or frame sets for itself hold inside it and nowhere else
(`rules.STEP`).

What the file may say is checked before a run starts (`problems`), each
reason a sentence at its box.

Author: Felix Vossel

## Classes

### PassError

```python
class PassError(RuntimeError)
```

A pass that cannot start or go on; the run says why and stops.

### Run

```python
class Run
```

What a pass runs with: where the harvest is, the spec, the stamp
this run would write, the means to read a document again, and what the
boxes count between them. The runner fills it; a box takes what it
needs.

#### Run.\_\_init\_\_

```python
def __init__(self, **given)
```

## Functions

### line

```python
def line(profile, name: str) -> list
```

[(profile name, path)] of the files the flow *name* can stand in,
nearest first: the profile's own `flows/<name>.json`, then those of the
profiles it extends, the default profile's last.

### path_of

```python
def path_of(profile, name: str) -> Path
```

Where *profile* writes its own file of the flow *name*.

### names

```python
def names(profile=None) -> list
```

The flows a run of *profile* can start: the main flow, and each
follow-up pass of the default profile or the profile's line.

### parse

```python
def parse(raw: str, where) -> list
```

The drawing of the text *raw*, read strictly: one JSON object with
"flow", the list of boxes. *where* names the file in what is said.

### dump

```python
def dump(tree: list) -> str
```

A pass flow's text in the one form it is written in.

### load

```python
def load(name: str, profile=None) -> list
```

The drawing of the pass *name* as the nearest file of *profile*'s
line says it, refused with every reason where the run could not do
it. LookupError where no profile of the line writes the flow.

### tree_of

```python
def tree_of(name: str, profile=None) -> list
```

The same, for a caller that has no use for the difference.

### problems

```python
def problems(tree, known: Optional[dict] = None) -> list
```

Everything the run could not do with the drawing *tree* of a pass:
[{"id": the box or frame or None, "message"}], [] where it can run.

### shared_trace

```python
def shared_trace(first: str, second: str, profile=None) -> Optional[str]
```

The reason the flows *first* and *second* never run together, or
None: they write their record into one folder, and the record of a
document is written anew by every pass that writes it.

### homes

```python
def homes(profile=None) -> dict
```

{kind of request: the first box of a pass flow that asks it}, the
boxes of the flows that a profile's line writes and the run can do. A
flow that cannot be read is left out and said.

### setting

```python
def setting(node: dict, key: str)
```

What a box of a pass says for the setting *key*: its own value or
the library's.

### stepped

```python
def stepped(node: dict) -> rules.Step
```

The values *node* sets for itself, laid over those of the frames it
stands in (`rules.STEP`).

### run_node

```python
def run_node(run: Run, doc, node: dict) -> None
```

One box or frame for one document, with its own values for as long
as it runs. A node that is off does not run.

### run_flow

```python
def run_flow(tree: list, run: Run) -> Counter
```

Every box of *tree*, in order: the chains for each of their
documents, the boxes that run once where they stand. What a chain
counted is in the returned counts, and in `run.stats`.

### one

```python
def one(tree: list, run: Run, document_id: int, filename: str,
        start: Optional[str] = None)
```

The first chain of *tree* (the one that starts with the box *start*,
where one is named) for one document of the run, the document that
comes out of it. For the callers that read a single document.

### run_named

```python
def run_named(name: str, run: Run, profile=None) -> Counter
```

The flow *name* of *profile* (the active profile where none is
given), run with *run*; what it counted.

### startable

```python
def startable(tree: list) -> Optional[str]
```

Why no run starts this flow, or None: a box that stands in the
library for a request no run starts (the example of a field is asked
while a spec is compiled) cannot be started from here.

[Back to the index](../README.md)
