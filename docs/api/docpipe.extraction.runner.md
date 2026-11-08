# docpipe.extraction.runner

`docpipe/extraction/runner.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

runner.py: Wires the pure harvest loop of `pipeline.py` to the live stack.

A run reads each plan passage by passage (`surveyed_flow`, which stops the
run where the spec names no groups or the profile lacks a prompt of the
harvest): the order of its passages, the reading of every passage for every
parameter and the combing per document (`surveyed.py`), then the fold, the
compute step and the file with its stamp as below. The passes over a
stored harvest run on the same steps.

This module supplies the loop's expensive dependencies from the real world:
FAISS retrieval with owner exclusion, the model calls, and locating a quote on
its page in the source PDF, plus resume stamps and the CLI. Heavy imports
(faiss, torch-backed embedders, fitz) happen inside functions, so importing
this module stays cheap and a test that only touches the package pays for no
GPU stack it does not use.

`make_retrieve` fuses every probe handed to it into one FAISS search per
document and ranks each owner by the best score any probe gave it; measured
over 65 documents and 15,082 values, the fused ranking put the source a value
was really read from at median rank 26, against 77 for the old per-probe
concatenation. A probe is a HyDE-style sentence a model writes:
`document_anchor` writes the one short sentence per parameter the document is
searched with, which is a cache miss by construction.

The requests parse the reply strictly: one JSON object and nothing else. A
reply that is not that is asked again with the cause named (`_reply_fault`).

`make_locate` finds where a quote sits on its page in the source PDF, through
the same alignment the app highlights with. Resume stamps (`_stamp_current`,
`stale`) record a fingerprint per question a spec asks (`spec.fingerprints`),
so an ontology edit restales only the documents asked through the coordinate it
touched, not the whole corpus. `main` is the CLI: a normal harvest, and the
`--recheck`, `--remap`, `--serialize`, `--review`, `--top-up` and
`--top-up-parameters` maintenance passes over a harvest already written.

Author: Felix Vossel

## Classes

### Unserved

```python
class Unserved
```

Documents one of whose requests ended on a 429, a 5xx or a timeout.

Such a request was never answered, so its document is not finished,
whichever request it was: a passage's rows, one coordinate, the frame, a
search sentence. `finish_document` leaves the document unstamped and a
resume harvests it again. Counted under None: requests of the run itself.

#### Unserved.\_\_init\_\_

```python
def __init__(self)
```

#### Unserved.note

```python
def note(self, document_id) -> None
```

#### Unserved.of

```python
def of(self, document_id) -> int
```

#### Unserved.clear

```python
def clear(self) -> None
```

### Failures

```python
class Failures
```

What the failures of one request mean, the same for every request of
the stage. The rule stands here once and not in each retry loop: of nine
loops, three kept all of it, and the compute request asked again at once
after a server error, asked a refused request again, and left its
document stamped as finished when no attempt of it was served.

A failure that is the server's (`server_side`) is asked again, after the
long wait (`retry_wait`). Any other refuses the request itself, every
time, and is not asked again. A request given up on whose last attempt
the server did not serve (`unserved`) leaves its document unfinished
(`UNSERVED`): the stamp is withheld and a resume reads it again.

*document_id* is the document the request reads, None for a request of
the run itself. *noted* is False for a request whose end is told another
way: one the document is finished without (the places map, the review),
or one whose hole carries its cause to the stamp itself (the rows
harvest, `not_happened`). It still waits and stops by the rule.

#### Failures.\_\_init\_\_

```python
def __init__(self, document_id=None, noted: bool = True)
```

#### Failures.failed

```python
def failed(self, exc: BaseException) -> bool
```

Whether the request that raised *exc* is asked again.

#### Failures.answered

```python
def answered(self) -> None
```

The server answered the request, whatever its reply says.

#### Failures.wait

```python
def wait(self, attempt: int) -> None
```

Before asking again after attempt *attempt*: the long curve after
the server's failure, the short one after a reply.

#### Failures.given_up

```python
def given_up(self) -> None
```

The request is asked no more and has no answer.

### Coalescer

```python
class Coalescer
```

embed(items) from any number of threads, sent to the model in batches.

The searches of every document in flight ask for vectors at the same
time, a few probes each. One worker takes everything that has queued up,
embeds it in one call, and hands each caller its slice; what arrives
while that call runs is the next batch. So a batch is as large as the
demand of the moment and no larger, and the card runs one call at a time
instead of a hundred small ones racing for it.

#### Coalescer.\_\_init\_\_

```python
def __init__(self, backend: Callable)
```

#### Coalescer.embed

```python
def embed(self, items: list) -> list
```

### PromptCounter

```python
class PromptCounter
```

The prompt of a request counted with the served model's own tokenizer.

The text of every message goes through the model's chat template with the
settings every request carries (`request_extras`) and is counted exactly;
a crop is counted at IMAGE_TOKENS, the most one can take. The estimate
this replaces ran short on tables of figures, where the tokenizer gives
every digit a token of its own: requests went out one token over the
window and were refused, and a refused request that carried a crop broke
the server's multimodal cache (vLLM before 0.28, CVE-2026-105753).

#### PromptCounter.\_\_init\_\_

```python
def __init__(self, tokenizer)
```

## Functions

### retry_temperature

```python
def retry_temperature(base: float, faults: int) -> float
```

The sampling temperature after `faults` unreadable replies.

### install_stop_handler

```python
def install_stop_handler() -> None
```

SIGTERM sets STOP instead of killing the interpreter mid-group.

Killed outright, a time-limit stop threw away the whole group in flight,
up to 64 documents and hours of work, including every batch that had
already come back. Only the main thread can install a handler, so a call
from anywhere else leaves the default in place.

### unheld_requests

```python
def unheld_requests() -> int
```

1 when this run replayed a cassette and asked something it does not
hold, else 0: such a harvest is not the recorded run's, and a job that
compares the two must not take it for one.

### retry_wait

```python
def retry_wait(attempt: int, transport: bool = False) -> float
```

Seconds to wait before attempt *attempt* + 1.

*transport* is the request that never reached the server: no HTTP status,
no refusal, nothing to read. Doubling from 15 seconds gives a restarting
vLLM 225 seconds over five attempts, which is what a model server needs
to come back; the model's own mistakes keep the short curve, because
waiting longer for those buys nothing.

### unserved

```python
def unserved(exc: BaseException) -> bool
```

A 429, a 5xx or a timeout: the server was asked and did not do the work.

None says anything about the request. A rate limit lifts and a server
recovers, and the same request is answered then. A request that timed out
was never answered either: a server whose engine stopped taking requests
kept its connections open until every one of them timed out, and their
documents were stamped with the coordinates never read. Every other 4xx
refuses the request itself, and refuses it every time.

### server_side

```python
def server_side(exc: BaseException) -> bool
```

Whether a failure is the server's: it never arrived, or was `unserved`.

These wait on the long curve and count towards the dead-server streak. A
429 retried after two seconds is the same 429.

### read_to_end

```python
def read_to_end() -> None
```

Every sweep from here on reads the rest of its document to the end, so
a coordinate ends read or `unstated` and never `exhausted`.

### embedder

```python
def embedder()
```

The one resident embedding model this run uses.

`get_embedder()` CONSTRUCTS a backend, it does not return a shared one, and
this call used to sit inside the per-probe `embed()`. With
EXTRACT_PLAN_PARALLEL threads each asking for its own probes, every probe
loaded another copy of the 8B model onto the same card: five fit into 80 GB,
the sixth died of CUDA OOM, and with it all sixteen documents.

The double check is not decoration — eight threads reach this together on
the first probe, and without the lock they would each build one.

### make_shared_content

```python
def make_shared_content(limit: Optional[int] = None) -> Callable
```

fetch_owner_content for every thread of a run, each owner read once.

The harvest's helpers used to give each thread a `make_content_fetcher`
of its own, unbounded, in pools that live as long as the run. The KWP run
of 2026-10-14 had 2,308 threads and grew from 46 to 53 GB of heap between
its third and its sixth hour: the same sections held once per thread that
had read them. One store for all threads holds each owner once.

A hit is a dict lookup and waits for nobody. A miss reads under the lock
and looks again first, so two threads missing the same owner read it once.
Each caller passes its own connection: the store is shared, the SQLite
handle is not.

### make_retrieve

```python
def make_retrieve(conn: sqlite3.Connection, index, id_to_pos: dict,
                  cache_conn, content_fetcher: Optional[Callable] = None,
                  limit: int = 0, per_probe_top: int = 0) -> Callable
