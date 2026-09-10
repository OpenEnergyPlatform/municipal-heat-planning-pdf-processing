## Purpose

`docpipe/extraction/` is the stage where a retrievable passage becomes a
typed value a knowledge graph can hold. Stages 1 through 6 turn a PDF into
sections, tables and figures a search can find; this stage reads those
passages against a profile's ontology contract and writes out value
tuples, a number, a class from a closed vocabulary, or a plain text
string, with its unit or vocabulary entry where the parameter has one,
and a handful of axes (which carrier, which sector, which year, which
scenario) that place it in the ontology's own terms.
`docpipe/extraction/__init__.py` names this ontology-based information
extraction, OBIE.

Nothing here is written on a model's word alone: every claim is checked
against the profile's closed vocabularies and the literal text of its
passage, and what survives carries that evidence, down to each
coordinate's own quote and source. A value the
run cannot back is refused rather than written with a gap where its
evidence should be. That is what separates this stage from a plain text
search: the question it answers is not only what the document says but
whether this run can support it with evidence, and the answer is recorded
next to the value, in a form later stages and the four maintenance
passes can act on without asking a model again.

## Position in the pipeline

| | |
|---|---|
| **In** | The corpus [chunking](chunking.md) built: the SQLite database's `Sections`, `Tables`, `Images`, `Embeddings`, `Documents` and `DocumentMeta` rows, and the FAISS index. No file under `results/` is read directly. Also a profile's validated `extraction_spec.json` (`spec.load`). |
| **Out** | One `<document>.jsonl` harvest and one `<document>.stamp.json` resume stamp per document, a per-document trace file under `trace/`, and, written once per run, `anchors.json` and `query_cache.db`. A `--serialize` call reads the harvest back and writes one Turtle file, feeding [the knowledge graph](graph.md) stage. |
| **Resumes on** | `<document>.stamp.json`, compared against what today's spec would produce, one key per parameter, value list, axis and slot; the whole-file spec sha stands in only for a stamp that carries none of those. The model, the anchor set and every prompt are written into the stamp for a reader and are never compared. A document with no stamp is read as fully stale, never as finished. |
| **Needs** | A served LLM reached over the network, the query embedder, the FAISS index, the corpus database, and, unless `EXTRACT_LOCATE=0`, the source PDF (`--pdf-root`) to place a quote's highlight rectangles. Unless `EXTRACT_ATTACH_IMAGES=0`, also the `images/` directory (`--image-root`) with the table and figure crops that ride along with every request. |

Extraction is the seventh of the pipeline's eight stages. [Chunking,
embedding, database](chunking.md) precedes it and is the last stage to
write anything under `results/`; from here on, a document's state lives
in the database and its stamp. [The knowledge graph](graph.md) follows,
reading only the tuples this stage accepted, never a refusal or the
spec itself.

## Method

### Loading and validating the spec

`spec.load` parses a profile's `extraction_spec.json` into a `Spec` of
`Parameter` and `Axis` objects, refusing anything wrong: too short a
parameter description, a numeric parameter missing a unit factor, two
vocabulary labels folding to one spelling under two different classes,
or an axis naming more than one of vocabulary, enum, type or dynamic.
`SpecError` names the offending field, failing at load time rather than
partway through a batch. A
parameter carries one of four value types, `spec.VALUE_TYPES`: `float`
and `int` take a unit, `category` a closed vocabulary, and `text` a
plain string compared verbatim rather than mapped to a class; `text` is
the majority type in the scenarios profile, 11 of its 14 parameters
(`profiles/scenarios/extraction_spec.json`). Unit spellings and vocabulary labels are
compared after `normalise_unit` or `fold_label`, not as raw strings: on
the 16-document pilot, 661 findings were refused for their unit and 302
of them already carried an accepted spelling under another form
(`spec.py:43`). An axis that still sets an evidence rule is refused at
load time (`spec.py:293-298`): a coordinate is
checked for its quote and its answer, wherever the passage stands.

### The retrieval plan

