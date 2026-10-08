"""
app.py: Starts the chat from where it used to live.

The app is part of the package now (docpipe/app/app.py) and `docpipe chat`
starts it. This file is what a deployment that still runs

    streamlit run scripts/inference_app/app.py

executes: it puts the checkout on the path and hands over.

Author: Felix Vossel
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from docpipe.app.app import main  # noqa: E402

main()
