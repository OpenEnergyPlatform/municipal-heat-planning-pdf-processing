# docpipe.extraction.runner

`docpipe/extraction/runner.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

runner.py: Wires the pure harvest loop of `pipeline.py` to the live stack.

This module supplies the loop's expensive dependencies from the real world:
FAISS retrieval with owner exclusion, the harvesting LLM call, and locating a
quote on its page in the source PDF, plus resume stamps and the CLI. Heavy
imports (faiss, torch-backed embedders, fitz) happen inside functions, so
importing this module stays cheap and a test that only touches the package pays
for no GPU stack it does not use.

`make_retrieve` fuses every probe handed to it into one FAISS search per
document and ranks each owner by the best score any probe gave it; measured
over 65 documents and 15,082 values, the fused ranking put the source a value
was really read from at median rank 26, against 77 for the old per-probe
concatenation. `make_candidates` is a deterministic floor under that ranking,
matched by LIKE over the corpus's own vocabulary tokens. A probe is either one
of the spec's query templates (`queries.expand`), stable across the whole
corpus so `prime_probe_cache`'s embeddings hit for every document, or a
HyDE-style anchor sentence a model writes: `make_anchors` writes one set per
question the field sweep asks, cached under `anchors.json` and reusable across
documents, and `document_anchor` writes the one short sentence per parameter
the document being planned is searched with, which is a cache miss by
construction.

`make_harvester` and `make_fieldwise_harvester` build the request to the model,
parse its reply, and rescue the tuples already written when a reply is cut off
at the token ceiling (`rescue_reply`). `make_sweeper` drives the field-wise
sweep: a coordinate the value's own passage does not answer is asked for again
over short overlapping windows of the rest of the document (`window_sources`),
bounded per axis. `find_frame` and `make_frame_asker` read a document's frame,
its scenario and year pairs, once before any value, so a value request states
the pair rather than deciding it. `harvest_batches` runs every batch of a whole
run in flight at once, not as ordered per-document chains.

`make_locate` finds where a quote sits on its page in the source PDF, through
the same alignment the app highlights with. Resume stamps (`_stamp_current`,
`stale`) record a fingerprint per question a spec asks (`spec.fingerprints`),
so an ontology edit restales only the documents asked through the coordinate it
touched, not the whole corpus. `main` is the CLI: a normal harvest, and the
`--recheck`, `--remap`, `--serialize`, `--review` and `--top-up` maintenance
passes over a harvest already written.

Author: Felix Vossel

## Functions

### window_budget

```python
def window_budget() -> dict
```

{stage: windows} for one coordinate's sweep, own then retrieval then
rest. Read at call time so a test that moves one constant moves this.

The sum is FIELD_MAX_WINDOWS + REST_MAX_WINDOWS. `own` can never bind --
one window, and the attempt loop already stops at FIELD_ATTEMPTS -- and
is written here so the three numbers add up in one place instead of two.

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

### make_content_fetcher

```python
def make_content_fetcher() -> Callable
```

fetch_owner_content, but each owner is read from SQLite once.

A sweep meets the same section again in the next round, and again for the
next parameter: four parameters times four rounds is the same row read up
to sixteen times over NFS. One planning thread owns one of these, so it
needs no lock.

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

### make_structure

```python
def make_structure(conn: sqlite3.Connection,
                   content_fetcher: Optional[Callable] = None) -> Callable
```

(document_id) -> every table and every figure of the document.

The floor of the plan, and it is structural rather than lexical on
purpose. The old floor searched the stored text with LIKE for the
vocabulary's own words, which is a worse version of the retrieval above
it — measured over the corpus it never had anything left to add, because
the sweep above had already walked the whole document.

This one adds what retrieval is bad at and structure is certain about:
12,094 of 15,082 values came from a table or a figure, and whether
something is a table is not a question a similarity search should be
asked. There are about 110 per document, which is affordable exactly
because the plan is no longer built once per parameter.

### make_parents

```python
def make_parents(db_path: Path) -> Callable
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

