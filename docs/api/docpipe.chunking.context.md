# docpipe.chunking.context

`docpipe/chunking/context.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

context.py: A sentence of context before each table and figure of the index.

Owner decision 2026-11-17, from the literature on contextual retrieval (a 2026
BM25 study finds a context sentence per piece the one extension with a steady
gain on number questions): with the rule `context_sentence` on, the chat model
is asked for each table and figure for one sentence that says what it is
about, in which unit, for which area, scenario and years, as far as the table
or figure, its caption and the heading of its section say it. The entries of
the table or figure in the index begin with that sentence
(`chunking.build_embedding_inputs`, `pieces.item_pieces`); a stage that embeds
without the rule on reads none.

The request shows the whole table or figure (owner decision 2026-11-17,
"Nichts kürzen"): its text whole, its caption and the heading of its section.
A table whose request does not fit the model's window is asked in parts
(`requests_of`): each part shows the table's title, head and the lines under
it, the rows its rows stand under, and as many of its rows as fit, and each
part's sentence goes before the entries whose rows stand in that part
(`lead_of`). The window is the server's (`docpipe.window`).

A sentence is kept beside the document's results (CONTEXT_SENTENCES_JSON), under
the hash of exactly what the request showed and of the prompt, so it is asked
again only when the table, the caption, the heading or the prompt changed; how
a table was asked in parts is kept with it, under the hash of the whole
request, so that the embedding finds the sentences without asking the server.
The database holds the sentence its vectors were embedded with (Tables and
Images, column `context_sentence`; the parts as one JSON list), which is how
`--step sync` finds that a changed sentence is a changed entry.

An answer that is not one JSON object with the key `sentence` is asked again,
with its cause named, as often as stage 4 asks (refine_max_attempts), and is
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

What the request shows of one table or figure, whole, or None for one
that has neither a caption nor a text to say anything about.

### requests_of

```python
def requests_of(kind: str, section: dict, item: dict,
                fits: Optional[Callable[[dict], bool]] = None) -> list
```

[(request, first line, last line)] that ask for the sentences of one
table or figure: the whole where it fits (*fits*, the model's window;
everything fits where none is given), lines None; else one request per
part, each showing the lines every piece of the table shows and as many
of its own rows as fit, with the first and the last of them. [] for one
with nothing to show. `window.TooLong` where the lines every part shows
do not fit beside one row, or, for an item without rows of its own, do
not fit at all: nothing is cut, the caller names the item.

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

### read_kept

```python
def read_kept(pdf_dir: Path) -> tuple
```

({key: sentence}, {key of a whole request: [[first, last, key]]})
kept for a document; empty where there is none or the file does not
read.

### read_store

```python
def read_store(pdf_dir: Path) -> dict
```

{key: sentence} kept for a document.

### write_store

```python
def write_store(pdf_dir: Path, sentences: dict,
                parts: Optional[dict] = None) -> None
```

### kept_sentence

```python
def kept_sentence(request: dict, salt: str, sentences: dict, parts: dict)
```

The sentence kept for what *request* shows (a string), the sentences
of its parts ([{"first", "last", "sentence"}], the ones answered), or
None.

### attach

```python
def attach(merged: dict, pdf_dir: Path, salt: Optional[str] = None) -> dict
```

*merged* with `context_sentence` set on every table and figure whose
kept sentence, or kept sentences of its parts, answer what the request
shows now; the others get none.

### load_document

```python
def load_document(pdf_dir: Path, salt: Optional[str] = None) -> dict
```

A document's merged JSON, with its kept sentences where the rule is on.

### sentences_of

```python
def sentences_of(value) -> list
```

[(first line, last line, sentence)] of an item's `context_sentence`:
a sentence for the whole (lines None), the parts' sentences as a list,
or that list as the JSON the database holds; [] for none.

### stored

```python
def stored(value) -> Optional[str]
```

An item's `context_sentence` as the database holds it: the sentence,
or the parts' sentences as one JSON list.

### lead_of

```python
def lead_of(item: dict, first: Optional[int], last: Optional[int]) -> str
```

The sentence and its line break that go before the entry of *item*
whose own lines run from *first* to *last*: the sentence of the whole,
or of the part that holds its first line (the first part for an entry
of carried lines only); "" where there is none.

### ask_document

```python
def ask_document(merged: dict, pdf_dir: Path, ask: Callable, *,
                 salt: Optional[str] = None, workers: int = 1,
                 fits: Optional[Callable[[dict], bool]] = None) -> dict
```

Ask for the sentences of each table and figure of one document that
has none kept for what it shows now; keep what came back. *ask* takes a
request and returns the sentence or None; *fits* says whether a request
fits the model's window (`requests_of`). Returns the counts: asked,
answered and dropped (requests: sent, with a sentence back, without
one), kept and too_long (tables and figures: with their sentences there
already; too long to be asked in any part, each named in the log and
left without a sentence).

### ask_all

```python
def ask_all(data_dir: Path, ask: Optional[Callable] = None,
            fits: Optional[Callable[[dict], bool]] = None) -> dict
```

Ask for every document under *data_dir*, when the rule is on; {} when it
is off (nothing is asked, nothing is written).

### messages_of

```python
def messages_of(system: str, request: dict) -> list
```

### window_fits

```python
def window_fits(system: str, max_tokens: int, *, base_url: str, model: str,
                api_key: str = "") -> Callable[[dict], bool]
```

fits(request): does a request with *system* and room for a reply of
*max_tokens* tokens fit the window of the server at *base_url*? The
window is the server's (`docpipe.window.served_limit`), else the rule
`model_window_tokens`; a request whose bytes and the frame of an empty
request fit is let through uncounted, any other one is counted by the
server's own template (`/tokenize`), and by its bytes where the server
counts none.

### make_ask

```python
def make_ask() -> tuple
```

(ask, fits): the request to the chat model of the refinement stage
(LLM_BASE_URL, LLM_MODEL, or the profile's provider settings), and
whether a request fits its window.

### ask_model

```python
def ask_model(client, request: dict, *, system: str, model: str,
              temperature: float, max_tokens: int, max_retries: int,
              wait: Callable = time.sleep,
              fits: Optional[Callable] = None) -> Optional[str]
```

One request. The reply is read as exactly one JSON object with the key
`sentence`; a reply that is not is asked again with its cause named, at most
*max_retries* times, all of it shown where that fits the window (*fits*
over messages), else the request anew with its cause named
(`reading.again`). None where no sentence came back.

[Back to the index](../README.md)
