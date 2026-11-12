# docpipe.ruleset.requests

`docpipe/ruleset/requests.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

requests.py: Asking the model: the request, its model, waiting and retrying,
the lanes of requests side by side (runner.py, throttle.py, scheduler.py,
llm_preflight.py, providers, settings.py).

Every value here stood in the code, or was read once at the start of the run
(owner, 2026-11-11: "alles soll anpassbar sein"). A request reads them where
it is sent, in the step that sends it, so each can have a value of its own at
a step.

[Back to the index](../README.md)
