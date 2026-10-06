# Glossary

Terms as the pipeline's own code defines them, alphabetical, each naming the
module it comes from and, where one exists, the page that documents it.

anchor
: A short sentence, written as a document would state the answer, used to
  probe retrieval in place of a bare query template. `runner.document_anchor`
  writes one per document from a parameter's label and description plus what
  the document itself has already said (`docpipe/extraction/runner.py`); see
  [extraction](stages/extraction.md).

axis
: One dimension a parameter's value varies along: a closed vocabulary, an
  integer, an enum, or a per-document dynamic list, each with its own
  question. Defined as the `Axis` dataclass in
  `docpipe/extraction/spec.py`; see [extraction](stages/extraction.md).

backend
: The concrete embedder `docpipe.embedding.get_embedder` returns: `local` (a
  GPU-resident model in this process), `api` (an OpenAI-compatible
  endpoint), or an import-path spec naming a deployment-supplied class.
  Defined in `docpipe/embedding/__init__.py`; see
  [embedding](stages/embedding.md).

batch
: Several sources read in one model request, for one parameter or, on a
  document-level plan, for the document as a whole, built by
  `docpipe.extraction.pipeline.group_items`. A batch never mixes
  parameters, because the closed lists a reply may answer from differ per
  parameter; see [extraction](stages/extraction.md).

block
: One content unit on a PDF page (text, table or image) with a bounding box
  in PDF points, defined as the `Block` dataclass in
  `docpipe/preprocessing/models.py`. A page's blocks combine Stage 1's
  PyMuPDF text runs with Stage 2's PP-DocLayoutV3 detections; see
  [preprocessing](stages/preprocessing.md).

cassette
: The answers of one run, each filed under what was asked, so the run can be
  made again without a model: `DOCPIPE_CASSETTE_RECORD` writes one and
  `DOCPIPE_CASSETTE_REPLAY` takes its answers from one. Defined in
  `docpipe/providers/cassette.py` and the basis of `docpipe benchmark`; see
  [the provider layer](stages/providers.md) and [measuring a
  harvest](stages/evaluation.md).

chunk
: One LLM question-answering attempt in the inference app: a token-budgeted
  group of retrieval hits, defined as the `Chunk` dataclass in
  `docpipe/inference/chunker.py` and assembled by `pack_chunks`. Distinct
  from the chunking pipeline stage, whose own retrieval unit is a section;
  see [app](stages/app.md).

citation
: One retrieved source shown under an inference-app answer: a dict of its
  content, a grounded quote, a `visual` flag, the number `n` the statement
  that stands on it is shown with, and, for a value the sandbox computed,
  `computed` and the number of the `run` that printed it, appended to the
  `citations` list `docpipe/inference/answer.py` builds and, through
  `pdf_link.py`, shown in the app with its page drawn from the source PDF
  (and a link into an external viewer where one is configured); see
  [app](stages/app.md).

claim
: One value the harvesting model asserts for one source, before it is
  checked. `docpipe.extraction.pipeline.route_claims` routes each of a
  batch's claims to the source whose text actually carries its quote;
  `fold_claims` then passes each source's own claims to
  `verify.verify_tuple`, which turns each into a tuple or a refusal; see
  [extraction](stages/extraction.md).

contract
: The JSON Schema `docpipe/extraction/schema.py` generates from a profile's
  spec: one for a harvest line, one for the resume stamp, one for a trace
  record, checked into `profiles/<name>/extraction_schema.json`. Published
  per profile at [kwp](contract/kwp.md) and
  [scenarios](contract/scenarios.md).

convoy
: Several municipalities that share one heat-plan PDF, identified in the
  KWW register by rows resolving to one plan filename.
  `profiles/kwp/source.py`'s `group_keys_by_filename` registers a convoy
  as a single `Documents` row keyed by the group's smallest `ags`, and
  `_warn_about_shared_files` reads the `Konvoi ID` column only to tell a
  genuine convoy from a register error; see [kwp](profiles/kwp.md).

coordinate
: One axis value of a tuple, such as its year or its carrier, each carrying
  its own state, wording, quote and source. Filled by the field sweep in
  `docpipe/extraction/pipeline.py`'s `merge_field`; see
  [extraction](stages/extraction.md).

corpus
: The whole collection of a profile's processed documents, held as a
  SQLite database (`<profile>.db`) and a FAISS index (`faiss_index.bin`),
  whose paths are `Profile.db_path` and `Profile.index_path` in
  `docpipe/profile.py`. Built by chunking and read by extraction and the
  inference app; see [chunking](stages/chunking.md).

