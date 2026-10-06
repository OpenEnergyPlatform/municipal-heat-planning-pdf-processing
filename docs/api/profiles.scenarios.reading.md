# profiles.scenarios.reading

`profiles/scenarios/reading.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

reading.py: What the refinement, visuals and page-transcription stages say to
the model when its reply was not the one JSON object that was asked for.

The prompts of these stages are English in this profile, so the sentences are
too. (The extraction prompts are German, and extraction.PHRASES is not this
table: it is the harvest's own.) See docpipe/reading.py for what each name is
filled with.

Author: Felix Vossel

[Back to the index](../README.md)
