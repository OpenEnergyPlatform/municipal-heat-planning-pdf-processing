# docpipe.inference.llm_client

`docpipe/inference/llm_client.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

llm_client.py – Remote LLM (OpenAI-compatible) for search-phrase generation and
chunk-by-chunk question answering.

Two independent budgets (do not conflate):
  * MAX_CHUNK_ATTEMPTS  – how many content chunks are shown to the LLM (the
    outer loop, in app.py).
  * LLM_MAX_RETRIES     – re-tries of a *single* call on malformed JSON or a
    transport error (the inner loop here). Does not advance the chunk count.

Author: Felix Vossel

## Functions

### get_client

```python
def get_client() -> OpenAI
```

Lazily build the OpenAI-compatible client (own retry loop → max_retries=0).

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
Never raises.

### revise_with_readings

```python
def revise_with_readings(task: str, answer_text: str, readings: list[str]) -> str
```

Fold the focused read-offs into the answer; the original on any failure.

### visual_reading

```python
def visual_reading(support: dict, attached_images: set) -> Optional[str]
```

The read-off text of a valid image-based support, else None.

Valid only when the cited index's crop was actually attached to the call —
otherwise a "image" support could launder parametric knowledge past the
grounding gate, which is exactly what the verbatim-quote rule exists to stop.

### answer_from_sources

```python
def answer_from_sources(task: str, chunk_items: list[dict],
                        prior: Optional[str] = None, as_json: bool = False,
                        code_runner=None, code_context: Optional[dict] = None,
                        max_compute: int = 0, history: Optional[list] = None,
                        images: Optional[dict] = None,
                        image_requester=None, max_image_requests: int = 0) -> dict
```

Answer `task` from the given batch of sources, extending an optional `prior`
partial answer. Returns:
    {"found": bool, "complete": bool, "answer": \<str|dict>,
     "supports": [{"index", "quote"} | {"index", "image", "reading"}],
     "compute": [{"code", "output"}], "attached_images": [\<int>, ...]}
`complete=False` → more sources may be needed. The CALLER must validate each
support against chunk_items (grounded_quote for text, visual_reading for
image-based ones); this function does not.

`images` maps an item index to a local crop path; those crops are attached
to the call so the model can read values that exist only in a chart.
`attached_images` lists the indices that actually made it into the request —
the only ones a "image" support may legitimately cite.

When `code_runner` is given and `max_compute > 0`, the model may reply with
{"action":"python","code":...} to offload a calculation: `code_runner(code,
code_context)` is called (→ {"ok","stdout","stderr","error"}), its printed
output fed back, and the model finalises — up to `max_compute` runs.

### format_as_json

```python
def format_as_json(task: str, answer_text: str) -> str
```

Reformat a finished text answer as a pretty JSON string (schema from the task).

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

[Back to the index](../README.md)
