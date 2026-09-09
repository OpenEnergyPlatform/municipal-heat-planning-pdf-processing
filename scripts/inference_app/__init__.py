"""
__init__.py: Marks inference_app as a package, a Streamlit retrieval and
question answering chat front end over a docpipe corpus.

The corpus is produced by the batch pipeline and read as a SQLite database
(`data/KWP.db` by default, or the active profile's own path) together with
a global FAISS index.

Author: Felix Vossel
"""
