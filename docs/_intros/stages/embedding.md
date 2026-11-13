## Purpose

`docpipe.embedding` turns an item dict, `{"text": ...}` or, for a backend
that can see images, `{"text": ..., "image": ...}`, into a vector, behind
one interface. `get_embedder()` (`docpipe/embedding/__init__.py:65`)
returns an object offering `embed()` and `embed_one()`, hiding which of
three backends does the work. Which backend runs is a matter of
`EMBEDDING_BACKEND`, not of the caller's code: `local` loads the model in
this process and keeps it resident on the GPU (`docpipe/embedding/local.py`);
`api` calls an embeddings endpoint, in one of two request forms chosen by
`EMBEDDING_API_FORMAT`: the OpenAI `/v1/embeddings` request, text only, or the
chat form a vLLM server takes, which also embeds a picture
(`docpipe/embedding/api.py`); a spec of the form `package.module:attribute`
imports that module and calls the named attribute with the caller's own
keyword arguments, the extension point for an implementation this
repository does not contain (`docpipe/embedding/__init__.py:47` to `62`).

Only the query side of the pipeline calls `get_embedder()`. The corpus itself
is built by stage 6 (see [chunking](chunking.md)), which never imports it. Its
own `load_embedder()` follows `EMBEDDING_INDEX_BACKEND`, a setting apart from
`EMBEDDING_BACKEND`: with `local`, the default, it talks to the embedding model
directly through `MultiGPUEmbedder`, since a batch run already owns the GPU it
was launched on and never has to swap backends mid-run, so the indirection this
package offers is unused overhead there. With `api` it returns an
`ApiIndexEmbedder` that wraps `docpipe.embedding.api.ApiEmbedder`, so the corpus
build uses this package's api backend, though not its factory. It embeds text
only in the OpenAI form and text and pictures in the messages form. What does
call `get_embedder()` is code asking the already-built corpus a question
after the fact: the retrieval sweep of stage 7 embedding a probe, or a
batch of probes, against the FAISS index
(`docpipe/extraction/runner.py:422`, `517`, `1938`), the inference app
embedding one chat turn's query (`docpipe/app/app.py`, `embed_query`), and
`docpipe values-index` embedding a line for each harvested value so that the
chat can find values by meaning (`docpipe/inference/values_index.py`). All of
them can run on hardware not used for the corpus build: a laptop
with no GPU pointed at `api`, or a small card that cannot hold an 8B model
resident, which is what the import-path form exists for.

## Position in the pipeline

| | |
|---|---|
| In | Item dicts from a caller already holding the corpus: a probe's text from the retrieval sweep (`docpipe/extraction/runner.py`), a chat query from the app (`docpipe/app/app.py`), a line of a harvested value from `docpipe values-index`; plus the `EMBEDDING_*` variables `docpipe/embedding/config.py` reads once |
| Out | A list of float vectors, in input order; nothing is written to disk, the database, or the FAISS index by this package |
| Resumes on | Nothing: `embed()` and `embed_one()` are plain functions of their input, so there is no cache or stamp file to clear |
| Needs | No GPU by default: `local` needs a CUDA device or falls back to the CPU; `api` needs network access; import-path needs whatever the deployment's class requires |

No numbered stage in the diagram on [How the parts fit together](../pipeline.md)
owns this page. It sits below stage 6's FAISS index and takes no part in
building it except through `ApiEmbedder` when `EMBEDDING_INDEX_BACKEND=api`
(see Purpose), and is called from three places downstream of that index: the
retrieval sweep inside [extraction](extraction.md), one chat turn inside
[the app](app.md) and the build of the values index (`docpipe values-index`).
No caller reconstructs the corpus's own
`embedding_type` vocabulary (`docpipe/chunking/config.py`); that label is
attached only after this package has already returned a vector.

## Method

### Choosing a backend

`get_embedder(backend=None, **kwargs)` takes an explicit `backend` or falls
back to `config.BACKEND`, strips whitespace, and dispatches: `:` in the
spec goes to `_from_path()`; the literal names `api` and `local`
(case-insensitive) construct `ApiEmbedder(**kwargs)` or
`LocalEmbedder(**kwargs)`; anything else raises `ValueError`. Every call
builds a fresh instance; nothing here is cached
(`docpipe/embedding/__init__.py:65` to `82`). While a cassette is being
replayed (`DOCPIPE_CASSETTE_REPLAY`) the call returns the cassette's
`ReplayEmbedder` before any of this and builds no backend (see [measuring a
harvest](evaluation.md)).

### The import-path extension point