### make_owner_sources

```python
def make_owner_sources(db_path: Path) -> Callable
```

(owners) -> {(kind, id): Source} for passages a harvest already named.

The harvest stores the address of a passage and not its text, so a pass
that reads one coordinate again has to fetch it back. Through the same
two functions the harvest used -- the cached fetcher and `_source_of` --
so the heading is prefixed the same way and a quote that was checkable
during the harvest stays checkable.

Its own connection per thread, read-only, and memoised across calls: one
section is the parent of several rows and would otherwise be read once
per row.

### make_review_sources

```python
def make_review_sources(db_path: Path) -> Callable
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
handles are not shared.

### own_section_number

```python
def own_section_number(sources) -> Optional[int]
```

The earliest section any of these passages stands in, or None.

The rest stage reads in the document's own order, and that order starts at
section 1 -- the title page of a 249-section plan, for a row that stands on
page 180. Earliest and not nearest, because one sweep asks for several rows
at once and only a start before all of them is close to every one.

### make_rest_of_document

```python
def make_rest_of_document(db_path: Path) -> Callable
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

### make_more_sources

```python
def make_more_sources(db_path: Path, index, id_to_pos: dict,
                      cache_path: Path) -> Callable
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

### fill_dynamic_axes

```python
def fill_dynamic_axes(spec: Spec, vocabularies: Optional[dict]) -> Spec
```

A copy of *spec* whose dynamic axes carry THIS document's list.

The AR6 scenario names are run identifiers — EN_INDCi2030_300f — and two
of 328 of them occur verbatim in the text they were extracted from. The
document says "the Current Policies scenario". Nothing but the model can
bridge that, and it can only do so if it is shown the list it may choose
from; the mapping then arrives flagged, like every other judgement call
the harvest records.

### anchor_question_key

```python
def anchor_question_key(target) -> str
```

The one question a stored anchor set was written for.

An anchor is a sentence written from a label, a description and a
wording. Those three and the anchor's own id are the target tuple, so the
tuple IS the question, and a set is reusable exactly while its tuple has
not moved.

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
`slot/parameter` -- and the anchor prompt and the model are stamp keys too
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

### document_anchor

```python
def document_anchor(spec: Spec, context: Optional[dict] = None,
                    client=None, prompt=None,
                    frame: Optional[dict] = None) -> dict
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

### years_in_sources

```python
def years_in_sources(sources, low: int = 0, high: int = 0) -> set
```

Every year-shaped number in these passages. A count, not a reading.

The frame carries the whole harvest: every value is asked for one of its
pairs, so a year the frame missed loses all of that year's values at once
and loses them silently -- which is the one failure this design has that
the old one did not. So the same passages the model was shown are scanned
without a model, and what it did not name is reported.

Reported, never added. "2045 MWh/a" is a year-shaped number and is not a
year, and a cross-check that decided would put it in the frame and ask
every table for a year the plan does not have.

### fitted_max_tokens

```python
def fitted_max_tokens(exc, asked: int, where: str = "") -> Optional[int]
```

A completion budget that fits the window this request overflowed, or
None when the error is another one or no answer fits.

The server names both numbers when it refuses. Measured on Kassel: one
field request of 26,625 prompt tokens asked for 6,144 more, was refused
for one token over 32,768, and the break on a 4xx wrote its coordinates
off. The prompt is what it is, so the room for the answer is what gives.

### make_frame_asker

```python
def make_frame_asker(image_root: Optional[Path] = None) -> Callable
```

ask(sources, slots, document_id, known, usage_out) -> reply or None.

One request, and the answer is a list of pairs with two quotes each. Two,
because a column header carries the years and a section heading carries
the scenario: one passage can back both halves only when it prints both,
and every coordinate is checked against its OWN quote exactly as a field
answer is.

### frame_pairs

```python
def frame_pairs(reply: Optional[dict], slots: list, sources: list) -> list
```

