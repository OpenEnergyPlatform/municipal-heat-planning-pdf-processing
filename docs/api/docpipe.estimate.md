# docpipe.estimate

`docpipe/estimate.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

estimate.py: What a run will cost, before it runs.

    docpipe estimate [STAGE ...] [--out DIR] [--db FILE] [--processed DIR]

For each stage named (default: all) it counts the work the stage still has,
by that stage's own rule for what is pending, and says how many requests that
is, how many tokens go in and out, and what that costs when the project file's
[prices] table names the model. It is an estimate and says so: it never calls
a model, and it stops nothing. It is a number to read before `docpipe <stage>`,
not a limit on it.

Every figure carries its basis, and there are two. Where this installation's
ledger (usage.py) holds requests of the stage under this profile and this
model, a request is taken to cost what those requests cost on average:
"measured". Where it holds none, the request is counted from the size of its
prompt: "counted", which is the stage's own over-estimate of tokens per word
and says nothing about the length of a reply. The two are not mixed inside one
figure, and the line says which one it used. A ledger kept the profile only
from the version that added the column on, so its older rows are no profile's.

The harvest (stage 7) is the exception to "counted". How many requests it
asks follows what retrieval finds and what the model reads, and neither is
known before it asks. So its basis is the trace of documents this profile has
harvested already, in the harvest directory (`--out`): requests and tokens
per section by kind of request, scaled to the sections still to harvest. With
no such trace it says it cannot estimate, and the command ends non-zero.

Author: Felix Vossel

## Classes

### EstimateError

```python
class EstimateError(Exception)
```

A stage whose work could not be counted at all.

### Where

```python
@dataclass
class Where
```

What the estimate reads: the profile's files and the ledger.

Fields:

- `profile: object`
- `pdf_dir: Path`
- `processed: Path`
- `db: Path`
- `out: Optional[Path]`
- `ledger: dict`
- `prices: dict`
- `unattributed: int = 0`: ledger rows of runs from before the profile

### Estimate

```python
@dataclass
class Estimate
```

One stage's figures, each with the line that says where it comes from.

Fields:

- `command: str`
- `what: str`
- `model: Optional[str] = None`
- `work: list = field(default_factory=list)`: [(count, unit)]
- `notes: list = field(default_factory=list)`: what is not counted
- `requests: Optional[int] = None`
- `kinds: list = field(default_factory=list)`: [(count, kind of request)]
- `tokens_in: Optional[int] = None`
- `tokens_out: Optional[int] = None`
- `tokens_embedded: Optional[int] = None`
- `cached_in: int = 0`
- `basis: str = ""`
- `missing: Optional[str] = None`: why the requests could not be counted

## Functions

### ingest

```python
def ingest(where: Where) -> Estimate
```

### preprocess

```python
def preprocess(where: Where) -> Estimate
```

Stages 2 and 3. Its own rule (pipeline.run_folder): a PDF of the
folder whose processed directory has no sections.json is still to do.

### refine

```python
def refine(where: Where) -> Estimate
```

Stage 4. Its own rule (refine.run_refine): a document with a stage-3
result and no refined result is still to do, and so is one with an
unfinished pass of the same input, of which only the windows the server
did not serve are asked.

### visuals

```python
def visuals(where: Where) -> Estimate
```

Stage 5. Its own rule (pipeline.run_single): a table without a
"markdown" and a figure without a "description" in visuals.json is still
to do, unless its image is missing, which the stage skips.

### chunk

```python
def chunk(where: Where) -> Estimate
```

Stage 6. Its own rule (pipeline.run, the embed step): the inputs of a
merged document that have no embedding in the database yet. The merge and
the database step come first in the same run and ask no model.

### extract

```python
def extract(where: Where) -> Estimate
```

Stage 7. Its own rule (runner.documents_to_harvest): a current
document whose harvest is missing, unstamped or, under the ontology's
keys and the PDF it was read from, current is not to do; the others
are.

### report

```python
def report(est: Estimate, prices: dict) -> list
```

The lines of one stage's estimate.

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
