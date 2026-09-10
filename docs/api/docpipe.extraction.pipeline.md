# docpipe.extraction.pipeline

`docpipe/extraction/pipeline.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pipeline.py: The harvest loop that turns a document's retrieved passages into
verified value tuples.

`plan_document` builds one retrieval plan per document rather than per
parameter: every table and every figure, taken whole because being a table or a
figure predicts a value better than any similarity ranking does, plus the best
ranked prose sections. `group_items` folds the plan into batches read in one
request each. A batch stays inside one document and one parameter, or the whole
document when the plan is not split by parameter, so it never mixes what a
different parameter's choice list would need. Every claimed tuple, whichever
request produced it, passes `verify_tuple`; refusals are kept alongside the
accepted tuples, because a harvest that cannot say what it threw away reads as
complete when it is not.

`Sweep` and `build_sweeps` carry the tuples a document's batches have already
verified forward as a hint to later batches, and grant a bounded follow-up
budget when a reply says more passages are needed (`follow_up`).
`fold_claims` and `fold_batch` verify a reply's claims into a
`DocumentReport`; `write_report` writes that report's tuples, refusals,
per-parameter states and one summary line to one JSONL file, atomically.

A coordinate is checked for two things and no third: its quote stands in a
passage that was shown, and the quote carries the answer (`merge_field`).

The three expensive dependencies, retrieval, the harvesting LLM call, and
locating a quote on its PDF page, are injected callables. The module's own
correctness is a pure-code property and is tested without a GPU; the wiring to
the live inference stack lives in `runner.py`.

Author: Felix Vossel

## Classes

### Source

```python
@dataclass
class Source
```

One retrieval owner as the harvest needs it.

Fields:

- `owner_kind: str`: "section" | "table" | "figure"
- `owner_id: int`
- `text: str`: what the model will read
- `provenance: dict = field(default_factory=dict)`
- `image_path: Optional[str] = None`: the crop, for tables and figures
- `body: Optional[str] = None`: The transcription without the heading prefixed to `text`, for the quote repair alone — that repair needs the value to occur exactly once.

### WorkItem

```python
@dataclass
class WorkItem
```

One harvest request: read THIS source.

`parameter` is None for a document-level plan, where which quantity a
value is gets asked for instead of assumed. It stays for the callers that
still plan per parameter.

`rank` and `origin` are carried, not recomputed: every knob this stage has
is a cut through a ranking, and a cut can only be measured if the number
it cuts at is written down next to what came out.

Fields:

- `document_id: int`
- `parameter: object`
- `source: Source`
- `rank: Optional[int] = None`: position in the fused ranking
- `origin: str = ""`: "structure" | "retrieval"

### Batch

```python
@dataclass
class Batch
```

Several sources read in ONE request, for one parameter.

A single source at a time is how the answer loop in the chat app works,
and it is the wrong unit here: a plan states the carrier in the heading,
the year in the caption and the number in the table, and a model shown
only the table has to invent the other two or refuse. A batch puts the
neighbouring passages in front of it at once, so a tuple can be assembled
across them instead of guessed from one.

Sources keep their label (`id`): the model names the label a value came
from, and every claim is verified against THAT source's text. The batch
widens what the model may read, not what a quote may be checked against.

Fields:

- `document_id: int`
- `parameter: object`
- `items: list = field(default_factory=list)`: [WorkItem], label = index + 1
- `followed_up: bool = False`: True for a batch the model asked for, which the plan never counted.
- `frame: Optional[dict] = None`: Which of the document's (scenario, year) pairs this request asks for, and its index. The same passages are read once per pair: a table with four year columns is four requests, each one asking for one column, which is what takes the coordinate out of the model's hands.
- `frame_index: int = 0`
- `anchors: tuple = ()`: The sentences this request's passages were searched with. They say, in the plan's own words, what the request asks for, so the pair reaches the model as a question and not only as a field.
- `frame_default: Optional[dict] = None`: The pair a passage that names no pair at all is read under, and its index: the profile's FRAME_DEFAULT. The request reads it like the rest, and the pair is written onto its rows afterwards.
- `frame_default_index: int = 0`

#### Batch.sources

```python
@property
def sources(self) -> list
```

#### Batch.label

```python
def label(self, index: int) -> str
```

### DocumentReport

```python
@dataclass
class DocumentReport
```

Fields:

- `document_id: int`
- `tuples: list = field(default_factory=list)`
- `refusals: list = field(default_factory=list)`
- `flags: list = field(default_factory=list)`
- `owners_harvested: int = 0`
- `sweep_rounds: dict = field(default_factory=dict)`: parameter uri -> rounds
- `fallback: dict = field(default_factory=dict)`: parameter uri -> {"candidates": n, "leftover": m}. The running quality metric of the retrieval sweep: how much of the deterministic candidate set retrieval never surfaced. A growing leftover means the probes (or the vocabularies they expand from) have a blind spot.
- `followups: dict = field(default_factory=dict)`: parameter uri -> {"asked": n, "served": m}: how often the model said the passages were not enough, and how often retrieval could answer that.
- `planned: dict = field(default_factory=dict)`: What the plan was built from, so a run can be read back against the settings it ran under instead of against the ones in the file today.
- `sources_of: dict = field(default_factory=dict)`: parameter uri -> {(owner kind, owner id)}: what that parameter's own anchors rank. Planned from nothing; it tells a parameter whose passages a cut-off request held from one whose passages were read.

### Row

```python
@dataclass
class Row
```

One value found in one source, before its coordinates are filled.

A row is created by the value request and by nothing else. Every later
request fills a column of rows that already exist, so no field request can
invent a value and none can quietly drop one: the count is fixed before
the first coordinate is asked for.

Fields:

- `label: str`: "R1", the id a field answer names
- `item_index: int`: which source of the batch it sits in
- `claim: dict = field(default_factory=dict)`

### Sweep

```python
class Sweep
```

The shared state of one (document, parameter), across its batches.

Batches used to be run one after another so that a later one could be
told what the earlier ones had found. That made a chain the unit of
scheduling, and the unit of scheduling is the unit of parallelism: a
single-document run — which is exactly what the pilot's canary stage is —
collapsed to one request per parameter, three at a time against a server
sized for two hundred, and the canary that used to take three minutes was
killed unfinished after nine.

So the ordering is gone and the bookkeeping stays. `prior` is a hint that
stops the model handing back a value a neighbouring passage already gave;
a hint does not need to be deterministic, and paying two orders of
magnitude of throughput to make it so is the wrong trade. Every batch
reads whatever has been verified by the time it is dispatched.

Verified, not claimed: a tuple that verification threw away used to be
handed to the next batch as "already extracted", and the prompt tells the
model not to repeat those — so a value refused once for a bad quote was
suppressed everywhere else in the document, leaving neither a tuple nor a
refusal behind.

#### Sweep.\_\_init\_\_

```python
def __init__(self, seen: set, budget: int)
```

#### Sweep.snapshot

```python
def snapshot(self) -> list
```

#### Sweep.record

```python
def record(self, verified: list) -> None
```

#### Sweep.take_followup

```python
def take_followup(self, sources: list) -> list
```

The passages of a follow-up this sweep has not already covered.

## Functions

### plan_document

```python
def plan_document(
    document_id: int,
    spec: Spec,
    templates: list,
    *,
    extra_probes: Optional[dict] = None,
    retrieve: Callable,                 # (probes, document_id, exclude) -> [Source]
    structure: Optional[Callable] = None,   # (document_id) -> [Source]
    prose_top: int = PROSE_TOP,
    top: Optional[int] = None,
) -> tuple
```

(work items, report skeleton) — the retrieval half, no model involved.

One plan per DOCUMENT, not one per parameter. Which quantity a number is,
is a coordinate the field sweep asks for like every other, so a table is
read once instead of once per parameter.

Two sets go in, and they are picked by different rules because the values
sit in them for different reasons:

* every table and every figure, from structure alone. Measured over 65
  documents, 12,094 of 15,082 values came from one of those, and "is a
  table" is a better predictor of holding a number than any similarity to
  any question. There are about 110 per document, so reading all of them
  is affordable exactly once the parameter stopped tripling the plan.
* the best `prose_top` sections by retrieval. Prose carries the other
  fifth of the values and there are 125 sections per document, so this is
  the half where a ranking has to earn its keep.

The probes are the HyDE anchors and nothing else. The query templates used
to ride along and they were measured as harmful: with them the source a
value was really read from sat at median rank 84, without them at 26. A
template names the thing, an anchor says the sentence as a plan would
write it, and a similarity search matches sentences.

No rounds. The old loop asked retrieval again with everything it had
already returned excluded, which walks down the ranking until the document
is exhausted — 277 planned sources against 234 owners, three times over.
That is a full scan wearing a vector store as a hat.

`top` replaces both rules with one. The plan is then the fused top `top`
in rank order, tables figures and prose together, and the structural floor
is not a source of items any more. It is still CALLED, and what it knows
and the ranking missed is reported as `leftover` — the number that says
whether the floor has to come back, which can only be taken while the
floor is still there to ask. Without `top` nothing about this function
changes.

### group_items

```python
def group_items(items: list, *, max_sources: int = BATCH_SOURCES,
                max_chars: int = BATCH_CHARS) -> list