```

(probes, document_id, exclude) -> ONE ranked Source list.

Takes every probe at once. One sub-index for the document instead of one
per probe, one FAISS search over a query matrix, and one ranking out of
it: the best score any probe gave an owner decides where it sits.

It used to return a list per probe, which the plan then concatenated. That
is not a ranking, it is a concatenation of rankings, and it put probe 17's
best match behind everything probes 1 to 16 had surfaced. Measured over 65
documents and 15,082 values: median rank 77 that way, 26 this way.

### make_parents

```python
def make_parents(db_path: Path, content: Optional[Callable] = None) -> Callable
```

(sources) -> the section each table or figure stands in, once each.

The own window used to be the batch's tables and nothing else, and the
coordinates a table does not carry live in the section around it: the
sentence that dates it ("Für das Jahr 2040 ergeben sich ..."), the
heading that names the scenario, the caption Stage 2 failed to link.
Measured on Kassel, section 349525 was in 0 of 1,043 field windows while
its three tables were asked for their year 39 times, and 69 tuples from
inventory tables came back as target-scenario values because no window
ever showed the word for what they are.

Once each: two tables of one section share one parent, and showing it
twice is the same passage paying twice.

Its own connection per thread, like more_sources: this runs inside the
harvest pool, and SQLite handles are not shared across a hundred threads.
The content read through it is: *content* is the run's shared store
(`make_shared_content`), or one of its own.

### make_owner_sources

```python
def make_owner_sources(db_path: Path,
                       content: Optional[Callable] = None) -> Callable
```

(owners) -> {(kind, id): Source} for passages a harvest already named.

The harvest stores the address of a passage and not its text, so a pass
that reads one coordinate again has to fetch it back. Through the same
two functions the harvest used -- the cached fetcher and `_source_of` --
so the heading is prefixed the same way and a quote that was checkable
during the harvest stays checkable.

Its own connection per thread, read-only, and memoised across calls in
*content*, the run's shared store or one of its own: one section is the
parent of several rows and would otherwise be read once per row.

### make_review_sources

```python
def make_review_sources(db_path: Path,
                        content: Optional[Callable] = None) -> Callable
```

(row) -> the passages one stored tuple may legally quote from.

Exactly two, in this order: the row's own source, and the section that
source stands in. That pair is where a row's labels, header and caption
stand, and it is a strict SUBSET of the window the sweep already walked --
which is what makes the second reading a check on the first and not an
independent one.

The parent goes through `make_parents` rather than being fetched from
`parent_section` directly, so a section too long for the window arrives
cut around this row's own placeholder instead of from its first character.

Its own connection per thread, like `make_parents`: read-only, and SQLite
handles are not shared. The content is, with the parents too: *content*,
the run's shared store or one of its own.

### make_rest_of_document

```python
def make_rest_of_document(db_path: Path,
                          content: Optional[Callable] = None) -> Callable
```

(document_id, exclude, start) -> every remaining section, in document order.

The floor under the field sweep, and the reason "not stated" can mean it.
Retrieval answers "which passages look like this question", and for a
coordinate that is stated once in a caption twelve pages away the answer
is often none of them — an embedding does not rank a table caption under
"which reference year does this figure belong to".

So when the probes stop bringing anything new, the sweep stops asking and
starts reading: the document's own sections, in their own order, until the
coordinate is found or the document is finished. Finite by construction,
which is what lets a sweep end in an answer rather than in a budget.

Where it starts reading is `start`, the section the open rows stand in. The
order is ROTATED there and never cut: what this floor promises is that "not
stated" means the whole document was read, and dropping the sections before
the row would make that a lie about the part a title page stands in. A
coordinate is far more often a few sections from its own row than on page
one, and the budget runs out long before the wrap comes round.

A section's tables and figures follow it, in page order. The floor read
sections only, and 71 percent of corpus_m5's tuples came out of images:
"the whole document" that left out every table was not the whole document.

Each call reads a whole document, so what it read goes into *content*, the
run's shared store, and not into a store per thread.

### make_search_reranker

```python
def make_search_reranker(image_root: Optional[Path] = None
                         ) -> Optional[Callable]