default profile
: The profile the package brings itself (`docpipe/builtin/default/`): any
  folder of English documents, with no subject. A project's profile extends it
  with `extends="default"` and writes only what it knows better. See
  [profiles](profiles.md).

derived coordinate
: A coordinate the spec decides on its own, such as the parameter a unit
  implies, without a model being asked. Written by
  `docpipe.extraction.fields.apply_derived` with state `derived`, keeping
  the wording it was derived from; see [extraction](stages/extraction.md)
  and [states](contract/states.md).

document
: One row of the `Documents` table: a filename, a profile-supplied
  `external_id`, an optional `group_key`, and the version-linking columns
  `is_current` and `supersedes`. Written by `docpipe/store/documents.py`,
  which a profile's own metadata table extends; see
  [store](stages/store.md).

dynamic list
: A closed vocabulary that is real but exists only per document, such as
  one publication's own AR6 scenario runs, filled in by a profile hook
  before the harvest. Declared as `Axis.dynamic` or
  `Parameter.vocabulary_dynamic` in `docpipe/extraction/spec.py`; where no
  list is filled for a document, the coordinate degrades to a plain
  wording. See [extraction](stages/extraction.md).

embedding_type
: One of six fixed strings naming which slice of a section, table or
  figure a stored vector represents: `section_text`, `section_title`,
  `table_text`, `table_vl`, `figure_text`, `figure_vl`. Defined in
  `docpipe/chunking/config.py` and written to the `Embeddings` table by
  `docpipe/chunking/database.py`; see [chunking](stages/chunking.md).

exhausted
: The state of a coordinate still open when the field sweep's window
  budget ran out with the document unread to the end, a finding about the
  run rather than about the document or the model. Defined in
  `docpipe/extraction/fields.py`; see [states](contract/states.md).

facet
: One filter the inference app offers over a profile's metadata: a field
  name, a label and a widget kind. Defined as the `Facet` dataclass in
  `docpipe/profile.py`; see [app](stages/app.md).

field
: One request of the field sweep asking a single coordinate over a window
  of sources, driven by the `extraction/field` prompt
  (`docpipe/prompts.py`). `docpipe.extraction.pipeline.merge_field` folds
  its answers back onto the rows they belong to; see
  [extraction](stages/extraction.md).

flag
: A non-fatal finding `verify.verify_tuple` appends to a tuple, such as
  `quote_repaired`, `period:unstated`, or an `unmapped:<axis>:<wording>`
  mapping gap. `docpipe/extraction/trust.py`'s `FLAG_REASONS` turns a
  handful of these into trust reasons; see [trust](contract/trust.md).

fold (folding)
: Turning a model reply's claims into a document's tuples and refusals by
  routing each claim to its real source and running it through the
  verifier. Performed by `docpipe.extraction.pipeline.fold_claims`
  and `fold_batch`; see [extraction](stages/extraction.md).

follow-up
: A batch's own request for more context: a `status: partial` reply naming
  `need_more`, honoured by `docpipe.extraction.pipeline.follow_up` up to a
  per-sweep budget of fresh passages. Distinct from top-up, which repairs
  an already-written harvest; see [extraction](stages/extraction.md).

frame
: The document-level coordinates, such as scenario and year for the kwp
  profile, found once per document and projected onto every row that has
  no better reading of its own. Named per profile
  (`profiles/kwp/extraction.py`'s `FRAME`) and applied by
  `docpipe.extraction.pipeline.apply_frame`; see
  [extraction](stages/extraction.md) and [kwp](profiles/kwp.md).

gold
: What people decided about harvested values: a field of a row is `correct`
  or `wrong`, the document states a value the harvest lacks, a document was
  read whole for a parameter. One JSON line each in `gold.jsonl`, appended and
  never rewritten, kept beside the harvest and never in it; the only thing
  precision and recall are counted against. A verdict also notes what its
  row said beside the value, so two rows that share a quote and a value keep
  their own decisions. Defined in
  `docpipe/extraction/gold.py`; see [measuring a
  harvest](stages/evaluation.md).

group_key
: The profile-assigned string that marks two or more `Documents` rows as
  versions of one work. `docpipe.store.documents.link_document_versions`
  marks the newest `published` date in each `group_key` group current and
  links the rest through `supersedes`; see [store](stages/store.md).

harvest
: The JSONL a run of `docpipe extract` (`python -m docpipe.extraction`) writes for one
  document: one line per accepted tuple, one per refusal, one
  `parameter_state` line per spec parameter, and a closing summary.
  Written by `docpipe.extraction.pipeline.write_report`; see
  [extraction](stages/extraction.md).

hole
: A unit that ended without a result, together with the cause it has none:
  a window of refinement, the cut of an oversized section, a table or figure
  of the visuals stage, a page of page transcription. The cause is one of
  `docpipe.reading.HOLE_CAUSES` (`cut_off`, `reasoning_only`, `empty`,
  `no_object`, `syntax`, `outside_text`, `not_an_object`, `missing_key`,
  `wrong_shape`, `refused`, `not_served`, `error`). A hole is written down with
  its cause in the stage's own output (`failed_windows`, `mechanical_cuts`,
  `vlm_why`, `failed_pages`); the window, item or page that is a hole is asked
  again by the next run (a section cut mechanically is not: the cut stands), and
  a hole changes no exit code. Distinct from `exhausted`, `unstated` and `unanswered`, which are
  states of a harvest's coordinate. Defined as `Hole` in `docpipe/reading.py`;
  see [the parts every stage uses](stages/core.md).

