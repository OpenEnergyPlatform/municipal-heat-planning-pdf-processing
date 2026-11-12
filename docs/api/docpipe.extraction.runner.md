# docpipe.extraction.runner

`docpipe/extraction/runner.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

runner.py: Wires the pure harvest loop of `pipeline.py` to the live stack.

A run reads each plan in pieces of numbered lines (`surveyed_flow`, which
stops the run where the spec names no groups or the profile lacks a prompt
of the harvest): every piece asked for every field in the order a reranker
gives it, each coordinate of each value found asked on its own, and a
coordinate its place does not state searched for (`addressed.py`, run per
document by `surveyed.py`), then the fold, the compute step and the file
with its stamp as below. The passes over a
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

Documents one of whose requests ended on a 429, a 5xx or a timeout,
on a refusal asked `refusal_retry_most` times (`refused`), or on a fault
of our own code (owner decision 2026-11-12).

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

A failure that is the server's (`server_side`: no reply, a 429, a 5xx)
is asked again, after the long wait (`retry_wait`), without a limit
until the run halts (`halted`, owner decisions 2026-11-09 and
2026-11-12: only the server's error codes are asked again without a
limit), or as often as the rule `server_retry_most` says where it is
above 0; a reply that could not be read is asked again as often as the
number `replies` says at most (`attempts`, read for the request, in its
step), and a request the server refuses (`refused`, owner decision
2026-11-09) as often as `refusal_retry_most` says, after the short
wait. Any other failure is a fault of our own code: asked again as
often as the rule `other_errors_retry` says (0: not at all). A request
given up on whose last attempt the server did not serve (`unserved`),
refused, or failed in our own code leaves its document unfinished
(`UNSERVED`): the stamp is withheld, the run goes on, a resume reads it
again, and the log names the fault with where it arose.

*document_id* is the document the request reads, None for a request of
the run itself. *noted* is False for a request whose end is told another
way: one the document is finished without (the places map, the review),
or one whose hole carries its cause to the stamp itself (the rows
harvest, `not_happened`). It still waits and stops by the rule.

#### Failures.\_\_init\_\_

```python
def __init__(self, document_id=None, noted: bool = True)
```

#### Failures.attempts

```python
def attempts(self, replies: int = 0)
```

The attempts of one request, 1, 2, ...: after a failure that is
the server's (`failed` True) the next one after the long wait, until
the run halts; after a reply that could not be read (`fault`) the
next one after the short wait, *replies* such replies at most (the
number `replies` of the flow, read for this request, where none is
given); after a refusal the next one after the short wait, as long
as `failed` says so. The caller ends the loop on an answer and where
`failed` says no more.

#### Failures.failed

```python
def failed(self, exc: BaseException) -> bool
```

Whether the request that raised *exc* is asked again: after the
server's failure until the run halts or the rule `server_retry_most`
is reached (`attempts`), after a refusal until it is the
`refusal_retry_most`th, after a fault of our own code as often as
the rule `other_errors_retry` says. A request not asked again has
no answer, and its document is not finished (`lost`).

#### Failures.answered

```python
def answered(self) -> None
```

The server answered the request, whatever its reply says.

#### Failures.fault

```python
def fault(self) -> int
```

The reply could not be read: how many such replies so far.

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

The request is asked no more and has no answer. A fault of our
own code is logged with where it arose, whether or not its document
is noted: it is what a person fixes.

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
a crop is counted at `image_tokens`, the most one can take. The estimate
this replaces ran short on tables of figures, where the tokenizer gives
every digit a token of its own: requests went out one token over the
window and were refused, and a refused request that carried a crop broke
the server's multimodal cache (vLLM before 0.28, CVE-2026-105753).

#### PromptCounter.\_\_init\_\_

```python
def __init__(self, tokenizer)
```

### Persistent

```python
class Persistent
```

A reranker whose every order is asked again until it answers or the
run halts, a refused one as often as the flow's `replies` says at most
(`persistently`).

#### Persistent.\_\_init\_\_

```python
def __init__(self, reranker)
```

## Functions

### in_home

```python
def in_home(kind: Optional[str])
```

Read with the values of the box that is the home of requests of this
kind (the first box of the flow that asks it) while the block runs,
unless the step that runs asks this kind itself. Requests of a kind are
asked from other steps too: the entry of a list from the step of a find,
the check that a find speaks about the value from the step that searches
(it is attached to it, and the engine does not enter its box), the name
of a scenario from a search. Such a request is asked as the step that
asks that kind says (its model, its answer room, its extras), so that
every request of a kind is asked alike, wherever it comes from.

### attached_homes

```python
def attached_homes(tree: list) -> dict
```

{(the id of a box, a kind of request): the step after it that asks
this kind for it}: the steps that stand right after a box and apply to
its answers (`blocks.Box.attached`), such as "Choose the list entry".

### llm_base_url

```python
def llm_base_url() -> str
```

Where the requests go (rule `llm_base_url`, set at the start).

### llm_api_key

```python
def llm_api_key() -> str
```

The key of the model server (rule `llm_api_key`, set at the start).

### llm_model

```python
def llm_model() -> str
```

The model the request sent now asks (rule `model`: the step's, else
the run's).

### llm_timeout

```python
def llm_timeout() -> float
```

What the first attempt of a request waits (rule `llm_timeout_s`).

### reply_limit

```python
def reply_limit() -> int
```

Replies out of their form the request sent now takes before it is
left unanswered: the number `replies` of the flow as the step that sends
it reads it, which the setting EXTRACT_MAX_RETRIES wins over.

### retry_timeout

```python
def retry_timeout() -> float
```

What a retry may take after a request timed out (rule
`repeat_timeout_s`). The first attempt keeps `llm_timeout_s`, which is
sized for a slow but working generation; a request the server did not
answer in that time is unlikely to differ on its repeat, and three full
timeouts held one field thread for 91 minutes.

### retry_temperature

```python
def retry_temperature(base: float, faults: int) -> float
```

The sampling temperature after `faults` unreadable replies. A
malformed reply asked again at temperature 0 comes back the same, byte
for byte, correction message or not: on corpus_m5 field retries repeated
their first attempt exactly and all three were lost. Every reply fault
raises the temperature of the next attempt by a step (rules
`retry_temperature_step`, `retry_temperature_most`).

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

### failure_statuses

```python
def failure_statuses() -> tuple
```

((first, last) of each status range, whether a timeout counts) of the
rule `server_failure_statuses`: the answers that mean the server did not
do the work. Refused where an entry is none of 429, 500-599, timeout.

### unserved

```python
def unserved(exc: BaseException) -> bool
```

A 429, a 5xx or a timeout: the server was asked and did not do the work
(the statuses of the rule `server_failure_statuses`).

None says anything about the request. A rate limit lifts and a server
recovers, and the same request is answered then. A request that timed out
was never answered either: a server whose engine stopped taking requests
kept its connections open until every one of them timed out, and their
documents were stamped with the coordinates never read. Every other 4xx
refuses the request itself (`refused`). The status is read as the
providers read it (`governor.status_of`): the client's own or that of
its response, the reranker's.

### server_side

```python
def server_side(exc: BaseException) -> bool
```

Whether a failure is the server's: no reply came at all (no
connection, one that broke off, a timeout: `providers.no_reply`), or the
server said it did not do the work (`unserved`).

These wait on the long curve and count towards the dead-server streak. A
429 retried after two seconds is the same 429. Any other failure without
a status is a fault of our own code (owner decision 2026-11-12: only the
server's error codes are asked again without a limit): asked again, the
same request runs through the same code.

### refused

```python
def refused(exc: BaseException) -> bool
```

A 4xx that is not the server's failure (429): the server refused the
request itself, such as one too long for the model or one our code built
wrong ("System message must be at the beginning."). It is asked again
`refusal_retry_most` times at most, and a request refused to the end
leaves its document unfinished (owner decision 2026-11-09): a later run
reads it again, and nothing is lost without a word.

### halted

```python
def halted() -> bool
```

Does the run stop: a SIGTERM, or a server that answers no more?

### persistently

```python
def persistently(what: str, call: Callable) -> Callable
```

*call*, asked again after the server's failure (`server_side`) until
it answers or the run halts (owner decisions 2026-11-09 and 2026-11-12:
only the server's error codes are asked again without a limit): a
search, an embedding or a reranker that failed is never replaced by
another order or by nothing. Each failure is logged and waited for on
the long curve (`retry_wait`); a run that halts raises the last one.
With the rule `search_retry_most` above 0 the server's failure is asked
that many times at most and then raised. A request the server refuses
(`refused`) is asked `refusal_retry_most` times at most, and a fault of
our own code as often again as the rule `other_errors_retry` says, then
each is raised: its document fails and stays unfinished, the run goes
on, and a later run reads it again (owner decisions 2026-11-09 and
2026-11-12).

### code_rounds

```python
def code_rounds() -> int
```

Sandbox rounds per calculation question (rule `code_rounds`). A
computed value carries its code and the code's output as evidence;
without the sandbox the model would have to work the number out itself,
and that number would have no evidence at all.

### sandbox_slots

```python
def sandbox_slots() -> threading.BoundedSemaphore
```

The semaphore of the code runs the sandbox takes at once, as the rule
`code_slots` says it now.

### attach_images

```python
def attach_images() -> bool
```

Tables and figures go to the model as pictures as well as text (rule
`attach_images`): the transcription IS a reading of that picture, and a
model that can see both can notice when they disagree.

### image_max_side

```python
def image_max_side() -> int
```

Pixels of a crop's longer side (rule `image_max_side`).

### read_to_end

```python
def read_to_end() -> None
```

Every search from here on shows every piece of its document, so a
coordinate ends read or `unstated` and never `exhausted`.

### take_flow

```python
def take_flow(profile=None)
```

The numbers of the flow a run of *profile* reads with
(`flow.in_effect`: its flow file, and the settings over it), taken for
every request from here on and returned. They are logged whenever they
differ from those logged before, each with where it comes from, so that
the log of a job says what it read with.

### numbers

```python
def numbers() -> flow_map.Numbers
```

The numbers of the flow the run reads with: those `take_flow` took
for the run's profile, else what the default profile's flow file and
the settings over it say now.

### embedder

```python
def embedder()
```

The one resident embedding model this run uses.

`get_embedder()` CONSTRUCTS a backend, it does not return a shared one, and
this call used to sit inside the per-probe `embed()`. With several
planning threads each asking for its own probes, every probe
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
None where the run is given no reranker server (rule
`rerank_base_url`; owner decisions 2026-11-06 and 2026-11-08). A figure
is scored with its picture, as the reading shows it.

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

### phrase_told

```python
def phrase_told(prompt) -> str
```

The system prompt a field's sentence request is told, every part of
*prompt* it may carry (`PHRASE_KEYS`).

### step_asking

```python
def step_asking(target: str, preset: str, profile=None) -> dict
```

The step of a request asked apart from the reading of a document (a
calculation, a second reading, the example of a field): the first of
the flow of *profile* whose answer goes to *target*, on or off, else
the first of the flow of a pass, else its *preset*; read once where the
request's sender is made.

### step_parts

```python
def step_parts(step: dict, standard: str, profile=None) -> tuple
```

(prompt, inputs) of a step asked apart from the reading: the prompt
of its kind (*standard*) where it names that one, else its own
(`own_prompt`), and the inputs its first message is built from.

### sentence_step

```python
def sentence_step() -> dict
```

The step whose request writes a field's sentence, which the chunks
of a field are ordered by and the search of a field of the whole
document goes with: the first of the run's flow that orders the chunks
by it (`targets.chunk_order`), on or off, else its preset.

### phrase_payload

```python
def phrase_payload(parameter, context: Optional[dict] = None,
                   step: Optional[dict] = None) -> dict
