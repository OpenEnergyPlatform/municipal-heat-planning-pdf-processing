# 7. Reading the values out

| | |
|---|---|
| **In** | A profile's validated `extraction_spec.json` (via `spec.load`), plus the corpus's Sections/Tables/Images and FAISS embeddings the chunking stage already wrote to SQLite. |
| **Out** | One JSONL harvest file per document (`tuple`/`refusal`/`parameter_state`/`summary` lines) plus a `.stamp.json` resume stamp per document; `review.py` also writes `review.csv`. |
| **Resumes on** | A document's `.stamp.json` carries a fingerprint per question; force a redo with `--recheck`/`--remap` (disk-only) or `--topup` (re-sweeps one coordinate), never by deleting the stamp yourself, which this pipeline reads as nothing outstanding rather than as a request to redo it. |

`docpipe/extraction/` is where the corpus stops being retrievable text and starts being data. Stages 1 through 6 turn a PDF into sections, tables and figures a search can find; this stage reads those passages against a profile's ontology and pulls out typed value tuples -- a number or a class, its unit or vocabulary entry, and a handful of axes (which carrier, which sector, which year, which scenario) that place it in the ontology's own terms. Nothing here is written on the model's word alone. Every claim is checked against the profile's closed vocabularies and against the literal text of the passage it says it came from, and what survives is written out with that evidence still attached, not just the conclusion. It is the step that decides what an OBIE-built knowledge graph downstream may assert about a plan, so its job is less "extract" than "extract, and prove it."

It reads two things. One is a `Spec`, loaded and validated from a profile's `extraction_spec.json` (`spec.load`) -- the only place the model's questions, closed lists and evidence rules come from, and validation there is deliberately strict so a broken spec fails at load time and not three hours into a batch. The other is the corpus itself, reached through injected callables (`retrieve`, `structure`) that in a real run go against the FAISS index and the SQLite `Sections`/`Tables`/`Images` tables the chunking stage already built. Nothing is re-embedded here -- retrieval spends vectors that already exist. It writes one JSONL harvest file per document, and every line says what kind it is: `tuple` for an accepted value, `refusal` for a claim that did not survive verification and why, `parameter_state` for what happened to each parameter of the spec even when it produced no row at all, and one closing `summary` line with that document's trust-level distribution. Next to each harvest file sits a `.stamp.json` resume stamp, and `review.py` additionally writes a `review.csv` working list of the values a second reading disputed.

The first decision worth knowing before touching this code: a document is planned once, not once per parameter. `plan_document` reads every table and figure whole and unranked, because on a 65-document measurement 12,094 of 15,082 values came out of one of those two kinds -- "is a table" predicts a number better than any similarity search does. Prose is capped and ranked instead, because there are around 125 sections per document against roughly 110 tables and figures, and that is the half where a ranking has to earn its keep. Which parameter a number belongs to is then asked as just another coordinate of the row, not assumed from which plan retrieved it -- planning per parameter used to read the same table three times over, 804 planned sources against 234 real owners on one run. And the probes driving that ranking are the profile's HyDE anchors, not its query templates: with templates riding along, the source a value was actually read from sat at median rank 84; without them, rank 26. Templates are dropped rather than kept as a fallback.

The second: nothing is asked as one combined tuple. `fields.py` breaks a parameter into one slot per coordinate and asks each its own question, with "the passages do not say" a real, required option in the closed list rather than a silent omission -- a single combined request lets a model quietly drop the field it is unsure of for free, and on a 204-document corpus run that dropped the year on 63.5% of all values, 13% of them from a passage the model had itself just quoted elsewhere. Answering is not enough either: `merge_field` only accepts a coordinate whose cited passage was actually shown to the model AND actually contains the answer, and how far from the row that passage may stand is set per axis rather than by one blanket rule. A row label sits in the row's own table, a scenario is usually named a page earlier, a class can be argued anywhere in a methods chapter -- on one measured document, 370 of 455 year readings cited a passage outside the row's own table and section, and holding every axis to the strictest standard would have flagged all of them as doubtful even though the rule permits it.

The third: a claim is filed under the source that actually contains its quoted text, never under the label the model wrote for it. `route_claims` settles ties this way on purpose, because trusting the label let a claim quoted from a batch's fourth passage be accepted carrying the first passage's page, section and image as its evidence -- and a claim that names no real source and quotes nothing findable is refused outright rather than parked under whichever source came first. The same caution runs through row-merging: a coordinate already `read` cannot be overwritten by a later window's answer, because letting the last reply win once cost one table 7 rows that took a wrong second answer over their own and 10 more that collided with the first reading and lost their identity entirely.

