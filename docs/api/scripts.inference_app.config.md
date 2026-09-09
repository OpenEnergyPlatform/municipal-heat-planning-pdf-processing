# scripts.inference_app.config

`scripts/inference_app/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py: Central configuration for the inference_app module.

Every value is overridable through an environment variable; the defaults
are safe placeholders. The corpus paths (the database, the FAISS index,
the image root, the knowledge-graph file) default to the active profile's
own paths, or to the historical `data/` layout when no profile is set; an
explicit environment variable overrides both.

Author: Felix Vossel

[Back to the index](../README.md)
