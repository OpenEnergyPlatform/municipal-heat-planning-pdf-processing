# docpipe.run

`docpipe/run.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

run.py: `docpipe run`, the stages that turn a folder into a corpus.

    docpipe run [--from STAGE] [--to STAGE] [--skip STAGE ...]

ingest, preprocess, refine, visuals, chunk and lexical, in that order, for
the profile in effect. Each is started the way `docpipe <stage>` starts it,
in a process of its own: a stage that holds a model, or dies, leaves nothing
behind for the next one. The harvest (`extract`) is not among them: it needs
a spec, and what it costs is for its own command to say.

A stage is given the arguments its command line needs and the profile
knows, and no others: ingest takes its paths from the profile and needs
`--source` only where the profile's source has a document list to name,
preprocess takes the profile's PDF folder as its input, refine and visuals
take `--batch` (their input is the profile's processed folder). A stage that
cannot start without an argument the profile cannot give is named before any
stage starts. The run stops at the first stage that ends non-zero, with that
stage's exit code.

Author: Felix Vossel

## Functions

### select

```python
def select(first: Optional[str] = None, last: Optional[str] = None,
           skip: Sequence[str] = ()) -> list
```

The stages from *first* to *last* without those in *skip*, in order.
A range that holds no stage is an error, not an empty run.

### stage_command

```python
def stage_command(stage: str, arguments: Sequence[str]) -> list
```

The process that is `docpipe <stage> <arguments>`. The profile and the
project file reach it through the environment.

### launch

```python
def launch(command: Sequence[str]) -> int
```

Run *command* to its end and return its exit code.

### run_stages

```python
def run_stages(profile, stages: Sequence[str],
               launcher: Optional[Callable] = None) -> int
```

Start *stages* one after the other, for *profile*. Returns 0 when all
ended 0, else the exit code of the first that did not. Nothing is started
while a stage lacks an argument the profile cannot give.

### main

```python
def main(rest: Sequence[str]) -> int
```

[Back to the index](../README.md)