Three things in this stage cost something, and `pipeline.py` names them itself: a retrieval lookup, one LLM call per batch of up to six sources or 14,000 characters, and locating a quote's coordinates on its PDF page. The stage does no embedding of its own -- the LLM call is the metered resource, a network round trip to wherever that model is served, needing whatever GPU backs it there. Locating is lazy on purpose, so a claim refused before that point never pays for opening the PDF, and it is optional: without a locator a text passage still gets its tuple, just no highlight rectangles, flagged `not_located` instead of dropped. A bad or missing model reply does not stop a document's run -- every fold point coerces a non-dict reply to an empty one, so a failed batch yields zero claims and the loop moves to the next batch rather than crashing. The one loop a bad reply could turn into a runaway cost, a batch's own "look for more passages" follow-up, is capped by a per-sweep budget (one follow-up by default) that also excludes everything already shown. And every rewrite this stage performs, including the ones `recheck`, `remap`, `topup` and `review` make to an existing file, writes to a temp file first and replaces the original only once it is complete, so a process killed mid-run cannot leave a truncated harvest file behind.

Resuming is per document and per question, not per corpus. `spec.py` computes a fingerprint for every question the model is asked -- its wording, its options, its evidence rule -- but deliberately leaves out anything that never reaches the model, like a comment or an option's order, and each fingerprint becomes its own key in the resume stamp. Changing one axis's vocabulary marks only that axis of that parameter stale, not the whole document: without that, a single new spelling used to make all 1,082 documents stale at once, about 93 GPU hours to re-read a corpus over one word. Redoing work is then priced to match what actually moved. `--recheck` re-applies a tightened evidence rule to what is already on disk, using only the quote and wording already stored, no model and no index, and drops the stamp only for what it actually rewrote. `--remap` re-resolves a moved or grown vocabulary the same way, model-free, and carries the stamp forward only for the axes it could fully settle, leaving a wording found in no list or a refusal that might now succeed stale until a real re-harvest. `--topup` is the one pass that costs a model call again, but only for the single coordinate the stamp names, re-swept over passages the document already cited rather than replanned from nothing -- and it refuses to touch any key that decided which rows exist at all, like a frame coordinate, because those rows would then not be this run's product to patch. `review.py` sits outside this whole ladder: it never writes a stamp and never rewrites a coordinate, only appends a flag, so running it costs a model call the same as `--topup` but touches nothing a later resume decision depends on. And do not just delete a `.stamp.json` to force a redo: elsewhere in this pipeline that exact shortcut produced the opposite of what was intended, because a missing stamp reads as "nothing outstanding" rather than "start over," and one run silently skipped 165 documents that way, exit 0.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/extraction/__init__.py`

Ontology-guided value extraction — the OBIE stage.

### `docpipe/extraction/pipeline.py`

pipeline.py – The harvest loop: sweep, dedup, verify, write.

Per document and parameter, the spec-generated queries probe retrieval in
rounds; every round excludes what earlier rounds saw, and the loop stops when
a full pass over the queries surfaces nothing new (bounded, because a stop
heuristic without a bound is an outage). Each surfaced owner — a section, a
table, a figure — is harvested exactly ONCE per parameter, however many
queries found it: that single rule is the whole dedup story for
query-overlap. Every claimed tuple then passes verify_tuple; refusals are
kept alongside the accepted, because a harvest that cannot say what it threw
away reads as complete when it is not.

The three expensive dependencies — retrieval, the harvesting LLM call, and
locating a quote on its PDF page — are injected callables. The loop's
correctness is a pure-code property and is tested without a GPU; the wiring
to the live inference stack lives with the CLI, not here.

Author: Felix Vossel

### `docpipe/extraction/runner.py`

runner.py – Wiring the harvest loop to the live stack.

pipeline.py owns the loop and is pure; this module supplies its three
callables from the real world — FAISS retrieval with owner exclusion, the
harvesting LLM call, and locating a quote on its page in the source PDF —
plus resume stamps and the CLI. Heavy imports (faiss, torch-backed embedders, fitz)
happen inside functions: importing this module must stay cheap, or every
test that touches the package pays for a GPU stack it never uses.

