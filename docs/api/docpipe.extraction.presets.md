# docpipe.extraction.presets

`docpipe/extraction/presets.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

presets.py: The presets of "Ask the model" (owner decision 2026-11-12
evening: "Umbauen", and for the scope "alles umbauen"; plan "modell_fragen",
point 6).

Every step that asks the model is "Ask the model" (`blocks.LIBRARY["ask"]`)
with a preset: the request it is in the log and whose settings it reads, its
prompt, its inputs, the form of its answer and its target, and the ways it
goes (`Preset`). A step of the drawing names its preset; whatever it sets of
its own wins over the preset (`general.parts_of`). The presets are the
questions the two use cases ask; a profile adds its own
(`profiles/<name>/blocks.py: PRESETS`).

The inputs of each preset are what its request always showed, in the order
it showed them, so that every request stays word for word as it was.

Author: Felix Vossel

## Classes

### Preset

```python
@dataclass(frozen=True)
class Preset
```

One preset of "Ask the model": its name and what the page calls it
and says of it, the request it is (*request*), its inputs, the form of
its answer (*reply*), its target (*into*), the values of the step's
other settings (*values*), the settings only it has (*settings*), the
frames it stands in, whether it stands at the top or prepares the
document, whether it is a question inside the answer of another
(*attached*: the requests it follows), the profile it belongs to and the
date of the owner's decision.

Fields:

- `name: str`
- `label: str`
- `says: str`
- `request: str`
- `inputs: tuple`
- `reply: object`
- `into: dict`
- `values: dict = None`
- `settings: tuple = ()`
- `needs: tuple = ()`
- `top: bool = False`
- `prepares: bool = False`
- `attached: tuple = ()`
- `profile: str = ""`
- `decided: str = ""`
- `spec: str = ""`
- `rules_as: str = ""`: The kind of step whose rules and numbers it reads (`rules.step_kind`): the step it was before every question became "Ask the model".
- `group: str = ""`: Where it runs besides the reading of a document: "end" for a step the run does once a document is read; for a step of the flow of a follow-up pass (`passflow`) the flow "pass", what it runs for (`blocks.Box.scope`) and the steps that stand before it.
- `flow: str = ""`
- `scope: str = ""`
- `after: tuple = ()`

#### Preset.kind

```python
@property
def kind(self) -> str
```

## Functions

### i

```python
def i(key: str, source: str, show: str, **more) -> dict
```

One input: the key of the message, the variable it comes from and
how it is shown.

### preset

```python
def preset(name: str)
```

The preset *name*, of the core or of a profile, None where there is
none.

### register

```python
def register(one: Preset) -> None
```

A preset of a profile (`profiles/<name>/blocks.py: PRESETS`).

[Back to the index](../README.md)