```

What a field's sentence request carries: the inputs of the step that
writes it (*step*, `sentence_step` where None), from the field (its
name, what it means and the names of its list, owner decision
2026-11-05) and from what the document says of itself (*context*, its
texts only).

### sentences_written

```python
def sentences_written(profile=None) -> str
```

What names the sentences the orders of a harvest are made with
(`addressed.Orders`): the part of the prompt a field's sentence is told
(`phrase_told`), and the inputs and answer form of the step that writes
them where they are not its preset's. An order kept from sentences
written otherwise is made again; a part told only to the sentence of
one coordinate's search changes no order.

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
def make_seek_probes(context_of: Optional[Callable] = None,
                     write: Optional[Callable] = None) -> Callable
```

probes(parameter, document_id) -> the sentences a plan's passages
are ranked with for a parameter, which sets the order it reads them in,
and the search after an open coordinate goes with where its answer
wrote none (`addressed.Orders`, `engine.Engine.box_order`).

Every parameter gets a sentence written for this document by the model,
from the parameter's label, description and list names and from what
the document says of itself (*context_of(document_id)*, the profile's
`document_context`: the municipality of a plan, the title of a
publication), as the chat turns a question into a sentence of the
document before it searches (owner decisions 2026-11-05, 2026-11-08 and
2026-11-09). *write(parameter, context)* writes the sentences, one
phrase request (`document_anchor`) where not given. A parameter no
sentence could be written for gets none, and the search falls back to
its label. Each sentence is sent in its document's turn (owner decision
2026-11-07).