`pipeline.plan_document` builds one plan per document, not per parameter,
since which quantity a number belongs to is asked as a coordinate later.
Two rules used to feed it: every table and figure taken whole through the
`structure` callable, since over 65 documents 12,094 of 15,082 values
came from one of the two (`pipeline.py:186`); prose ranked and capped at
`prose_top` sections, the half a ranking retains. A newer
single cut (`top`, `EXTRACT_PLAN_TOP`) replaces both with one fused
ranking, keeping the structural floor only as a counter of what it would
have missed. There are no repeated rounds: retrieval is asked once per
document, not asked again with everything already found excluded. The
single call fuses every probe into one ranked
list rather than concatenating a ranking per probe: over 65 documents and
15,082 values, concatenation put a value's real source at median rank 77,
fusion at rank 26 (`runner.py:350`).

### Anchors

The plan searches not with the spec's query templates but a sentence
written as a document would state the answer, a HyDE anchor; two
mechanisms produce them. `document_anchor` (`runner.py:837`) writes the
plan's own probe per document and parameter, from the parameter's
label, description, the document's name and an early caption; recorded,
never compared, in the stamp as `question_text/<key>`.
Dropping query templates for it was measured directly: with templates
included alongside the anchor, a value's real source sat at median rank
84; without them, rank 26 (`pipeline.py:196`). `plan_document` falls back to
`queries.expand`'s templates only when no anchor exists. `make_anchors` (`runner.py:1320`) is the second,
corpus-wide mechanism: one set per question the field sweep asks, each
axis question and the parameter choice, written once per run and cached
per question. The value itself has no set: the plan searches with the
one short sentence `document_anchor` writes (`anchor_targets`,
`runner.py:812`). This set backs the field sweep once a
coordinate is not in the value's own passage, and is fingerprinted as
one `anchors` stamp key.

### The frame

