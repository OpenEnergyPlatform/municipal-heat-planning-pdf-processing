# docpipe.extraction.flow

`docpipe/extraction/flow.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

flow.py: How a document is read, as a drawing of boxes and frames, and the
numbers that bound it, read from a file of the profile.

    <profile folder>/flow.json

Since 2026-11-11 (owner decisions 2026-11-10 evening, "Freie Ablaufgrafik")
the file is the drawing itself, a tree: boxes in their order, frames with
their boxes, an "if" with its ways side by side. The run does exactly what
it says (`engine.Engine`); there is no second order in the code. Each box is
a kind of the library (`blocks.LIBRARY`): what it takes and gives, its
settings, where it has to stand. What a box does with an answer stays code.

    {"numbers": {"piece_lines": 8, ...},
     "flow": [{"id": "document", "box": "document"},
              ...,
              {"id": "values", "each": "value", "order": "names_first",
               "together": true, "steps": [...]},
              {"id": "write", "box": "write"}]}

A box: {"id", "box": kind, "set": {setting: value}, "own": {setting: whole
number}, "rules": {name: value}, "when": condition, "off": true}. "own"
gives a number setting a value of its own ("only here") instead of the
named number. A frame: {"id", "each": what, "which", "when", "together",
"order", "rules", "steps"}, {"id", "round": {"most": n} or {"supply":
true}, "stop": condition, "rules", "steps"}, {"id", "if": [{"when":
condition, "steps"}], "else": steps, "rules"}. Conditions are
`conditions.py`'s.

"rules" gives a rule (`docpipe.rules`) or a number of the flow a value of
its own while the box runs, or while anything in the frame runs (owner
2026-11-11: "alles soll anpassbar sein"): the step's own value, then the
frames' from the inside out, then the setting of the start, then the file.
Only a rule the step reads may be set at it (`Rule.steps`,
`Number.steps`).

The default profile writes the whole file: every number (`NUMBERS`) and the
drawing. A profile that extends it writes the numbers it sets differently,
laid over the default's number by number (`load`), and may write a drawing
of its own, which is then the whole drawing. A setting of the run wins over
the file for the numbers that have one (`Number.env`), never over a box's
own value.

Before a drawing is kept, `problems` says everything the run could not do
with it (owner decisions 2026-11-10, section 11 of the plan): a box where it
cannot stand (a question of a coordinate outside "each coordinate", a find
outside "each piece"), a round that may not end, a frame of coordinates
without a state, a condition that cannot be evaluated where it stands, the
order the run needs (the document first, its pieces before anything shows
them, writing before computing). A file with a problem is refused with it.

Nothing here decides whether a harvest is current. A stamp names, in the
entry of each pass that asked a model, the numbers the pass read with and
the sha256 of the flow's files (`runner.producer`, `Numbers.sha256`), for a
reader, as it names every prompt (owner decision 2026-09-10).

Author: Felix Vossel

## Classes

### FlowError

```python
class FlowError(ValueError)
```

A flow a run cannot read. It names the file or the setting.

### Number

```python
@dataclass(frozen=True)
class Number
```

One number the reading takes.

Fields:

- `name: str`
- `least: int`
- `help: str`
- `env: Optional[str] = None`: the setting that wins over the file
- `part: Optional[int] = None`: its place where the setting lists several
- `steps: tuple = ()`: the kinds of steps that read it

### Numbers

```python
@dataclass(frozen=True)
class Numbers
```

The numbers one run reads with, and where each comes from.

Fields:

- `piece_lines: int`
- `title_page_lines: int`
- `headings: int`
- `list_meanings: int`
- `search_pieces: int`
- `search_tables: int`
- `search_figures: int`
- `search_text: int`
- `search_per_request: int`
- `listed_field_factor: int`
- `follow_ups: int`
- `replies: int`
- `origin: dict = field(default_factory=dict, compare=False, repr=False)`: name -> where its value comes from: "flow.json of \<profile>", or what set the setting that won over the file (`settings.origin`).
- `sha256: str = field(default="", compare=False, repr=False)`: Of the flow's file as laid over each other, drawing and numbers; the settings that won are not in it.
- `set_by_run: frozenset = field(default=frozenset(), compare=False,
                                  repr=False)`: The names of the numbers a setting of the run set.

#### Numbers.shares

```python
def shares(self) -> dict
```

{kind of passage: its share of a search's pieces}.

#### Numbers.as_dict

```python
def as_dict(self) -> dict
```

### Flow

```python
@dataclass(frozen=True)
class Flow
```

A profile's flow as its files say it, no setting applied.

Fields:

- `numbers: dict`: name -> value, in the order of NUMBERS
- `owners: dict`: name -> the profile whose file says it
- `tree: list`: the drawing
- `files: tuple`: ((profile name, path)), nearest first
- `sha256: str`
- `tree_from: str = ""`: the profile whose file draws it

## Functions

### number

```python
def number(numbers: Numbers, name: str) -> int
```

The number *name* of the flow as the step that runs reads it: its
own value or that of a frame around it (`rules.STEP`), else the run's
(*numbers*). The one way a number of the flow is read.

### kind_of

```python
def kind_of(node: dict) -> str
```

"box", "each", "round" or "if".

### children

```python
def children(node: dict) -> list
```

[(label, steps)] of a frame: its steps, or each way of an "if".

### walk

```python
def walk(tree: list, frames: tuple = ())
```

(node, its frames outermost first) of every node of *tree*, in
order.

### on

```python
def on(tree: list)
```

(node, its frames outermost first) of every node of *tree* that
takes part in a run, in order: one that is off, or stands in a frame
that is off, is not asked, checked or counted anywhere.

### boxes

```python
def boxes(tree: list) -> list
```

### asked

```python
def asked(tree: list) -> set
```

The requests the boxes of *tree* ask, of the boxes that are on.

### box_on

```python
def box_on(tree: list, kind: str) -> bool
```

Does the top box of *kind* stand in *tree* and is it on? The boxes
the runner does after the reading (compute, catalogue) run only so.

### compute_on

```python
def compute_on(tree: list) -> bool
```

Is the calculation after the reading on in *tree*?

### problem

```python
def problem(name: str, value) -> Optional[str]
```

Why *value* is not the number *name* of the flow, None where it
is: *name* is none of its numbers, or *value* no whole number of at
least its least value.

### checked

```python
def checked(where, name: str, value) -> int
```

*value* as the number *name* of the flow, FlowError where it is
none (`problem`). *where* names the file in what is said about it.

### availability

```python
def availability(tree: list) -> dict
```

{id(node): the variables there before *node* runs} of every step of
*tree* (owner decision 2026-11-12: what may stand where follows from
the inputs and outputs alone): what the run starts with, the item of
each frame around the step, and what the steps before it gave. An
output that lasts for the whole document (`variables.lasting`) is
there for every step after the one that made it; any other only in the
item it was made for, which a round's turn or an if's way shares with
the steps around it. A step that is off gives nothing.

### available_by_id

```python
def available_by_id(tree: list) -> dict
```

{id of a step: [the variables there before it], in order} of every
step of *tree*, for the page's choice of a variable.

### outputs_of

```python
def outputs_of(node: dict) -> list
```

The variables a box gives: its kind's, and for a general step the
ones its settings name.

### inputs_of

```python
def inputs_of(node: dict) -> tuple
```

What a box takes (`variables.wanted`): its kind's, and for a general
step the variables its settings name.

### lasting_of

```python
def lasting_of(node: dict, name: str) -> bool
```

Does the variable *name* that *node* gives last for the whole
document?

### makers

```python
def makers(tree: list) -> dict
```

{variable: [the labels of the boxes that are on and give it]}.

### known_rules

```python
def known_rules(profile) -> dict
```

{name: Rule} of every rule a box or frame of *profile*'s flow may
set for itself: the rules of its line (`rules.registry`) and those its
graph file declares (`graphfile.declared`), which steps read too (the
rounding a compute box checks a computed number with).

### problems

```python
def problems(tree, known: Optional[dict] = None, profile=None) -> list
```

Everything the run could not do with the drawing *tree*: [{"id": the
box or frame or None, "message"}], [] where it can run. *profile* (a
profile or its name) is the profile the drawing belongs to, whose boxes
it may take; *known* are the rules a step may set (`known_rules`), the
profile's where not given. Without a profile, the active one.

### prompt_problems

```python
def prompt_problems(tree: list, profile) -> list
```

The boxes of *tree* that are on and ask a request whose prompt
*profile* writes not, nor the profiles it extends: [{"id", "message"}].
A request a profile may leave unwritten (`addressed.OPTIONAL`) is no
problem: its box is never taken by that profile.

### path_of

```python
def path_of(profile) -> Path
```

Where *profile* writes its flow.

### kinds

```python
def kinds() -> tuple
```

The requests the code can send while it reads a document: those of
the reading (`addressed.KINDS`) and the calculation after it.

### parse

```python
def parse(raw: str, where, whole: bool, profile=None) -> dict
```

{"numbers": {name: value}, "flow": [...]} of the text *raw*, read
strictly. A *whole* file names every number and the drawing; any other
is laid over one and names numbers, and may draw a whole drawing of
its own. *where* names the file in what is said about it, *profile*
(a profile or its name) the profile it belongs to.

### dump

```python
def dump(data: dict, newline: str = "\n") -> str
```

A flow file's text in the one form it is written in.

### line

```python
def line(profile) -> list
```

[(profile name, path)] of the files a profile's flow can stand in,
nearest first; the default's alone where no profile is given or it has
no folder of its own.

### load

```python
def load(profile=None) -> Flow
```

The flow of *profile* as its files say it: the file of the farthest
profile of its line that writes one is the whole flow, and the numbers
of every nearer one are laid over it. LookupError where no profile of
the line writes one.

### inherited

```python
def inherited(profile) -> Optional[Flow]
```

The flow of the profiles *profile* extends, its own file left out:
what a number is where the profile does not set it. None where no
profile it extends writes a flow, so that its own file is the whole
one.

### tree_of

```python
def tree_of(profile=None) -> list
```

The drawing a run of *profile* reads by (the default profile's where
None).

### in_effect

```python
def in_effect(profile=None, environ=None) -> Numbers
```

The numbers a run of *profile* reads with: the flow of its files, and
over it the settings that are set (*environ*, the environment where not
given, into which the project file was put). `Numbers.origin` says for
each where it comes from.

### default

```python
def default() -> Numbers
```

The numbers of the default profile's file, no setting applied: what
a reading takes where it is given none.

[Back to the index](../README.md)