```

() -> one thread's reranker of every search (`rerank.Reranker`), or
None where the run is given no RERANK_BASE_URL (owner decisions
2026-11-06 and 2026-11-08). A figure is scored with its picture, as the
reading shows it.

### make_more_sources

```python
def make_more_sources(db_path: Path, index, id_to_pos: dict,
                      cache_path: Path,
                      content: Optional[Callable] = None,
                      reranker: Optional[Callable] = None) -> Callable
```

(document_id, queries, exclude) -> the passages the model asked for.

Retrieval a second time, but from a query the MODEL wrote rather than one
the spec generated. It runs during the harvest, not the plan, so it opens
its own connections per thread: the harvest pool is a hundred threads
wide and SQLite handles are not shared across them.

Queries the model invents are one-offs, so they miss the primed cache and
are embedded on the spot. That is the whole cost of the round trip, and
it only happens when the model says the passages it was given are not
enough.

*limit* bounds what one call hands back. The ranking covers the whole
document, and handed over whole it marked every passage of the plan as
seen after the first round: the stage that reads the rest in order then
found nothing left, and a sweep whose budget had cut the ranked list
ended "unstated" instead of "exhausted". corpus_m5 wrote 0 exhausted
coordinates in 263,997 sweeps that way. 0 means no bound.

The passages' content comes from *content*, the run's shared store or one
of its own, and not from a store per thread.

*reranker()* makes one thread's reranker (`rerank.Reranker`), which puts
the best passages of each kind in its own order before they are handed
back; None leaves the vector search's order.

### fill_dynamic_axes

```python
def fill_dynamic_axes(spec: Spec, vocabularies: Optional[dict]) -> Spec
```

A copy of *spec* whose dynamic axes carry THIS document's list.

The countries a publication names differ per publication, and a list of
all 249 would bury the handful it names. Nothing but the model can map a
wording onto an entry, and it can only do so if it is shown the list it
may choose from; the mapping then arrives flagged, like every other
judgement call the harvest records.

### spec_of

```python
def spec_of(batch, spec)
```

The spec a batch is read against: its document's, or the run's.

The lists a document closes were built for the search and then left
behind: the requests that read the passages and the check of their
answers were built from the run's spec, where a dynamic list is empty.
So the model was offered nothing to choose from on exactly the fields
whose point is the choice, and wrote a wording instead.

### narrow_spec

```python
def narrow_spec(spec: Spec, only) -> Spec
```

A copy of *spec* that asks these parameters (by uri) and no other.

The spec itself when `only` is empty, so a harvest that names no
parameter reads what it always read. Every request is built from the spec
its batch carries (`spec_of`): the quantities the rows request offers,
the units, the parameter question and the grammar of the reply. A batch
that carries the narrowed copy therefore offers the model the named
parameters and their units alone, which is how a pass for a new parameter
keeps every row of a stored parameter from arising.

### make_document_spec

```python
def make_document_spec(conn, spec: Spec,
                       document_axes: Optional[Callable]) -> Callable
```

(document id) -> this document's spec, or None when its lists cannot
be closed.

For the passes that read a harvest already on disk. Asked against an
empty list a dynamic axis degrades to a wording, which is a demotion
nothing would report, so such a document is left alone and counted.

### document_spec_per_call

```python
def document_spec_per_call(db_path, spec: Spec,
                           document_axes: Optional[Callable]) -> Callable
```

`make_document_spec` for a caller that runs one document per thread.

A SQLite connection belongs to the thread that opened it, so each call
opens its own, reads the document's lists and closes it again. Nothing
is open between two calls.

### document_specs

```python
@contextmanager
def document_specs(db_path, spec: Spec, document_axes: Optional[Callable])
```

`spec_for` for a pass over a harvest on disk, the corpus open for as
long as the pass runs. None when the profile closes no list per document:
such a pass needs no database.

### anchors_key

```python
def anchors_key() -> str
```

Everything an anchor set depends on that is NOT one question: the
anchor prompt, the model and the version of the target SET. The cache is
stored under it and the stamp records it.

Not the questions, though it used to hash them. Everything a target tuple
carries is already a stamp key of its own -- a parameter's label and
description in `parameter/<uri>`, an axis' question in
`axis/<uri>/<name>`, the spec's own question and the parameter list in
`slot/parameter`, the unit question and its lists in `slot/unit` -- and
the anchor prompt and the model are stamp keys too
(`extraction/anchors`, `model`). Hashing the targets in here as well made
every document in the corpus stale over ONE changed question, which is
exactly what the per-question keys were written to stop.

The empty last field held the sha of a file of anchors a profile could
freeze. That file is gone, and the field stays empty rather than going,
so a harvest that never had one keeps its key.

### anchor_key

```python
def anchor_key(parameter_uri: str, slot_name: Optional[str] = None) -> str
```

The anchors.json key of one question: the value's, or one axis's.

### anchor_targets

```python
def anchor_targets(spec: Spec) -> list
```

(key, label, description, question) for every question the run asks.

One anchor set per QUESTION, not per parameter. An anchor is a sentence as
the document would write it, and the sentence that states a value and the
sentence that states its reference year are not the same sentence. Six
anchors written from "Endenergieverbrauch" find tables of consumption and
say nothing about where a bilanz year is printed, which is why the field
sweep searched with the raw question and found captions by accident.

The value itself has no set here. The plan searches with the one short
sentence `document_anchor` writes for the document it plans, and a set
written once for the whole corpus was never searched with.

### phrase_payload

```python
def phrase_payload(parameter, context: Optional[dict] = None,
                   frame: Optional[dict] = None) -> dict
```

What a phrase request is written from: the parameter's label and
description, the names of its list where it has one, what the document
says of itself (*context*) and the pair the sentence searches for
(*frame*).

### document_context_of

```python
def document_context_of(db_path: Optional[Path],
                        document_context: Optional[Callable]) -> Callable
```

context_of(document_id): what the document says of itself (the
profile's `document_context`), each call on its own read-only
connection; {} where the profile has none.

### make_seek_probes

```python
def make_seek_probes(own=(), context_of: Optional[Callable] = None,
                     write: Optional[Callable] = None) -> Callable
