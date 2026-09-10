# The embedders

## Purpose

`docpipe.embedding` turns an item dict, `{"text": ...}` or, for a backend
that can see images, `{"text": ..., "image": ...}`, into a vector, behind
one interface. `get_embedder()` (`docpipe/embedding/__init__.py:65`)
returns an object offering `embed()` and `embed_one()`, hiding which of
three backends does the work. Which backend runs is a matter of
`EMBEDDING_BACKEND`, not of the caller's code: `local` loads the model in
this process and keeps it resident on the GPU (`docpipe/embedding/local.py`);
`api` calls an OpenAI-compatible `/v1/embeddings` endpoint
(`docpipe/embedding/api.py`); a spec of the form `package.module:attribute`
imports that module and calls the named attribute with the caller's own
keyword arguments, the extension point for an implementation this
repository does not contain (`docpipe/embedding/__init__.py:47` to `62`).

Only the query side of the pipeline calls it. The corpus itself is built by
stage 6 (see [chunking](chunking.md)), and that build talks to the
embedding model directly through its own `load_embedder()` and
`MultiGPUEmbedder`, never importing `get_embedder()`: a batch run already
owns the GPU it was launched on and never has to swap backends mid-run, so
the indirection this package offers is unused overhead there. What does
call `get_embedder()` is code asking the already-built corpus a question
after the fact: the retrieval sweep of stage 7 embedding a probe, or a
batch of probes, against the FAISS index
(`docpipe/extraction/runner.py:276`, `371`, `1453`), and the inference app
embedding one chat turn's query (`scripts/inference_app/app.py:112` to
`122`). Both can run on hardware not used for the corpus build: a laptop
with no GPU pointed at `api`, or a small card that cannot hold an 8B model
resident, which is what the import-path form exists for.

## Position in the pipeline

| | |
|---|---|
| In | Item dicts from a caller already holding the corpus: a probe's text from the retrieval sweep (`docpipe/extraction/runner.py`), a chat query from the app (`scripts/inference_app/app.py`); plus the `EMBEDDING_*` variables `docpipe/embedding/config.py` reads once |
| Out | A list of float vectors, in input order; nothing is written to disk, the database, or the FAISS index by this package |
| Resumes on | Nothing: `embed()` and `embed_one()` are plain functions of their input, so there is no cache or stamp file to clear |
| Needs | No GPU by default: `local` needs a CUDA device or falls back to the CPU; `api` needs network access; import-path needs whatever the deployment's class requires |

No numbered stage in the diagram on [How the parts fit together](../pipeline.md)
owns this page. It sits below stage 6's FAISS index, but takes no part in
building it, and is called from two places downstream of that index: the
retrieval sweep inside [extraction](extraction.md) and one chat turn
inside [the app](app.md). Neither caller reconstructs the corpus's own
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
(`docpipe/embedding/__init__.py:65` to `79`).

### The import-path extension point

`_from_path(spec, **kwargs)` splits `spec` on its first `:` into a module
and an attribute name. `import_module()` is tried, then `getattr()` for the
attribute; each raises `ImportError` or `AttributeError` respectively,
re-raised as `ValueError` naming the spec and the original error. The
resolved class or factory function is called with `**kwargs`, and whatever
it returns is the embedder (`docpipe/embedding/__init__.py:47` to `62`).

### Embedding through an OpenAI-compatible endpoint

`ApiEmbedder.__init__` resolves `base_url`, `api_key`, `model` and
`batch_size` against `config.*`, raising `ValueError` at once if
`base_url` is still empty. `embed()` scans items for an `image` key and
refuses the whole call if any carry one, rather than embedding only the
text half; otherwise it chunks `text` values into groups of `batch_size`
and calls `self.client().embeddings.create()` once per chunk, concatenating
results in order. `embed_one()` wraps one item in a one-element list and
calls `embed()` (`docpipe/embedding/api.py:24` to `57`).

### Embedding with a resident local model

