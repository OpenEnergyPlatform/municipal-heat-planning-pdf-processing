# docpipe.artifacts

`docpipe/artifacts.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

artifacts.py: Names the per-document result files under `<doc>/results/`,
in the order the pipeline writes them.

One definition serves all five pipeline modules: a filename spelled out in
four separate config.py files drifts, and the module that reads a file is
rarely the one that wrote it.

Author: Felix Vossel

[Back to the index](../README.md)