```

probes(parameter, document_id) -> the sentences a plan's passages
are ranked with for a parameter, which sets the order it reads them in
(`survey.Ranking`, owner decisions 2026-11-05 and 2026-11-08).

A parameter about the document itself (*own*, the profile's
`FRONT_PAGE_PARAMETERS`: its title, authors, date, DOI and abstract) gets
a sentence written for this document from what it says of itself
(*context_of(document_id)*, the profile's `document_context`), since the
document's own name finds its title page. Any other gets one sentence per
run, written once from
its label, description and list names and kept: the document's name
pulls such a sentence toward the title page and away from the passage
that states the value. *write(parameter, context)* writes the sentences,
one phrase request (`document_anchor`) where not given. A parameter no
sentence could be written for gets none, and the search falls back to
its label. A document's own sentence is sent in that document's turn, the
run's before every document, since every document waits on it
(`document_anchor`, *shared*; owner decision 2026-11-07).

### document_anchor

```python
def document_anchor(spec: Spec, context: Optional[dict] = None,
                    client=None, prompt=None,
                    frame: Optional[dict] = None,
                    document_id: Optional[int] = None,
                    shared: bool = False) -> dict
```

{parameter uri: [one sentence]} — the probe THIS document is searched with.

The QA app turns a question into one short statement before it searches,
because a similarity search matches sentences and a question is the one
sentence that never stands in a document. This stage searched with 24
frozen 600-character passages instead, and a 600-character passage is not
an anchor: it is half a hit put back into the query.

Per document, not per corpus, and that is the whole point. The sentence is
written from the ontology annotation the spec inlines -- `label` and
`description` -- AND from what the document itself has already said: its
name, and the caption of what a first search in it returned. So the anchor
grows with the document instead of asking all 1,082 plans the same
sentence.

The price, stated: the corpus-wide query-embedding cache stops hitting.
A per-document sentence is a miss by construction, so the plan pays one
embed per parameter per document instead of one per corpus.

A parameter whose sentence could not be written is left out rather than
filled with the label. `plan_document` says out loud when it plans without
anchors, and a probe that is a bare label is the "silently worse
retrieval" this whole stage exists to end.

Each request is sent for *document_id*, in that document's turn, with
the ticket of the thread that asked (`_for`), although a thread of the
pool below sends it: such a thread belongs to no document, and a request
of none goes before every document. A *shared* sentence, the one the run
keeps for every document (`make_seek_probes`), is sent for none, as
everything every document waits on is; *document_id* still notes its
failures and traces it (owner decision 2026-11-07).

### set_model_len

```python
def set_model_len(tokens: Optional[int]) -> None
```

The window the server reports, when it reports one.

### start_limit

```python
def start_limit() -> None
```

Steer the requests by the server's queue unless EXTRACT_LIMIT_ADAPTIVE=0.

### start_fixed_limit

```python
def start_fixed_limit(requests: int) -> None
```

The run's one queue (`SCHEDULER`), with a limit of *requests* open at
once that does not move: a probe's places (owner decision 2026-11-07,
the places count requests with the model, not the conversations open,
so one that waits for its search holds none). Every client made after
this sends through it (`_client`).

### start_counting

```python
def start_counting(model: Optional[str] = None) -> None
```

Count every prompt of the run with the served model's tokenizer.

For a server of one's own, whose tokenizer lies in the local model cache.
A hosted API's tokenizer is its own and a recorded run sends nothing;
both keep the estimate. A tokenizer that cannot be loaded ends the run
here, before the first request, and not as refusals hours into it.

### prompt_tokens

```python
def prompt_tokens(system: str, conversation: list) -> int
```

What a request's system prompt, messages and crops take.

Counted before sending, so a request is sized to the window instead of
shrunk after the server refused it. vLLM's refusal names only a lower
bound ("at least N input tokens" is the window minus the requested answer,
plus one), and reading that as the prompt shrank the answer by 33 tokens
per attempt until the coordinates were written off. With the model's
tokenizer (`start_counting`) the text is counted exactly; without one it
is estimated high.

### answer_room

```python
def answer_room(system: str, conversation: list, wanted: int) -> int
```

max_tokens for this request: *wanted*, or what the window leaves.

### make_page_count

```python
def make_page_count(db_path: Optional[Path]) -> Callable
```

document_id -> its page count in the catalog, None where unknown.

### system_text

```python
def system_text(prompt, example: Optional[dict]) -> str
```

The system prompt one request sends: the prompt with its example
reply ({{example}}) written for this request, as one line of JSON (owner
decisions 2026-11-06: every request's example shows exactly the
coordinates it asks, each read, so the model has no key to leave out). A
prompt without that place is sent as it is written; one with it and no
example is an error before anything is sent, as every open placeholder
is (`prompts.Prompt.render`).

### ask_in_grammar

```python
def ask_in_grammar(client, prompt, conversation: list, shape: dict,
                   document_id: int, where: str, key: str,
                   example: Optional[dict] = None,
                   thread: Optional[thread_map.Thread] = None, **noted)
```

One request of the rebuilt harvest: the reply as a dict, "cut_off"
when it did not fit its room, or None when it could not be read. The
prompt shows *example*, the reply this request asks for
(`system_text`).

With *thread* the request is one message of a conversation (owner
decisions 2026-11-07): a follow-up is sent under the system prompt the
conversation began with, and the answer that stands is kept in it with
every message sent, so the next follow-up goes after it
(`thread.Thread`).

Asked again with the cause when the reply is no JSON object, or one
without a key its schema requires (`_lacking`), as every request of the
stage is; a reply cut off at its limit is not rescued. Each answer is
traced as `<where>_ask` with *noted*.

A request whose last attempt ended on a 429, a 5xx or a timeout was
never answered, so its document is noted (`UNSERVED`) and goes
unstamped, as for every request of the run. One that timed out is asked
again with the time a repeat gets (`_repeating`), whatever client it was
handed, as every request of the harvest is.

### parts_of

```python
def parts_of(prompt_id: str, spec: Optional[Spec] = None, profile=None)
```

The prompt *prompt_id* cut at its parts (`thread.cut`): with *spec*,
the reading's groups must each have theirs, and every field its
follow-ups carry (`FOLLOWS`) its words. LookupError where it does not
fit.

### threaded

```python
def threaded(parts, thread, payload: Optional[dict] = None,
             follow: Optional[dict] = None, content=None,
             example: Optional[dict] = None) -> tuple
