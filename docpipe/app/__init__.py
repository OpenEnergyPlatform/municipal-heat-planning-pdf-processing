"""
app: The chat over a processed corpus, and the page on which a person
decides about harvested values.

`app.py` is the only module that imports Streamlit; `docpipe chat` runs it.
`config.py` is where every path and limit of the app is read, `pdf_link.py`
draws the cited page of the source PDF and builds the link into an external
viewer, and `sandbox_service.py` is the service that runs code a model wrote
(`docpipe sandbox`), on the machine where that is allowed.

Author: Felix Vossel
"""
