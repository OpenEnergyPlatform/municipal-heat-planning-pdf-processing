# docpipe.editor.flow

`docpipe/editor/flow.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

flow.py: A profile's flow for the editor: its drawing of boxes and frames,
the library they come from, its numbers with where each comes from, the
check of an edited drawing and what a save writes.

The flow itself is the run's (`extraction.flow`): its file, its strict
reading, the drawing the run does (`extraction.engine`), the numbers a run
takes and the settings that win over them. This module only turns it into
what the page draws and decides what a save does to the profile's own file:

- `view`: the drawing as the file says it, the library of boxes and frames
  (`extraction.blocks`), what a condition can be about
  (`extraction.conditions`), every number with its value, whether the
  profile sets it itself, what it inherits and what a run started here
  would read with; for each kind of box why this profile never takes it
  (its prompt unwritten, its switch of the spec off), the prompt of each
  request and the entries of the spec each switch stands for, each a link
  into the spec; and what the run could not do with the drawing.
- `judge`: whether edited numbers are numbers of the flow and an edited
  drawing one the run can do (`flow.problems`, `flow.prompt_problems`),
  what changes and what the profile's file would then be. A profile that
  extends another writes only the numbers that differ from what it
  inherits and the drawing where it differs, so a number set back leaves
  the file, and a file that would hold nothing is removed.
- `save`: `judge`, and the bytes to write where it holds.
- `pass_names`, `pass_view`, `pass_judge`, `pass_save`: the same for the
  flow of a follow-up pass (`extraction.passflow`), one file for each, by
  name: the flow of `--top-up`, `--remap` and the others, which a profile
  overrides by its own `flows/<name>.json`.

No file is read here but through the run's loader; the server checks every
path first and hands in the bytes of the profile's own file.

Author: Felix Vossel

## Functions

### sha256

```python
def sha256(data: bytes) -> str
```

### step_rules

```python
def step_rules(profile) -> dict
```

What a box or frame can set for itself (`"rules"` in flow.json,
owner 2026-11-11: "alles soll anpassbar sein"): every rule and number of
the flow a step reads, with its standard (the files of the profile), the
run's value and where that comes from, and per kind of step
(`rules.step_kind`) the names it reads. A key's value is never sent.

### own_at

```python
def own_at(tree: list) -> dict
```

{rule or number: [{"id", "kind"} of the steps of *tree* that give it
a value of their own]}: what a box or frame writes under "rules", and
what a box writes under "own" for a number setting (named by its
number).

### view

```python
def view(profile, own_raw: Optional[bytes], data: Optional[dict],
         shown: Callable, computes: bool = False,
         project: Optional[Path] = None) -> dict
```

The flow of *profile* as the page draws it (see the module's head).
*own_raw* are the bytes of the profile's own flow file, None where it
has none; *data* its spec as written, None where it has none;
*shown(path)* a path as the user sees it; *computes* whether the
profile computes. *project* is the project file the machine's values
are written to, None where the page cannot say.

### tree_changes

```python
def tree_changes(old: list, new: list) -> list
```

What an edit did to a drawing, one line each: boxes and frames added,
removed, changed or moved.

### judge

```python
def judge(profile, own_raw: Optional[bytes], numbers, name: str,
          tree=None) -> dict
```

What a save of *numbers* ({name: value}, those not named as the
files say them) and of the drawing *tree* (None: as the files say it)
would do: {"ok", "errors": [{"name" or "id", "message"}], "changed":
[{"name", "from", "to"}], "file", "writes" ("created", "changed",
"removed", "unchanged"), "diff", "says", "text"}. *text* is the
profile's file as it would stand, in the line ends it has (plain ones
where it is new), None where it would be removed. *name* is the file
as the user sees it. A drawing the run cannot do is refused with every
reason, each at its box (`flow.problems`, `flow.prompt_problems`).

### save

```python
def save(profile, own_raw: Optional[bytes], numbers, base: Optional[str],
         name: str, tree=None) -> tuple
```

(what the page is told, the bytes to write or None, whether the
file is to be removed). Bytes come back only for numbers the flow
takes and an order the run can read in, and only where the file is as
the page loaded it (*base*, the sha256 of its bytes, None where it had
none).

### pass_names

```python
def pass_names(profile) -> list
```

[{"name", "path" (where the profile writes its own file of it),
"own" (the profile writes one), "starts_from" (the profile whose file
is the farthest of the line)}] of every flow of a follow-up pass that a
run of *profile* can start. The main flow is the page's own tab and not
among them.

### pass_library

```python
def pass_library() -> dict
```

The library a flow of a follow-up pass is drawn with, in the form of
the main flow's: its boxes, and the one frame a pass knows, which goes
through the dimensions a box before it chose.

### pass_view

```python
def pass_view(profile, own_raw: Optional[bytes], name: str,
              shown: Callable) -> dict
```

The flow *name* as the page draws it: its drawing (the profile's own
file where it has one, else the nearest below), the boxes of the
library a pass takes, what the run could not do with the drawing, and
why no run starts it. *own_raw* are the bytes of the profile's own file
of it, None where it has none.

### pass_judge

```python
def pass_judge(profile, own_raw: Optional[bytes], name: str,
               shown_name: str, tree=None) -> dict
```

What a save of the drawing *tree* of the flow *name* would do, as
`judge` says it for the main flow: {"ok", "errors": [{"id",
"message"}], "file", "writes", "diff", "text"}. A drawing the run
cannot do is refused with every reason, each at its box. A profile
that extends another writes the file only where the drawing differs
from what it inherits.

### pass_save

```python
def pass_save(profile, own_raw: Optional[bytes], name: str,
              base: Optional[str], shown_name: str, tree=None) -> tuple
```

(what the page is told, the bytes to write or None, whether the file
is to be removed), as `save` for the main flow: bytes come back only for
a drawing the run can do, and only where the file is as the page loaded
it (*base*, the sha256 of its bytes, None where it had none).

[Back to the index](../README.md)
