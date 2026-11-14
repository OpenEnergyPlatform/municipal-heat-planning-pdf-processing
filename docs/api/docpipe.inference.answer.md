# docpipe.inference.answer

`docpipe/inference/answer.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

answer.py: Runs one retrieval and answer turn, with no user interface
attached.

The chat app and the batch runner ask the same question of the same
corpus. Only what they do with the progress and the result differs,
so everything the turn needs from outside is passed in: the open
corpus, how to embed a query, where an image lives, and an optional
progress reporter.

Author: Felix Vossel

## Classes

### Corpus

```python
@dataclass
class Corpus
```

The open resources one turn works on.

Fields:

- `conn: sqlite3.Connection`
- `index: Any`
- `id_to_pos: dict`
- `embed: Callable[[dict], tuple]`: query item -> (vector, came_from_cache)
- `resolve_image: Callable[[Optional[str]], Optional[Path]] = lambda p: None`: stored image path -> a readable path, or None
- `log_conn: Optional[sqlite3.Connection] = None`
- `lexical: Optional[sqlite3.Connection] = None`: The word index beside the vectors (`lexical.py`), or None: the search is then by meaning alone.
- `document_label: Callable[[Optional[int]], Optional[str]] = lambda i: None`: document id -> what a reader calls the document. Asked only when the whole corpus is searched, where a source has to say whose it is. Where it says nothing, the document's file name does (`_whose`).
- `retrieve: Optional[Callable] = None`: How the corpus is searched: `hybrid.retrieve` over the index and the database, else a corpus's own (the editor's try of the chat, which searches made-up passages).

### Anchor

```python
@dataclass
class Anchor
```

What a turn searches with: how the query is made (`mode`: text,
image+text or image), the item the embedding is given, the search
sentence, whether the question asks to look again, and the temporary
file of an image.

Fields:

- `mode: str`
- `item: dict`
- `phrase: Optional[str]`
- `recheck: bool`
- `tmp_path: Optional[str] = None`

### Packed

```python
@dataclass
class Packed
```

The sources a turn reads (`top_hits`, best first) and the batches
they are asked in, each fitting the context.

Fields:

- `top_hits: list`
- `batches: list`

### Asked

```python
@dataclass
class Asked
```

What the batches came to: the statements that stood their check, in
the order they were made (`shown`), how many were made and dropped
(statements, not batches and not citations), the sources the model read,
the crops it asked for, whether a batch was asked without the statements
that stood before it (`ahead`), and how many batches were taken.

Fields:

- `shown: list = field(default_factory=list)`
- `made: int = 0`
- `dropped: int = 0`
- `examined: set = field(default_factory=set)`
- `requested: list = field(default_factory=list)`
- `ahead: bool = False`
- `batches: int = 0`

## Functions

### scopes_are_visual

```python
def scopes_are_visual(scopes: list) -> bool
```

True if the query targets ONLY figure/table scopes → caption-style anchor.

### search_hits

```python
def search_hits(task: str, phrase: Optional[str], query_vec, corpus: Corpus,
                document_id: Optional[int], scopes: list, *,
                image_only: bool = False, exclude=frozenset(),
                top_k: Optional[int] = None, words: bool = True) -> list
```

The passages a turn searches: the hybrid search over the scopes'
embedding types, *top_k* of them (TOP_K), best first. One definition for
the chat and for whoever measures its search, so the two cannot drift
apart.

The word index is asked with the question and its search anchor: the
question has the names and numbers, the anchor the wording a document
would use. An image query has no words to ask it with, and *words*
False asks it with none (the search is by meaning alone).

### answer_question

```python
def answer_question(task: str, corpus: Corpus, document_id: Optional[int],
                    scopes: list, *,
                    image_bytes: Optional[bytes] = None, image_only: bool = False,
                    as_json: bool = False, history: Optional[list] = None,
                    progress: Callable = _silent) -> dict
```

Execute one full retrieval + answer turn. *document_id* None asks the
whole corpus: every source then names its document. Returns a dict with:
answer (str|None), answer_text (str|None), citations (list[dict]),
n_findings (int), cache_hit (bool), n_hits (int), phrase (str|None),
as_json (bool), n_batches (int), compute (list), examined, recheck,
n_excluded, requested (block ids), statements (list[dict]),
statements_made / statements_shown / statements_dropped /
statements_repeated (int, counting statements), faults (list of
{"request", "cause"}).

The answer is made of the statements the model wrote whose evidence
stood in the source they cite (`statements.back`); the rest are counted
in `statements_dropped`, never shown. Each batch is told the statements
already checked and writes only new ones, so what was checked is carried
forward as it was and the model cannot rewrite it. Batches may be sent
ahead of that (`pool.in_order`) and are taken in order all the same; what
one of them says again is named by one request over the checked
statements and leaves (`statements_repeated`). `answer_text` is the
same statements without list marks and citation numbers, which is what a
follow-up and a comparison read.

answer is None when nothing was retrieved or no statement was backed.
`faults` says which requests of the turn stayed unreadable: with no
statement made and a fault on the answer, the sources were not read, and
that is not "nothing found in them". `as_json` is True only when the
answer was reshaped as JSON; where that did not happen the answer is the
prose and `faults` says why.

### answer_from_values

```python
def answer_from_values(task: str, corpus: Corpus, values: list,
                       document_id: Optional[int], *, as_json: bool = False,
                       history: Optional[list] = None,
                       progress: Callable = _silent) -> dict
