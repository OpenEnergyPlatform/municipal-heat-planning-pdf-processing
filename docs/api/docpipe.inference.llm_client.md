# docpipe.inference.llm_client

`docpipe/inference/llm_client.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

llm_client.py – Remote LLM (OpenAI-compatible) for search-phrase generation and
batch-by-batch question answering.

Two independent budgets (do not conflate):
  * MAX_CHUNK_ATTEMPTS: how many content chunks are shown to the LLM (the
    outer loop, in answer.py).
  * LLM_MAX_RETRIES: attempts of a *single* call: a reply that cannot be
    read is asked again with its cause named, a transport error after a
    pause (the inner loop here). Does not advance the chunk count.

A reply is exactly one JSON object, read by `docpipe.reading`. Nothing is
repaired: no fence, no think block, no text around the object is removed, and
no bracket is closed. A reply that is not that object is classified, asked
again with the cause named, and where it stays unreadable the request ends
with a `ReplyError` that carries the cause. A reply cut off at its token
limit is not asked again as it stands: a batch of excerpts is halved, and a
single unit gets more room once.

Author: Felix Vossel

## Classes

### ReplyError

```python
class ReplyError(RuntimeError)
```

A request that ended with no reply that could be read.

*cause* is one of `reading.HOLE_CAUSES` (the last thing that went wrong:
a reply that was not the one object, a reply cut off at its token limit,
or a server that did not answer), *request* the name of the reply that
was asked for. A RuntimeError, so what always caught the failure of a
call still does; what is new is that it says why.

#### ReplyError.\_\_init\_\_

```python
def __init__(self, cause: str, request: str, attempts: int = 1)
```

## Functions

### get_client

```python
def get_client()
```

Lazily build the client (own retry loop → max_retries=0).

### collecting

```python
@contextlib.contextmanager
def collecting()
```

The faults of the requests made inside the block, as a list of
{"request": the reply asked for, "cause": why there is none}.

### note_fault

```python
def note_fault(request: str, cause: str) -> None
```

Record that *request* has no reply, in the turn that is collecting.

### describe_faults

```python
def describe_faults(faults: list) -> str
```

"request: cause" per kind of fault, with "xN" where it happened N
times, in the order the first of each happened.

### choose

```python
def choose(prompt, task: str, question: str, options: dict) -> Optional[str]
```

One closed question: the answer is a key of `options`, or None.

The KG route's field request. `prompt` is the profile's, loaded by
kg_route; the payload keys are the wire protocol and its prose is not.
An answer outside the list is None and never the nearest key: the caller
reads None as "no constraint", and a guessed key would filter the graph
on something nobody asked. An empty list is a number slot, and any
non-empty answer passes through for the caller to parse.

### grounded_quote

```python
def grounded_quote(quote, chunk_item: dict) -> Optional[str]
```

Return the cleaned quote iff it is a grounded verbatim span of `chunk_item`.

### make_search_phrase

```python
def make_search_phrase(task: str, visual: bool = False,
                       history: Optional[list] = None) -> tuple[str, bool]
```

Turn a free-text extraction task into a HyDE-style search anchor: a short
hypothetical passage written as it would appear IN a heat plan, rather than a
question. `visual=True` produces a figure/caption-style anchor instead.

Returns (phrase, recheck). `recheck` is True when the task re-asks an earlier
question from the history ("schau noch einmal nach") — the caller then steers
retrieval away from the sources that earlier attempt already examined. Only
meaningful with history; forced False without one.

Never raises: falls back to (raw task, False), which is always a safe
retrieval probe. The anchor is only a retrieval probe — the answer still
comes from the real retrieved text under the grounding gate.

### ask_chunk

```python
def ask_chunk(task: str, chunk_items: list[dict]) -> dict
```

Ask the LLM to answer `task` using only `chunk_items`.

Returns {"found": True, "answer", "quote"} or {"found": False}. Never raises:
a malformed response, an empty answer, or a quote that is not grounded in the
excerpt all come back as {"found": False}.

### read_off_image

```python
def read_off_image(task: str, image_path: str, hint: str) -> Optional[dict]
```

Focused single-image read-off: one crop, one short question — the setting
in which the model demonstrably reads charts correctly, unlike the big
answer call whose many sources and images dilute attention (observed:
total bar height returned as a single segment's value).

Returns the parsed {"reading", "value", "unit", "confidence"} or None.
Never raises. None leaves the turn's record a fault: a reply that could
not be read is the request's `ReplyError`, a reading that came back blank
is noted here.

### crop_id

```python
def crop_id(block) -> str
```

A crop a model names (as a statement's `block`, or as the `id` it asked
for) as a block id: the model quotes what it saw, and what it saw was
[p17_img1].

### visual_reading

```python
def visual_reading(statement: dict, attached_images: set,
                   delivered=frozenset()) -> Optional[str]
