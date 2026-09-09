# scripts.inference_app

`scripts/inference_app/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

\_\_init\_\_.py: Marks inference_app as a package, a Streamlit retrieval and
question answering chat front end over a docpipe corpus.

The corpus is produced by the batch pipeline and read as a SQLite database
(`data/KWP.db` by default, or the active profile's own path) together with
a global FAISS index.

Author: Felix Vossel

[Back to the index](../README.md)