```

(prompt, conversation) of one message of *thread* (owner decisions
2026-11-07): a follow-up (*follow*) goes after the answer that stands,
in the words of the parts its fields need, with the reply the request
asks for (*example*) where they show one; a first message shows
*payload* (as *content* where given, such as a figure with its crop)
under the system prompt of what every request of its kind is told and
the part of each field it carries.

### told

```python
def told(follow: Optional[dict]) -> int
```

How many corrections a follow-up carries, for the trace.

### worded

```python
def worded(words: str, payload: dict) -> str
```

A message: its words, then what it shows as JSON.

### answers_in

```python
def answers_in(thread) -> int
```

How many answers a conversation holds.

### shows_in_full

```python
def shows_in_full(thread, parameter) -> bool
```

Has a message of this conversation shown *parameter* with its full
definition? A coordinate that classifies is shown it once, with the
first of them that is asked (owner decision 2026-11-07: one coordinate
per message).

### make_reader

```python
def make_reader(spec: Spec, image_root: Optional[Path] = None)
```

The reading of one parameter's passages (`reading.Reader`), or None
when the profile writes no prompts for it or its spec names no groups.
Two kinds of request, each with one task (owner decisions 2026-11-04
and 2026-11-05), each a message of a conversation (owner decisions
2026-11-07, `thread.py`): all values of a passage in one answer, what
follows it asking for those not named yet (owner decisions 2026-11-08),
and one value's coordinates, one coordinate per
message with the words of its group (`thread.Parts.group`). A system
prompt holds what its kind of request is told and the part of each
field its first message carries. A figure goes with its crop, in the
first message, and a value only the crop shows is read off it (owner
decisions 2026-11-05 and 2026-11-07). Neither request has tools (owner
decision 2026-11-05, ticket 26).

### check_asker

```python
def check_asker(client, parts=None) -> Optional[Callable]
```

The request that asks of a find whether the place it was quoted from
speaks about its value (`reading.Judge`, owner decisions 2026-11-07),
the same for a find of the second reading and one of the combing; None
where the profile writes no prompt for it. *parts* is the prompt cut at
its parts where the caller has it.

### make_namer

```python
def make_namer(spec: Spec, passages_of: Callable) -> Optional[Callable]
```

The requests that ask which of a document's names mean the same
thing once it is folded (`naming.Namer`, owner decisions 2026-11-06):
`name(report)`, which marks the report's rows. None where the spec
merges no names or the profile writes no prompt for it, which
`surveyed_flow` refuses at the start of a run. *passages_of(document_id)*
is the plan's passages in their order. The names are embedded with the
run's embedding model (`COALESCED`).

### make_comber

```python
def make_comber(spec: Spec, rank: Callable)
```

The search for what the reading left open (`combing.Comber`), or None
when the profile writes no prompt for it or its spec names no groups.
*rank(document_id, probes, exclude)* is the plan's passages best first
for the search sentences, `make_more_sources` in a harvest.

### frame_slots_of

```python
def frame_slots_of(spec: Spec) -> list
```

The coordinates of the plan's frame, which its base and target years
date a value by: the pair of each group that names one
(`spec.Group.paired`).

### dates_by_plan

```python
def dates_by_plan(spec: Spec) -> bool
```

Does the spec date a value by the plan's own years: has its frame a
year?

### make_years

```python
def make_years(spec: Spec, rank: Optional[Callable] = None)
```

The request for a plan's base and target years, once per plan
(`years.PlanYears`, owner decision 2026-11-06), or None where the spec's
frame has no year or the profile writes no prompt for it. *rank* is the
plan best first for a sentence the model writes ("similar").

### make_settings

```python
def make_settings(spec: Spec, rank: Optional[Callable] = None)
```

The request for what a plan settles for all its values, once per plan
(`settings.PlanSettings`, owner decision 2026-11-07), or None where the
profile writes no prompt for it. *rank* is the plan best first for a
sentence the model writes ("similar").

### title_line

```python
def title_line(passages: list, name: Optional[str],
               pages: tuple = (1, 2)) -> Optional[Source]
```

The first line of the plan's first page, else its second, that names
*name*, the place the plan is about, as a passage a quote may stand in
(owner decision 2026-11-06: every reading request shows it). None where
no such line stands there, or no name is known.

### make_title_page

```python
def make_title_page(db_path: Optional[Path], profile) -> Optional[Callable]
```

title_page(document_id, passages): the line of the title page that
names the plan's own place (`title_line`), its name from the profile's
`document_context`; None where the profile does not show it
(`TITLE_PAGE_LINE`).

### make_survey

```python
def make_survey(spec: Spec, out: Path, rank: Optional[Callable],
                every: Callable, probes: Optional[Callable] = None,
                scope: str = "")
```

The order every passage of a plan is read in for each parameter
(`survey.Ranking`, owner decisions 2026-11-08): *rank(document_id,
sentences, exclude)* is the whole plan best first, `make_more_sources`
with the run's reranker in a harvest; *probes(parameter, document_id)*
the parameter's search sentences (`make_seek_probes`); *every* is
(document, exclude) -> passages. *scope* names an order of part of a
plan, kept beside the whole one's.

### frame_pairs

```python
def frame_pairs(reply: Optional[dict], slots: list, sources: list,
                rejected: Optional[list] = None) -> list
```

The pairs of a reply that carry their own evidence, in order.

Every coordinate is held to what a field answer is held to: its quote sits
verbatim in one of the passages that were SHOWN, the quote contains the
answer, and a scenario is one of the keys the request listed. Nothing else
is checked. A frame reading is document-level by construction -- it is
read once, from a caption or a heading, and every row of the document
inherits it -- so "is this passage near this row" is not a question about
it, and no reading anywhere in the harvest is asked it.

*rejected* collects one sentence per pair that did not get through, to be
put back in front of the model. Silently dropping them is
how a plan ended up with a scenario the ontology has no class for: the
pair was refused, nobody said so, and the next window was asked the same
question in the same way.

### probe_server

```python
def probe_server(base_url: str = None, timeout: float = 10.0) -> bool
```

Whether the server answers `GET {base_url}/models` at all.

Any reply below 500 counts: a server that refuses the key is still there.

### watch_server

```python
def watch_server(on_dead: Callable, *, probe: Callable = probe_server,
                 every: float = SERVER_PROBE_EVERY,
                 dead_after: float = SERVER_DEAD_AFTER,
                 clock: Callable = time.monotonic,
                 sleep: Callable = time.sleep) -> threading.Thread