```

Work items grouped into batches — one request reads several sources.

Grouping is per document AND per parameter, in the order the plan built
them, so a batch holds passages that were ranked next to each other. It
never mixes parameters: the choice lists differ per parameter, and a batch
spanning two of them would have to carry both.

A document-level plan has `parameter is None` on every item, so the rule
still holds and the grouping is simply per document. Which parameter each
value belongs to is asked for afterwards, per row, with its own evidence.

### route_claims

```python
def route_claims(batch: Batch, tuples: Optional[list]) -> tuple
```

(one claim list per work item, unroutable claims).

The model names the source a value came from, but a label is the easiest
thing in a batch to get wrong, and a mislabelled tuple would be refused
for a quote that is verbatim in the document. So the quote settles it:
the claim goes to the source whose text actually carries it, and the
label only breaks the tie when several do.

A claim that neither carries a findable quote nor names a real label is
NOT filed under the first source. It used to be, and that was a way to
manufacture evidence: verify rebuilds a missing quote from the source it
was handed whenever the value occurs there exactly once, so a claim read
from the fourth passage could be accepted carrying the first passage's
page, section and image as its provenance. It comes back as unroutable
instead, and the caller refuses it.

The claims handed in are not changed. A routed claim is a copy without
its label: the runner routes one reply twice, once for the next batch's
prior and once to fold it, and popping the label in place took from the
fold the label the field-wise harvester had put back for it.

### row_label

```python
def row_label(index: int) -> str
```

### cell_index

```python
def cell_index(quote: str, value) -> Optional[tuple]
```

(cell holding this value, cells in the row), 1-based, or None.

The one thing a field request should not have to work out for itself. A
table row quoted whole carries three numbers under three year columns, and
which year applies is decided by which cell the number sits in — a fact
that is already known here, because the value and the row it was quoted
from are both in hand. Handing it over turns "count the cells" into a
given and leaves the model the part that actually needs reading: which
year the header's nth cell names.

None whenever it is not certain: no table row, the value in no cell, or
the same number in two of them. A wrong column is worse than none.

### names_pair

```python
def names_pair(source, pair: Optional[dict], slots: list) -> bool
```

Does this passage print the scenario and the year of this pair?

The whole passage, not a line of it. Where the year stands is the plan's
business: a column header, a caption, a sentence above the table.

### names_no_pair_at_all

```python
def names_no_pair_at_all(source, pairs: list, slots: list) -> bool
```

Does this passage print no scenario of any pair and no year at all?

The one kind of passage a document's default pair is read under: an
inventory table that states neither is the plan's inventory. A passage
that prints a year, any year, or the scenario of one of the pairs keeps
what it says and stays where its year is asked per row.

### rows_from_reply

```python
def rows_from_reply(batch: Batch, reply: Optional[dict],
                    frame_axes: Optional[list] = None) -> tuple
