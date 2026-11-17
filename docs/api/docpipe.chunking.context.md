# docpipe.chunking.context

`docpipe/chunking/context.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

context.py: A sentence of context before each table and figure of the index.

Owner decision 2026-11-17, from the literature on contextual retrieval (a 2026
BM25 study finds a context sentence per piece the one extension with a steady
gain on number questions): with the rule `context_sentence` on, the chat model
is asked once for each table and figure for one sentence that says what it is
about, in which unit, for which area, scenario and years, as far as its
caption, its head and the heading of its section say it. The text input and the
text of the picture input of the table or figure begin with that sentence
(`chunking.build_embedding_inputs`); a stage that embeds without the rule on
reads none.

A sentence is kept beside the document's results (CONTEXT_SENTENCES_JSON), under
the hash of exactly what the request showed and of the prompt, so it is asked
again only when the caption, the head, the heading or the prompt changed. The
database holds the sentence its vectors were embedded with (Tables and Images,
column `context_sentence`), which is how `--step sync` finds that a changed
sentence is a changed entry.

An answer that is not one JSON object with the key `sentence` is asked again,
with its cause named, as often as the other stages ask (MAX_RETRIES), and is
never embedded: the table or figure keeps its text as it was and is asked again
by the next run. Nothing is repaired.

Author: Felix Vossel

## Functions

### enabled

```python
def enabled() -> bool
```

### items_of

```python
def items_of(merged: dict)
```

(kind, section, item) of every table and figure of a merged document.

### shown

```python
def shown(kind: str, section: dict, item: dict) -> Optional[dict]
```

What the request shows of one table or figure, or None for one that has
neither a caption nor a body to say anything about.

### key_of

```python
def key_of(request: dict, salt: str) -> str
```

The hash of exactly what a request shows, and of the prompt it is asked
with.

### prompt_salt

```python
def prompt_salt() -> str
```

### read_store

```python
def read_store(pdf_dir: Path) -> dict
```

{key: sentence} kept for a document; {} where there is none or the file
does not read.

### write_store

```python
def write_store(pdf_dir: Path, sentences: dict) -> None
```

### attach

```python
def attach(merged: dict, pdf_dir: Path, salt: Optional[str] = None) -> dict
```

*merged* with `context_sentence` set on every table and figure whose
kept sentence answers what the request shows now; the others get none.

### load_document

```python
def load_document(pdf_dir: Path, salt: Optional[str] = None) -> dict
```

A document's merged JSON, with its kept sentences where the rule is on.

### ask_document

```python
def ask_document(merged: dict, pdf_dir: Path, ask: Callable, *,
                 salt: Optional[str] = None, workers: int = 1) -> dict
```

Ask for the sentence of each table and figure of one document that has
none kept for what it shows now; keep what came back. *ask* takes the
request and returns the sentence or None. Returns the counts: asked,
answered, kept (already there), dropped (no sentence came back).

### ask_all

```python
def ask_all(data_dir: Path, ask: Optional[Callable] = None) -> dict
```

Ask for every document under *data_dir*, when the rule is on; {} when it
is off (nothing is asked, nothing is written).

### make_ask

```python
def make_ask() -> Callable
```

The request to the chat model of the refinement stage (LLM_BASE_URL,
LLM_MODEL, or the profile's provider settings).

### ask_model

```python
def ask_model(client, request: dict, *, system: str, model: str,
              temperature: float, max_tokens: int, max_retries: int,
              wait: Callable = time.sleep) -> Optional[str]
```

One request. The reply is read as exactly one JSON object with the key
`sentence`; a reply that is not is asked again with its cause named, at most
*max_retries* times. None where no sentence came back.

[Back to the index](../README.md)
