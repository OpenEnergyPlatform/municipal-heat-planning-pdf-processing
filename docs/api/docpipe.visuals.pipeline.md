# docpipe.visuals.pipeline

`docpipe/visuals/pipeline.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pipeline.py: Orchestrates the imageprocessing stage.

Enriches one PDF's output directory, or every PDF subdirectory under
a root directory with `--batch`, by sending each table and figure
image to a vision language model. `_build_parser` lists the CLI
flags.

Author: Felix Vossel

## Functions

### collect_cached

```python
def collect_cached(data: dict, into: dict) -> None
```

Into *into*, by id: every table of *data* that carries its markdown
and every figure that carries its description. What a later run does
not ask the model for again, and what `docpipe status` counts as done.

### run_single

```python
def run_single(
    output_dir: Path,
    *,
    input_json: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    force_stale: bool = False,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    holes: Optional[list] = None,
) -> Optional[dict]
```

Sends each table/figure image in one PDF's output directory to the vision
model and writes the enriched output.

Caching is item-level: tables that already have a "markdown" key and figures
that already have a "description" key are reused from a previous enriched
output unless *force* is set. An item the model gave no object for has
none, says why in "vlm_why", and is asked again by the next run. An item
an older run stored as a plain-text answer is treated like one described
under older prompts: said once, with its number, and asked again only with
*force_stale*. *input_json* is relative to *output_dir*.

*holes*, when given, gets one entry (`_hole_entry`) for a document with
items that ended without content.

Returns:
    Enriched data dict, or None on failure.

### summarise

```python
def summarise(holes: list) -> str
```

One sentence for the items a run left without content, in tables,
figures and documents. *holes* are the entries `run_single` adds, one per
document.

### run_batch

```python
def run_batch(
    root_dir: Path,
    **kwargs,
) -> dict[str, bool]
```

Runs enrichment for every document directory under *root_dir*, at any
depth, that contains one of the expected structured output JSONs.

Returns:
    Dict mapping directory name → success boolean.

### run

```python
def run(
    input_path: str | Path,
    *,
    batch: bool = False,
    **kwargs,
) -> Optional[dict] | dict[str, bool]
```

Entry point: auto-selects single or batch mode.

### main

```python
def main() -> None
```

CLI entry point.

[Back to the index](../README.md)