```

A daemon thread that calls *on_dead(seconds)* once the server has not
answered for *dead_after* seconds, then stops watching.

### shared_http

```python
def shared_http(limit=None)
```

The one connection pool every request of the run goes out through.

Each kind of request has a client of its own (reading, combing, the
check, the years, ...), and each client used to keep a pool of its own:
connections it had opened stayed open while it sent nothing, so a probe
with 18 requests in flight held 40 connections to the proxy, and a server
that takes about 20 at once refused the rest outright (one probe,
1,110 requests refused). One pool for all, as large as the requests the
run may have open at once (*limit*, the run's `LIMIT`), holds no more
connections than requests in flight. Made once, with the first client.

### log_usage

```python
def log_usage(budget: Optional[int] = None) -> None
```

One line at the end of a run: what the window was really asked for.

### row_context

```python
def row_context(claim: dict, asked=()) -> dict
```

{axis: the plan's wording} of every coordinate this row has READ,
the ones asked now left out. A derived coordinate is the spec's decision
and its wording is the unit, so it says nothing about the number.

### cell_facts

```python
def cell_facts(value, quote, own=None, head=None) -> dict
```

Which cell of the quoted table row a number sits in and the head of
that column. Three numbers under three year columns share one quote, and
the column is what tells them apart: a fact already in hand here, so it
is handed over rather than left to be counted. A number printed in two
cells has its *head* from its place in its row's list (`with_head`).

### keeps_row

```python
def keeps_row(slot, answer, allowed) -> bool
```

Does this gate answer keep the row in the slice this run serializes?

The answer is the option's LABEL, because that is what a field reply
carries and what merge_field writes: "Nutzenergie", not
"out:useful_energy". The profile names classes, so the label is resolved
here — reading the profile
as if it held German spellings would have kept every potential and thrown
away every target scenario, which is exactly what it did.

Undecided keeps the row. A coordinate that came back empty or "not stated"
is a finding about the passages, not a licence to throw the value away,
and dropping on it would silently shrink the harvest by whatever the sweep
happened to miss.

*allowed* None means every class the graph takes, which is every entry
that does not ride the out: convention. A tuple names the answers.

### make_review_asker

```python
def make_review_asker(image_root: Optional[Path] = None) -> Callable
```

ask(row, shown, parameter, slots) -> reply, or None.

One stored value, read again over the two passages it may quote from. The
same model and a narrower window, so what it can find is a reading that
contradicts itself -- not a reading that is wrong about the picture in the
same way twice.

### make_completer

```python
def make_completer(profile, db: Optional[Path] = None) -> Optional[Callable]
```

The step that completes a document's rows from outside the document,
after its fold and its computing (`profiles/\<name>/completion.py:
complete(report, spec, db=)`, *db* the run's database, for what the
profile looks up there): `completed(report, spec)`, which adds what it
found to the report and returns what it came to, traced as `completion`,
or None where nothing was open. None where the profile has no such step.

### make_computer

```python
def make_computer(profile, passages_of: Optional[Callable] = None,
                  pages_of: Optional[Callable] = None,
                  rank: Optional[Callable] = None) -> Optional[Callable]
```

The step that works out what a document's verified rows leave open
(`compute.py`): `compute(answered, report, locate=, spec=, stop=)`, which
folds what it computed into the report and says False if a stop ended it.

None where it cannot run: the profile names no open question or writes no
prompt, or the run has no sandbox, since a number the model works out
itself has no evidence.

Two questions that come to one statement leave one row: the profile's
`same` says when two worked-out rows are (owner decision 2026-11-03).

*passages_of(document_id)* is the plan's passages in their order. With it
a request has the reading's tools (`reading.Gathered`: the next or the
previous section, a table or figure by its placeholder, a search by
pattern or by a sentence), each passage cut to two pages of the plan
(*pages_of*, `survey.budget_of`), and a question that takes a number
(`Question.take`) may take it from whatever the request showed: a
passage, its title, a hit's line or title (owner decision 2026-11-05).
*rank(document_id, probes, exclude)* is the plan ranked for a sentence,
which "similar" lists (`make_more_sources` in a run); without it that
search finds nothing.

### document_room

```python
def document_room(limit) -> Optional[Callable]
```

(documents open) -> how many more may start now, or None without a
steered limit (the ceiling alone decides then).

A document is let in while the model requests in flight stay below what
the throttle allows, one per look. A fixed count did not track the load:
64 documents read to their end each kept one request open, and four
GPUs ran at a fifth of their cache with nothing waiting. Planning sends
nothing, so a document planning does not hold the next one back; the
ones that start asking fill the limit, and while they hold it no further
document starts.

### harvest_documents

```python
def harvest_documents(documents: list, harvest_document: Callable, *,
                      in_flight: int, stop=None,
                      halted: Optional[Callable] = None,
                      room: Optional[Callable] = None) -> tuple
