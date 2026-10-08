# docpipe.cli

`docpipe/cli.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

cli.py: The one command.

    docpipe [--profile P] [--config FILE] <command> [arguments]

A stage binds part of what a profile and a project say when it is imported.
So this module imports no stage. It settles the profile and the project file
first, and then runs the stage the way `python -m docpipe.<stage>` runs it,
which keeps working and takes the same arguments.

Author: Felix Vossel

## Functions

### main

```python
def main(argv: Optional[Sequence[str]] = None) -> int
```

[Back to the index](../README.md)