`LocalEmbedder.__init__` stores `model` and `max_length` (falling back to
`config.*`) and sets `self._resident` to `None`; nothing loads yet. On the
first call to `embed()`, a double-checked lock (check, acquire
`self._lock`, check again) constructs
`docpipe.chunking.qwen3_vl_embedding.MultiGPUEmbedder`; later calls reuse
that instance. `embed()` then calls `self._resident.process(list(items))`,
not `.embed()` (`MultiGPUEmbedder` speaks `process()` and returns a bf16
tensor), converting the result with `.detach().float().cpu().tolist()`.
`normalize` is left at its default (`True`) because the vectors already
stored in the index were written with that same default; embedding a
query any other way would score it against them incorrectly rather than
raise (`docpipe/embedding/local.py:36` to `68`).

### What the local backend delegates to

`MultiGPUEmbedder` is not part of this package; it belongs to stage 6 (see
[chunking](chunking.md)), which also constructs it independently for the
batch build. `LocalEmbedder` only holds one instance and calls its
`process()`; what that call actually does is described under Modules,
below (`docpipe/chunking/qwen3_vl_embedding.py:385` to `478`).

## Data model

The `Embedder` protocol (`docpipe/embedding/__init__.py:37` to `44`) is the
only shape this package defines: `embed(items: Sequence[dict]) -> list` and
`embed_one(item: dict) -> list`. An item dict carries `text` (a string or
`None`) and, optionally, `image` (a file path or URL string). The
underlying local model also recognizes `video`, `instruction`, `fps` and
`max_frames` per item (`docpipe/chunking/qwen3_vl_embedding.py:230` to
`237`), but no caller in this repository sets these. `ApiEmbedder` reads
only `text`, refusing `image` and silently ignoring any other key.

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
| `EMBEDDING_BATCH_SIZE` | environment variable | `8` | Texts per `/v1/embeddings` request; read only by `ApiEmbedder` | `docpipe/embedding/config.py:24` |
| `EMBEDDING_BASE_URL` | environment variable | `""` | Endpoint for `api`; empty raises `ValueError` at construction | `docpipe/embedding/config.py:27` |
| `EMBEDDING_API_KEY` | environment variable | `"EMPTY"` | API key for `api`; the placeholder works against endpoints that do not check it | `docpipe/embedding/config.py:28` |

`get_embedder(**kwargs)` forwards `**kwargs` unfiltered to the chosen
backend's constructor, so only the names that constructor defines take
effect: `model` and `max_length` for `local`
(`docpipe/embedding/local.py:37` to `38`); `base_url`, `api_key`, `model`
and `batch_size` for `api` (`docpipe/embedding/api.py:25` to `26`).
`EMBEDDING_DIM` matches no parameter on either backend and cannot be
overridden this way; a name belonging to the other backend raises
`TypeError`. `docpipe/chunking/config.py` imports `EMBEDDING_DIM`,
`EMBEDDING_MODEL` and `EMBEDDING_MAX_TOKEN_LENGTH` from here rather than
declaring its own copies, a fix for a defect its own comment records:
setting `EMBEDDING_MODEL` in `.env` once moved only the query side and left
the index builder on the old model, same dimension, different vectors, no
error raised anywhere (`docpipe/chunking/config.py:11` to `14`).

## Failure modes

- `EMBEDDING_BACKEND` (or a `backend` argument) that is not `local`, `api`,
  and contains no `:` makes `get_embedder()` raise `ValueError` naming the
  three valid forms (`docpipe/embedding/__init__.py:77` to `79`). An
  import-path spec with no `:` is refused before any import is attempted
  (`docpipe/embedding/__init__.py:50` to `53`); an unimportable module or
  a missing attribute instead raise `ValueError` from an actual, failed
  `import_module()` or `getattr()` call (`docpipe/embedding/__init__.py:54`
  to `61`).
- `ApiEmbedder` constructed with no usable `base_url` raises `ValueError`
  in the constructor, before any request is attempted
  (`docpipe/embedding/api.py:31` to `32`).
- `ApiEmbedder.embed()` called with any item carrying an `image` key
  refuses the whole call with `ValueError` naming the offending indices,
  rather than silently embedding only the text half
  (`docpipe/embedding/api.py:41` to `46`).
- A dead endpoint or a rejected model name is not caught: whatever the
  `openai` client raises propagates unchanged, and nothing is retried
  (`docpipe/embedding/api.py:52`).