Probes are embedded directly, without the QA path's HyDE anchor call: the
spec-generated queries are already precise, skipping the anchor saves one
LLM call per probe, and a stable probe string means the query-embedding
cache hits across all documents.

Author: Felix Vossel

### `docpipe/extraction/spec.py`

spec.py – The contract between a profile's ontology knowledge and the core.

The core never reads OWL or TTL. A profile distils its ontology into this
declarative form: which parameters to extract, along which axes, with which
closed vocabularies — and one real example per parameter. Everything the
extraction stage does downstream (prompt building, verification, refusal of
out-of-vocabulary answers) leans on this file being right, so loading is
strict: a spec that is wrong fails loudly here, naming the field, not three
hours into a batch.

Author: Felix Vossel

### `docpipe/extraction/fields.py`

fields.py – The deterministic skeleton of a tuple.

A tuple's shape is not something a model decides. The spec already says which
coordinates a parameter has, which of them are a choice from a closed list and
which are a number or a wording, and that shape is identical for every value
in the corpus. So it is computed here, from the spec, and the model is never
asked for it. It is asked, one field at a time, to fill it.

Asking per field is the point. One request for a whole tuple lets a model
quietly drop a coordinate it is unsure of, and dropping is free: the field is
nullable, nothing refuses, nothing counts it. Measured on the 204-document
corpus run, the year was missing on 63.5% of all values, and on 13% of those
it stood in the very quote the model had itself cited. A request that asks for
one field and shows the choices has no such exit — it names the entry and the
passage it read it in, or it says the passage does not say.

Author: Felix Vossel

### `docpipe/extraction/queries.py`

queries.py – Precise retrieval queries, generated from the spec.

One broad question per parameter under-harvests: retrieval ranks, ranking
caps, and the tenth-most-similar table wins over the eleventh for no reason
a corpus cares about. So the profile supplies query *templates* and the spec
supplies the material — parameter labels and axis vocabularies — and every
combination becomes its own retrieval probe. The templates live with the
profile because their wording is corpus language (German for the heat
plans); this module only expands placeholders.

Placeholders:
    {label}        the parameter's label
    {axis:NAME}    one query per vocabulary entry of that axis, using the
                   entry's first (primary) corpus label

Author: Felix Vossel

### `docpipe/extraction/verify.py`

verify.py – No claim enters the output on the model's word.

The extraction reply states something and cites the passage it read it in.
Before anything is written, the claim is checked against what the model does
not control: the spec's closed vocabularies, and the source text the quote
must literally sit in. What survives carries an evidence tier saying how the
claim is backed:

  TIER_TEXT   The quote sits in the document's refined section text, and the
              passage was located in the source PDF, so the value can be
              shown highlighted on its page. The strongest evidence there is.
  TIER_VISUAL The quote sits in a table transcription, a caption, or a figure
              description, or the model read it off the image itself. The
              evidence is the page and that image. It cannot be confirmed
              automatically: the transcription is a model output too, so
              checking a claim against it would be model against model. A
              human confirms it by looking at the picture.
  (refusal)   The claim is backed by neither. It is recorded with a reason
              and never reaches the output.

Values are not only numbers. An ontology asks for categories and for plain
statements just as often, and those are evidenced the same way — by the
passage they stand in. What differs is only how a value is compared to its
quote: digits for a number, text for everything else.

Author: Felix Vossel

### `docpipe/extraction/trust.py`

trust.py – How much of a value the run can actually stand behind.

Every accepted tuple is verified: its number is in its quote, its quote is in
a shown source, every coordinate names the passage it was read in. That is a
floor, not a grade. Two values that both clear it can still differ by a lot:

  one has every coordinate read off its own table, in the plan's own text
  one has its year read off the caption of a different table three pages away

The second is the failure this whole repair is about, and until now nothing
downstream could tell the two apart. A reader of the graph saw two numbers.

So: a deterministic level per value, computed from what the harvest already
records. No model, no second opinion, no threshold anybody tuned.

  A  the plan's own text says it, every coordinate read, every passage local
  B  the same, but read out of a table transcription or a figure description
     -- which is a model's reading of a picture -- or out of a plan whose
     pages had no text layer at all and were transcribed page by page
  C  something is off: a passage that belongs to another row, a coordinate
     the run gave up on, a repaired quote, a computed number, a contested
     identity

