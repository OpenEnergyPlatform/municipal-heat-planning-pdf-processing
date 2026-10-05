# docpipe.app

`docpipe/app/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

app: The chat over a processed corpus, and the page on which a person
decides about harvested values.

`app.py` is the only module that imports Streamlit; `docpipe chat` runs it.
`config.py` is where every path and limit of the app is read, `pdf_link.py`
builds the link into the source PDF, and `sandbox_service.py` is the
service that runs code a model wrote (`docpipe sandbox`), on the machine
where that is allowed.

Author: Felix Vossel

[Back to the index](../README.md)
