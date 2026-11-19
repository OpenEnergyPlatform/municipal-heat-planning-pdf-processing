# docpipe.extraction.flowparts

`docpipe/extraction/flowparts.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

flowparts.py: Steps drawn once and used by several frames, and a profile's
drawing as what it changes in the drawing it inherits (owner request
2026-11-19, point C2 of the review of that day).

The steps for one value stood twice in every flow file, once in the frame of
the fields a document has once and once in that of the values of its pieces,
and every profile held the whole drawing: a change to them was made six times
by hand, and a change to the default's drawing reached no profile. Now:

- A drawing names steps once, a part (`"parts": {name: [steps]}`), and a
  frame uses them where it stands: "part" (and "prefix") in place of
  "steps". Drawn (`expand`), the frame's steps are the part's, every id in
  them prefixed with the prefix, so that the frames that use one part have
  ids of their own. What a frame goes through, its order and its rules stay
  the frame's: the default uses the steps for one value in the frame of the
  fields a document has once (order "document", prefix "document\_") and in
  that of the values of its pieces (order "names_first", no prefix), with
  the ids they always had.
- A profile that extends another writes what it changes in the drawing it
  inherits ("changes", `apply`): a step set to other settings, inserted,
  moved or removed, named by its id, in the drawing or, with "part", in a
  part, where it changes every frame that uses it; a part of its own is
  defined.
- The page edits the drawn drawing. Saved, it is folded back (`fold`): each
  frame that used a part uses it again, and the steps it shows, their ids
  without its prefix, are the part; a part changed in one frame is changed
  in all; changed differently in two is refused. A profile's file then holds
  the changes from the drawing it inherits (`as_changes`), checked by
  applying them; where they do not give the drawing, the whole drawing.

The run reads the drawn drawing (`flow.Flow.tree`) and nothing of this.

Author: Felix Vossel

## Classes

### PartError

```python
class PartError(ValueError)
```

A part that is not named, a change that names no step, a part
changed differently in two frames.

## Functions

### kind

```python
def kind(node: dict) -> str
```

### is_use

```python
def is_use(node) -> bool
```

Is *node* a frame that uses a part?

### lists_of

```python
def lists_of(node: dict) -> list
```

[(way, steps)] of a node: "steps" of a frame, each way of an "if"
by its number, "else"; [] for a box and a frame that uses a part.

### places

```python
def places(steps: list, parent=None, way=None)
```

(node, the list it stands in, its index, its frame's id, the way of
the frame) of every node of *steps*, in reading order.

### own

```python
def own(node: dict) -> dict
```

What a step says of itself, the steps in it left out: its settings,
the conditions of an "if"'s ways, whether it has an "else".

### with_steps

```python
def with_steps(said: dict, old: Optional[dict] = None) -> dict
```

The step *said* (as `own` says one) with the steps of *old* in it,
way by way, or none where *old* is None or has no such way.

### with_prefix

```python
def with_prefix(node: dict, prefix: str) -> dict
```

A copy of *node* whose id and every id in it start with *prefix*.

### without_prefix

```python
def without_prefix(node: dict, prefix: str) -> dict
```

A copy of *node* whose ids lose *prefix* where they start with it.

### uses

```python
def uses(tree: list) -> list
```

The frames of *tree* that use a part, in reading order.

### expand

```python
def expand(tree: list, parts: Optional[dict], where: str = "flow") -> list
```

*tree* with the steps of every part drawn in each frame that uses it,
every id in them prefixed with the frame's prefix. A part uses no part.
PartError where a frame uses one the drawing does not name.

### checked_parts

```python
def checked_parts(parts, where: str = "flow") -> dict
```

*parts* as a file writes them: {name: [steps]}; PartError if not.

### fold

```python
def fold(drawn: list, top: list, parts: Optional[dict]) -> tuple
```

(drawing, parts) of the drawn drawing *drawn*, in which the frames of
*top* that use a part were drawn: each of them, found by its id, uses
its part again, its settings as *drawn* shows them; the steps it shows,
their ids without its prefix, are the part. A part changed in one frame
is changed in all; changed differently in two is PartError. A frame
whose id the edit changed or that it removed no longer uses its part,
and a part no frame uses is left out.

### apply

```python
def apply(top: list, parts: Optional[dict], changes) -> tuple
```

(drawing, parts) with *changes* made, in their order (see the
module's head); PartError where one names a step or part that is not
there.

### diff

```python
def diff(base_top: list, base_parts: Optional[dict], top: list,
         parts: Optional[dict]) -> list
```

The changes that make the drawing (*base_top*, *base_parts*) the
drawing (*top*, *parts*): a part the base does not name is defined, each
part it names is changed, then the drawing.

### as_changes

```python
def as_changes(base_top: list, base_parts: Optional[dict], top: list,
               parts: Optional[dict]) -> Optional[list]
```

`diff`, where making it in the base gives the drawing and every part
it uses exactly; else None (the file then holds the whole drawing).

[Back to the index](../README.md)
