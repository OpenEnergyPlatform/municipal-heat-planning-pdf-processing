# docpipe.extraction.flow

`docpipe/extraction/flow.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

flow.py: The steps a document is read in and the numbers that bound them,
read from a file of the profile.

How a document is read stood in four places: the order in the code of the
reading (`addressed.Reader`), some of its numbers in the settings, others as
constants in three modules, its switches in the spec. Since 2026-11-10 the
numbers stand in one file and the steps beside them, so that both can be
seen and the numbers set where the spec and the prompts are (`docpipe
edit`):

    <profile folder>/flow.json

The default profile writes the whole file: every number the reading takes
(`NUMBERS`) and its steps. A profile that extends it writes only the numbers
it sets differently, and its file is laid over the default's number by
number (`load`); the steps are the default's. A setting of the run wins over
the file for the numbers that have one (`Number.env`): the environment, then
the project file, then this file (`in_effect`).

The steps say what the code does and are not run from the file: the order is
the code's until the reading is cut into steps that can be (the plan's stage
4). So that the file cannot say something else than the code, it is read
strictly: every request the code sends stands in a step (`kinds`), a step
asks no request the code does not send, every number bounds a step, and a
number the code does not take is refused.

Nothing here decides whether a harvest is current. A stamp names, in the
entry of each pass that asked a model, the numbers the pass read with and
the sha256 of the flow's files (`runner.producer`, `Numbers.sha256`), for a
reader, as it names every prompt (owner decision 2026-09-10: a stamp rests on
the questions alone).

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
- `sha256: str = field(default="", compare=False, repr=False)`: Of the flow's file as laid over each other, steps and numbers; the settings that won are not in it.

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
- `steps: list`
- `files: tuple`: ((profile name, path)), nearest first
- `sha256: str`

## Functions

### path_of

```python
def path_of(profile) -> Path
```

Where *profile* writes its flow.

### kinds

```python
def kinds() -> tuple
```

The requests the code sends while it reads a document: those of the
reading (`addressed.KINDS`) and the calculation after it.

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

### parse

```python
def parse(raw: str, where, whole: bool) -> dict
```

{"numbers": {name: value}, "steps": [...]} of the text *raw*, read
strictly. A *whole* file names every number and the steps; any other is
laid over one and names numbers only. *where* names the file in what is
said about it.

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