Some coordinates belong to the document, not the row: a plan's scenario
containers and reference years stand in headings, captions and column
headers rather than varying cell by cell. `runner.find_frame` reads these
once, before any value, over up to `FRAME_ROUNDS` rounds of up to
`FRAME_SOURCES` passages, keeping only pairs with their own verbatim
quote (`frame_pairs`). A
deterministic cross-check, `years_in_sources`, scans the same passages
for year-shaped numbers the model did not name and offers them back once,
never adding a year on its own. Which coordinates form a frame is named
by the profile: kwp sets `FRAME = ("scenario", "year")`
(`profiles/kwp/extraction.py:73`); the scenarios profile sets none.
`pipeline.apply_frame` projects each pair onto its rows, state `read`,
before any field job is queued; a row that already answered better keeps
its own reading. A passage that prints several pairs, a table with a
column per year, is read under each of them, and each request takes its
own pair's column
(`test_a_passage_of_several_pairs_is_read_under_each_of_them`,
`tests/test_extraction_frame.py:650`). A passage that prints none of a
request's pair gives no row: its claims are refused as `passage is not of
this pair` (`rows_from_reply`, `pipeline.py:509`). The gain was measured directly: before the frame
existed, the year axis alone produced 1,849 refusals against 0 readings,
since every window after the first excluded the row's own source
(`runner.py:2931`).

### The row request

Which values exist at all is decided once, by the value request
(`make_harvester` with `ROWS_PROMPT_ID`, `find_rows` inside
`make_fieldwise_harvester`). `pipeline.rows_from_reply` turns its claims
into `Row` objects through `route_claims`: the quote decides which source
a value belongs to, a label only breaks a tie, and a claim naming no real
source and quoting nothing findable is an orphan rather than filed under
the first source. Routing matches a quote to its source with the same
whitespace-collapsed test verification uses, `quote_in`, not a literal
substring test: a stricter test would refuse claims verification would
have accepted, since a table row retyped without its padding is the
normal case, not the exception, worth 276 of one pilot's refusals
(`pipeline.py:379`). A
wording not in its own quote is caught here too, before it becomes a
row (`pipeline.py:544`). A `Row` is created only here, never later. The request can turn to
a code sandbox, bounded
to `CODE_ROUNDS` rounds, and a reply cut off at the token ceiling is
rescued rather than retried, since retrying recovered nothing over one
pilot (`runner.py:2132`).

### The field sweep: three window stages and a budget

Every coordinate a row still needs is asked for on its own by
`sweep_field` (`runner.make_sweeper`). Asking per field is why a
whole-tuple request cannot quietly drop an unsure coordinate: on a
204-document run, one combined request left the year missing on 63.5%
of values (`fields.py:15`). The sweep walks three stages, each with its own
allowance rather than a shared pool. **Own** reads
the value's own sources and the section its table stands in, for up to
`FIELD_ATTEMPTS` (3) attempts, each retry naming the reason. **Retrieval**
follows, searching further out with the per-question anchors in short
overlapping windows (`FIELD_WINDOW` 2, `FIELD_OVERLAP` 1) for up to
`FIELD_ROUNDS` (4) rounds. **Rest** is the floor: once retrieval has
nothing new, `rest_of_document` reads the document's own remaining
sections in order, rotated to start near the open rows, until the
coordinate closes or the document runs out (`runner.py:2864`). A
coordinate the whole sweep cannot close is `exhausted`, never
`unstated`: the first is a finding about the run, the second about the
document. The budget sums to `FIELD_MAX_WINDOWS`
(24) plus `REST_MAX_WINDOWS` (12) per coordinate, with several
coordinates batched into one request rather than one request each
(`runner.py:2586`).

### Merging a coordinate

`pipeline.merge_field` folds each field's answers onto the open rows,
holding every answer to the two clauses the value's own quote is held to:
its cited passage sits verbatim in a shown source, and it contains the
answer, with a floor of `MIN_QUOTE_CHARS` so that a quote names a place.
Those are the whole check (`pipeline.py:732-754`;
`test_a_coordinate_is_dropped_for_the_agreed_reasons_and_no_other`,
`tests/test_extraction_reasons.py:111`). Which table the passage belongs
to, how far from the row it stands and which column of a table it heads
are the model's reading, not a rule. Failures are recorded separately,
`unquoted` against `unbacked`, so a retry can name what to fix. A
coordinate already read once is never overwritten by a later window
(`pipeline.py:688`). A wording naming no token of the option
it claims is counted `raw_foreign` rather than trusted silently.

### Folding and verification

`pipeline.fold_claims` hands every claim to `verify.verify_tuple`, the
last check against the spec's closed lists and the literal source text. A
number is compared digit for digit after `canonical_number` normalises
locale grouping and decimal marks; a category or text value is compared
case- and whitespace-folded against its own wording. Where a quote is
not verbatim in its source but the value occurs there
exactly once, the quote is rebuilt around that occurrence rather than the
claim refused: on the 16-document pilot, 303 of 377 such refusals were
repaired this way, against 8 where the value truly was absent
(`verify.py:291`). A verified tuple's tier comes from its source
alone, not whether the quote could be placed on the page:
`text_located` for prose, `visual_source` for a table transcription or
figure description, an uncheckable model reading of a picture. A prose
quote that could not be placed on the PDF page still keeps the
`text_located` tier; it only gains a `not_located` flag (`verify.py:443`).
Non-fatal findings are carried as flags: `quote_repaired`, `computed`
(a sandbox result checked against its own printed output),
`unit_not_chosen`, `not_located`, `unmapped:<axis>:<wording>`, and, for
an amount over a span, whether the quote states the year it runs over.

### Trust levels

`trust.trust` grades every accepted tuple deterministically, from what
the harvest already recorded, no further model call and no tuned
threshold. Level A: its own text states it, every coordinate read.
Level B: the same, from an image transcription or a model-transcribed
page. Level C: one of the following holds: a coordinate the sweep could
not back or gave up on, a repaired quote, a computed number, or a
contested identity decided at graph build time. Where a coordinate's
passage stands is no reason. A second
reading from `--review` can mark a tuple `corroborated`, described
under The passes that revisit a harvest, but never raises its level.
`trust.document_summary`
folds one document's tuples into a closing line, its level distribution
and reason counts. See [how much of a value the run can stand
behind](../contract/trust.md) for the full list.

### The harvest file, the stamp and the trace

`pipeline.write_report` writes one document's tuples, refusals, parameter
states and closing summary to a temp file and only replaces the real
`.jsonl` once complete, so a killed process cannot leave a truncated
harvest; every rewrite in this stage follows the same rule. The stamp is
withheld until `runner.finish_document` decides a harvest genuinely
happened, not merely that a file was written; see Failure modes for
when it withholds one. What the stamp records,
`_stamp_current`, is deliberately not one hash over the whole spec file:
`spec.fingerprints` computes one sha per question, so `runner.stale`
names exactly which one moved. The earlier whole-file design cost this
project directly: one new vocabulary spelling made all 1,082 documents
stale at once, about 93 GPU hours to re-read a corpus over one word
(`remap.py:6`). The coarse `spec` key is compared only while no finer
key exists; once fine keys exist, a changed value and a dropped
question are both checked. Beside every harvest sits
`<document>.trace.jsonl`, on by default and disabled with
`EXTRACT_TRACE=0`.

Every tuple, refusal, parameter state and summary line is checked
against the published schema before it is written:
`_harvest_validators` builds one `jsonschema` validator per branch from
`schema.build(spec)["harvest"]`, run by `check_against_schema` inside
`finish_document` on every call carrying a spec (`runner.py:3589`). A
row the schema refuses is counted
and logged as an `invalid` trace event, never withheld, since blocking on
a schema mismatch would turn a documentation defect into a data loss.
`scripts/preflight_profiles.py` calls `schema.build` directly, ahead of
any run, to confirm a profile's published schema file is current
(`scripts/preflight_profiles.py:220`).

### The passes that revisit a harvest

Four passes act on a harvest already written, without starting a
document over from its first passage, and they differ in what they cost
and what they may touch.

| Pass | Needs | May touch | Leaves the stamp |
|---|---|---|---|
| `--recheck` | Nothing: no model, no GPU, no index | Every tuple's coordinates | Clears every stamp in the directory (unless `--keep-stamps`) |
| `--remap` | Nothing: no model, no GPU, no index | A category coordinate's mapped class | Writes forward only the answer spaces it fully settled |
| `--top-up` | The model, the FAISS index, the embedder, the database | One named coordinate of every row that has it | Writes forward only the exact stamp keys it could settle |
| `--review` | The model, and the crops for image-attached prompts | Only a row's `flags` | Adds `review/prompt` and `review/model`, compared by nothing |

`--recheck` (`recheck.py`) reapplies the answer-in-quote rule to the
wording and quote already on disk: a coordinate whose quote does not
contain its claimed answer is stripped back to `unanswered`; on a
corpus written before the rule existed, 27.6% of years cited a passage
with no year at all (`recheck.py:8`). A stripped
coordinate can only be repaired by a real harvest, so `recheck.run`
deletes every stamp by default; `--keep-stamps` keeps one that no longer
matches the file. `--remap` (`remap.py`) re-resolves a coordinate's
recorded wording against today's vocabulary instead, a pure function of
the harvest and spec files: a newly listed wording is rewritten and its
stale flags dropped, one in neither list or with none recorded is left
as it stands, and a refusal a grown list might now place keeps its axis
stale, since only a real harvest turns a refusal into a tuple.
`stamp_forward` writes forward only the answer spaces a file fully
settled.

`--top-up` (`topup.py`) is the one pass that is not free: it costs a
model call, but only for the coordinate a stamp says moved, over the
harvest's own sweep. `actionable` blocks the whole document the
moment a changed key names anything other than one sweepable
coordinate: a key naming no coordinate the spec still asks blocks
outright, and so does one naming a frame axis, since the frame decides
how many passes a document gets, or, unless allowed, a dynamic axis
with no per-document list, since sweeping it empty would demote a class
to a wording (`topup.py:69-103`). `--top-up-key` names only one axis
coordinate, `axis/<uri>/<name>` (`slot_of`, `topup.py:109-120`); nothing
sweeps every asked coordinate of every row at once any more. `reopen` strips one coordinate's keys before
the sweep runs; `restore` puts the old block back unless the fresh
sweep genuinely improves on it. A row whose passage no longer carries
its stored quote is left untouched, and top-up traces land under their
own `trace-topup/` directory.

`--review` (`review.py`) differs from the other three: it writes only
`review/prompt` and `review/model`, recorded and never compared, so it
never makes a document look stale. It rereads a harvest's lowest-trust
values once more, over a window narrowed to the value's own two legal
passages, a self-consistency check rather than an independent opinion.
Only a disagreement counts as a trust reason; an agreement is marked
`corroborated` without raising the level. The second reading goes to
`review.csv`, never onto the tuple itself.

Three further scripts, `curation_list.py`, `harvest_compare.py` and
`trace_report.py`, read a harvest and print or write a report, described
under Modules; none writes back into one.

## Data model

A harvest line is one of four kinds, named by its `kind` field.

| Kind | Carries | Written by |
|---|---|---|
| `tuple` | A resolved value, every filled coordinate (`_state`, `_raw`, `_quote`, `_source`, `_window` each), an evidence tier, non-fatal flags, and provenance | `verify.verify_tuple`, folded by `pipeline.fold_claims` |
| `refusal` | The raw claim plus a reason from a closed family | `verify.verify_tuple`, or `pipeline.route_claims` if unroutable |
| `parameter_state` | One line per spec parameter with no tuple at all: its state and its tuple/refusal counts | `trust.parameter_states` |
| `summary` | The document's trust-level distribution and reason counts, the last line | `trust.document_summary` |

A coordinate's own `<name>_state` is one of seven values, each a
different kind of finding.

| State | What it says |
|---|---|
| `read` | Answered; the cited passage carries the answer |
| `derived` | Not asked: the spec decided it from the row itself |
| `unstated` | Answered: the shown passages do not state it |
| `unanswered` | The field reply never mentioned it |
| `exhausted` | Still open when the window budget ran out, document unread to the end |
| `unbacked` | Answered, but no shown passage carried it, or it was another row's |
| `out_of_slice` | Never asked: a gate coordinate put the row outside what this run serializes |

The resume stamp, `<document>.stamp.json`, is a flat dict: `spec` (the
whole file's sha; see Method for how it is compared), `slot/parameter`
(the value question itself), `parameter/<uri>` and, where it has one,
`value/<uri>` per parameter, `axis/<uri>/<name>` per axis; these are the
only keys `stale` compares. `model`, `anchors`, one entry per
`PROMPT_IDS` prompt, `question_text/<key>` and `review/*` are written
into the stamp too, so a reader can place a harvest, and are never
compared. A trace event is one JSON
line, `{"t": kind, "doc": document_id, ...}`, of one of eleven kinds
(`schema.py`'s `trace_schema`): `plan`, `anchor`, `frame`, `rows`,
`field`, `sweep`, `drop` and `error` from the harvest loop, `coord` and
`refusal` per folded tuple or refusal, and `invalid` from the schema
self-check described under Method. `review.csv` carries one line per
field a review asked about, named by `review.COLUMNS`.

A harvest directory (`out`) holds, per document,
`<name>.jsonl`, `<name>.stamp.json` and `trace/<name>.trace.jsonl`; per
run, `anchors.json` and `query_cache.db`; and, only after `--top-up`,
`trace-topup/<name>.trace.jsonl` beside it. `--review` also writes
`review.csv` at the top.

## Configuration

| Name | Kind | Default | Effect | Where read |
|---|---|---|---|---|
| `EXTRACT_FIELDWISE` / `EXTRACT_FIELD_WINDOW` / `_OVERLAP` | env var | `1` / `2` / `1` | `FIELDWISE`: one request per coordinate, not one per whole tuple. `WINDOW`/`OVERLAP`: sources per retrieval-stage window, and how many repeat in the next one | `runner.main`, `runner.make_sweeper` |
| `EXTRACT_FIELD_ROUNDS` / `EXTRACT_FIELD_ATTEMPTS` | env var | `4` / `3` | Retrieval rounds before falling to the rest stage; retries of the own-stage window when unbackable | `runner.make_sweeper` |
| `EXTRACT_FIELD_MAX_WINDOWS` / `EXTRACT_REST_MAX_WINDOWS` | env var | `24` / `12` | Own plus retrieval windows, and the rest stage's separate allowance, before a coordinate is exhausted | `runner.make_sweeper` |
| `EXTRACT_PLAN_TOP` / `EXTRACT_PROSE_TOP` | env var | `50` / `200` | `PLAN_TOP`: the fused top-N cut replacing the older structural-floor plan. `PROSE_TOP`: ceiling on prose sections drawn from, always overriding `plan_document`'s own default of `50` | `runner.main` |
| `EXTRACT_FRAME_ROUNDS` / `_SOURCES` / `EXTRACT_FRAME_YEAR_MIN` / `_MAX` | env var | `3` / `12` / `1990` / `2100` | Rounds and passages per round the frame request may spend; bounds of a calendar year for `years_in_sources`, its deterministic cross-check | `runner.find_frame`, `runner.years_in_sources` |
| `EXTRACT_CODE_ROUNDS` / `EXTRACT_FIELD_RE_ENTRY` | env var | `2` / `3` | Sandbox rounds the row request may spend on a self-checked value; already-shown passages carried into a coordinate's next field window | `runner.make_harvester`, `runner.make_sweeper` |
| `EXTRACT_LLM_PARALLEL` / `EXTRACT_PLAN_PARALLEL` / `EXTRACT_FIELD_PARALLEL` | env var | `128` / `8` / `192` | Concurrency caps: LLM requests for the whole run, retrieval-planning threads (FAISS/SQL, separate from the LLM), and field-sweep threads beneath row-request batches | `runner.harvest_batches`, `runner.main`, `runner.make_fieldwise_harvester` |
| `EXTRACT_ATTACH_IMAGES` / `EXTRACT_LOCATE` | env var | `1` / `1` | Off, respectively: no crop attaches to a row, field, frame or review request (no `images/` dir needed), or `make_locate` returns `None`, no quote placed on the page | `runner.py` askers, `runner.make_locate` |
| `EXTRACT_TRACE` | env var | `1` | Off, every trace call returns immediately and no trace file is written | `trace.py` (`ENABLED`) |
| `--document ID` / `--force` / `--force-stale` | CLI flag (ID repeatable) | none / off / off | `--document` restricts a run to named ids; `--force` redoes every document, `--force-stale` only those `stale` | `runner.main`, `runner.stale` |
| `--image-root` / `--pdf-root` | CLI flag | profile's processed dir / none | Crop directory for `EXTRACT_ATTACH_IMAGES`, and source PDF directory for `EXTRACT_LOCATE`; `--pdf-root` also backs `--image-root` when absent | `runner.main`, `resolve_image_root`, `make_locate` |
| `--recheck` / `--remap` / `--keep-stamps` | CLI flag | off | Runs `recheck.run` / `remap.run` over `--out`, no model needed; `--keep-stamps` (recheck only) leaves stamps instead of clearing them | `runner.main`, `recheck.run` |
| `--top-up` / `--top-up-key KEY` | CLI flag (KEY repeatable) | off / none named | Runs `topup.run`, needing the model and index; `--top-up-key` restricts the changed keys swept to the named axis coordinates | `runner.main`, `topup.actionable` |
| `--review` / `--review-limit N` | CLI flag | off / `0` | Runs `review.run`, one request per level-C value, up to N total | `review.run` |
| `--serialize TTL` / `--print-context-budget` | CLI flag | none / off | `--serialize`: no harvest, hands `--out` to `serialize.run`, which calls the profile's `kg.make_serializer`. `--print-context-budget`: prints the tokens one harvest request needs, then exits | `serialize.run`, `runner.main` |
| `SLICE` / `FRAME` | profile hook | none / none (every coordinate per row) | `SLICE`: gate coordinate(s) asked first, a row that fails them never asked its others. `FRAME`: document-level coordinates found once and projected onto every row | `runner.main`, `topup.actionable` |

## Failure modes

A claim is refused, not silently dropped, whenever `verify.verify_tuple`
finds a fixed problem: the value is not a number where required, a
required axis is missing or outside its own list, the quote is missing,
too short, or not found in its source even after repair, or the value
does not occur in its own quote. `pipeline.route_claims` refuses a
claim before verification when it names no real source and quotes
nothing found in any of them. A category or axis value the model chose
that is outside the spec's vocabulary is not refused outright, unless
the axis is required: it is kept with its wording and flagged
`unmapped:<axis>:<wording>`, since refusing every unforeseen spelling
would shrink the harvest on exactly the wordings a vocabulary review
most needs.

Inside the field sweep, an unbacked or unquoted answer does not end a
row's chance of being read: it stays open (`unbacked`, never final)
until a later window, stage or round closes it, or budget runs out
with the document unread, turning it `exhausted`. A reply that does not
parse, is empty, or arrives as a non-dict is coerced to an empty one at
every fold point, so a bad batch yields zero claims and the loop moves
on.

At the document level, `finish_document` withholds the stamp entirely,
forcing a full redo on the next run, when more than half a document's
planned sources came back from a server it could not reach
(`UNREACHABLE_LIMIT`, `0.5`, `runner.py:3530`, `:3573`) or when not one
batch answered at all (`runner.py:3578`); the JSONL file is still
written either way, so only a resume, not a byte count, tells the two
cases apart from a genuinely finished document.

Among the four maintenance passes, `--recheck` and `--remap` never call a
model, so their only failure mode is a coordinate they cannot settle,
left open rather than guessed at. `--top-up` blocks an entire document
the moment a changed stamp key names anything it cannot sweep, and a
re-swept claim the verifier refuses keeps its prior reading. `--review`
never overwrites a value; a row
already flagged `review:` is never asked twice, and a reply the model
never sends leaves no trace, so the row is offered again later.

## Measured behaviour

- Planning per parameter instead of per document once turned one
  document's owner set into three documents' worth of requests: 804
  planned sources against 234 real owners (`fields.py:164`).
- The kwp spec's numeric units, nine for energy and forty-two for
  emissions, share not one spelling; on Kassel not one of 559 accepted
  tuples contradicted its own unit, yet asking the model to choose the
  parameter anyway cost 322 of 1,043 field windows, 30.9%, and 18.0 of
  187.5 field minutes per plan, before the unit was used to derive it
  instead (`fields.py:218`).
- Letting the passage a coordinate was last read in drop out of the
  window after one use, rather than remaining in the window, cost one
  batch 520 dropped readings against 31 kept (`runner.py:2742`).
- On the 20-plan draft where the slice gate was measured, of 6,763
  harvested tuples the serializer dropped 1,554 for a quantity the graph
  does not hold and, while the scenario axis still gated a row, 2,510
  more for not being the target scenario (`profiles/kwp/extraction.py:11`).

## Verification

`tests/test_extraction_spec.py` pins spec validation and the fingerprint
functions the stamp is built from. `tests/test_extraction_pipeline.py`
pins the retrieval plan and routing, among them
`test_the_plan_asks_retrieval_once_and_not_until_the_document_is_gone`,
`test_every_table_is_planned_whether_or_not_a_probe_ranked_it` and
`test_only_verified_values_become_the_next_batch_s_prior`.
`tests/test_extraction_fieldwise.py` pins the field sweep and its two
checks: `test_an_answer_whose_evidence_is_not_in_the_source_is_not_written`,
`test_a_quote_that_does_not_contain_the_answer_is_not_evidence`,
`test_the_field_prompt_states_the_two_checks_and_no_other`,
`test_a_read_coordinate_is_not_overwritten_by_a_later_window`,
`test_a_row_outside_the_slice_is_not_asked_for_its_other_axes`,
`test_a_sweep_that_ran_out_of_budget_still_reads_the_rest_of_the_plan`,
`test_the_last_stage_keeps_its_allowance_when_it_is_larger_than_the_first`,
`test_the_sweep_starts_again_where_it_last_read_instead_of_striking_it_off`
and `test_the_sweeper_is_the_one_the_harvest_uses`.
`tests/test_extraction_frame.py` pins the frame's two quotes per pair and
its projection onto rows: `test_every_half_of_a_pair_quotes_for_itself`,
`test_a_frame_reading_may_quote_a_heading_anywhere_in_the_plan`,
`test_a_passage_of_several_pairs_is_read_under_each_of_them`,
`test_every_row_gets_the_year_of_its_own_pair`,
`test_a_coordinate_the_row_itself_answered_is_not_overwritten` and
`test_a_search_that_never_completes_says_exhausted_rather_than_complete`.
`tests/test_extraction_verify.py` pins `canonical_number`, quote repair,
and the evidence tiers. `tests/test_extraction_trust.py` pins the level
cutoffs. `tests/test_extraction_reasons.py` pins that a coordinate is
dropped for the agreed reasons and no other, that every reason a claim is
refused for is a published one, and that no closure in the package reads
a name bound after it. `tests/test_extraction_schema.py` validates
that a harvest, a stamp and a trace event all conform to the published
contract. `tests/test_extraction_runner.py`, 79 tests, pins `runner.py`
itself: among them `test_a_document_the_server_never_answered_for_is_not_stamped`,
`test_a_document_no_reply_ever_came_back_for_is_not_stamped`,
`test_the_image_root_follows_the_pdf_root` and
`test_the_context_budget_holds_a_full_window_and_a_crop`.
`tests/test_extraction_ranking.py` pins the fused ranking behind the
retrieval plan: `test_the_structural_floor_is_every_table_and_every_figure`,
`test_a_table_whose_content_is_gone_is_skipped_and_not_planned_empty`
and `test_the_plan_is_built_from_the_anchors_and_not_from_the_templates`.
`tests/test_extraction_dry_run.py` pins the spec-to-schema round trip and
the context budget against the batch size:
`test_every_example_survives_its_own_round_trip` and
`test_the_answer_budget_and_the_batch_size_agree`.
`tests/test_extraction_trace.py` pins the trace file itself:
`test_switched_off_it_writes_nothing_at_all` and
`test_a_document_harvested_twice_does_not_leave_two_traces_in_one_file`.

For the four maintenance passes, `tests/test_extraction_recheck.py` pins
`test_a_coordinate_its_quote_carries_survives`,
`test_a_year_whose_caption_names_no_year_does_not_stay`,
`test_a_coordinate_with_no_quote_at_all_does_not_stay`, and
`test_the_stamps_go_with_the_rewrite` against
`test_keeping_the_stamps_is_something_you_have_to_ask_for`.
`tests/test_extraction_remap.py` pins
`test_a_wording_the_new_list_knows_reaches_its_class`,
`test_a_wording_in_no_list_keeps_the_reading_it_has`,
`test_a_fully_remapped_answer_space_is_written_forward` against
`test_a_space_the_pass_could_not_settle_stays_stale`, and
`test_a_refusal_the_grown_list_might_place_keeps_its_space_stale`.
`tests/test_extraction_topup.py` pins
`test_only_a_coordinate_key_is_topped_up_and_the_rest_blocks`,
`test_a_frame_coordinate_is_never_a_top_up`,
`test_the_old_reading_comes_back_unless_the_new_state_is_better`,
`test_a_row_whose_source_no_longer_carries_its_quote_is_left_alone`, and
`test_the_top_up_writes_its_trace_beside_the_harvests_and_not_over_it`.
`tests/test_extraction_review.py` pins
`test_only_the_values_nobody_can_stand_behind_are_reviewed`,
`test_a_row_is_reviewed_once`,
`test_a_corroborated_row_is_still_a_c`,
`test_a_disagreement_is_a_reason_a_curator_can_count`, and
`test_the_limit_bounds_the_whole_run_and_not_each_document`.

## Modules

`spec.py` loads and validates a profile's contract into `Spec`,
`Parameter` and `Axis`, and computes the per-question fingerprints the
stamp is built from; every other module imports it. `fields.py`
computes a tuple's deterministic skeleton, its slots, from the spec
alone, and defines the seven coordinate states. `queries.py` expands a
profile's query templates into retrieval probes, a fallback used only
when no anchor could be written.

`pipeline.py` holds the harvest loop itself: the retrieval plan, batching,
routing a claim to its real source, `merge_field`, and the `Sweep` object
sharing verified answers across a document's batches regardless of
order. `verify.py` is the last
check a claimed tuple passes, value against the spec's closed lists and
units, quote against the literal source text, returning a `Verified`
tuple or a `Refusal`. `trust.py` grades an accepted tuple's evidence, A, B
or C, from what the harvest already recorded, and folds a whole
document's tuples into the closing summary line; every maintenance pass
calls it to recompute a rewritten file's summary.

`trace.py` writes the per-event trace files this stage and `--top-up`
produce, never aggregating anything itself; `schema.py` generates the
published JSON Schema for a harvest line, a stamp and a trace event from
the spec and from `trust.py`'s own constants, so the two cannot drift
apart. Called by the tests, its own CLI entry point, `runner.py`'s
schema self-check, and `scripts/preflight_profiles.py`. `serialize.py`
walks a harvest
directory, keeps only the rows a run accepted (`collect`), and hands
each document's rows to the profile's own `kg.make_serializer`; `run`
refuses to write when no document produced anything, so an empty or
unreadable directory cannot overwrite a valid graph from an earlier
run. Called only by `runner.py`'s `--serialize` branch.

`runner.py` is the harvest CLI, 4,383 lines against the next-largest
module's 1,184 (`pipeline.py`): the retrieval, anchor and frame
machinery described above, the field sweep, the resume-stamp
comparison, and the argparse branches dispatching `--recheck`,
`--remap`, `--top-up`, `--review` and `--serialize` to their own
modules.

`scripts/curation_list.py`, `scripts/harvest_compare.py` and
`scripts/trace_report.py` are read-only reporting tools over a harvest
directory: a sorted list of untrustworthy values, a profile's own
acceptance numbers, and a trace's event distributions, called only by
a person from the shell.

See [the harvest contract for kwp](../contract/kwp.md) and [the harvest
contract for scenarios](../contract/scenarios.md) for what a profile's
parameters and vocabularies publish, [what a coordinate's state
means](../contract/states.md) for the seven states in full, [how much of
a value the run can stand behind](../contract/trust.md) for the trust
levels and reasons, and [the knowledge graph](graph.md) for how only
an accepted tuple becomes a triple.