### document_anchor

```python
def document_anchor(spec: Spec, context: Optional[dict] = None,
                    client=None, prompt=None,
                    document_id: Optional[int] = None,
                    step: Optional[dict] = None) -> dict
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
of none goes before every document (owner decision 2026-11-07).

The request is built from the inputs of the step that orders the chunks
by the sentence (*step*, `sentence_step` where None) and asked with its
prompt (owner decision 2026-11-12 evening: every question is "Ask the
model").

### model_window

```python
def model_window() -> int
```

The window every request is sized against.

### image_tokens

```python
def image_tokens() -> int
```

One crop at its longest side on both sides, one visual token per
square of `image_token_side_px` pixels.

### least_answer_tokens

```python
def least_answer_tokens() -> int
```

Less room than this for the answer and the request is not sent
(rule `least_answer_tokens`).

### set_model_len

```python
def set_model_len(tokens: Optional[int]) -> None
```

The window the server reports, when it reports one.

### start_limit

```python
def start_limit() -> None
```

Steer the requests by the server's queue unless the rule
`limit_adaptive` is off.

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

### request_room

```python
def request_room(system: str, conversation: list, wanted: int,
                 whole: bool = False) -> Optional[int]
```

max_tokens a request may ask, None where the room is less than
`least_answer_tokens`: such a request is not sent and counts as an
answer that was cut off. The room is the answer that is asked for, or,
with *whole*, what the window leaves, however short the answer asked for
is (a search sentence of 300 tokens is sent where the window holds 512
more).

### request_wanted

```python
def request_wanted(kind: str) -> int
```

The longest answer, in tokens, a request may ask for (rule
`max_tokens` of the step that asks its kind).

### asked_values

```python
def asked_values(kind: Optional[str], profile=None) -> dict
```

The `max_tokens` and `temperature` a request of *kind* is asked with
where no run is going (the editor's try, the compile step): the values
of the box that is the kind's home in the flow of *profile*, else the
run's. A request of no kind the flow has asks with the run's.

### reply_grammar

```python
def reply_grammar(name: str, schema: dict, always: bool = False)
```

The `response_format` of a request whose reply is *schema*: always
for a request that never goes without its grammar, else as the rule
`schema_grammar` and the provider say (`providers.reply_format`).

### send_request

```python
def send_request(client, system: str, conversation: list, limit: int,
                 faults: int, response_format=None)