```

Run *harvest_document(id, filename)*, *in_flight* at most at a time
and, with *room* (`document_room`), as many as the server has room for.

Not in groups: the moment one document is done the next one starts, so a
slow plan holds its own place and nobody else's. A group of sixteen used
to wait for its slowest batch, and on corpus_m5 that was a single field
request answering alone on four GPUs for half an hour.

*harvest_document* returns (written, failures). *stop* (SIGTERM) ends the
loop at once without waiting for what is open; *halted* only stops new
documents from starting, and the open ones are waited for. A document
that is done, written or not, has the answers kept for its requests
forgotten (`scheduler.read_out`).

Returns (done, written, failures).

### make_locate

```python
def make_locate(db_path: Path, pdf_root: Optional[Path]) -> Optional[Callable]
```

(Source, quote) -> highlight rects in the source PDF, or None.

Uses the same alignment the app highlights with, so a value's recorded
provenance and the box a reader sees are produced by one implementation.
A section can run over a page break, so the section's other pages are
tried too - bounded, because this opens the PDF each time.

### survey_prompt_ids

```python
def survey_prompt_ids(profile=None) -> tuple
```

The prompts of a harvest passage by passage: `SURVEY_PROMPT_IDS`, and
the naming's and the plan's years' where the profile writes them, which
a spec that merges names or dates a value by the plan's years sends
(`naming.NAMING_PROMPT_IDS`, `years.YEARS_PROMPT_ID`, required by
`surveyed_flow`).

### surveyed_flow

```python
def surveyed_flow(spec: Spec, profile=None) -> bool
```

Whether a run can harvest passage by passage: its spec names groups.
A spec without groups cannot be harvested (`main` stops on it).

A spec with groups whose profile lacks a prompt of the harvest is a
broken profile: the run stops and names the prompt, as `spec.load` stops at a
broken group (owner decision 2026-11-04). So does a group prompt whose
parts are not the spec's groups, or one whose file lacks the words of a
field its follow-ups carry (`parts_of`), before a request is sent rather
than at the first plan's reading.

### producer

```python
def producer(kind: str, model: Optional[str] = None) -> dict
```

Who wrote into a harvest in one pass. Recorded, never compared.

A harvest is written once and then written into: a top-up reads single
coordinates again, possibly under another model or prompt, a second
reading flags values, a remap moves answers without a model at all. The
stamp's `model` names the first of them only. This is one entry of the
list that names them all. A coordinate a top-up re-read points at its
entry by position (`fields.PRODUCER`), so entries are never removed or
reordered.

### note_documents

```python
def note_documents(db_path) -> int
```

Read which bytes each document of the database is. Returns how many
documents have that recorded.

### note_index_model

```python
def note_index_model(db_path, command: str = "extraction") -> None
```

Say so when this run embeds its probes with another model than the
one the database's index was built with. A line in the log, no more;
`command` is whose line it is.

### stamp_record

```python
def stamp_record(name: str, kind: str = "harvest") -> dict
```

The stamp keys that place a harvest. The version decides nothing,
`document` is compared (`document_moved`), and of the producers
`read_in_part` reads whether the document was read to its end.

### document_current

```python
def document_current(name: str) -> dict
```

The stamp key this run can say about one document, or {}.

Per document and not part of `_stamp_current`: that is the key set of the
whole run, which a top-up and a remap carry forward, and neither of them
reads a PDF. Kept out of it, they neither earn this key nor lose it.

### document_moved

```python
def document_moved(stored: dict, current: dict) -> bool
```

True when the stamp and this run both name the document's bytes and
the sha256 differs.

A missing key on either side is not a difference. A stamp written before
the key existed cannot say which PDF it read, and calling that stale would
report the whole corpus for a sentence it never recorded; a database that
records no checksum cannot say which PDF this run reads.

### recorded_questions

```python
def recorded_questions(questions: Optional[dict]) -> dict
```

{key: [sentence]} -> the stamp keys that record what was really asked.

A question the model writes for THIS document exists nowhere else once the
run is over: it is not in the spec, not in a prompt and not in the JSONL.
Without it a harvest cannot be placed at all -- "which sentence found these
passages" has no answer, and `--force-stale` loses its meaning, because
nothing says what would be redone differently.

So it is written down, and never compared: `stale` compares the
ontology keys alone.

### stale

```python
def stale(stamp_path: Path, current: dict) -> list
```

Which keys differ from now; everything when unstamped.

The ontology keys are compared (`QUESTION_KEYS`: one per parameter,
value list, axis and slot), the whole-file sha `spec` only for a stamp
that has none of them, and the sha256 of the PDF the harvest read from
(`DOCUMENT_KEY`) where the stamp and `current` both carry one. The model,
the anchors, every prompt and every recorded sentence are in the stamp for
a reader and decide nothing: the owner's rule of 2026-09-10 is that a
stamp rests on the KG/ontology parameters alone, so a reworded prompt or
another model leaves a harvested corpus current. The PDF is the one
addition the owner decided on: another file under the same name is not
the document the ontology keys were read against.

A key the stored stamp does not have counts as changed, which is what
makes a stamp from before the per-parameter keys read as stale: it cannot
vouch for a coordinate it never recorded, and pretending otherwise is how
a document keeps a harvest nobody can place.

Both directions: every key is written from what the spec still HAS, so a
question that is gone is in no current key at all. Dropping an axis moved
nothing and the document read as current under a spec that no longer asks
that coordinate -- the whole-file sha used to catch it, and stopped once
it was no longer compared.

### documents_to_harvest

```python
def documents_to_harvest(documents, out_dir: Path, spec_sha: str, *,
                         force: bool = False, force_stale: bool = False,
                         anchors_sha: str = "", spec: Optional[Spec] = None,
                         top_up: bool = False,
                         start_at: bool = False) -> list
```

Which of these documents this run has work for.

A top-up is the exception and it is not a small one: this filter drops
exactly the documents whose stamp moved, which is the entire population a
top-up exists to re-read. Filtered, the flag is a no-op that logs
"nothing to harvest" unless --force-stale is also given. The pass that
appends a parameter (`--top-up-parameters`) asks for the same, for the
same reason.

### read_in_part

```python
def read_in_part(stamp_path: Path) -> bool
```

Whether the stamp's document was read at its found places alone, with
nothing having read the rest of it since.

### already_done

```python
def already_done(name: str, out_dir: Path, spec_sha: str, *,
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "", spec: Optional[Spec] = None,
                 start_at: bool = False) -> bool
```

True when this document needs no work: harvested under the current
ontology keys — or stale with nobody asking for the redo. A document read
at its found places alone is no work only for a run that starts at them:
any other run owes it the rest of the plan.

### not_happened

```python
def not_happened(report, *, answered: Optional[int] = None,
                 lost: int = 0) -> Optional[tuple]
