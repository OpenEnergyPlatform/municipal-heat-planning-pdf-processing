"""__init__.py: Retrieval and grounded answering, usable from a UI or
from a batch job.

`Corpus` and `answer_question` are loaded when they are first asked for and
not when the package is. A command that builds the word index (`lexical.py`)
or reads harvested values has no use for the answer loop and the libraries
it brings, and a module run as a command must not have been imported by its
own package before it runs.
"""

__all__ = ["Corpus", "answer_question"]


def __getattr__(name: str):
    if name in __all__:
        from . import answer
        return getattr(answer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