- Two or more threads calling `LocalEmbedder.embed()` before the model has
  ever loaded are serialized by the double-checked lock, so only the first
  thread through constructs `MultiGPUEmbedder`; without the second check
  inside the lock, concurrent threads could each start their own load
  (`docpipe/embedding/local.py:47` to `57`).
- `ApiEmbedder.client()` builds `self._client` the same lazily-checked
  way, but with no lock: two threads calling `embed()` before any client
  exists could each construct their own `OpenAI` client
  (`docpipe/embedding/api.py:35` to `39`), and no test exercises
  concurrent calls on it the way
  `test_the_local_backend_guards_its_lazy_load` does for `LocalEmbedder`.
- A single replica's forward pass raising inside `MultiGPUEmbedder.process()`
  is captured per thread; once every thread joins, the first captured
  exception is re-raised on the main thread and the whole call fails
  (`docpipe/chunking/qwen3_vl_embedding.py:453` to `467`).
- A sequence truncated to `max_length` is still embedded, not refused, but
  logged with its index and real token count
  (`docpipe/chunking/qwen3_vl_embedding.py:329` to `336`).

## Measured behaviour

- Calling `.embed()` directly on `MultiGPUEmbedder`, instead of the
  `.process()` it actually exposes, raised `AttributeError`, meaning the
  local backend had never once run successfully before this was corrected
  (`docpipe/embedding/local.py:58` to `61`, comment).
- One resident replica occupies roughly 16 GB of GPU memory that nothing
  releases for the life of the process, the reason `embed()` guards its
  lazy load rather than using a bare check
  (`docpipe/embedding/local.py:49` to `52`, comment).
- In the pilot that motivated the singleton `docpipe/extraction/runner.py`
  wraps around `get_embedder()`, five replicas of the model fit on one
  card, a sixth raised a CUDA out-of-memory error, and none of the
  sixteen documents in that pilot completed
  (`docpipe/extraction/runner.py:276` to `283`, the `embedder()`
  docstring; pinned by
  `test_the_embedder_is_built_once_however_many_threads_ask` below).
- The `api` backend batches eight texts per request by default
  (`docpipe/embedding/config.py:24`), a different number from the 32 items
  `docpipe/chunking/config.py:25` batches into one call to the model when
  the corpus is built, a constant this package neither reads nor uses.

## Verification

- `tests/test_embedding_backends.py`: `test_backend_is_configuration_not_code`,
  `test_a_deployment_can_bind_its_own_implementation`,
  `test_the_import_path_may_name_a_function_too` and (three malformed
  specs) `test_a_broken_backend_says_which_part_broke` pin the three
  backend forms and how a broken one fails; `test_api_backend_needs_an_endpoint`,
  `test_api_embeds_text_in_batches`, `test_api_refuses_images_instead_of_dropping_them`
  and `test_embed_one_goes_through_the_batch_path` pin `ApiEmbedder`,
  including that three items at `batch_size=2` cost two requests, not three.
- `tests/test_extraction_runner.py`: `test_the_embedder_is_built_once_however_many_threads_ask`
  pins that eight threads asking `runner.embedder()` at once produce one
  construction, shared by every thread; `test_the_local_backend_guards_its_lazy_load`
  asserts `LocalEmbedder._lock` is a real `threading.Lock`, replacing an
  earlier timing-based check that passed with or without the lock.
- `tests/test_multigpu_embedder.py` pins, across three tests, that 30 items
  across 4 replicas return in input order, that 4 long items among 40
  short ones land one per shard rather than four in one, and that a single
  replica skips the sharding machinery entirely.
- `tests/test_dotenv.py::test_the_value_reaches_the_config_that_reads_it`
  pins that a fresh interpreter, given only `DOCPIPE_ENV_FILE`, sees an
  `.env` file's `EMBEDDING_BACKEND` at import time; checked here because
  this module pulls in no third-party package.

## Modules

`docpipe/embedding/__init__.py` defines the `Embedder` protocol and
`get_embedder()`, the one factory every caller uses to obtain a backend.
It is what `docpipe/extraction/runner.py`, `scripts/inference_app/app.py`
and `scripts/inference_app_smoketest.py` import `get_embedder` from.

