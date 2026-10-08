# docpipe.inference

`docpipe/inference/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

\_\_init\_\_.py: Retrieval and grounded answering, usable from a UI or
from a batch job.

`Corpus` and `answer_question` are loaded when they are first asked for and
not when the package is. A command that builds the word index (`lexical.py`)
or reads harvested values has no use for the answer loop and the libraries
it brings, and a module run as a command must not have been imported by its
own package before it runs.

## Exports

What `__all__` names, and where each name is defined:

- `Corpus`
- `answer_question`

[Back to the index](../README.md)
