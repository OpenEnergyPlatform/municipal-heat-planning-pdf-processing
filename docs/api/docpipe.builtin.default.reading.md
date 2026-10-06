# docpipe.builtin.default.reading

`docpipe/builtin/default/reading.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reading.py: What the refinement, visuals and page-transcription stages say to
the model when its reply was not the one JSON object that was asked for, in
English.

The prompts of these stages are English, so the sentences are. A profile
that words those prompts in another language writes its own table. See
docpipe/reading.py for what each name is filled with: a phrase is a template
for `str.format`, `!r` shows a value the way the model wrote it, and a brace
that is meant as a brace is doubled.

Author: Felix Vossel

[Back to the index](../README.md)