```

The one place a request of the harvest goes out: the model, the
temperature after *faults* unreadable replies (rules `temperature`,
`retry_temperature_step`, `retry_temperature_most`), the answer room
*limit*, the system prompt and *conversation*, the reply grammar where
one is asked for and the settings every request carries
(`request_extras`), each read for the step that sends it.

### make_page_count

```python
def make_page_count(db_path: Optional[Path]) -> Callable
```

document_id -> its page count in the catalog, None where unknown.

### system_text

```python
def system_text(prompt, example) -> str
```

The system prompt one request sends: the prompt with its example
reply ({{example}}) written for this request, as one line of JSON (owner
decisions 2026-11-06: every request's example shows exactly the
coordinates it asks, each read, so the model has no key to leave out).
A request that finds values gives two, a pair (owner decision
2026-11-09: "immer ein Positiv und ein Negativbeispiel"): the first
goes to {{example}}, the second to {{nothing}}. A prompt without such a
place is sent as it is written; one with it and no example for it is an
error before anything is sent, as every open placeholder is
(`prompts.Prompt.render`).

### ask_in_grammar

```python
def ask_in_grammar(client, prompt, conversation: list, shape: dict,
                   document_id: int, where: str, key: str, /,
                   example: Optional[dict] = None, **noted)