The reasons are a closed list, because a reason nobody can enumerate is a
reason nobody can count. What makes a C is what a curator should look at.

A value can be read a second time (`review.py`), and what that came to is
recorded here as a mark. It never lifts a level: the second reading uses the
same model over a narrower window, so an agreement says the reading is
self-consistent and not that the passage it cites belongs to the row.

Measured on Kassel's 559 tuples, which is why the levels are cut here and not
somewhere else: 527 of 559 came out of a table or figure image, so image
origin alone separates nothing and is not a warning. What did separate, on
that run: 370 of 455 year readings cited a passage outside the row's own
table and its section, 87 percent of the area readings, 47 percent of the
scenarios, 49 percent of the sectors -- and 13 percent of the carriers, which
is the one coordinate the row itself really carries.

That run had no evidence rule at all, and this is where the reading of those
numbers has to be careful. The spec now sets the rule per axis -- own, local
or any -- and the harvest enforces it: a coordinate that broke its own rule
comes out `unbacked`, never `read`. So on a harvest written under the rule,
a passage outside the row's own source is only a finding for an axis whose
rule is `own`; for the others it is the rule working as written. Judging all
seven by the strictest one would report every legal reading as a doubt, which
is a signal that fires on the corpus and separates nothing -- the exact
mistake image origin was kept out of the reasons for.

Hence `own`: the set of axes a reader may hold to the row's own source. It
is a property of the spec, so the caller passes it; without it every read
coordinate is judged, which is right for a harvest from before the rule.

Author: Felix Vossel

### `docpipe/extraction/schema.py`

schema.py – A JSON Schema for the harvest, the stamp and the trace.

The harvest is the durable artifact. The graph is a function of it, and every
later question — what does this key mean, which OEO predicate does it become,
may it be null, what is the closed list — was answered until now by reading
`runner.py`. That is not an answer anyone outside this repository can use, and
it is not one this repository can check.

So the schema is GENERATED from the spec, not written beside it. The parameters,
their axes, the closed lists, the questions and the `kg` blocks all come from
`profiles/<name>/extraction_spec.json`, which means a spec change that is not
reflected in the schema is a failing test rather than a stale document. Three
schemas come out:

  harvest  one line of <name>.jsonl: an accepted tuple or a refused claim
  stamp    <name>.stamp.json, what produced that harvest
  trace    one line of <name>.trace.jsonl, one event of the run

Every property carries a `description`, and every coordinate additionally
carries `x-question` (the German question the model was asked), `x-options`
(the closed list with the corpus spellings) and `x-kg` (what it becomes in the
graph). `x-kg` is the spec's own `kg` block, the same one the serializer reads,
so what a reader is told and what is written cannot drift apart.

    python -m docpipe.extraction.schema kwp            # print
    python -m docpipe.extraction.schema kwp --write    # write into the profile

Author: Felix Vossel

### `docpipe/extraction/trace.py`

trace.py – What the harvest did, written down so it can be counted afterwards.

The text log says what happened to a human reading it live. It cannot answer
"at which rank was this value found", "in which window did this coordinate
close", "did the retry help", because those are questions about a million
requests and the answer is a distribution, not a line. Every setting this
stage has was picked without such a distribution at least once, and every one
of those picks was wrong: top_k, the window budget, the batch threads.

So each document gets a second file next to its harvest, one JSON object per
event, and nothing in it is aggregated. Aggregating is what the report script
does, and it can be rewritten when the question changes. The trace cannot.

Cost is a few hundred bytes per model request, about half a megabyte per
document. EXTRACT_TRACE=0 turns it off and every call becomes a return.

Author: Felix Vossel

### `docpipe/extraction/recheck.py`

recheck.py – The evidence rule, applied to a harvest that was written without it.

A coordinate is only as good as the passage cited for it, and for one corpus
run that passage was checked against the wrong thing: merge_field held it to
sitting verbatim in the source and never to containing the answer. 27.6% of
the years that came out of that run cite a passage with no year in it, one of
them the caption "Tabelle 1: Bestehende Wärmenetze und Heiz(kraft)werke"
offered as evidence for 1990.

Both halves are in the harvest files already — the wording in <axis>_raw, the
passage in <axis>_quote — so the rule can be applied to what is written
without asking a model anything. That is the whole point of keeping the
evidence next to the claim: a rule that tightens can be enforced backwards.

