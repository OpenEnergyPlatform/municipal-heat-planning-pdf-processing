# docpipe.prompts

`docpipe/prompts.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

prompts.py: Loads a profile's prompts, one Markdown file per stage, from
`profiles/<profile>/prompts/<stage>/<name>.md`.

There is no core default. A prompt names the corpus it is written for and
the language it answers in, and the core knows neither: a fallback here
could only be some other project's prompt, which is worse than a missing
file.

Optional YAML front matter carries the model parameters that belong to the
prompt (temperature, max_tokens), so the two never drift apart.

Every prompt has a sha256 over its file. Stages record those hashes with
their output; when a hash no longer matches, the result was produced by a
different prompt and is stale (see `stale()`).

Author: Felix Vossel

## Classes

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

## Functions

### path_for

```python
def path_for(prompt_id: str, profile: Profile) -> Path
```

### load

```python
def load(prompt_id: str, profile: Optional[Profile] = None,
         use_ambient: bool = True) -> Prompt
```

The prompt as the profile writes it.

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

[Back to the index](../README.md)
