# docpipe.prompts

`docpipe/prompts.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

prompts.py: Loads a profile's prompts, one Markdown file per stage, from
`profiles/<profile>/prompts/<stage>/<name>.md`.

There is no core default for what a prompt says about a corpus. A prompt names
the corpus it is written for and the language it answers in, and the core
knows neither: a fallback here could only be some other project's prompt,
which is worse than a missing file. A profile that extends another one has
asked for that profile's prompts where it wrote none itself, and gets exactly
those.

Optional YAML front matter carries the model parameters that belong to the
prompt (temperature, max_tokens), so the two never drift apart.

One kind of prompt is written in two halves. A prompt of the extraction stage
that names a template in its front matter (`template: rows`) is a parts file:
the profile writes what is about its corpus (the role, the examples, the
sentences about its own tables), and the core's contract text of the profile's
language (docpipe/extraction/contract.py) says the rest, once. `load` puts the
two together, so a request, a stamp and the render tool see one prompt. A file
without a `template` key is read as it always was.

A parts file is a front matter and sections that each start with a line
`<!-- part: name -->`. A template is a text with these marks:

    {{name}}                 where a part goes, or a fact the code fills in
    <!-- block: name -->     a stretch of contract text a profile may word
    <!-- /block -->          itself (a part of the same name replaces it) or,
                             where the template allows it, leave out
                             (`without: [name]`)
    <!-- rule: name -->      a numbered rule; the number is written at load,
    {{rule:name}}            counted over the rules that are left, and a
                             reference gives it, so omitting a rule moves the
                             numbers and what points at them

The mark of a block and the slot of a part take their line with them when they
stand alone on it: an absent optional part and an omitted block leave no blank
line behind. A part put in a block's place keeps the whitespace the block ended
with, so the lines around it stay. A block may stand more than once, and then
it can be left out but not worded, since one part cannot say two places. A part
keeps its own lines as written, apart from the blank lines around it; it may
use a fact and a reference to a rule, and nothing else with double braces. The
template's front matter says what it has: `required` and `optional` parts,
`blocks`, and the `omittable` ones among them.

Whatever does not fit fails at load with `PromptPartsError`, which names the
prompt, the part or block, the profile and the two files: a part that is
missing, a part the template does not know, a part whose place is gone, a block
that cannot be left out, a reference to a rule that is not there, a mark or a
double brace that is left in the text. Nothing is filled in for a part that is
missing.

Every prompt has a sha256 over its file. Stages record those hashes with
their output; when a hash no longer matches, the result was produced by a
different prompt and is stale (see `stale()`). A composed prompt has the
sha256 of the file a person would have written by hand: its front matter
without the two keys of the loader, and the text that is sent.

Author: Felix Vossel

## Classes

### PromptPartsError

```python
class PromptPartsError(ValueError)
```

A prompt that names a template could not be composed.

It says which prompt, which part or block, which profile and which two
files, so that whoever reads it in a log knows what to open.

#### PromptPartsError.\_\_init\_\_

```python
def __init__(self, message: str, *, prompt_id: Optional[str] = None,
             part: Optional[str] = None, profile: Optional[str] = None,
             files: Iterable = ())
```

### Prompt

```python
@dataclass(frozen=True)
class Prompt
```

Fields:

- `id: str`
- `text: str`
- `meta: Mapping`
- `sha256: str`
- `path: Path`
- `composition: Optional[Mapping] = None`: How the text was made when the file is a parts file, else None: a mapping with `template`, `language`, `overrides` (the blocks the profile words itself), `omitted` (the blocks it leaves out) and `what_if` ({an omitted block: the text with that block put back}, made when asked for).

#### Prompt.placeholders

```python
@property
def placeholders(self) -> frozenset
```

#### Prompt.render

```python
def render(self, **values) -> str
```

Substitute {{name}}. Unknown or missing names are an error, so a
renamed placeholder fails loudly instead of shipping '{{foo}}' to the
model.

### Template

```python
@dataclass(frozen=True)
class Template
```

One template of the core, read: what it asks of a profile and what it
says. `nodes` is the body as a tree: ("text", s), ("slot", name, indent,
newline) for a part, ("fact", name), ("rule", name), ("ref", name) and
("block", name, children).

Fields:

- `name: str`
- `language: str`
- `path: Path`
- `required: tuple`
- `optional: tuple`
- `blocks: tuple`
- `omittable: tuple`
- `nodes: tuple`
- `rules: tuple`: the rules in the order the template has them
- `places: Mapping`: part or block name -> the blocks it lies in
- `rule_blocks: Mapping`: rule name -> the blocks it lies in
- `block_counts: Mapping`: block name -> how often the template has it

#### Template.shape

```python
def shape(self) -> dict
```

What the template asks of a profile, by name: what two templates
of one name in two languages have to share.

## Functions

### path_for

```python
def path_for(prompt_id: str, profile: Profile) -> Path
```

Where the prompt lies: in the profile, else in the nearest profile
it extends. The profile's own place when nobody has it, for the message
that says so.

### owner_of

```python
def owner_of(prompt_id: str, profile: Profile) -> Profile
```

The profile whose file the prompt is: the profile itself, else the
nearest one it extends that has it.

### load

```python
def load(prompt_id: str, profile: Optional[Profile] = None,
         use_ambient: bool = True) -> Prompt
```

The prompt as the profile writes it, or, for a parts file, as the core
and the profile make it together.

### per_profile

```python
def per_profile(read)
```

Make *read()* run once per ambient profile, on first use.

For what a stage needs from its prompts: read when it is first asked for
and not when the stage is imported, so a stage can be imported, and print
its --help, before anybody has named a profile. Read once, so one run
works with one prompt.

### text

```python
def text(prompt_id: str, **values) -> str
```

Shorthand for module-level constants: text('refinement/refine').

### versions

```python
def versions(prompt_ids: Iterable[str],
             profile: Optional[Profile] = None) -> dict
```

{id: sha256} — write this next to a stage's output.

### record

```python
def record(directory: Path, prompt_ids: Iterable[str],
           profile: Optional[Profile] = None) -> None
```

Write the prompt hashes next to a stage's output.

### check

```python
def check(directory: Path, prompt_ids: Iterable[str],
          profile: Optional[Profile] = None) -> list
```

Prompt ids that changed since the result in *directory* was produced.

### stale

```python
def stale(stored: Optional[Mapping], current: Mapping) -> list
```

Prompt ids whose hash changed since the stored result was produced.

An absent entry counts as changed: results from before prompts were
versioned cannot be vouched for either.

### line_at

```python
def line_at(body: str, offset: int, index: int) -> int
```

The line of the file that character *index* of *body* is in, for a body
that starts *offset* lines into the file.

### read_template

```python
def read_template(path: Path, *, language: str, name: str,
                  fact_names: Iterable = (), fail=None) -> Template
```

A template file, read and checked as a template: its front matter, its
marks and what refers to what. `fail(message, part)` makes the exception
to raise; by default one that names the file.

### read_parts

```python
def read_parts(raw_body: str, fail, offset: int = 0) -> dict
```

{part name: its text} of a parts file's body, which starts `offset`
lines into the file. A section starts with a line `<!-- part: name -->`;
its text is what follows up to the next one, without the blank lines
around it.

[Back to the index](../README.md)