```

(rows, orphans) from the value request - the only request that counts.

Routing is the same as for a whole tuple: the quote decides which source a
value belongs to, the label breaks a tie, and a claim that neither quotes
nor names any source of the batch is an orphan.

Under a frame, a passage that does not print the request's pair gives no
row: `apply_frame` writes the pair onto every row, so the pair has to
stand in the passage the row was read from. A passage that prints several
pairs, a table with a column per year, is read under each of them, and
each request takes the column of its own pair.

A sentinel for a request that never came back is not a claim. It passes
through untouched, its `_why` included, because the resume reads it there.

### answer_in_quote

```python
def answer_in_quote(slot, given, wording: Optional[str], quote: str) -> bool
```

Does the coordinate actually stand in the passage cited for it?

Both halves of a quote's job, and the second one is the one that was
missing. A passage that sits in the source proves the model read
something; only a passage that CONTAINS the answer proves it read this.
Measured on the corpus run that had the first half alone: 27.6% of years
cited a passage with no year in it, one of them the caption "Tabelle 1:
Bestehende Wärmenetze und Heiz(kraft)werke" offered as evidence for 1990.

A number is compared as a number, a wording as text — the same split
value_in_quote makes for the value itself, because these are the same
question asked one level down.

### wording_names_option

```python
def wording_names_option(slot, given, wording) -> bool
```

Does `value_raw` name the option the answer chose?

field.md rule 2 says the wording is what the mapping is checked against,
and until now nothing checked it. A reply could answer "Biogas" with the
wording "Klärgas" and the quote would verify -- the passage really does
say Klärgas -- while the graph carried Biogas on the strength of it.

Whole tokens, not substrings: "Gas" inside "Erdgas" is a different word,
and a containment test would call every carrier evidence for every other.
A wording longer than a label is not one either; measured on Kassel, the
rounding footnote was offered as `value_raw` 15 times.

This is a COUNT, not a refusal. 29 of Kassel's carrier readings map
Klärgas onto Biogas and 17 map "Holzige Festbrennstoffe" onto woody
biomass, and both are right: the model is allowed to decide that a
document's word belongs to a class the spec spells differently. What we
have no measurement of is how often it decides wrongly, and that is
exactly what this counter is for.

### merge_field

```python
def merge_field(rows: list, sources: list, slot, reply: Optional[dict],
                *, window: Optional[tuple] = None) -> dict
