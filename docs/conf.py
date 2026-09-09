"""Sphinx configuration for the Read the Docs site.

It renders the Markdown that `scripts/build_docs.py` generates and does not
generate anything itself: the pages are checked in, and
`tests/test_docs_build.py` fails when a page and its source disagree. So this
file imports nothing from the project, which is why the docs build needs
neither the GPU stack nor the corpus.

`autodoc` is deliberately absent for the same reason: importing
`docpipe.preprocessing.stage2_layout` to render its docstring would pull in
OpenCV, PyMuPDF and torch. The docstrings reach the site through the
generator, which reads them with `ast`.
"""
import re

project = "municipal heat planning pdf processing"
author = "Felix Vossel"
copyright = "2026, Felix Vossel"

extensions = ["myst_parser"]

# The generated pages carry ordinary Markdown links between each other
# (`../README.md`), because they are also read in the repository. Sphinx
# resolves those to the built pages.
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

source_suffix = {".md": "markdown"}
master_doc = "index"

# `README.md` is the repository-side index; `index.md` is the site's, and it
# carries the toctree. Both are generated, and excluding neither would give
# Sphinx two documents that are not in any toctree.
# `_intros/` holds the prose the generator folds into the pages. Those
# files are sources, not pages, and Sphinx would otherwise build each
# one as a document nothing links to.
exclude_patterns = ["_build", "_intros", "requirements.txt",
                    "README.md"]

html_theme = "furo"
html_title = "docpipe"
html_static_path = []

# A link to a page that does not exist is a broken site, and the generated
# index links every page there is. Warnings are errors in .readthedocs.yaml,
# so this is enforced rather than reported.
nitpicky = True

_README_LINK = re.compile(r"\]\((\.\./)?README\.md(#[^)]*)?\)")


def _site_links(app, docname, source):
    """`README.md` links become `index.md` links while the site is built.

    Every generated page ends in a link back to `README.md`, the index a
    reader of the repository opens. The site excludes that file (see above)
    and has `index.md` in its place, so left alone each of those links is a
    missing cross-reference and, with warnings as errors, a failed build.
    Measured on the first build: 19 warnings, all of them this one.
    """
    source[0] = _README_LINK.sub(r"](\g<1>index.md\g<2>)", source[0])


def setup(app):
    app.connect("source-read", _site_links)