index
: The FAISS vector index a corpus is searched through, an
  `IDMap(IndexFlatIP)` built and updated by `docpipe/chunking/embedding.py`
  and stored at `Profile.index_path` (`faiss_index.bin`,
  `docpipe/profile.py`). Read by extraction's retrieval and by the
  inference app; see [chunking](stages/chunking.md).

knowledge graph
: The Turtle graph a profile's serializer builds from an accepted,
  trust-graded harvest: MHPKG on the Open Energy Platform for kwp, OEKG
  for scenarios. Built by `profiles/<name>/kg.py`'s `make_serializer`,
  called through `docpipe/extraction/serialize.py`'s `run`; see
  [graph](stages/graph.md).

layout
: The per-page object detection PP-DocLayoutV3 performs in preprocessing
  Stage 2, classifying each region (table, paragraph title, footer, and so
  on) into the `layout_label` a block carries. Run by
  `docpipe/preprocessing/stage2_layout.py`; see
  [preprocessing](stages/preprocessing.md).

OBIE
: Ontology-based information extraction, the name
  `docpipe/extraction/__init__.py` gives the extraction stage: turning
  passages a document's index already found into typed value tuples for a
  knowledge graph, using a profile's ontology as the contract. See
  [extraction](stages/extraction.md).

out: sentinel
: A vocabulary entry whose identifier begins with the literal prefix
  `out:`, naming a deliberate non-class answer, such as a share or a
  potential, that no ontology term is waiting for. Offered as an option
  like any other but refused as a class or an IRI by a profile's
  serializer, for example `profiles/kwp/kg.py`'s `NOT_IN_GRAPH`; see
  [graph](stages/graph.md).

owner
: The `(owner_kind, owner_id)` pair naming which section, table or figure
  a piece of evidence came from: `owner_kind` is `section`, `table` or
  `figure`, `owner_id` is that table's row id. Used by
  `docpipe/extraction/pipeline.py`'s `Source` and by the `Embeddings`
  table of `docpipe/chunking/database.py` alike; see
  [extraction](stages/extraction.md) and [chunking](stages/chunking.md).

parameter
: One quantity or category a spec defines an extraction question for: its
  uri, label, description, value type, unit or vocabulary, and axes.
  Defined as the `Parameter` dataclass in `docpipe/extraction/spec.py`;
  see [extraction](stages/extraction.md).

