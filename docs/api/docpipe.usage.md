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
    python -m docpipe.usage [--profile P]

One row per run instead of one counter that grows: a flush repeats the same
absolute numbers, so writing twice never counts twice, and a total can still be
split by stage, model or job afterwards.

Each row also says which profile the run was under and, where the provider
reports it, how many of the input tokens it served from its cache. A ledger
written before that has neither column: the first write adds them, and a read
never writes, so an older file stays readable as it is.

A process counts only after `begin(stage)`, which each stage's entry point
calls. The inference app, the tests and any library use record nothing. The
row is rewritten every FLUSH_SECONDS while requests come back and once more at
exit, so a job the scheduler kills loses at most that window. Counting must
never take a run down: a database that cannot be written is logged once and
the run goes on.

Author: Felix Vossel

## Classes

### Sum

```python
class Sum(NamedTuple)
```

What the ledger holds for one stage and model, over its runs.

Fields:

- `runs: int`
- `requests: int`
- `input_tokens: int`: the cached ones included
- `output_tokens: int`
- `embedding_tokens: int`
- `cached_tokens: int`

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

The profile in effect is read here: a stage settles it before it begins.

### add

```python
def add(model: str, input_tokens: int = 0, output_tokens: int = 0,
        embedding_tokens: int = 0, requests: int = 1,
        cached_tokens: int = 0) -> None
```

Count one request (or `requests` embedded inputs) against `model`.

`cached_tokens` are the part of `input_tokens` the provider served from
its cache: they are counted beside them, never instead.

### cached_of

```python
def cached_of(usage) -> int
```

The input tokens a reply's usage block says came from the provider's
cache. 0 where it says nothing, which is what a server without a cache,
or one that does not report it, comes to.

The adapters of the hosted providers put it on `cached_tokens`; the
OpenAI client of a server of one's own carries it under
`prompt_tokens_details`.

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

### sums

```python
def sums(path: Optional[Path] = None,
         profile: Optional[str] = None) -> dict
```

{(stage, model): Sum}, over the runs of one profile when it is named.

A read never writes: a ledger from before the profile and the cached
tokens were kept is read as it is, its rows carrying no profile and no
cached tokens, so none of them is any profile's.

### unattributed

```python
def unattributed(path: Optional[Path] = None) -> int
```

How many rows of the ledger carry no profile: the runs from before it
was kept.

### totals

```python
def totals(path: Optional[Path] = None,
           profile: Optional[str] = None) -> list
```

(stage, model, runs, requests, input, output, embedding) per stage and
model, over one profile's runs when it is named.

### cost

```python
def cost(row, prices: dict, cached: int = 0) -> Optional[float]
```

What one row of `totals` cost, or None when its model has no price.

*prices* is the project file's table: per model what a million input,
output, embedding and cached input tokens cost. A kind the table leaves
out costs nothing, which is right for a model that is only ever used for
the other.

*cached* is how many of the row's input tokens the provider served from
its cache. They cost the model's `cached` price where the table has one;
without it they cost what any input token does, so a cache the table says
nothing about never makes the bill smaller than it was.

### main

```python
def main(argv=None) -> int
```

[Back to the index](../README.md)
