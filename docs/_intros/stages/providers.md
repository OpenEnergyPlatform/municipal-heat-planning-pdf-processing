## What it is for

Every stage that asks a model asks through one client shape: a chat request
with a model, messages, a token limit and a reply format, answered by an
object with the reply text, a finish reason and a usage count. This package
puts the API behind that shape, so no stage knows which one it talks to.

A request has a role: `llm` (text: repair, extraction, chat), `vlm` (tables,
figures, scanned pages) or `embedding`. Each role names its provider in a
setting of its own (`LLM_PROVIDER`, `VLM_PROVIDER`, `EMBEDDING_PROVIDER`),
so a corpus can be read by a hosted model and embedded by a local one.

| provider | what it is |
|---|---|
| `openai-compatible` | the default: a server of one's own, reached with the OpenAI client and nothing between (`LLM_BASE_URL`) |
| `openai` | the hosted OpenAI API |
| `anthropic` | the Anthropic API (the `anthropic` extra) |
| `gemini` | the Google Gemini API |

Three things follow from a hosted API and are handled here and not in the
stages:

- JSON is asked for only inside a reply schema, which the API enforces while
  it generates. Each stage writes the schemas of its requests in a
  `replies.py`; `schema.strict` rewrites one into the dialect an API takes
  and reads the reply back in the shape the stage asked for. Refinement, the
  visuals stage, page transcription and the chat's answer requests send their
  schema as the grammar of every request, whatever the server is
  (`providers.grammar`): a server of one's own and a hosted API get the same
  `response_format`, no value of `LLM_SCHEMA` turns it off, and the stage reads
  the reply as exactly one JSON object (see [the parts every stage
  uses](core.md)). The harvest's requests go through `reply_format`: a server of
  one's own gets a schema where it always did, and everywhere with
  `LLM_SCHEMA=all`.
- A rate limit is waited out once for everybody: one gate per endpoint,
  closed while the API says to wait (`governor.py`). The gate decides when
  a request is sent and retries nothing.
- What only one hosted API takes goes into `LLM_REQUEST_OPTIONS` and
  `VLM_REQUEST_OPTIONS`, a JSON object laid over every request body of that
  role. Keys belong in `.env`; a placeholder key means the provider's own
  variable is used.

Before its first document a stage asks the server what it serves
(`docpipe/llm_preflight.py`); a hosted model that cannot answer inside a
reply schema is refused there. A stage that sends its schema with every request
has each of its schemas put to the server once as well
(`assert_reply_schemas`): a server that refuses one with a 4xx other than 429
ends the run before the first document.

The usage block of a reply carries `cached_tokens` where the API says so: the
part of the input tokens it served from its cache. The adapters read it from
`prompt_tokens_details.cached_tokens` (OpenAI), `cache_read_input_tokens`
(Anthropic, whose input count already includes cache reads and creations) and
`cachedContentTokenCount` (Gemini); a server of one's own that reports it under
`prompt_tokens_details` is read the same way. The ledger books it beside the
input tokens (see [the parts every stage uses](core.md)), and the `cached`
price of the project file's `[prices]` table prices it. A replayed run books no
cached tokens, because the cassette holds only prompt and completion tokens.

## The cassette

A cassette is the answers of one run, each filed under what was asked
(`cassette.py`):

```
DOCPIPE_CASSETTE_RECORD=file    a run with a model writes its answers
DOCPIPE_CASSETTE_REPLAY=file    a run takes its answers from the file
```

A replay asks again in the same words and gets the answer it got, on a
machine without a model. That holds the model still and shows the code: how
an answer is read, what is accepted, how rows are settled. A prompt or a
spec that changed asks in other words, finds no answer, and stops the stage;
that change needs a recording of its own. `docpipe benchmark` is the
command built on it (see [measuring a harvest](evaluation.md)).

A cassette holds the text of the documents the run read, so recording is
refused for a profile that does not say its documents may be passed on
(`Profile(documents_shareable=True)`).
