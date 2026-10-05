# scripts.inference_app.app

`scripts/inference_app/app.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

app.py: Starts the chat from where it used to live.

The app is part of the package now (docpipe/app/app.py) and `docpipe chat`
starts it. This file is what a deployment that still runs

    streamlit run scripts/inference_app/app.py

executes: it puts the checkout on the path and hands over.

Author: Felix Vossel

[Back to the index](../README.md)
