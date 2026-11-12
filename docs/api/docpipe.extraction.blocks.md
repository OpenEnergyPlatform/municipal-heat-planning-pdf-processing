# docpipe.extraction.blocks

`docpipe/extraction/blocks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

blocks.py: The library of a flow's boxes and frames (owner decisions
2026-11-10 evening: the flow is a drawing of boxes and frames, a library to
take them from, and the run does exactly what the drawing says).

Each box (`Box`) says what it takes and what it gives (the arrow before and
after it: document, pieces, supply, answers, ...), its settings with their
defaults (`Setting`), the frames it has to stand in, why it is fixed where
it cannot be removed or switched off, the date of the owner's decision where
the code names one, and where it runs in the code. What a box does with an
answer stays code (`engine.py`, `addressed.Reader`); a box of a new kind, or
a property the run does not know yet, comes as code and appears here.

A setting that takes a number of the flow (`flow.NUMBERS`) takes the named
number unless the box has an own value for it ("only here"); a setting of
the run wins over the named number, never over an own value
(`flow.Numbers`, `engine.Box.number`).

Three frames hold boxes (`FRAMES`): "each" (for each piece of the plan's
settlement, field, piece, value or coordinate, optionally only where a
condition holds, side by side, in an order), "round" (at most N times or
until the supply is used up, stopping where a condition holds), "if" (ways
side by side, each under its condition, the last without one, which join
again below it).

Author: Felix Vossel

## Classes

### Setting

```python
@dataclass(frozen=True)
class Setting
```

One setting of a box. A "number" takes the named number of the flow
(*number*) unless the box gives it a value of its own; a "rule" is a
rule of `rules.json` shown at the box, set where the rules are.

Fields:

- `key: str`
- `kind: str`
- `label: str`
- `default: object = None`
- `number: Optional[str] = None`
- `choices: tuple = ()`
- `help: str = ""`
- `where: tuple = ()`: the frames it applies in, () = everywhere
- `words: tuple = ()`: what the page shows for each choice
- `rule: str = ""`: the rule that gives its value where the

### Box

```python
@dataclass(frozen=True)
class Box
```

One kind of box of the library.

Fields:

- `type: str`
- `label: str`
- `group: str`
- `takes: str`
- `gives: str`
- `says: str`
- `code: str`
- `asks: Optional[str] = None`
- `needs: tuple = ()`: frames it stands in, innermost first
- `settings: tuple = ()`
- `fixed: str = ""`: why it cannot be removed
- `switch: bool = True`: whether it may be switched off
- `decided: str = ""`
- `attached: tuple = ()`: the boxes whose answers it checks
- `prepares: bool = False`: a step of the document's preparation
- `spec: Optional[str] = None`: the switch of the spec it needs
- `top: bool = False`: stands at the top of the drawing only
- `marks: tuple = ()`: fixed checks shown at the box
- `flow: str = ""`: A box of a follow-up pass (`passflow`) says "pass" here: the main flow does not take it, and a pass does not take the others. Its *scope* is "files" or "documents" where it starts what runs for each document (a harvest file, or a document of the run), "chain" where it runs for that document after the start, "run" where it runs once. Its *after* are the boxes one of which stands before it, and *inside* the frame it stands in.
- `scope: str = ""`
- `after: tuple = ()`
- `inside: str = ""`
- `inputs: tuple = ()`: What it takes and gives by name (`variables.VARIABLES`): an input "a|b" takes one of them, one ending in "?" is taken where a step before it gives it (owner decision 2026-11-12: what may stand where follows from the inputs and outputs alone).
- `outputs: tuple = ()`
- `profile: str = ""`: A box of a profile (profiles/\<name>/blocks.py, owner decision 2026-11-12): the profile it belongs to, and the code of its step, run(engine, node, scope). A box of the core has neither; its step is the engine's `box_<type>`.
- `run: Optional[Callable] = None`

## Functions

### preset_of

```python
def preset_of(node: Optional[dict])
```

The preset a step of "Ask the model" names (`presets`), None for
any other step.

### box_of

```python
def box_of(node: Optional[dict]) -> Optional[Box]
```

The box a step is, seen through its preset: a step of "Ask the
model" with a preset has the preset's name, explanation, frames,
settings and request; None where the library has no such box.

### label_of

```python
def label_of(kind: str) -> str
```

What the page calls a kind of step (`rules.step_kind`): a box of
the library, or the preset of "Ask the model" that stands for it.

### settings_of

```python
def settings_of(node: dict) -> tuple
```

The settings of a step: its box's, and its preset's.

### is_attached

```python
def is_attached(node: dict) -> bool
```

Is *node* applied to the answers of the question before it (an own
check, a list entry, whether a place speaks about the value), so that
no frame runs it?

### target_of

```python
def target_of(node: dict) -> Optional[str]
```

The target of a step of "Ask the model" (`targets`), None for any
other step.

### asks_of

```python
def asks_of(node: dict) -> Optional[str]
```

The request a step sends, None where it sends none.

### box

```python
def box(type_: str) -> Box
```

### offered

```python
def offered(b: Box, profile=None) -> bool
```

Does the page offer *b* where *profile* (a profile or its name) is
open: a box of the core always, a box of a profile where *profile* is
that profile or extends it. Without a profile, every box.

### catalogue

```python
def catalogue(profile=None) -> dict
```

The library as the page shows it where *profile* is open: the
boxes of the main flow, those of the core and those of the profile
(`offered`), the presets of "Ask the model" its flow takes, and apart
from them the boxes of the follow-up passes.

### presets_catalogue

```python
def presets_catalogue(profile=None) -> list
```

The presets of "Ask the model" the page offers where *profile* is
open, in the order of the library: each as the box it is
(`box_of`: its name, explanation, settings, frames and where it runs)
with its five parts and the values of its settings.

[Back to the index](../README.md)