```

Fold one field's answers. Returns {"filled", "unquoted", "unbacked"}.

*window* is (stage, index) and is written next to each coordinate this
call reads, together with the source the passage was found in. Which
passage proved a coordinate is the one thing a later audit cannot
reconstruct.

Every answer brings its own passage, and that passage has to pass exactly
what the value's own quote passes: it sits verbatim in one of the sources
that were SHOWN, AND it contains the answer. A field that fails either is
left empty rather than written unbacked — the point of asking per field is
that each coordinate is evidenced, and an answer that cannot show where it
read the year is exactly the answer a whole-tuple request used to hide
inside a tuple the value's quote had already justified.

Shown, not the row's own source: the year of a table is in its caption and
the scenario is in the section heading, so a coordinate's evidence is
routinely in a different passage than the number's. Checking it against
the row's own source would refuse exactly the readings this stage exists
to collect.

Those two clauses, and a quote long enough to name a place in the
document, are the whole check. Which table a passage belongs to, how far
from the row it stands, and which column of a table it heads are the
model's reading, not a rule of this function. Every reason a reading is
dropped for is listed in `schema.DROP_REASONS`, and a test holds this
function to that list.

### line_naming

```python
def line_naming(slot, given, wording, text: str) -> Optional[str]
```

The line of this passage that carries the answer, or None.

So that a projected coordinate cites the passage the row itself was read
from rather than the passage the frame was read from. Both are true, and
only one of them tells a reader whether the row's own table says it.

### apply_frame

```python
def apply_frame(rows: list, pair: Optional[dict], index: int,
                slots: list, sources: Optional[list] = None) -> int
```

Write the document's frame onto these rows. Returns coordinates written.

The pair was read once, for the document, and every row this request
produced is a row of that pair: the request asked for it by name and
`rows_from_reply` refused the passages that do not print it. So the
coordinate is not asked again per row, it is projected, and the window
says `frame` so a reader can tell a coordinate that was read for the
document from one that was read for the row.

A table with a column per year is no exception. It prints several pairs
and is read under each of them, the request for one pair takes the column
of that pair, and every row it produced carries that pair's year.

Cited on the row's own passage where that passage names the answer, and on
the frame's passage otherwise. `read`, not `derived`: `derived` means the
SPEC decides a coordinate without anybody reading anything, and this is a
model reading with a passage behind it.

A coordinate already read is left alone. The frame is what the request
asked for, but if the row itself carried a better answer the row wins,
the same rule `merge_field` has and for the same reason.

### open_rows

```python
def open_rows(rows: list, slot) -> list
```

The rows this field still has no reading for.

Both the never-answered and the answered-with-"not stated": the second is
only a statement about the passages that were shown, and the next window
shows different ones. It becomes a statement about the document when the
windows run out, and not before.

### window_sources

```python
def window_sources(pool: list, size: int, overlap: int)
```

Walk a source pool in short overlapping windows.

Short, not wide. A coordinate that is not in the passage the value came
from is somewhere else in the plan, and the way to it is more requests
with little context each, not one request with all of it: the window that
holds the answer holds it whether or not ninety other passages ride along,
and the ninety cost the attention that finds it.

The overlap is why a caption is never cut off from the table it belongs
to, which is the seam the year lives on.

### mark_unanswered

```python
def mark_unanswered(rows: list, slots: list) -> int
```

Every coordinate no field reply mentioned, named as such. Returns how many.

The number this exists to expose. Before it, a coordinate the model had
skipped and a coordinate the document does not state were the same empty
cell — 16% to 34% of every axis on the 1079-document run, and no way to
tell which half was the corpus and which half was the harvest. A row that
reaches this with no state was asked and did not answer, and that is a
defect of the run, not a property of the plan.

### sweep_key

```python
def sweep_key(batch: Batch) -> tuple
```

What one follow-up budget and one `prior` belong to.

The document, its parameter and the frame pair the request asks for. The
same passages are read once per pair, so telling the request for 2035 that
the request for 2040 already has these numbers tells it to skip its own:
`prior` says "do not repeat", and two pairs of the same table are not a
repeat.

### build_sweeps

```python
def build_sweeps(batches: list, rounds: int = 1) -> dict
```

One Sweep per (document, parameter, frame pair), keyed as the batches
are.

A document-level plan has no parameter, so the key is the document and the
follow-up budget is the document's.

### follow_up

```python
def follow_up(batch: Batch, reply: dict, sweep: Sweep, more_sources: Callable,
              *, max_sources: int = BATCH_SOURCES,
              max_chars: int = BATCH_CHARS) -> list