`_from_path(spec, **kwargs)` splits `spec` on its first `:` into a module
and an attribute name. `import_module()` is tried, then `getattr()` for the
attribute; each raises `ImportError` or `AttributeError` respectively,
re-raised as `ValueError` naming the spec and the original error. The
resolved class or factory function is called with `**kwargs`, and whatever
it returns is the embedder (`docpipe/embedding/__init__.py:47` to `62`).

### Embedding through an endpoint

`ApiEmbedder.__init__` resolves `base_url`, `api_key`, `model`, `batch_size`
and the request form against `config.*`, raising `ValueError` at once if
`base_url` is still empty and the embedding role is not a hosted API, if the
form is neither `input` nor `messages`, or if the form is `messages` and
`base_url` is empty. `text_only` is true in the `input` form and false in the
`messages` form (`docpipe/embedding/api.py:103` to `125`).

The `input` form, the default, is the OpenAI `/v1/embeddings` request.
`embed()` scans items for an `image` key and refuses the whole call if any
carry one, rather than embedding only the text half; otherwise it chunks
`text` values into groups of `batch_size` and sends each chunk through
`_create`, concatenating results in order. `_create` calls
`self.client().embeddings.create()` once for a server of one's own, whose
client retries by itself, and for a hosted API that answers "not now" asks
again, up to `HOSTED_ATTEMPTS` times in all (`docpipe/embedding/api.py:133` to
`152`, `188` to `204`).