```

The question answered from the passages the harvest read *values*
from, as `answer_question` answers it from the passages a search found.

The harvest decides which passages are read and the model decides which
of their numbers answer the question: the total or a carrier, which
variant, which year. Every statement stands its check against its
passage exactly as in a document turn, and the citations are the same
kind. Returns what `answer_question` returns; `n_hits` counts passages.

### make_anchor

```python
def make_anchor(task: str, scopes: list, *, image_bytes: Optional[bytes] = None,
                image_only: bool = False, history: Optional[list] = None,
                visual: Optional[bool] = None,
                progress: Callable = _silent) -> Anchor
```

Step 1 of a turn: the search sentence the model writes for the
question (none for a question that is only an image). *visual* None
takes a caption-style sentence where every scope is a table or figure
(`scopes_are_visual`); an image with text always does.

### examined_before

```python
def examined_before(history: Optional[list]) -> set
```

The sources the attempts before a re-check examined.

A re-check ("schau noch einmal nach") searches PAST the sources earlier
attempts already examined — otherwise it re-reads the same top sources
and can only repeat itself. Walk back through the whole re-check chain to
the original question, or the second re-check resurfaces the first
turn's sources.

### embed_anchor

```python
def embed_anchor(corpus: Corpus, anchor: Anchor,
                 progress: Callable = _silent) -> tuple
```

Step 2: (the query's vector, whether it came from the cache). The
temporary file of an image is removed after.

### sandbox

```python
def sandbox() -> Optional[Callable]
```

Where a turn runs code: the sandbox (`code_exec.run_code`) where it
is set up, else nowhere.

### pack

```python
def pack(hits: list, most: Optional[int] = None,
         context_tokens: Optional[int] = None) -> Packed
```

Step 4a: the best *most* hits (MAX_CHUNK_ATTEMPTS) in batches of at
most *context_tokens* (ANSWER_CONTEXT_TOKENS) each.

The real tokenizer, not the char/4 heuristic: German prose runs ~3.0-3.5
chars per token and table markdown lower still, so a batch packed as
10k "tokens" was really 12-14k and overran the context it was sized for.
get_tokenizer() falls back to the heuristic on its own when offline.

### ask_batches

```python
def ask_batches(task: str, corpus: Corpus, document_id: Optional[int],
                packed: Packed, faults: list, compute: list, *, history,
                until_complete: bool = True,
                progress: Callable = _silent,
                code_runner=SANDBOX) -> Asked
```

Step 4b: the answer across the batches, each statement checked
against its source; a further batch runs only while the answer is still
incomplete (with *until_complete*). The code runs of the batches are
added to *compute*; they run in *code_runner*, the sandbox where it is
set up unless the caller gives another (None: nowhere).

### drop_repeats

```python
def drop_repeats(task: str, asked: Asked,
                 progress: Callable = _silent) -> set
```

Step 4c: the statements that say again what an earlier one said, by
their place, taken out of `asked.shown`. A batch asked ahead did not see
what came before it. Only then can a statement be a repeat, and only
then is this asked.

### refine_readoff

```python
def refine_readoff(task: str, corpus: Corpus, shown: list, citations: list,
                   most: Optional[int] = None,
                   progress: Callable = _silent) -> None
```

Step 4d: every image-derived value read again in a focused
single-image call, at most *most* (READOFF_MAX_CALLS).

The big call only IDENTIFIES which figure carries the answer; with ten
sources and several charts in one prompt it misreads (returned a stack's
total height as one segment). The sentence of the focused call is then
the statement itself: the model's first wording of it is not shown.

### assemble

```python
def assemble(task: str, corpus: Corpus, document_id: Optional[int],
             scopes: list, asked: Asked, repeated: set, citations: list,
             result: dict, faults: list, *, mode: str,
             phrase: Optional[str], start_time: float) -> bool
```

Step 5a: the answer made of the statements that stood their check,
into *result*. False where none stood: then the log says why (the
replies could not be read, none was backed, none was made).

### json_answer

```python
def json_answer(task: str, result: dict, progress: Callable = _silent) -> None
```

Step 5b: the answer reshaped as JSON, in *result*, and `as_json`
True; where the reply could not be read the answer stays prose and
`as_json` is False.

The shape is the user's, written as prose in the task, so it is made
by one more call over the checked text. That call can add or leave
out, and nothing checks what it wrote; the citations stand below.

### log_answer

```python
def log_answer(corpus: Corpus, document_id: Optional[int], task: str,
               scopes: list, result: dict, faults: list, *, mode: str,
               phrase: Optional[str], start_time: float) -> None
```

Step 5c: the log line of an answered turn, over the answer as it is
shown (after `json_answer`).

[Back to the index](../README.md)