```

One request of the harvest, in the step that asks its kind
(`in_home`); see `_ask_in_grammar`.

### worded

```python
def worded(words: str, payload: dict) -> str
```

A message: its words, then what it shows as JSON.

### run_each

```python
def run_each(jobs: list, run: Callable) -> list
```

*run(job)* for each of *jobs*, side by side on the run's threads
(`AHEAD`) where it has them, the results in the order of the jobs. Only
the caller waits: no job waits for another, so the threads never wait
for themselves. A job that fails takes back every job not yet begun.

### request_prompt

```python
def request_prompt(parts, payload: dict, shape: Optional[dict] = None)
```

The prompt of one request: what every request of its kind is told,
and the part of each field its payload carries (`thread.Parts.system`,
owner decision 2026-11-07: no request is told about a field it does not
carry); where its reply may fetch (*shape* offers "more"), the part
`more`, and `get_image` where it may ask for a figure's picture (owner
decision 2026-11-12).

### reply_offers

```python
def reply_offers(shape: Optional[dict]) -> set
```

{"more", "get_image"} as far as the reply form *shape* offers them:
what a request's prompt tells about besides its payload.

### make_asks

```python
def make_asks(profile=None) -> Optional[addressed_map.Asks]
```

The requests of the harvest (`addressed.Asks`), each with a prompt of
its own and its payload as one message, no conversation (owner decisions
2026-11-08) where the rule `conversation` keeps none (`messages`); None
where the profile writes one of their prompts not,
those of `addressed.OPTIONAL` aside. A request asked again
(`follow`) goes under the prompt of the request it follows, its words
after the payload. The sentence a search goes with is a request of its
own (`phrase`, owner decision 2026-11-09), under the prompt the
document's search sentences are written with.

### own_prompt

```python
def own_prompt(prompt, profile=None)
```

The prompt of a general step: the prompt file *prompt* names
("extraction/find"), or {"text": ...} a text of the step's own, made as
a prompt file of the profile would be (`prompts.made`).

### image_path_of

```python
def image_path_of(source, image_root: Optional[Path]) -> Optional[str]
```

Where a figure's crop is, None where the run sends no image or the
figure has none.

### transcript_fingerprint

```python
def transcript_fingerprint(profile) -> Callable
```

fingerprint(told=None): what names the prompt and model that wrote a
kept transcription of a figure (`addressed.Transcripts`, owner decision
2026-11-08, e), told where it is read, in the step that writes out the
figures, whose model it names; *told* the step's own prompt, inputs and
answer form where they are not its preset's
(`engine.Engine.writes_figures`). "" where the profile writes no prompt
for it.

### search_budget

```python
def search_budget() -> tuple
```

(pieces, shares, per request) of every search of the run: how many
pieces a search for an open coordinate or a field the document has
once shows, how many of them each kind of passage gets first, and how
many a request shows (owner decisions 2026-11-09: 50, 20 of tables, 15
of figures, 15 of text, 5 a request), from the run's flow (`NUMBERS`);
a pass that reads to the end shows every piece (`read_to_end`).

### make_reader

```python
def make_reader(spec: Spec, profile, order: Callable, search_order: Callable,
                probes: Optional[Callable] = None,
                rerank: Optional[Callable] = None,
                context: Optional[Callable] = None,
                image_of: Optional[Callable] = None)
```

The reading of a document piece by piece (`addressed.Reader`), or
None where its spec names no groups or the profile writes no prompts
for it. What is asked once of a plan beside its fields
(`Spec.plan_fields`) and the field that names other works
(`Spec.works`) come from the spec (owner decision 2026-11-10); how much
a search shows (`search_budget`) and every other number that bounds the
reading from the run's flow (`NUMBERS`).

### make_chunk_reranker

```python
def make_chunk_reranker() -> Optional[Callable]
```

() -> one thread's reranker of the pieces of a plan, which scores
every piece it is given (`rerank.Reranker`), asked again until it
answers (`Persistent`), or None where the run is given no reranker
server (rule `rerank_base_url`). How many pieces it scores is the rule
`rerank_chunk_pool`, read when it orders.

### make_harvest

```python
def make_harvest(spec: Spec, *, db_path: Optional[Path], out: Path,
                 image_root: Optional[Path], profile, every: Callable,
                 spec_for: Optional[Callable] = None,
                 rank: Optional[Callable] = None,
                 reranker: Optional[Callable] = None)