The `messages` form is the chat a vLLM server takes. `conversation(item)`
builds the turns of `Qwen3VLEmbedder.format_model_input`. The system turn
carries the instruction, `DEFAULT_INSTRUCTION` ("Represent the user's
input.") when the item names none, with a full stop added when it ends
without punctuation. The user turn holds the picture, an `image_url` data URI,
before the text, and "NULL" stands for an item with neither. An empty
assistant turn follows, which the request continues
(`continue_final_message`), so the pooled last token is the one the model's own
code pools (`docpipe/embedding/api.py:64` to `91`). `embed()` sends all items of
one call as concurrent requests, one chat each, and the server batches them;
`batch_size` is not used. The vectors come back scaled to length one by
`unit_rows`, because the index is an inner-product index of unit vectors
(`docpipe/embedding/api.py:94` to `99`, `154` to `186`).

`embed_one()` wraps one item in a one-element list and calls `embed()`
(`docpipe/embedding/api.py:206`).

### Embedding with a resident local model

`LocalEmbedder.__init__` stores `model` and `max_length` (falling back to
`config.*`) and sets `self._resident` to `None`; nothing loads yet. On the
first call to `embed()`, a double-checked lock (check, acquire
`self._lock`, check again) constructs
`docpipe.chunking.qwen3_vl_embedding.MultiGPUEmbedder`; later calls reuse
that instance. `embed()` then calls `self._resident.process(list(items))`,
not `.embed()` (`MultiGPUEmbedder` speaks `process()` and returns a tensor
in its device's precision, bf16 on a GPU and fp32 on the CPU), converting
the result with `.detach().float().cpu().tolist()`.
`normalize` is left at its default (`True`) because the vectors already
stored in the index were written with that same default; embedding a
query any other way would score it against them incorrectly rather than
raise (`docpipe/embedding/local.py:37` to `69`).

Every local call embeds in length groups (`Qwen3VLEmbedder.process` wraps
`_embed` in `qwen3_vl_embedding.in_groups`, owner decision 2026-11-07): the
inputs are sorted by length (`_input_size`), cut into up to `PAD_GROUPS = 10`
groups of neighbouring lengths (`pad_groups`), and each group is one forward,
padded only to its own longest input; the rows come back in the caller's
order. This holds for the index, the queries and the names, on a GPU and on
the CPU. One forward over 240 scenario names (mean 116 characters, longest
403) padded all of them to the longest and cost 2.3 times their tokens.

### What the local backend delegates to

`MultiGPUEmbedder` is not part of this package; it belongs to stage 6 (see
[chunking](chunking.md)), which also constructs it independently for the
batch build. `LocalEmbedder` only holds one instance and calls its
`process()`; what that call actually does is described under Modules,
below (`docpipe/chunking/qwen3_vl_embedding.py:410` to `495`).

## Data model

The `Embedder` protocol (`docpipe/embedding/__init__.py:37` to `44`) is the
only shape this package defines: `embed(items: Sequence[dict]) -> list` and
`embed_one(item: dict) -> list`. An item dict carries `text` (a string or
`None`) and, optionally, `image` (a file path or URL string). The
underlying local model also recognizes `video`, `instruction`, `fps` and
`max_frames` per item (`docpipe/chunking/qwen3_vl_embedding.py:240` to
`247`), but no caller in this repository sets these. In the `input`
form `ApiEmbedder` reads only `text`, refusing `image` and silently ignoring
any other key. In the `messages` form it reads `text`, `image` and
`instruction`, and ignores any other key.

The output is a plain list of Python floats per item, its dimension a
property of whichever model is running (`EMBEDDING_DIM`, declared but
never asserted here). No table, file, or FAISS entry is written by this
package; storing a returned vector is the caller's job.

## Configuration

| name | kind | default | effect | where |
|---|---|---|---|---|
| `EMBEDDING_BACKEND` | environment variable | `"local"` | Selects `local`, `api`, or an import-path spec; a `backend` argument to `get_embedder()` overrides it per call | `docpipe/embedding/config.py:19` |
| `EMBEDDING_MODEL` | environment variable | `"Qwen/Qwen3-VL-Embedding-8B"` | HF model id, or served model name for `api` | `docpipe/embedding/config.py:21` |
| `EMBEDDING_DIM` | environment variable | `4096` | Vector width the rest of the pipeline sizes its FAISS index to; not checked here | `docpipe/embedding/config.py:22` |
| `EMBEDDING_MAX_TOKEN_LENGTH` | environment variable | `16384` | Token ceiling passed as `max_length`, overriding `qwen3_vl_embedding.py`'s own default of `8192` | `docpipe/embedding/config.py:23` |
| `EMBEDDING_BATCH_SIZE` | environment variable | `8` | Texts per `/v1/embeddings` request; read by `ApiEmbedder`, and by `docpipe values-index` for the lines it embeds per call | `docpipe/embedding/config.py:24` |
| `EMBEDDING_BASE_URL` | environment variable | `""` | Endpoint for `api`; empty raises `ValueError` at construction | `docpipe/embedding/config.py:27` |
| `EMBEDDING_API_KEY` | environment variable | `"EMPTY"` | API key for `api`; the placeholder works against endpoints that do not check it | `docpipe/embedding/config.py:28` |
| `EMBEDDING_API_FORMAT` | environment variable | `"input"` | Request form of `api`: `input` is the OpenAI request, text only; `messages` is the chat form a vLLM server takes, with the picture and the model's own instruction, and needs `EMBEDDING_BASE_URL`; any other value raises `ValueError` | `docpipe/embedding/config.py:35` |

`get_embedder(**kwargs)` forwards `**kwargs` unfiltered to the chosen
backend's constructor, so only the names that constructor defines take
effect: `model` and `max_length` for `local`
(`docpipe/embedding/local.py:38` to `39`); `base_url`, `api_key`, `model`,
`batch_size` and `form` for `api` (`docpipe/embedding/api.py:103` to `105`).
`EMBEDDING_DIM` matches no parameter on either backend and cannot be
overridden this way; a name belonging to the other backend raises
`TypeError`. `docpipe/chunking/config.py` imports `EMBEDDING_DIM`,
`EMBEDDING_MODEL` and `EMBEDDING_MAX_TOKEN_LENGTH` from here rather than
declaring its own copies, a fix for a defect its own comment records:
setting `EMBEDDING_MODEL` in `.env` once moved only the query side and left
the index builder on the old model, same dimension, different vectors, no
error raised anywhere (`docpipe/chunking/config.py:13` to `16`).

## Failure modes

- `EMBEDDING_BACKEND` (or a `backend` argument) that is not `local`, `api`,
  and contains no `:` makes `get_embedder()` raise `ValueError` naming the
  three valid forms (`docpipe/embedding/__init__.py:80` to `82`). An
  import-path spec with no `:` is refused before any import is attempted
  (`docpipe/embedding/__init__.py:50` to `53`); an unimportable module or
  a missing attribute instead raise `ValueError` from an actual, failed
  `import_module()` or `getattr()` call (`docpipe/embedding/__init__.py:54`
  to `61`).
- `ApiEmbedder` constructed with no usable `base_url` raises `ValueError`
  in the constructor, before any request is attempted, unless the embedding
  role is a hosted API, which needs none (`docpipe/embedding/api.py:114` to
  `115`). A form other than `input` or `messages`, or the `messages` form
  with no `base_url` even for a hosted role, raises `ValueError` there too
  (`docpipe/embedding/api.py:111` to `118`).
- `ApiEmbedder.embed()` in the `input` form, called with any item carrying
  an `image` key, refuses the whole call with `ValueError` naming the
  offending indices, rather than silently embedding only the text half
  (`docpipe/embedding/api.py:188` to `193`). The `messages` form embeds the
  picture instead.
- In the `messages` form a failing request raises from the `httpx` call or
  `raise_for_status()` and propagates: nothing is retried, and the other
  requests of the call are not cancelled (`docpipe/embedding/api.py:154` to
  `164`, `179` to `186`).
- A dead endpoint or a rejected model name is not caught: whatever the
  `openai` client raises propagates unchanged, and nothing is retried against
  a server of one's own; only a hosted API that answers "not now" is asked
  again, in the `input` form (`docpipe/embedding/api.py:133` to `152`).
- Two or more threads calling `LocalEmbedder.embed()` before the model has
  ever loaded are serialized by the double-checked lock, so only the first
  thread through constructs `MultiGPUEmbedder`; without the second check
  inside the lock, concurrent threads could each start their own load
  (`docpipe/embedding/local.py:48` to `58`).
- `ApiEmbedder.client()` builds `self._client` the same lazily-checked
  way, but with no lock: two threads calling `embed()` before any client
  exists could each construct their own `OpenAI` client
  (`docpipe/embedding/api.py:127` to `131`).
- A single replica's forward pass raising inside `MultiGPUEmbedder.process()`
  is captured per thread; once every thread joins, the first captured
  exception is re-raised on the main thread and the whole call fails
  (`docpipe/chunking/qwen3_vl_embedding.py:470` to `484`).
- A sequence truncated to `max_length` is still embedded, not refused, but
  logged with its index and real token count
  (`docpipe/chunking/qwen3_vl_embedding.py:344` to `351`).

## Measured behaviour

- Calling `.embed()` directly on `MultiGPUEmbedder`, instead of the
  `.process()` it actually exposes, raised `AttributeError`, meaning the
  local backend had never once run successfully before this was corrected
  (`docpipe/embedding/local.py:59` to `62`, comment).
- One resident replica occupies roughly 16 GB of GPU memory that nothing
  releases for the life of the process, the reason `embed()` guards its
  lazy load rather than using a bare check
  (`docpipe/embedding/local.py:50` to `53`, comment).
- In the pilot that motivated the singleton `docpipe/extraction/runner.py`
  wraps around `get_embedder()`, five replicas of the model fit on one
  card, a sixth raised a CUDA out-of-memory error, and none of the
  sixteen documents in that pilot completed
  (`docpipe/extraction/runner.py:422` to `433`, the `embedder()`
  docstring).
- The `api` backend batches eight texts per request by default
  (`docpipe/embedding/config.py:24`), a different number from the 32 items
  `docpipe/chunking/config.py:32` batches into one call to the model when
  the corpus is built, a constant this package neither reads nor uses.

## Modules

`docpipe/embedding/__init__.py` defines the `Embedder` protocol and
`get_embedder()`, the one factory every caller uses to obtain a backend.
It is what `docpipe/extraction/runner.py`, `docpipe/app/app.py`,
`docpipe/inference/values_index.py` and `scripts/inference_app_smoketest.py`
import `get_embedder` from.

`docpipe/embedding/config.py` declares the `EMBEDDING_*` environment
variables once, read directly by the other modules here and re-exported,
not redeclared, by `docpipe/chunking/config.py`,
`docpipe/inference/faiss_store.py` and `docpipe/app/config.py`.

`docpipe/embedding/local.py` implements `LocalEmbedder`, the GPU-resident
backend that lazily constructs and holds one `MultiGPUEmbedder` behind a
double-checked lock, translating its `process()`/tensor interface into
this package's `embed()`/list-of-floats contract. It is used directly by
`docpipe/extraction/runner.py` and, through `get_embedder()`, by
`docpipe/app/app.py`.

`docpipe/embedding/api.py` implements `ApiEmbedder`, the backend calling an
embeddings endpoint in one of two forms: the OpenAI-compatible `/v1/embeddings`
request in batches, text only (or, with `EMBEDDING_PROVIDER` set to `openai` or
`gemini`, that hosted API; see [the provider layer](providers.md)), or the chat
form of a vLLM server, which also embeds a picture. It is constructed by
`get_embedder()` when `EMBEDDING_BACKEND=api`, and by
`docpipe/chunking/embedding.py`'s `ApiIndexEmbedder` when
`EMBEDDING_INDEX_BACKEND=api`.

`docpipe/chunking/qwen3_vl_embedding.py` is not part of this package, but
`LocalEmbedder` depends on it entirely: `Qwen3VLForEmbedding` (a Qwen3-VL
wrapper returning hidden states, no language-modeling head),
`Qwen3VLEmbedder` (one replica, forward pass, pooling, normalization) and
`MultiGPUEmbedder` (one replica per visible GPU, length-balanced sharding,
order-preserving reassembly). Its own account, and
`docpipe/chunking/embedding.py`'s independent, direct use of
`MultiGPUEmbedder` for the corpus build when `EMBEDDING_INDEX_BACKEND` is
`local`, are documented at [chunking](chunking.md).