```

(cause, requests, of) when the reading of this document did not happen.

The three ways a document comes back with a file and no reading, counted
in the unit the message needs: "unreachable" is the sources that never
reached the server, of the sources the plan held; "no_reply" is the
sources planned, when not one batch came back (`answered` is how many did;
None means the caller does not track it and the count is not checked);
"unserved" is the requests that ended on a 429, a 5xx or a timeout, `lost` of them
noted beside the report and the rest in its sentinels. None when the
reading happened. `finish_document` withholds the stamp on any of them
and the pass for a new parameter writes nothing.

### finish_document

```python
def finish_document(report, name: str, out_dir: Path, spec_sha: str,
                    anchors_sha: str = "", answered: Optional[int] = None,
                    spec: Optional[Spec] = None,
                    questions: Optional[dict] = None,
                    lost: int = 0) -> bool
```

Write one document's JSONL and stamp it with what produced it.

The stamp is what a resume trusts, so it is withheld when the harvest did
not happen. A dead server answers every request the same way and every
document comes back all sentinels; stamping those would write up to a
thousand empty documents down as finished, and the run that resumed would
skip every one of them without a word.

`answered` is how many of the document's batches came back at all. None
means the caller does not track it and the count is not checked. Zero
against a plan that had sources is the second way a harvest fails to
happen, and the sentinel arithmetic below cannot see it: with no reply
there is no tuple and no refusal either, so it reads 0 > n/2, says no, and
stamps an empty file. That is how a dead server turned 872 planned
documents into 0-byte results a resume would have skipped.

`lost` is how many of the document's other requests (a coordinate,
the frame, a search sentence) ended on a 429 or a 5xx, or timed out; the passages that
ended there carry it in their sentinel. One is enough to withhold the
stamp: the request was never answered and nothing says it cannot be.

An earlier stamp is removed before the file is written. It vouched for
the file this one replaces, and left in place it would have a resume
skip a document whose stamp was just withheld. Returns whether the
document is stamped.

### check_against_schema

```python
def check_against_schema(report, name: str, spec,
                         states: Optional[list] = None) -> int
```

Count the rows this document would write that the schema refuses.

Counted and traced, never blocking. The harvest is the durable artifact
and a row the schema does not recognise is still evidence; refusing to
write it would turn a documentation defect into a data loss. What it must
not do is pass unnoticed, because the schema is what everyone downstream
reads instead of this file.

### resolve_image_root

```python
def resolve_image_root(pdf_root: Optional[Path],
                       fallback: Path) -> Path
```

Where the table and figure crops live, given where the PDFs live.

The crops sit next to the PDFs they were cut from, so a run that names its
PDF root has already said where they are. Falling back to the profile's
processed dir is only right when nothing was named: this deployment passes
db, index and pdf root explicitly and keeps its data somewhere else
entirely, and the profile default pointed every crop at a directory that
does not exist — one warning per table, and a harvest that read every
picture's transcription without the picture.

### field_slots

```python
def field_slots(spec) -> list
```

Every slot a request can ask, one per request: the parameter, the
unit, each parameter's coordinates and the value of a category parameter
asked again.

### context_budget

```python
def context_budget(prompt, spec=None) -> int
```

Tokens one harvest request needs at worst — a floor for the server.

Counted, not guessed: system prompt, parameter payload and JSON envelope,
a source window at its ceiling, the crop that rides along, and the reply.
The estimate this replaces allowed 6000 tokens for "largest source,
generous" and no image at all, and the job script served that number as
--max-model-len; every section over it came back as a 400.

The payload term is measured off the spec when there is one: a parameter
that hands the model a class list to choose from is many times the size of
one that asks for a wording, and a flat allowance for both underserves the
first. A request comes in two shapes, and the larger counts: one planned
for a single parameter carries that parameter whole, and one planned for
no parameter carries every parameter's class lists at once. The second
was not counted until a profile had four lists, one of 153 classes, and
its reading requests outgrew a budget that still measured the widest
single parameter. A field request carries one slot's options as the
model reads them, definitions and all, and the value of a category
parameter asked again carries its whole list: 63,230 characters for 154
sectors whose parameter payload counts 9,627. Unmeasured, that request
did not fit the window and was never sent.

A request carries several sources now, so the text term is the batch's
ceiling rather than one window's — and one source too long to share a
request rides alone, which is why the larger of the two is what counts.
Every source in a batch may bring a crop, and the prior block rides along
on top.

### request_budget

```python
def request_budget(spec, profile=None) -> int
```

Tokens the largest request this run sends needs, per request.

The window a server is started with has to hold every request kind of the
run, so it follows the largest of them. Read off the prompts the run
sends (`survey_prompt_ids`): the two reading requests, the combing and, where the profile writes it, the match. Never off one that
no request carries, and not the review, which has a line of its own in
the doctor.

### select_documents

```python
def select_documents(documents: list, wanted: Optional[list]) -> tuple
```

(chosen, missing) for a --document restriction; no restriction = all.

`missing` is what was asked for and is not on offer, which for this corpus
means superseded rather than absent: `_documents` lists current versions
only. A pilot has to hear about that instead of quietly being smaller than
it was meant to be.

### span_marks_of

```python
def span_marks_of() -> dict
```

{coordinate: entry} a value stated for a span of years takes on each
of its rows, as the active profile says it (`SPAN_MARKS`,
`reading.span_rows`); {} where it says nothing.

### year_states_of

```python
def year_states_of(profile) -> dict
```

{state: which frame pairs are that state of the plan}, as the profile
says it: their years date a row that names the state by word
("Basisjahr", "Zieljahr") and prints no year. None for a state the
profile does not name, which then has no years.

### fold_answers

```python
def fold_answers(answered: list, report, *, locate: Optional[Callable],
                 spec: Spec) -> None
```

Every answered batch of a document folded into its report, and the
rows and refusals that came of it traced.

The harvest and the pass for a new parameter fold the same way: the same
`fold_batch` against the spec the batch carries, so the checks a row
meets are the harvest's own whichever of them read it.

### run_spec_path

```python
def run_spec_path(args, profile)
```

The spec file this run reads: the one --spec names, else the
profile's own, None where the profile names none. The stamps are written
from this file, so a column of one's own has stamps of its own; the
folder it writes into is kept apart by `scratch.folder_problem`.

### main

```python
def main(argv: Optional[list] = None) -> int
```

### write_stats

```python
def write_stats(out: Path, traces: list, names: set) -> None
```

Where this run found the harvest hard (stats.py), beside it. A
failure to count is logged and never fails the run.

[Back to the index](../README.md)