What this cannot do is fill anything. A coordinate dropped here is a
coordinate the next run has to read properly, and it is marked so the
difference between "the plan does not say" and "the last run did not check"
stays visible instead of collapsing into an empty cell.

Author: Felix Vossel

### `docpipe/extraction/remap.py`

remap.py – A moved vocabulary, applied to a harvest that is already written.

The resume stamp used to be one sha over the whole spec file, so a single new
spelling made all 1.082 documents stale at once: about 93 GPU hours to re-read
a corpus over a word. The ontology this spec is written against keeps moving,
and that bill would come again and again.

But nothing was actually re-read in those hours. The harvest keeps both halves
of every coordinate — the class in `<axis>`, the document's own wording in
`<axis>_raw` — precisely so that mapping the one onto the other stays a pure
function of the files. A new alias, a renamed label, an option that moved to
another class: all of those are answered by running that function again, and
it needs no model, no GPU and no index.

What it cannot do is fill anything. Four things stop it, and each is counted
rather than papered over:

  no wording   the model never sent `<axis>_raw`, so there is nothing to map
               from and the URI is all that survives. Those coordinates stay
               open for a targeted top-up.
  not listed   the wording is in no list, old or new. The reading that stands
               is the model's own judgement call, and overwriting it with an
               empty cell would destroy a finding rather than correct one.
  a refusal    a claim this axis was refused for may map now that the list has
               grown. Only a re-harvest can turn it back into a tuple.
  no parameter a row naming a parameter the spec does not have. Nothing here
               may touch it, and nothing here may vouch for the document.

The stamp is carried forward for exactly what this pass could account for. An
answer space it fully re-mapped in a document — `axis/<uri>/<name>`, or
`value/<uri>` for a category parameter's own list — is written forward; every
other key keeps what the stamp said. So a document whose carrier list moved
and whose carrier wordings all resolved comes out current, while one with a
wording nobody listed stays stale in that one key and in nothing else.

Author: Felix Vossel

### `docpipe/extraction/review.py`

review.py – A second, narrower reading of the values nobody can stand behind.

What it is, said first because the record it writes is read as more than it
is: the same model, over the same document, shown a window that is a strict
SUBSET of the one the sweep already walked -- the row's own passage and the
section that passage stands in. So this is a self-consistency check under a
narrowed window, not an independent second reading.

That is enough to catch the failure the lowest trust level names, a value read
off a passage belonging to another row, because the narrowed window holds no
such passage. It cannot catch a misreading of the same picture in the same
way twice. A real second opinion needs a different model or a different window
-- the page image instead of the transcription -- and neither is what this is.

Consequence, on purpose: an agreement never lifts a level. It is recorded as a
mark and nothing else. A disagreement IS a reason, because two readings of the
same passage that do not match is a fact about the value.

What it writes: one flag per reviewed row, on `flags`, and one line per
reviewed row in `review.csv` beside the harvest. Not a new record kind and not
a new key on the tuple: the tuple branch of the published schema is closed,
and the second reading's own content is a curation artifact rather than
evidence.

Author: Felix Vossel

### `docpipe/extraction/topup.py`

topup.py – Re-read the one coordinate the stamp says moved, not the document.

A question is reworded, an option list grows a class the model can now choose,
an evidence rule tightens. The stamp knows exactly which key moved and the
resume then does the only thing it can: it reports the document stale and the
next run harvests it from the first passage. For one axis of one parameter
that is a corpus run to answer a question nothing else asked.

What this does instead: take the coordinate off the rows that carry it, walk
the SAME sweep the harvest walks -- `runner.make_sweeper`, so there is one
sweep and one set of numbers -- and write the answer back. Then carry that one
stamp key forward and leave every other key exactly as it was, so a run that
comes later still sees what it has to redo.

What it refuses to do is more important than what it does. A key that decided
which rows exist, which passages were planned, or which model read them is not
a coordinate: the rows are then not this run's product at all and the document
is skipped whole rather than half-repaired. The frame is refused for the same
reason one level up -- it decides how many passes a document gets.

And the old reading is put back whenever the re-sweep cannot better it. No
coordinate of the two profiles is required, so an emptied one would pass
verification in silence and the reading would be gone with nothing saying so.

Not model-free and not index-free, unlike `--recheck` and `--remap`: it needs
the database, the index, the embedder and a served model. What it saves is the
plan, the row requests and the frame.

Author: Felix Vossel

[Back to the index](../README.md)