```

The read-off text of a valid image-based statement, else None.

Valid only when the crop it names was actually in front of the model: the
cited index's crop was attached to the call, or the block is one the model
asked for and got (`delivered`); otherwise an "image" statement could
launder parametric knowledge past the grounding gate, which is exactly
what the verbatim-quote rule exists to stop. The reading has to say what
was read (8 characters at least).

### answer_from_sources

```python
def answer_from_sources(task: str, chunk_items: list[dict],
                        prior: Optional[list] = None,
                        code_runner=None, code_context: Optional[dict] = None,
                        max_compute: int = 0, history: Optional[list] = None,
                        images: Optional[dict] = None,
                        image_requester=None, max_image_requests: int = 0,
                        _depth: int = 0) -> dict
```

Answer `task` from the given batch of sources with statements, each with
its own evidence (`replies.answer`). `prior` is the texts of the
statements already checked in earlier batches, or None; only new
statements come back. Returns:
    {"statements": [\<what the model wrote>], "complete": bool,
     "compute": [{"code", "output"}], "attached_images": [\<int>, ...],
     "requested": [{"block_id", "delivered", ...}], "fault": cause | None}
`complete=False` → more sources may be needed. The CALLER checks every
statement against its source (`statements.back`); this function does not.
There is no `found`: a batch said something if `statements` is not empty.

`fault` is None when a reply was read. A request that stays unreadable
leaves `statements` empty and names the cause (and is noted in the turn's
fault list); it is a hole, never "nothing found". A reply cut off at its
token limit halves the batch (up to SPLIT_DEPTH times) and joins what the
halves say; a single excerpt gets more room once, then it is a hole.

`images` maps an item index to a local crop path; those crops are attached
to the call so the model can read values that exist only in a chart.
`attached_images` lists the indices that actually made it into the request —
the only ones an "image" statement may legitimately cite by index.

When `code_runner` is given and `max_compute > 0`, the model may reply with
{"action":"python","code":...} to offload a calculation: `code_runner(code,
code_context)` is called (→ {"ok","stdout","stderr","error"}), its printed
output fed back, and the model finalises, up to `max_compute` runs. The
runs are numbered from 1 in every call, which is what a "computed"
statement names as its `run`.

### format_as_json

```python
def format_as_json(task: str, answer_text: str) -> Optional[str]
```

Reformat a finished text answer as a pretty JSON string (schema from the task).

None where this model cannot be asked for it: the shape is the user's own
and exists only as prose in the task, so there is no schema to generate
in, and a model that is asked inside schemas only is not asked for it.
That is noted as a fault of the turn, so the reader is told that the
answer stays prose, where it used to get a JSON that was only the answer
wrapped in a key. A request that stays unreadable raises `ReplyError`.

### compare_answers

```python
def compare_answers(task: str, plans: list) -> Optional[str]
```

Compare the finished answers of several documents. None on any failure.

`plans` is [{"label", "answer"}] and that is all the call gets: no source
text, no quotes, no pages. With the passages in front of it the model can
ground a claim about one document in another document's sentence, and the
citations shown under the table are per document -- they would not show
it. An entry whose answer is None found nothing grounded, which the prompt
is told to report rather than fill in.

A failure leaves a fault in the collecting turn: a request that stays
unreadable through `_chat_json`, a comparison that came back blank here.

[Back to the index](../README.md)