The pairs of a reply that carry their own evidence, in order.

Every coordinate is held to what a field answer is held to: its quote sits
verbatim in one of the passages that were SHOWN, and the quote contains
the answer. Nothing else is checked. A frame reading is
document-level by construction -- it is read once, from a caption or a
heading, and every row of the document inherits it -- so "is this passage
near this row" is not a question about it, and no reading anywhere in
the harvest is asked it.

### frame_windows

```python
def frame_windows(sources: list, max_sources: int = 0,
                  max_chars: int = 0) -> list
```

The plan's passages in windows one frame request can hold.

All of them, not a prefix. A pair may only be quoted from a passage that
was shown (`frame_pairs`), so a year printed past the cut cannot enter the
frame at all, and a pair the frame does not have loses every value of that
pair. Measured on Kassel: a frame over the first 12 of 50 passages found
2 pairs, 2040 and 2024, and 174 of the 234 table tuples the hand reading
covers were then stamped with a year printed on another table.

### find_frame

```python
def find_frame(sources: list, slots: list, document_id: int, ask: Callable,
               more_sources: Optional[Callable] = None,
               probes: Optional[list] = None) -> tuple
```

(pairs, status, missed) - which scenarios and years this document has.

Asked once per document and over every window of the plan, before any
value. Every value question is then one of these pairs, which is what
takes the coordinate out of the model's hands: it is not asked which year
a number belongs to, it is asked what the number for THIS year is.

`missed` is the deterministic cross-check: the year-shaped numbers in the
passages that no pair names. It is a finding for the second pass, never an
addition to the frame, and the second pass shows the window that CARRIES
the missed year instead of the first window again.

### load_anchors

```python
def load_anchors(path: Path, key: str, targets: list) -> dict
```

The anchor sets a previous run wrote that are still the answer to the
same question.

Per question, not per file. One changed question used to miss the whole
cache and have the model rewrite all nineteen sets, and those sets decide
which passages a document is read from -- so an edit to the year question
changed the retrieval of the carrier coordinate, which nothing had asked
for and no line anywhere reported.

A file written before the per-question map existed carries none of it and
is therefore reused for nothing: it cannot say which of its sets still
answer, and guessing is how a run comes to search with a set nobody
checked.

### save_anchors

```python
def save_anchors(path: Path, key: str, anchors: dict,
                 targets: Optional[list] = None) -> None
```

Write the sets and, beside each, the question it answers.

### make_anchors

```python
def make_anchors(spec: Spec, client=None, *, store: Optional[Path] = None,
                 key: str = "") -> dict
```

anchor id -> search anchors the model wrote for one question.

The QA app turns a question into a HyDE anchor before it searches: a
sentence written as it would READ in the document, because that is what a
similarity search matches against. This stage searched with the spec's
templates alone, which name the thing rather than say it.

Once per run and per question, not per document: the anchor depends on
the question, not on the plan, and a stable probe string is what makes the
query-embedding cache hit across the whole corpus.

### probe_texts

```python
def probe_texts(spec: Spec, templates: list, anchors: Optional[dict] = None) -> list
```

Every retrieval probe the run will ever send, once, order-stable.

### prime_probe_cache

```python
def prime_probe_cache(cache_conn, spec: Spec, templates: list,
                      anchors: Optional[dict] = None) -> int
```

Embed every probe of every parameter in one batch, before any planning.

The probes come from the spec, not from a document, so the whole corpus
asks the same few dozen questions. Embedded from inside the sweep they
cost one GPU round trip per miss and put every planning thread behind the
same lock; embedded here they cost one call, and retrieval afterwards
reads nothing but the cache.

### make_candidates

```python
def make_candidates(conn: sqlite3.Connection,
                    content_fetcher: Optional[Callable] = None) -> Callable
```

Token-filtered owners of one document, straight from SQL.

LIKE over the stored text is deliberately dumb: it is the *floor*, not
the harvest. Retrieval finds what wording variance hides from tokens;
this finds what ranking hides from retrieval.