`docpipe/embedding/config.py` declares the `EMBEDDING_*` environment
variables once, read directly by the other modules here and re-exported,
not redeclared, by `docpipe/chunking/config.py`,
`docpipe/inference/faiss_store.py` and `scripts/inference_app/config.py`.

`docpipe/embedding/local.py` implements `LocalEmbedder`, the GPU-resident
backend that lazily constructs and holds one `MultiGPUEmbedder` behind a
double-checked lock, translating its `process()`/tensor interface into
this package's `embed()`/list-of-floats contract. It is used directly by
`docpipe/extraction/runner.py` and, through `get_embedder()`, by
`scripts/inference_app/app.py`.

`docpipe/embedding/api.py` implements `ApiEmbedder`, the text-only backend
calling an OpenAI-compatible `/v1/embeddings` endpoint in batches,
constructed by `get_embedder()` when `EMBEDDING_BACKEND=api`, and directly
by `tests/test_embedding_backends.py`.

`docpipe/chunking/qwen3_vl_embedding.py` is not part of this package, but
`LocalEmbedder` depends on it entirely: `Qwen3VLForEmbedding` (a Qwen3-VL
wrapper returning hidden states, no language-modeling head),
`Qwen3VLEmbedder` (one replica, forward pass, pooling, normalization) and
`MultiGPUEmbedder` (one replica per visible GPU, length-balanced sharding,
order-preserving reassembly). Its own account, and
`docpipe/chunking/embedding.py`'s independent, direct use of
`MultiGPUEmbedder` for the corpus build, are documented at
[chunking](chunking.md).

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/embedding/__init__.py</code></summary>

__init__.py: Exposes one Embedder interface behind several backends.

get_embedder() reads EMBEDDING_BACKEND and returns one of three
things. "local" loads the model in this process, on this machine's
GPU (embedding/local.py). "api" calls an OpenAI-compatible
/v1/embeddings endpoint (embedding/api.py). Anything of the form
"package.module:attribute" is an import path: the module is imported,
the named attribute is called with the given keyword arguments, and
whatever it returns is used as the embedder. Which of the three a
deployment uses is a matter of configuration, not of code: a laptop
without a GPU points at an endpoint, a compute node loads the model.

The import-path form is the extension point. Loading a model
quantized, on demand, and freeing the memory again between queries
depends on one machine's hardware and not on the pipeline, so such an
implementation lives next to the deployment that needs it rather than
in this repository. It is named here only by import path; the
package requires of it only an `embed` method and an `embed_one`
method. See scripts/inference_app/README.md.

One limitation holds for every deployment: the OpenAI embeddings API
is text only. Image and image+text items (the *_vl embedding types)
therefore need a local backend, or an endpoint that accepts
multimodal input.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/embedding/local.py</code></summary>

local.py: Embeds items with a model loaded and kept resident in this
process.

LocalEmbedder loads the model once, under a lock, and keeps it on the
GPUs for every later call. This is what a batch run wants: thousands
of items against one load. embed() delegates to
docpipe.chunking.qwen3_vl_embedding.MultiGPUEmbedder, whose
process() method returns a bf16 tensor; embed() converts that tensor
to a list of floats, so this backend returns the same shape of
result as ApiEmbedder. The `normalize` setting is left at its
default because the corpus vectors already stored in the index were
written by the same call with that default
(docpipe/chunking/embedding.py); a query embedded with a different
setting would score against them wrongly rather than fail outright.

The opposite case, a small card that also serves an interactive app
and must give its memory back between queries, is deployment specific
(which quantization, which card, how long to wait for the lock) and
lives outside this repository. Point EMBEDDING_BACKEND at it by
import path; see docpipe/embedding/__init__.py.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/embedding/api.py</code></summary>

api.py: Embeds items by calling an OpenAI-compatible /v1/embeddings
endpoint.

ApiEmbedder is for deployments without a GPU, or for a deployment
where the embedding model is served centrally. It batches items into
groups of batch_size before calling the endpoint. The OpenAI
embeddings schema has no place for an image, so embed() is text
only: an item carrying an image is refused with a ValueError rather
than silently embedded as text.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
