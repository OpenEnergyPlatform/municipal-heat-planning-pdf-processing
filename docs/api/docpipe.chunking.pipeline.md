# docpipe.chunking.pipeline

`docpipe/chunking/pipeline.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pipeline.py: Orchestrates the chunkingandembedding stage: merge, then
the database step, then embedding.

Runs as a command line module:
  python -m docpipe.chunking /data/processed/ /path/to/KWP.db
      /path/to/faiss.index

Author: Felix Vossel

## Functions

### peak_rss_gb

```python
def peak_rss_gb() -> float
```

Peak resident memory of this process in GB, 0.0 where unavailable.

Logged per flush so a memory trend is visible in the log while it grows.
The run this was added for died at 194 GB with nothing in the log but the
kill message, which said what happened and nothing about the approach.

### prepared_ahead

```python
def prepared_ahead(pool, items, work, ahead=EMBED_PREPARE_AHEAD)
```

Yield work(item) in order, with at most `ahead` items in flight.

Executor.map submits EVERY item immediately and makes only the consumption
lazy (measured on the cluster's 3.11: after the first result was taken, all
500 tasks had already run). With preparation far faster than embedding, the
finished results pile up until the whole corpus is resident - a million
section texts for 1078 plans, which is what the OOM kill at 194 GB was. A
sliding window keeps the overlap that made this a pool and bounds what is
resident to a constant.

### run

```python
def run(
    data_dir: str | Path,
    db_path: str | Path,
    index_path: str | Path,
    *,
    step: Optional[str] = None,
    force: bool = False,
) -> None
```

Run the pipeline over the PDF subdirectories of `data_dir`.

`step` limits the run to 'merge', 'db', 'embed' or the standalone
'enrich-bbox', 'enrich-page-source' or 'enrich-caption'; None runs
merge → db → embed (the db step backfills the page source and the
captions itself). `force` ignores caches and clears old embeddings.

### main

```python
def main() -> None
```

CLI entry point.

[Back to the index](../README.md)
