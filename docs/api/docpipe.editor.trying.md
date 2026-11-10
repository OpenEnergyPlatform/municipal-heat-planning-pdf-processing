# docpipe.editor.trying

`docpipe/editor/trying.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

trying.py: A recorded request sent once more with a changed prompt, and what
the new answer is worth.

"Try" takes requests of a trace, makes each one's instruction from the text
being edited (`prompts.preview`) and sends it as it was recorded otherwise:
the same message, reply form and settings, to the model the installation
names for it. One request is one call, never repeated, and a click sends
`LIMIT` at most (owner decision 2026-11-10: "nicht mit 20, max 3"). Nothing
is sent by anything else in the editor.

The new answer is read as the run reads one (`runner._loads_object`,
`runner._lacking`), and each address it names is held against the lines the
request showed with the run's own check (`addressed.resolve`). The lines
are those of the recorded message, so a line's cells are taken from its
text: a row of a table as the run cuts one, any other line where "|"
divides it in two or more.

Where the model is: EDIT_TRY_BASE_URL, EDIT_TRY_API_KEY and EDIT_TRY_MODEL;
without the first, the text model of the run (LLM_BASE_URL, LLM_API_KEY,
LLM_MODEL) where the environment names one. With neither, nothing is sent
and the reason is said.

Author: Felix Vossel

## Classes

### Refused

```python
class Refused(ValueError)
```

A try that is not sent, said in one sentence.

## Functions

### settings

```python
def settings() -> dict
```

Where a try goes: `configured`, and then `base_url`, `api_key`,
`model` and the `host` to show; else `why` not.

### client_of

```python
def client_of(config: dict)
```

The run's client for the text model, at the address of *config*.
It repeats nothing.

### shown_of

```python
def shown_of(payload) -> object
```

The lines a message shows, as the run keeps them (`units.Shown`):
every text in *payload* that starts with an address, under the letter
of its block.

### addresses

```python
def addresses(answer, payload) -> list
```

Each address *answer* names, with whether it holds against what
*payload* showed: `holds` None for the answer that nothing shown says
it (0), else whether the run's check takes it, with its reason
(`why`) where it does not.

### once

```python
def once(client, model: str, request: dict, sent: dict, view: dict) -> dict
```

One call: the recorded request *sent* with the instruction (and,
for a request asked once more, the message) of *view*
(`prompts.preview`), and what came back.

### run

```python
def run(profile, trace, indexes: list, edits: dict, read: Callable, *,
        config: Optional[dict] = None,
        make_client: Optional[Callable] = None) -> dict
```

The requests *indexes* of *trace* (`requests.Trace`), each sent once
with the texts of *edits*. `Refused` where nothing may be sent: more
than `LIMIT` requests, none, or no model named. A request whose
instruction cannot be put together is not sent and says why.

[Back to the index](../README.md)