```

The extra batches a "there is more here, look for this" earns.

The third of the four answers a batch may give. "Found it" and "not in
these passages" end the batch; the sandbox is a turn inside the request
and never reaches here. This one does work: the model writes what to
search for, retrieval answers with passages this document has not shown
yet, and they join the pool like any other batch. Bounded per sweep, and
what arrives is excluded from every later round, so a model that keeps
asking cannot loop.

### harvest_document

```python
def harvest_document(
    document_id: int,
    spec: Spec,
    templates: list,
    *,
    retrieve: Callable,                   # (probes, document_id, exclude) -> [Source]
    harvest: Callable,                    # (Batch, prior) -> reply dict
    locate: Optional[Callable] = None,    # (Source, quote) -> rects | None
    structure: Optional[Callable] = None,   # (document_id) -> [Source]
    more_sources: Optional[Callable] = None,  # (doc, queries, exclude) -> [Source]
    extra_probes: Optional[dict] = None,
    prose_top: int = PROSE_TOP,
    max_sources: int = BATCH_SOURCES,
    max_chars: int = BATCH_CHARS,
) -> DocumentReport
```

Plan and harvest one document, one batch after another.

The serial path: it keeps the loop's semantics in one readable piece and
is what the tests own. Real runs do the same work with every batch of
every document in flight at once, which is the whole reason a batch and
not a chain is the unit here.

### fold_claims

```python
def fold_claims(item: WorkItem, claims: Optional[list],
                report: DocumentReport, *,
                locate: Optional[Callable] = None,
                spec: Optional[Spec] = None) -> None
```

Verify one source's claims into the report — the pure half of a harvest.

The parameter comes from the claim when the plan did not fix one: a
document-level plan reads a passage once and the field sweep decides, per
row and with its own quote, which quantity the number is. A claim that
names no parameter the spec knows cannot be verified against anything and
is refused rather than folded under a guess.

### batch_uri

```python
def batch_uri(batch: Batch) -> Optional[str]
```

The parameter a batch was planned for, or None for a document plan.

Public because the parallel scheduler in the runner keys the same sweeps
by the same thing. It was not, and the runner reached through
`batch.parameter.uri` in three places, which is how a plan that had
correctly dropped 825 sources to 162 died on its first batch.

### refused_upstream

```python
def refused_upstream(claim) -> bool
```

A claim the harvester already refused, its reason in `_why`.

Not a sentinel: a sentinel's `_why` says why a request never came back,
and it stays on the claim for the resume to read.

### fold_batch

```python
def fold_batch(batch: Batch, reply: Optional[dict], report: DocumentReport, *,
               locate: Optional[Callable] = None,
               spec: Optional[Spec] = None) -> None
```

Verify one batch's reply into the report.

The reply carries the tuples, and it carries what the model said about
them: `complete` means these passages hold nothing else for this
parameter, `partial` with `need_more` means a value is in here but its
context is not. The second is the number that matters for the next
sweep — it is the model telling us where retrieval was too narrow.

A claim the harvester already refused keeps the reason it was refused
for. Verified a second time, 631 of Kassel's claims came out as "claim
names no parameter of the spec" instead of saying why.

### write_report

```python
def write_report(report: DocumentReport, out_path: Path,
                 states: Optional[list] = None) -> None
```

Tuples, refusals, parameter states and one summary, written atomically.

Refusals are rows too (kind=refusal): the file is the audit trail, and an
audit that only shows the survivors cannot answer why a value is missing.

The last line (kind=summary) is the distribution over this document's own
values, so "how much of this plan can I use" has an answer that does not
require reading 559 rows. It goes last because it is computed from
everything above it.

`states` is one line per PARAMETER (kind=parameter_state). Every other
state in this file belongs to a row, so a parameter that produced no row
left nothing behind at all, and "the document does not carry it" read
exactly like "we never got round to asking".

[Back to the index](../README.md)
