# docpipe.ruleset

`docpipe/ruleset/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

ruleset: the rules of the reading by the part of the run that reads them.

Each module names its rules (`RULES`, made with `kit.rule`) with
the kinds of steps that read them (`steps`); their values stand in the
default profile's rules.json like every rule of the core.

[Back to the index](../README.md)
