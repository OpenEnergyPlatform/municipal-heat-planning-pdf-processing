# docpipe.rules

`docpipe/rules.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

rules.py: The rules a run follows, read from a file of the profile.

Every rule of the reading that is a value stood in the code until
2026-11-10: a number ("a quote has at least 8 characters"), a switch, a
choice ("the documents write the decimal with a comma"), a list of words or
characters ("the abbreviations whose point ends no sentence"), a table. Since
then each stands in a file of the profile, beside its spec, its prompts and
its flow, so that `docpipe edit` shows and sets it in the tab it belongs to
(owner, 2026-11-10: "Alle Regeln etc. sollen auch immer über die GUI
Editierbar sein"):

    <profile folder>/rules.json

The code knows of each rule its name, its kind, its bounds and what it does
with it (`RULES`); its value stands in the file and nowhere in the code. The
default profile's file names every rule of the core. A profile that extends
it writes only the rules it sets differently, laid over the default's rule by
rule, as the numbers of its flow are (`flow.py`). A profile whose own code
follows rules the core does not know declares them (`profiles/\<name>/
rules.py: RULES`), and its file is the one they start from. A rule that has
a setting (`Rule.env`) is set by it where it is set: the environment, then
the project file, then the file.

A run reads with the rules of its profile (`use`; `current` takes the
ambient profile's where no run said which). A step of the flow and the
frames around it may set a rule for themselves (`"rules"` of a box or frame
in `flow.json`, owner 2026-11-11: "alles soll anpassbar sein"): while the
step runs, its values lie over the run's (`STEP`, set by
`engine.Engine.step`), the innermost frame's over the outer ones', so a
value is read in this order: the step, its frames from the inside out, the
setting of the start, the file. `get` is the one way a rule is read.
Nothing here decides whether a harvest is current: a pass names the sha256
of its rules in its entry of the stamp for a reader, as it names its
prompts and its flow (owner decision 2026-09-10: a stamp rests on the
questions of the spec alone).

Author: Felix Vossel

## Classes

### RuleError

```python
class RuleError(ValueError)
```

A rules file or a value a run cannot read. It names the file or the
rule.

### Rules

```python
@dataclass(frozen=True)
class Rules
```

The rules one run reads with, and where each comes from.

Fields:

- `values: dict`: name -> value, in the order of RULES
- `owners: dict`: name -> "rules.json of \<profile>" or
- `files: tuple = ()`: ((profile name, path)), farthest first
- `sha256: str = ""`: of the files' rules, settings left out
- `state: str = ""`: of the values in effect, settings in

#### Rules.get

```python
def get(self, name: str, default=None)
```

### Step

```python
@dataclass(frozen=True)
class Step
```

The values a step of the flow and its frames set for themselves,
laid over each other (the innermost wins), while it runs.

Fields:

- `kind: str`: of the innermost node (`step_kind`)
- `ident: str`: its id in the drawing
- `values: dict`: name -> value: rules and numbers of
- `owners: dict`: name -> "step \<id>" or "frame \<id>"
- `state: str = ""`: of the values, "" where there are none

### in_step

```python
class in_step
```

Read with *step*'s values while the block runs (`STEP`).

#### in_step.\_\_init\_\_

```python
def __init__(self, step: Step)
```

### recording

```python
class recording
```

Note every read of a rule or a number of the flow while the block
runs, in every thread: {(step kind, name)}.

### overlaid

```python
class overlaid
```

The rules a run reads with, with *values* laid over them, while the
block runs: for a test that wants one rule set otherwise.

    with rules.overlaid(year_range=None):
        ...

#### overlaid.\_\_init\_\_

```python
def __init__(self, **values)
```

## Functions

### problem

```python
def problem(name: str, value, known: Optional[dict] = None) -> Optional[str]
```

Why *value* is not the rule *name*, None where it is. *known* are
the rules the profile's line knows (`registry`), the core's where not
given.

### checked

```python
def checked(where, name: str, value, known: Optional[dict] = None)
```

### declared

```python
def declared(profile) -> list
```

[(profile name, its own rules, the file beside them)] of *profile*'s
line, farthest first: the rules a profile declares for its own code
(`profiles/<name>/rules.py: RULES`), which the core does not know, and
the rules.json beside that module, which they start from.

### registry

```python
def registry(profile=None) -> dict
```

{name: Rule} of every rule a run of *profile* reads: the core's and
those its line declares, in the order a file writes them.

### parse

```python
def parse(raw: str, where, known: Optional[dict] = None,
          needed: tuple = ()) -> dict
```

{name: value} of the text *raw*, read strictly against the rules
*known* (the core's where not given). *needed* are the rules the file
has to name: those it is the first file of.

### dump

```python
def dump(rules: dict, newline: str = "\n", known: Optional[dict] = None) \
        -> str
```

A rules file's text in the one form it is written in: the rules in
the order of the registry.

### path_of

```python
def path_of(profile) -> Path
```

### line

```python
def line(profile) -> list
```

[(profile name, path)] of the files a profile's rules can stand in,
nearest first, the default's last.

### load

```python
def load(profile=None, environ=None) -> Rules
```

The rules of *profile* (the default's where None): its files laid
over each other, and over them the settings that are set (*environ*,
the environment where not given).

### inherited

```python
def inherited(profile) -> Optional[Rules]
```

The rules *profile* has where its own file says nothing, no setting
applied: those of the files of the profiles it extends. None for the
default profile.

### default

```python
def default() -> Rules
```

The default profile's rules, no setting applied.

### use

```python
def use(profile=None, environ=None) -> Rules
```

Read with the rules of *profile* from here on, while it is the
ambient profile (`DOCPIPE_PROFILE` names it); returned.

### reset

```python
def reset() -> None
```

Forget the rules taken and read, so that the next read takes the
files as they are now (for tests, and after a rules file was written).

### current

```python
def current() -> Rules
```

The rules a run reads with: those a run took (`use`) for the
ambient profile, else the ambient profile's (`DOCPIPE_PROFILE`), else
the default's.

### step_kind

```python
def step_kind(node: dict) -> str
```

How a node of a flow is named where a rule says which steps read it:
a box by its kind ("find"), a frame as "each \<what>", "round" or
"if".

### stepped

```python
def stepped(node: dict, values: dict) -> "Step"
```

The step of *node* with its own *values* laid over the step it
stands in.

### noted

```python
def noted(name: str) -> None
```

Note a read of *name* where `recording` asks for it.

### stepped_value

```python
def stepped_value(name: str)
```

(True, the step's own value of *name*) where the step that runs or
a frame around it sets one, else (False, None). Noted as a read.

### get

```python
def get(name: str, owner: Optional[str] = None)
```

The value of the rule *name* in the rules a run reads with: the own
value of the step that runs or of a frame around it (`STEP`), else the
run's. A profile's own code names itself as *owner*: where the ambient
profile's line does not declare the rule, it is *owner*'s (a test of
the scenario profile's regions run under another ambient profile).

### derived

```python
def derived(key: str, build: Callable)
```

What *build* makes of the rules in effect, made once per state of
the rules and of the step's own values: a pattern compiled from a list
of words.

### of_tab

```python
def of_tab(tab: str, profile=None) -> list
```

The rules of *tab* a run of *profile* reads, in their order.

[Back to the index](../README.md)