Bound to the caller's connection. It used to open its own for every call,
which on an NFS-backed database is a file open, a header read and a schema
parse per document and parameter.

### expand_defaults

```python
def expand_defaults(defaults: Optional[dict], tuples: list) -> list
```

Fold the reply's shared coordinates into every tuple that omits them.

Measured on the one table that truncated in three consecutive pilots: of
the sixteen keys a tuple carries, ten are identical across all 39 of its
tuples, and rewriting them costs 52% of the whole answer. So the model
writes them once. A tuple's own key always wins, and a key in
NOT_DEFAULTABLE is dropped however the model labelled it.

### rescue_reply

```python
def rescue_reply(raw_text: str) -> Optional[dict]
```

Every complete tuple in an answer the generation cut short.

A reply that hits the token ceiling stops mid-key, never on a boundary,
so the JSON is unparsable — but the tuples written before the cut are
whole, and each of them is quote-checked downstream like any other. The
walk uses the standard decoder rather than counting braces, because the
quotes are lifted verbatim from the plans and the plans contain BibTeX:
15 of 1936 sections in the pilot set are `@misc{...}` dumps, and a
quote-sized window of those is almost never brace-balanced. Only a real
JSON scanner knows which brace is structure and which is evidence.

### log_usage

```python
def log_usage(budget: Optional[int] = None) -> None
```

One line at the end of a run: what the window was really asked for.

### make_harvester

```python
def make_harvester(image_root: Optional[Path] = None,
                   prompt_id: str = HARVEST_PROMPT_ID,
                   spec=None) -> Callable
```

The request loop, for either contract.

The whole-tuple prompt and the field-wise value prompt differ in what they
ask for and in nothing else: same sources, same crops, same sandbox, same
rescue of a reply cut off at the token ceiling. So the prompt is the
argument and the loop is shared.

### keeps_row

```python
def keeps_row(slot, answer, allowed) -> bool
```

Does this gate answer keep the row in the slice this run serializes?

The answer is the option's LABEL, because that is what a field reply
carries and what merge_field writes: "Potenzial", not "out:potential". The
profile names classes, so the label is resolved here — reading the profile
as if it held German spellings would have kept every potential and thrown
away every target scenario, which is exactly what it did.

Undecided keeps the row. A coordinate that came back empty or "not stated"
is a finding about the passages, not a licence to throw the value away,
and dropping on it would silently shrink the harvest by whatever the sweep
happened to miss.

*allowed* None means every class the graph takes, which is every entry
that does not ride the out: convention. A tuple names the answers.

### make_field_asker

```python
def make_field_asker(image_root: Optional[Path] = None) -> Callable
```

ask(batch, rows, slot) -> reply, or None when the field stays unasked.

No sandbox and no rescue of a truncated reply. A field answer is a choice
and a quote, never arithmetic, and a reply cut off in the middle fills
fewer rows than it could — which is a gap the harvest can see, because the
coordinate is simply empty and counted as empty. That is the difference
the whole change is about: what is missing is missing on the record.

### make_review_asker

```python
def make_review_asker(image_root: Optional[Path] = None) -> Callable
```

ask(row, shown, parameter, slots) -> reply, or None.

One stored value, read again over the two passages it may quote from. The
same model and a narrower window, so what it can find is a reading that
contradicts itself -- not a reading that is wrong about the picture in the
same way twice.

### make_sweeper

```python
def make_sweeper(ask: Callable, *,
                 more_sources: Optional[Callable] = None,
                 rest_of_document: Optional[Callable] = None,
                 parents: Optional[Callable] = None,
                 anchors: Optional[dict] = None) -> Callable
```

sweep_field(batch, rows, slots, anchor_id) -> what the sweep came to.

Lifted out of the harvester so a pass that re-reads ONE coordinate of an
already harvested document walks the same three stages, in the same
order, under the same allowances. A second copy of this would be a second
set of numbers, and every measurement the sweep has ever produced is
about this one.

