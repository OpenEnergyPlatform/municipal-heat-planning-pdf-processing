# docpipe.visuals.vision

`docpipe/visuals/vision.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

vision.py: Vision model interaction layer over an OpenAI compatible
API.

Creates the client, checks model availability, and makes the chat
completions call that sends a base64 encoded image and reads the one
JSON object that comes back. The reply schema is the grammar of the
request; the reply is read as exactly one object (see
docpipe/reading.py): nothing is stripped, cut out, closed or salvaged,
and no second, unconstrained request fills in for a reply that could
not be read.

Author: Felix Vossel

## Functions

### create_client

```python
def create_client(base_url: str | None = None, timeout: float | None = None)
```

The client of the vision model, for the provider it is set to.

### check_model_available

```python
def check_model_available(
    client: openai.OpenAI,
    model: str = VLM_MODEL,
) -> bool
```

Verifies that the vLLM endpoint is reachable and serves *model*.

### reply_type

```python
def reply_type(reply: tuple) -> type
```

What the first required key of *reply* (a `replies` entry) has to be
in the reply: a list where its schema is an array, else text.

### logged

```python
def logged(traced: dict | None, sent: dict, image_path: Path,
           picture: bytes | None, attempt: int, asked_at: float, *,
           response=None, error=None) -> None
```

One attempt of a request in the request log of the stage, as the
harvest writes its own (`docpipe.extraction.trace`; owner request
2026-11-19, A3): the request as sent, its reply or error, its times,
the tokens it cost and what *traced* says of it (`doc`, `kind`, what
its messages are `made` of, its item, page and heading). The picture is
written as the file it is cut from (its path in the document's folder,
for a strip with the strip's sha256 and height), not as its data: the
file stays beside the log, and a strip is cut from it again the same
way (`strips.strip_of`). Nothing where *traced* is None.

### call_vision

```python
def call_vision(
    client: openai.OpenAI,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    *,
    reply: tuple,
    model: str = VLM_MODEL,
    max_retries: int | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    repetition_penalty: float | None = None,
    budget: int | None = None,
    picture: bytes | None = None,
    traced: dict | None = None,
) -> dict | Hole
```

Sends an image + prompt to the vision model and reads the one JSON object
it answers with.

*max_retries*, *temperature* and *max_tokens* are the rules
vision_max_attempts, figure_temperature and vision_max_tokens where not
given.

The wall-clock bound per request is the client timeout set by
create_client(), not *max_retries*. *reply* is the (name, schema) of the
object asked for (see `replies`): the grammar of every request, and its
first required key (a table's `rows`, a figure's `description`) has to be
in the reply as what its schema says, a list or text (`reply_type`).

A reply that is not that object is asked again with its cause named, the
answer echoed back. A reply that was cut off at its token limit is not
asked again as it stands: an image has no halves, so it is asked once more
from the original prompt with more room and the next repetition penalty (a
runaway grid is what ends at the limit), without a word about the cut. The
room is twice *max_tokens* or as much as the served window leaves,
whichever is smaller (`llm_preflight.further_room`); where it leaves none
the request ends at once in the Hole "cut_off" and nothing more is sent,
as it does when the further attempt is cut off too. A table is then read
in strips (`strips`, by `process.process_table`); a figure has no
content.

*budget* is the largest request, in tokens, of the stage this call belongs
to: the prompt, the largest input and ONE reply of *max_tokens*, which its
preflight checked the window against. Without it the room is twice.

*picture*, where given, is the PNG sent instead of the file at
*image_path* (a strip of it, `strips`); the file still names the request
in the log.

*traced*, where given, writes every attempt into the request log of
the stage (`stage_log`): {"doc", "kind", "made", and what else the log
notes of the request}; see `logged`.

Returns:
    The parsed JSON dict, or a Hole that names why there is none:
    "refused" for a request the server rejected itself (a 4xx, which no
    retry would change), "not_served" when the last attempt got no answer,
    "error" for a failure of our own after the reply arrived, or the cause
    the reply was unreadable for (see `reading`).

[Back to the index](../README.md)
