# docpipe.doctor

`docpipe/doctor.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

doctor.py: Can this installation run? One line per thing looked at.

    docpipe doctor [--stage S] [--offline] [--json]

Nothing here needs a GPU, reads a document or asks a model a question: a
server is asked which models it serves, a database how many documents it
holds. What fails makes the command exit 1, with what to do about it on the
line, so a first start and a CI job can both stop on it.

A stage whose packages are not installed is a warning, not a failure: an
installation that only chats needs no layout model. Named with --stage, the
same finding is a failure.

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

### check_endpoints

```python
def check_endpoints(stage: Optional[str], offline: bool) -> list
```

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
