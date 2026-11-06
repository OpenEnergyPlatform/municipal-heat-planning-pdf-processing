# docpipe.visuals.replies

`docpipe/visuals/replies.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

replies.py: The reply each vision request asks for, as a JSON schema.

The grammar of every request of this stage and of page transcription, on
every provider (see `docpipe.providers.grammar`). The prompts state the same
shapes in words; nothing here is a check beyond the required keys, the first
of which `vision.call_vision` reads as text. The first entry of `required` in
each schema is that key.

Author: Felix Vossel

[Back to the index](../README.md)
