# docpipe.doctor

`docpipe/doctor.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

doctor.py: Can this installation run? One line per thing looked at.

    docpipe doctor [--stage S] [--offline] [--json]

Nothing here needs a GPU or reads a document: a server is asked which models
it serves and answers one request of one token, a database says how many
documents it holds and which embedding model built its index. What fails
makes the command exit 1, with what to do about it on the line, so a first
start and a CI job can both stop on it.

What the stages ask of the setup is looked at where the stages say it: the
context a stage needs is the budget the stage computes, the request fields
are probed by the preflight the stages run, the completeness of a stage's
prompts and wording is the loader's and the wording tables' own. Nothing here
counts any of it again.

A stage whose packages are not installed is a warning, not a failure: an
installation that only chats needs no layout model. Named with --stage, the
same finding is a failure. With --offline no server is asked, and each
group of lines that needs one says it was skipped.

Author: Felix Vossel

## Classes

### Check

```python
@dataclass
class Check
```

Fields:

- `area: str`
- `name: str`
- `status: str`
- `detail: str`
- `hint: str = ""`

### Unconfigured

```python
class Unconfigured(Exception)
```

A part the profile does not provide: its line is skipped, not failed.

### Asked

```python
@dataclass
class Asked
```

One role's server as its endpoint line found it. Kept for the lines
that need the same answer: asking again is a second request, and it could
answer something else.

Fields:

- `role: str`
- `base_url: str`
- `api_key: str`
- `model: str`
- `check: Check`
- `window: Optional[int] = None`
- `served: bool = False`: it answered, and it serves the model

## Functions

### check_python

```python
def check_python() -> list
```

### check_project

```python
def check_project() -> list
```

### check_profile

```python
def check_profile() -> tuple
```

(checks, the profile or None).

### check_packages

```python
def check_packages(stage: Optional[str]) -> list
```

### servers

```python
def servers(stage: Optional[str], offline: bool) -> list
```

The servers the stage's command talks to, each asked once.

### check_endpoints

```python
def check_endpoints(stage: Optional[str], offline: bool,
                    asked: Optional[list] = None) -> list
```

### check_context

```python
def check_context(stage: Optional[str], profile, asked: list,
                  skipped: str = "") -> list
```

The context each stage needs against the context its server reports.
Only the servers that were asked count: a role nobody asked about has no
line here either.

### check_request

```python
def check_request(stage: Optional[str], asked: list,
                  skipped: str = "") -> list
```

Whether each server takes the request fields the stages send. The one
request of one token that `assert_serving` sends, sent on its own.

### check_stages

```python
def check_stages(stage: Optional[str], profile) -> list
```

Whether the profile in effect holds each stage's prompts and wording.
What a stage asks of a profile is read from the stage.

### check_embedding

```python
def check_embedding(stage: Optional[str], profile) -> list
```

The embedding model and dimension the database records for its index,
against the ones configured for queries. Offline: it reads the file.

### check_data

```python
def check_data(profile) -> list
```

### run

```python
def run(stage: Optional[str] = None, offline: bool = False) -> list
```

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