```

The harvest of a document piece by piece (`surveyed.SurveyedHarvest`)
as a run and a probe make it: the order of the pieces by the reranker
(*reranker*, `make_chunk_reranker`) and the search over passages
(*rank*, `make_more_sources` with its reranker), a field's search
sentences (`make_seek_probes`), the figures transcribed once and kept
under *out* (`transcripts/`), the orders kept there too (`survey/`), and
the numbers of the profile's flow (`take_flow`: the lines of a piece
among them). *every(
document_id, exclude)* is the plan's passages in its order. A search
that fails is asked again until it answers, a refused one as often as
the flow's `replies` says (`persistently`).

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

### probe_server

```python
def probe_server(base_url: str = None,
                 timeout: Optional[float] = None) -> bool
```

Whether the server answers `GET {base_url}/models` at all.

Any reply below 500 counts: a server that refuses the key is still there.
The time it waits is the rule `server_probe_timeout_s`.

### watch_server

```python
def watch_server(on_dead: Callable, *, probe: Callable = probe_server,
                 every: Optional[float] = None,
                 dead_after: Optional[float] = None,
                 clock: Callable = time.monotonic,
                 sleep: Callable = time.sleep) -> threading.Thread
```

A daemon thread that calls *on_dead(seconds)* once the server has not
answered for *dead_after* seconds (rule `server_dead_after_s`), probing
every *every* (rule `server_probe_every_s`), then stops watching.

### shared_http

```python
def shared_http(limit=None)
```

The one connection pool every request of the run goes out through.

Each kind of request has a client of its own (finding, coordinates,
lists, the search, the check, ...), and each client used to keep a
pool of its own:
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
or None where nothing was open. None where the profile has no such step
or the flow has its box (`catalogue`) off or not at all.

### compute_pool

```python
def compute_pool() -> ThreadPoolExecutor
```

The threads the calculation questions of the whole run take turns on,
as many as the rule `compute_parallel` says now (one pool for each size
it has had).

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
(*pages_of*, `lookup.two_pages`), and a question that takes a number
(`Question.take`) may take it from whatever the request showed: a
passage, its title, a hit's line or title (owner decision 2026-11-05).
*rank(document_id, probes, exclude)* is the plan ranked for a sentence,
which "similar" lists (`make_more_sources` in a run); without it that
search finds nothing.

### step_models

```python
def step_models(profile=None) -> dict
```

{step id: model} of the steps of the flow that name a model of their
own (rule `model`), for the check before the run
(`llm_preflight.assert_step_models`). A step that is off asks
nothing, so the model it names is not needed.

### preflight

```python
def preflight(required: int, *, what: str, profile=None) -> bool
```

The check before the run (rule `preflight_on`): the server offers
the model, its window holds *required* tokens, and, where a *profile*
is given, the models its steps name are offered too. True where the
check ran, False where the rule has the run ask nothing.

### documents_at_once

```python
def documents_at_once() -> int
```

The most documents read at the same time (rule
`documents_in_flight`), at least one.

### dead_server_ends_run

```python
def dead_server_ends_run(seconds: float) -> bool
```

Does a server that has not answered for *seconds* end the run (rule
`dead_server_ends_run`)? Where it does not, the run says so and goes
on.

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

The prompts of a harvest piece by piece (`SURVEY_PROMPT_IDS`), and
those of `addressed.OPTIONAL` the profile writes: the check of a find
from another passage, the names request.

### surveyed_flow

```python
def surveyed_flow(spec: Spec, profile=None) -> bool
```

Whether a run can harvest piece by piece: its spec names groups. A
spec without groups cannot be harvested (`main` stops on it).

A spec with groups whose profile lacks a prompt of the harvest is a
broken profile: the run stops and names the prompt, as `spec.load`
stops at a broken group (owner decision 2026-11-04), before a request
is sent rather than at the first plan's reading.

### names_asked

```python
def names_asked(spec: Spec) -> bool
```

Whether a run asks names against a document's lists: its spec
merges a field or a coordinate into a list of names (a scenario), or
keeps a list of works (`Spec.works`).

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

A pass that asks a model also names the flow it read with (`take_flow`):
`numbers`, every number in effect, a setting that won over the flow file
among them, and `flow_file`, the sha256 of the flow's files; and the
rules (`rules_file`, the sha256 of the rules files, `rules_set`, the
rules a setting set). For a reader: a changed number or rule makes no
harvest stale.

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

### question_keys

```python
def question_keys() -> tuple
```

The keys of a stamp that decide whether a document is read again
(rule `question_keys`, owner decision 2026-09-10).

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

The ontology keys are compared (`question_keys`: one per parameter,
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
"unserved" is the requests that ended on a 429, a 5xx, a timeout, a
refusal asked `refusal_retry_most` times or a fault of our own code
asked `other_errors_retry` times, `lost` of them
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
the frame, a search sentence) ended on a 429 or a 5xx, timed out,
were refused to the end or failed in our own code; the passages that
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

A request shows the pieces of a search: as many as the flow says
(`search_per_request`), each of its lines (`piece_lines`) and headings
(`headings`) at the tokens the longest line takes (`window_line_tokens`);
each piece may bring a crop. Each number counts at its largest in the
flow, wherever a box sets one for itself.

### most_of_number

```python
def most_of_number(name: str) -> int
```

The largest value the number *name* of the flow takes in any box or
frame of it that is on (the run's number, and what each node sets for
itself).

### answer_tokens_of

```python
def answer_tokens_of(prompt) -> int
```

The longest answer a request of *prompt*'s kind may ask for: the
longest of those the steps of the flow that ask this kind set for
themselves (rule `max_tokens`), else the run's.

### request_budget

```python
def request_budget(spec, profile=None) -> int
```

Tokens the largest request this run sends needs, per request.

The window a server is started with has to hold every request kind of the
run, so it follows the largest of them. Read off the prompts the run
sends (`survey_prompt_ids`): one per kind of request of the reading
(`addressed.KINDS`). Never off one that no request carries, and not the
review, which has a line of its own in the doctor.

### select_documents

```python
def select_documents(documents: list, wanted: Optional[list]) -> tuple
```

(chosen, missing) for a --document restriction; no restriction = all.

`missing` is what was asked for and is not on offer, which for this corpus
means superseded rather than absent: `_documents` lists current versions
only. A pilot has to hear about that instead of quietly being smaller than
it was meant to be.

### year_states_of

```python
def year_states_of(spec: Spec) -> dict
```

{state: which frame pairs are that state of the plan}, as the spec
says it at the plan field of the state's year (`plan_fields`, key `of`,
owner decision 2026-11-10): their years date a row that names the state
by word ("Basisjahr", "Zieljahr") and prints no year, in a pass over a
stored harvest, which asks no plan its years. None for a state the spec
does not say it of, which then has no years.

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

### chosen_flow

```python
def chosen_flow(args) -> tuple
```

(the flow this run starts, why it cannot): `--flow NAME` or the flow
the switch chooses, the main flow where there is neither. A switch that
chooses another flow than `--flow` names is refused.

### follow_up_problem

```python
def follow_up_problem(name: str, profile) -> Optional[str]
```

Why the flow *name* cannot be started for *profile*, or None.

### follow_up_run

```python
def follow_up_run(args, spec, current, documents, document_name, whole,
                  every, locate, document_axes, frame_axes, year_states,
                  sweep, owner_sources, in_flight, room, harvest_document,
                  make_found, harvest_documents_of) -> passflow.Run
```

What a flow of a follow-up pass runs with (`passflow.Run`): where the
harvest is, the stamp this run would write, and the means to read a
document again as the harvest reads it (`whole`: the survey of the
plan, asked for the new parameters alone or for the passages nobody
read).

### log_follow_up

```python
def log_follow_up(name: str, stats) -> None
```

The line that says what a pass over a stored harvest did.

### main

```python
def main(argv: Optional[list] = None) -> int
```

The call line of the run. What a call switch sets for the run alone
(`--document`, `--force`) is a rule laid over the rules for as long as
the run goes (`rules.overlaid`), and gone after it.

### write_stats

```python
def write_stats(out: Path, traces: list, names: set) -> None
```

Where this run found the harvest hard (stats.py), beside it. A
failure to count is logged and never fails the run.

[Back to the index](../README.md)