passage
: The stretch of source text a coordinate's or a value's quote is checked
  against, cut at sentence boundaries when a quote has to be rebuilt
  (`docpipe/extraction/verify.py`'s `_sentence_around`). At least
  `MIN_QUOTE_CHARS` characters, 8 in `docpipe/extraction/verify.py`, so
  it identifies a specific place rather than a recurring token. See
  [extraction](stages/extraction.md).

plan (the retrieval plan)
: The ranked, deduplicated list of work items for one document, built once
  before any model call by `docpipe.extraction.pipeline.plan_document`
  from every table and figure plus the best-ranked prose sections. Not the
  same word as a municipal heat plan document. See
  [extraction](stages/extraction.md).

profile
: Everything a project (kwp, scenarios) contributes to the generic
  pipeline: where its documents live, which Python components and prompts
  it supplies, which facets its inference app offers. Represented by the
  `Profile` dataclass in `docpipe/profile.py` and never imported by the
  core, only received by it. It may extend another profile and then takes
  what it does not provide from that one; see [profiles](profiles.md).

prompt
: A Markdown file under `profiles/<profile>/prompts/<stage>/<name>.md`,
  with optional YAML front matter carrying model parameters, loaded as a
  `Prompt` with an id, text and sha256 by `docpipe/prompts.py`. The core has
  no default prompt of its own, so a profile without a matching file fails
  to import, unless it extends a profile that has one (`default` has them
  all). See [core](stages/core.md).

provenance
: The block on an accepted tuple recording where its evidence came from:
  owner, page, section, table or figure identifiers, and, where locatable,
  a crop path and highlight rectangles. Attached by
  `docpipe.extraction.pipeline.fold_claims`; see
  [extraction](stages/extraction.md).

provenance file
: `<graph>.prov.ttl`, written beside a graph by `--serialize`: for every value
  its page, quote, run and trust level, as PROV-O and Web Annotation
  statements. Not the same as a tuple's provenance block. Written by
  `docpipe/extraction/provenance.py`; see [the knowledge
  graph](stages/graph.md).

provider
: The API a role (`llm`, `vlm` or `embedding`) sends its requests to:
  `openai-compatible` (a server of one's own), `openai`, `anthropic` or
  `gemini`, set per role (`LLM_PROVIDER` and its two siblings). Defined in
  `docpipe/providers/__init__.py`; see [the provider
  layer](stages/providers.md).

quote
: The verbatim passage a claim or a coordinate cites as its evidence,
  checked with whitespace collapsed against the source it names.
  `docpipe/extraction/verify.py`'s `quote_in` performs the check, and
  `_repair_quote` rebuilds an abridged quote when the value occurs exactly
  once in its source. See [extraction](stages/extraction.md).

recheck
: The `--recheck` pass that reapplies the answer-in-quote rule to an
  already-written harvest with no model call, dropping any coordinate
  whose recorded quote does not actually carry its answer and clearing the
  affected stamps. Implemented in `docpipe/extraction/recheck.py`; see
  [extraction](stages/extraction.md).

refusal
: A claim that did not survive `verify.verify_tuple`, or that named no
  real source, recorded in the harvest with a reason rather than dropped
  silently. `docpipe/extraction/schema.py` publishes the closed list of
  refusal reason patterns. See [extraction](stages/extraction.md).

remap
: The `--remap` pass that re-resolves a coordinate's recorded document
  wording onto the vocabulary as the spec reads today, with no model call,
  carrying the stamp forward only for the answer spaces it could fully
  settle. Implemented in `docpipe/extraction/remap.py`; see
  [extraction](stages/extraction.md).

resume stamp
: `<document>.stamp.json`, the record of what produced a document's
  harvest: the spec's sha256, the model, the anchor set, one fingerprint
  key per question asked (`docpipe/extraction/spec.py`'s `fingerprints`),
  the sha256 of the PDF it was read from, the passes that wrote into it, and
  the recorded sentences a review or a per-document question wrote.
  `docpipe/extraction/runner.py`'s `stale` compares the fingerprint
  keys (`parameter/`, `value/`, `axis/`, `slot/`) and the PDF's sha256
  where the stamp and the database both carry one, and the spec's sha256
  only where no fingerprint key is present; the model, the anchor set and
  every prompt id are written for a reader and never compared. The stamp
  is withheld, and the next run harvests the document again, when more than
  half its sources never reached the server, when no batch answered, or when
  any request ended on a 429 or a 5xx; an earlier stamp is removed with it,
  and the run exits 1 for the document. See [extraction](stages/extraction.md).

review
: The `--review` pass reading each of a harvest's level-C values a second
  time, by the same model, over a window narrowed to that value's own two
  legal passages, where only a disagreement counts as a trust reason.
  Implemented in `docpipe/extraction/review.py` and written to
  `review.csv`. See [extraction](stages/extraction.md).

route
: Whether an inference-app turn is answered directly from the knowledge
  graph (`route: "kg"`) or falls back to document retrieval
  (`route: "rag"`), decided by `docpipe/inference/kg_route.py` from a
  closed set of reasons, or overridden by the app's own answer-path
  control. See [inference](stages/inference.md).

row
: One value found by the value request, before its other coordinates are
  filled, defined as the `Row` dataclass in
  `docpipe/extraction/pipeline.py`. Every later field request fills a
  column of rows that already exist and can neither invent one nor drop
  one. See [extraction](stages/extraction.md).

row name
: One text for a harvested row as it reads now: its document, its tuple id and
  its parameter, and a short hash of what it says beside its value (its unit
  and each coordinate). Two rows of one document can share a tuple id, and a
  decision is about the row it was made on; the review page keys a row by this
  name. `gold.row_name` in `docpipe/extraction/gold.py`; see [measuring a
  harvest](stages/evaluation.md).

section
: One assembled unit of document structure: a title, joined prose content,
  its table and figure references, and its reading-order segments.
  Assembled in preprocessing Stage 3 (`docpipe/preprocessing/models.py`'s
  `Section`) and stored as one row of the `Sections` table by chunking;
  see [preprocessing](stages/preprocessing.md) and
  [chunking](stages/chunking.md).

segment
: One reading-order content unit inside a section: a run of text, or a
  marker standing for one table or figure, tagged with the page it came
  from. Defined by `docpipe/preprocessing/models.py`'s `Section.segments`
  and stored as one row of the `Segments` table by chunking; see
  [preprocessing](stages/preprocessing.md).

slice
: The profile-named coordinate, or coordinates, that decide first whether
  a row belongs in the graph a run serializes at all, also called the
  gate. A row that fails it is closed with state `out_of_slice` and never
  asked its other axes, for example `profiles/kwp/extraction.py:28`'s
  `SLICE = {"quantity": None}`. See [extraction](stages/extraction.md) and
  [kwp](profiles/kwp.md).

slot
: One field of one parameter as a single question with a single answer: a
  name, a kind (value, choice, number or text), a question, and, for a
  choice, its closed options. Defined as the `Slot` dataclass in
  `docpipe/extraction/fields.py`, computed from the spec rather than
  decided by a model. See [extraction](stages/extraction.md).

spec
: The validated, in-memory form of a profile's `extraction_spec.json`,
  produced by `docpipe.extraction.spec.load`: its parameters, axes,
  vocabularies and one worked example per parameter. A spec that fails
  validation refuses to load, naming the offending field. See
  [extraction](stages/extraction.md).

stage
: One numbered step of the pipeline, from file processing through
  preprocessing, refinement, visuals, chunking and embedding, to
  extraction and the graph, each reading and writing a fixed artifact or
  database state. Listed in order in [pipeline](pipeline.md).

state
: One of seven values a coordinate's `<name>_state` key can hold: `read`,
  `derived`, `unstated`, `unanswered`, `exhausted`, `unbacked`, or
  `out_of_slice`, each naming a different kind of finding about the model,
  the document, the run, or the run's scope. Defined in
  `docpipe/extraction/fields.py`; published at
  [states](contract/states.md).

statement
: One claim of an answer of the chat with its own quote: the answer is a list
  of statements, and a statement is shown only if its quote stands whole in the
  excerpt it cites (an image reading, a computed value: see the page for the
  other two bases). One statement is shown as a sentence, two or more as a list
  with the number of each citation, and the reader is told how many of those the
  model made were removed. `docpipe/inference/statements.py` decides which
  stand; see [asking the corpus](stages/inference.md).

sweep
: The repeated, windowed ask-and-fold loop that reads one coordinate of
  one or more rows until it is answered or the window budget runs out. The
  shared bookkeeping across a document's batches is
  `docpipe.extraction.pipeline.Sweep`. See
  [extraction](stages/extraction.md).

tier
: Which kind of evidence backs an accepted tuple: `text_located`, the
  quote sits in the document's own refined text and was placed on its PDF
  page, or `visual_source`, the quote sits in a table or figure
  transcription. Assigned by `docpipe/extraction/verify.py`'s
  `verify_tuple` from the source's `owner_kind`. See
  [trust](contract/trust.md).

top-up
: The `--top-up` pass that re-reads only the coordinates a resume stamp
  says moved, over the harvest's own sweep logic, instead of harvesting a
  document from its first passage again. Implemented in
  `docpipe/extraction/topup.py`; with `--top-up-parameters`, one of the two
  passes over a stored harvest that need the model and the index. The keys
  that only a parameter the spec gained moved are left to the other one. See
  [extraction](stages/extraction.md).

top-up-parameters
: The `--top-up-parameters` pass for a parameter added to the spec after
  documents were harvested, instead of harvesting them again. Per stored
  document it plans, asks the frame (with the stored pairs as its start) and
  reads for the new parameter alone, and appends the new tuples, refusals and
  one `parameter_state` line after the stored lines, which stay the same
  bytes, with the summary built again last. It carries forward the stamp keys
  of the addition only and enters itself into the stamp's `producers`. A
  document whose stamp moved in anything but the addition stays stale as a
  whole; one that was not read completely is left as it was and the run ends
  with exit 1. Implemented in `docpipe/extraction/topup_parameter.py`. See
  [extraction](stages/extraction.md).

trace
: The per-document, per-event JSONL log (`<document>.trace.jsonl`)
  recording every plan, anchor, frame, rows, field, sweep, drop, error and
  coord event, written by `docpipe/extraction/trace.py` and never
  aggregated by the writer itself. Turned off by setting
  `EXTRACT_TRACE=0`. See [extraction](stages/extraction.md).

trust level
: The deterministic A, B or C grade `docpipe/extraction/trust.py`'s
  `trust` computes for an accepted tuple from what the harvest already
  recorded, with no model and no second opinion. Published at
  [trust](contract/trust.md).

trust reason
: One token in a verdict's `reasons` list, naming why a tuple is not
  level A: `repaired`, `computed`, `not_located`, `review:disagree`,
  `conflict`, `page_transcribed`, or an `exhausted:<axis>` or
  `unbacked:<axis>` pointer at the axis at fault.
  Produced by `docpipe/extraction/trust.py`'s `reasons` and published as
  the closed pattern list `docpipe/extraction/schema.py`'s
  `TRUST_REASONS`; see [trust](contract/trust.md).

tuple
: One accepted value line of a harvest: a resolved value, every axis
  coordinate the field sweep could fill, an evidence tier, non-fatal flags
  and provenance. The output of `verify.verify_tuple`, folded into the
  report by `docpipe/extraction/pipeline.py`. See
  [extraction](stages/extraction.md).

tuple id
: A name for a harvested row made from its document, its quote and its value
  as written. It survives a re-chunk and a re-harvest that reads the same
  thing, so a decision, an export and a provenance record can hold on to it.
  `identity.tuple_id` in `docpipe/extraction/identity.py`; see
  [extraction](stages/extraction.md).

unstated
: The state (`SAID_UNSTATED`, wire value `unstated`) a coordinate is given
  when the model answers that the passages shown do not state it, an
  answer in its own right rather than a gap. Offered in every field
  request's closed list as `docpipe/extraction/fields.py:48`'s sentinel
  `out:unstated`. See [states](contract/states.md).

value request
: The batch that opens a document's sweep, asking a window of sources for
  every value they carry for one parameter, or, on a document-level plan,
  for the document as a whole. Turned into `Row` objects by
  `docpipe.extraction.pipeline.rows_from_reply`, the only request that
  creates rows; see [extraction](stages/extraction.md).

verdict
: The `{level, reasons, image_origin, corroborated}` dict
  `docpipe/extraction/trust.py`'s `trust` returns for one accepted tuple,
  rendered into a graph comment line by a profile's own `TRUST_PROSE`
  wording. See [trust](contract/trust.md).

verifier
: `docpipe/extraction/verify.py`'s `verify_tuple`, the last check a
  claimed tuple passes: its value against the spec's closed vocabularies
  and units, its quote against the literal source text. It returns a
  `Verified` tuple or a `Refusal`, never a claim accepted without its
  quote checked against the source text. See
  [extraction](stages/extraction.md).

vocabulary
: The closed list of labels a category axis or parameter may answer from,
  mapped to ontology URIs and folded to one comparable spelling by
  `docpipe/extraction/spec.py`'s `fold_label`. Distinct from a profile's
  ontology snapshot (`profiles/<name>/vocabulary.py`), which checks that
  this list still exists in the pinned ontology. See
  [graph](stages/graph.md).

window
: A short, possibly overlapping span of source passages one field request
  is shown at a time, walked by `pipeline.window_sources`
  (`docpipe/extraction/pipeline.py`). Kept short and overlapping on
  purpose, so a caption is never cut off from the table it belongs to. See
  [extraction](stages/extraction.md).

word index
: The SQLite FTS5 file `<name>.lexical.db` beside a corpus database, one row
  per section, table and figure, built by `docpipe lexical`. The chat searches
  it beside the vectors and merges the two rankings; a stale one is not asked.
  Defined in `docpipe/inference/lexical.py`; see [asking the
  corpus](stages/inference.md).

work item
: One planned document, parameter (or none), and source triple before
  batching, carrying its retrieval rank and origin (`structure` or
  `retrieval`). Defined as the `WorkItem` dataclass in
  `docpipe/extraction/pipeline.py`. See [extraction](stages/extraction.md).
