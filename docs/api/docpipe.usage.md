# docpipe.usage

`docpipe/usage.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

usage.py: Counts the tokens every run spends, into one SQLite file that
outlives the runs.

The model server reports what each request really cost: input and output
tokens on a chat reply, input tokens on an embedding. Until now those numbers
reached a log line at best and were gone with the job. Here they are summed per
stage and model and written as one row per run, so the total over every run is
a query:

    sqlite3 data/usage.db "SELECT * FROM token_totals"
    python -m docpipe.usage

One row per run instead of one counter that grows: a flush repeats the same
absolute numbers, so writing twice never counts twice, and a total can still be
split by stage, model or job afterwards.

A process counts only after `begin(stage)`, which each stage's entry point
calls. The inference app, the tests and any library use record nothing. The
row is rewritten every FLUSH_SECONDS while requests come back and once more at
exit, so a job the scheduler kills loses at most that window. Counting must
never take a run down: a database that cannot be written is logged once and
the run goes on.

Author: Felix Vossel

## Functions

### db_path

```python
def db_path() -> Path
```

Where the counts go. Read at flush time, so a test can redirect it.

### begin

```python
def begin(stage: str) -> None
```

Count this process's requests under `stage` from here on.

### add

```python
def add(model: str, input_tokens: int = 0, output_tokens: int = 0,
        embedding_tokens: int = 0, requests: int = 1) -> None
```

Count one request (or `requests` embedded inputs) against `model`.

### reply

```python
def reply(response, model: str) -> None
```

Count a chat completion by what the server says it cost.

A reply without a usage block (a stub, a server that omits it) counts
nothing rather than a guess.

### flush

```python
def flush(wait: bool = True) -> None
```

Write this run's rows. Never raises.

### totals

```python
def totals(path: Optional[Path] = None) -> list
```

(stage, model, runs, requests, input, output, embedding) per stage and model.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