Its five dependencies are exactly what it closed over inside the
harvester: the asker, and the three ways of finding more passages plus
the anchor sets that seed them.

### make_fieldwise_harvester

```python
def make_fieldwise_harvester(image_root: Optional[Path] = None,
                             more_sources: Optional[Callable] = None,
                             rest_of_document: Optional[Callable] = None,
                             spec=None, anchors: Optional[dict] = None,
                             slice_gate: Optional[dict] = None,
                             parents: Optional[Callable] = None,
                             frame_axes: Optional[list] = None
                             ) -> Callable
```

A harvest(batch, prior) that asks per field and answers like the old one.

Same signature as make_harvester's, so the scheduler above it does not
change: the batch is still the unit in flight, and the sweep over the
fields happens inside one batch's turn.

### split_long_sources

```python
def split_long_sources(items: list, max_chars: int = MAX_SOURCE_CHARS) -> list
```

Work items whose source text fits one request.

A section longer than the window used to be sent whole, rejected by the
server with a 400, retried twice and written off — the values in it were
lost without ever being read. Windows overlap so a number is never cut in
half at the seam; both windows carry the same owner, so the provenance and
the dedup that hang off it do not notice the split.

### harvest_batches

```python
def harvest_batches(batches: list, harvest: Callable, *,
                    more_sources: Optional[Callable] = None,
                    verify: Optional[Callable] = None,
                    on_give_up: Optional[Callable] = None,
                    workers: int = LLM_PARALLEL) -> list
```

Every batch of the whole run in flight at once.

The batch is the unit, not the chain. A chain — one document, one
parameter — has to be read in order only if a later batch must be told
what an earlier one found, and making that ordering real made it the unit
of scheduling too: the pilot's canary stage is a single document, which
is three chains, so three requests faced a server sized for two hundred.
The same document had taken three minutes when every source was its own
request; it was killed unfinished after nine.

So `prior` became a hint that each batch reads at dispatch instead of a
sequence it waits for. *verify* turns one reply into the rows that
survived checking, and only those are recorded — the hint must not carry
claims the verifier threw away, or a value refused once is suppressed
everywhere else in the document.

Returns [(batch, reply)] in submission order, follow-up batches appended
as they are earned. Ordering is by index, not by completion: the server
answers a 40-token table long before a 6000-token section, and the report
must not depend on that.

*on_give_up* is called once when the dead-server cut fires. Cancelling this
group is not enough on its own: the cut fired sixteen times in one run and
the loop went on to the next group each time, so a server that died at
01:44 was still being asked at 05:14. What the caller does with it is the
caller's business, but it has to be able to know.

### make_locate

```python
def make_locate(db_path: Path, pdf_root: Optional[Path]) -> Optional[Callable]
```

(Source, quote) -> highlight rects in the source PDF, or None.

Uses the same alignment the app highlights with, so a value's recorded
provenance and the box a reader sees are produced by one implementation.
A section can run over a page break, so the section's other pages are
tried too - bounded, because this opens the PDF each time.

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

So it is written down and never compared. See `RECORDED_PREFIXES`.

### stale

```python
def stale(stamp_path: Path, current: dict) -> list
```

Which stamped versions differ from now; everything when unstamped.

A key the stored stamp does not have counts as changed, which is what
makes a stamp from before the per-parameter keys read as fully stale: it
cannot vouch for a coordinate it never recorded, and pretending otherwise
is how a document keeps a harvest nobody can place.

What it does NOT count is the whole-file sha, once there are per-question
keys to go on. That is the point of them: a change no question is asked
through must cost nothing. Writing a graph block for all fourteen
scenarios parameters moves `spec` and not one question -- measured -- and
a run that re-read the corpus over it would be re-reading it over a
comment.

Both directions, and the second one is why: every key is written from what
the spec still HAS, so a question that is gone is in no current key at
all. Dropping an axis moved nothing and the document read as current under
a spec that no longer asks that coordinate -- the whole-file sha used to
catch it, and stopped once it was no longer compared.

