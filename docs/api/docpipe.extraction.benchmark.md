# docpipe.extraction.benchmark

`docpipe/extraction/benchmark.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

benchmark.py: One harvest, recorded once and made again without a model.

    docpipe benchmark DIR --record     harvest with the configured model and
                                       keep every answer
    docpipe benchmark DIR              harvest again from those answers and
                                       hold the result against the first one

A benchmark is a directory:

    benchmark.json    which profile, which database and index, which
                      arguments and settings the harvest is run with
    cassette.jsonl    the answers of the recorded run (`providers/cassette`)
    harvest/          what the recorded run harvested, and its query cache
    gold.jsonl        what people decided about it (`gold.py`), once
                      somebody has

Both runs take their command line and their settings from `benchmark.json`,
so the second one asks what the first one asked. Nothing else reaches the
harvest: no setting of the shell the benchmark is started in, no project
file, no .env. The one exception is how the models are reached (provider,
address, key), which a recording takes from where it is run and a replay
does not need. Which model is asked is a setting like any other.

Both runs ask one request at a time. A request shows the model what earlier
requests of the same sweep found, so with several in flight its words
depend on which thread was faster, and a replay would ask other words than
the recording answered.

What a replay shows is what a change to the code does to a harvest whose
answers are held still: how a reply is read, what is accepted, how rows are
settled. A change that makes the run ask something else (a prompt, the
spec, how passages are picked) is not answered from the cassette. The
replay says so and fails, and that change needs a recorded run of its own.

Recording asks a model and writes down the text of the documents it read,
so it is only done on purpose (`--record`) and only for a profile whose
documents may be passed on.

Author: Felix Vossel

## Functions

### manifest

```python
def manifest(directory: Path) -> dict
```

The benchmark's description, checked.

### command

```python
def command(directory: Path, described: dict, out: Path) -> list
```

The harvest's command line: the same for both runs.

### profile_of

```python
def profile_of(directory: Path, described: dict) -> str
```

The name of the benchmark's profile. `profile` is a name, or the
directory of a profile as seen from the benchmark's directory, for a
profile that is not on the search path where the benchmark is run.

### environment

```python
def environment(directory: Path, described: dict, variable: str,
                path: Path, no_env_file: Path) -> dict
```

The harvest's environment: the benchmark's settings and no others.

Every setting docpipe reads is taken out of this process's environment
first, except, for a recording, how the models are reached. *no_env_file*
is an empty file the harvest is given as its .env, so that it reads
none of its own.

### record

```python
def record(directory: Path, *, run: Callable = _run) -> int
```

Harvest with the configured model and keep every answer.

### replay

```python
def replay(directory: Path, out: Optional[Path] = None, *,
           run: Callable = _run) -> int
```

Harvest again from the recorded answers and hold the result against
the recorded harvest and the decisions.

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