### documents_to_harvest

```python
def documents_to_harvest(documents, out_dir: Path, spec_sha: str, *,
                         force: bool = False, force_stale: bool = False,
                         anchors_sha: str = "", spec: Optional[Spec] = None,
                         top_up: bool = False) -> list
```

Which of these documents this run has work for.

A top-up is the exception and it is not a small one: this filter drops
exactly the documents whose stamp moved, which is the entire population a
top-up exists to re-read. Filtered, the flag is a no-op that logs
"nothing to harvest" unless --force-stale is also given.

### run_document

```python
def run_document(document_id: int, name: str, out_dir: Path, spec: Spec,
                 spec_sha: str, templates: list, deps: dict, *,
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "") -> bool
```

### already_done

```python
def already_done(name: str, out_dir: Path, spec_sha: str, *,
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "", spec: Optional[Spec] = None) -> bool
```

True when this document needs no work: harvested under the current
spec, prompts, model and anchors — or stale with nobody asking for the
redo.

### finish_document

```python
def finish_document(report, name: str, out_dir: Path, spec_sha: str,
                    anchors_sha: str = "", answered: Optional[int] = None,
                    spec: Optional[Spec] = None,
                    questions: Optional[dict] = None) -> None
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
first.

A request carries several sources now, so the text term is the batch's
ceiling rather than one window's — and one source too long to share a
request rides alone, which is why the larger of the two is what counts.
Every source in a batch may bring a crop, and the prior block rides along
on top.

### fit_batch_sources

```python
def fit_batch_sources(prompt, spec, wanted: int = BATCH_SOURCES) -> int
```

The largest batch this profile can be ANSWERED for, at most *wanted*.

The two numbers that killed a pilot lived in different files and nobody
ever compared them: how many sources one request reads is set here, and
how much the model may write about them is set in the prompt's
frontmatter. Six sources of kwp tuples fit in 8192 tokens; six sources of
ar6 tuples, whose quotes are whole sentences, need 11000 and would be cut
off — every time, deterministically, on five GPUs.

So the batch follows the answer budget rather than a hand-picked
constant, and what one tuple costs comes from the profile's own example,
which is the very contract the prompt shows the model.

### select_documents

```python
def select_documents(documents: list, wanted: Optional[list]) -> tuple
```

(chosen, missing) for a --document restriction; no restriction = all.

`missing` is what was asked for and is not on offer, which for this corpus
means superseded rather than absent: `_documents` lists current versions
only. A pilot has to hear about that instead of quietly being smaller than
it was meant to be.

### pair_batches

```python
def pair_batches(items: list, pairs: list, pair_plans: list, frame_axes: list,
                 anchors: list, *, default: Optional[dict] = None,
                 max_sources: int = BATCH_SOURCES,
                 max_chars: int = BATCH_CHARS) -> tuple
```

(batches, rest, added, assumed) for one document with a frame.

A pair is read over every passage that prints it. Its own search and the
document's search keep `PLAN_TOP` passages each, cut from two rankings.
A table the document's search found that prints 2045, below the cut of
the 2045 search, was in no batch at all: not under the pair, whose search
had not kept it, and not in the rest, which is what prints none of the
pairs. So every passage any search of the document planned goes to every
pair it prints. `added` counts the ones a pair's own search had not kept;
a pair whose own search failed (`None`) is read over those alone.

`rest` is what the document's search found that prints none of the pairs.
With a `default` (the profile's FRAME_DEFAULT) that exactly one pair of
the document matches, a passage of the rest that names no pair at all,
no scenario of any pair and no year, is read under that pair instead: the
owner's rule for an inventory table that states neither, after Kassel's
Tabelle 3 left 35 values without a year. `assumed` counts those passages.

### main

```python
def main(argv: Optional[list] = None) -> int
```

[Back to the index](../README.md)
