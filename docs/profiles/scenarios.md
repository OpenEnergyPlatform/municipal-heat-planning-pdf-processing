# The scenarios profile

## The AR6 literature corpus

The scenarios profile targets a different corpus than the kwp profile: not
municipal heat plans but the publications the IPCC AR6 scenario database
cites, staged from a crawl over that citation list, each entry's PDF
placed by hand and the AR6 scenarios it documents becoming the
`DocumentScenarios` link table described next
(`profiles/scenarios/source.py`'s module docstring).
`profiles/scenarios/profile.py` sets the source and answer language to
English for the whole profile, `document_noun` to `Publikation`, and
three catalog facets a reader can filter by: publication year, venue, and
the AR6 scenarios a publication documents. That setting covers
`profile.py`'s own fields only: `extraction_spec.json`'s
`parameter_question` and every parameter's label and description are
German sentences, and the spec's `_comment` states that
`out:not_in_list`'s meaning is worded in the language of its prompts,
German here, not the profile's declared English (`extraction_spec.json`,
lines 35 to 36).

The corpus's own schema carries this identity in three tables, applied by
`profiles/scenarios/schema.sql` after the core schema. `DocumentMeta` holds
one row per document with `doi`, `title`, `year`, `venue`, `is_oa` and
`scenario_count`, filled from the crawl rather than from this profile's
own extraction; the graph stage's cross-check against these columns is
covered below. `Scenarios` holds one row per AR6 scenario run known to
the database, keyed by that database's own `ar6_id` and its `name`.
`DocumentScenarios` links the two tables many to many: a comment above it
in the schema states that one publication documents as many as 146
scenarios, and one scenario is in turn documented by as many as three
publications. `profiles/scenarios/extraction.py`'s module docstring puts
the database's own scale at 1,389 scenario runs in total.

Trust computation for this profile also has to account for one
corpus-wide fact: `ar6.db`'s `Documents` table carries no
`page_text_transcribed` column, so `PAGE_TRANSCRIBED` is fixed `False`
for every value this profile serializes, never read per document the
way an axis coordinate is (`profiles/scenarios/kg.py`, lines 496 to
500). Over the 164-document ar6 harvest the module calls its own, 298 of
11,129 scenario-scope tuples could not be attached to any scenario: 289
because the run's window budget was exhausted, 9 because the paper
itself never states which scenario the value belongs to
(`profiles/scenarios/kg.py`, lines 800 to 804; the full account is at
[../stages/graph.md](../stages/graph.md)).

## What the profile contributes to each stage

Every attribute below is one seam `docpipe/` or a script asks a profile
for by name, described in general on [profiles](../profiles.md); this
table gives this profile's own answer.

| Stage | Module | Attribute | Contributes |
|---|---|---|---|
| File processing | `source.py`, `schema.sql`, `store.py` | `SOURCE`, `DocumentMeta`, `Scenarios`, `DocumentScenarios` | the ar6 crawl as a `Source`, and the profile's tables and upsert helpers |
| Layout detection | `profile.py` | `column_layout` | `"auto"`, a two-column journal or report page read column by column |
| Structure assembly | `preprocessing.py` | `HYPHEN_EXCEPTIONS`, `CAPTION_MAX_WORDS`, `TITLE_EXCLUDE_PREFIXES`, `DIRECTORY_FIGTAB_WORDS`, `BIBLIOGRAPHY_TITLE_WORDS` | English hyphenation, caption length, heading and bibliography rules |
| Preprocessing, refinement, visuals | `prompts/preprocessing`, `prompts/refinement`, `prompts/visuals` | 1, 3 and 7 prompt ids | page transcription, English artefact repair, table and figure captioning |
| The picker (app) | `catalog.py`, `profile.py` | `CATALOG`, `facets` | publication labels and three filters |
| Extraction | `extraction.py`, `prompts/extraction/*.md` | `SPEC_PATH`, `document_axes`, eight prompt ids | the spec, the per-document scenario and region lists, and the harvest's own questions |
| The graph | `kg.py` | `make_serializer` | OEKG Turtle, the trust wording |
| The answer app | `inference.py`, `prompts/inference/*.md` | `PHRASES`, `NON_ANCHOR`, `READOFF_MARKER`, `READOFF_NOTE`, 16 prompt ids | the English chat wording and the answer loop's own prompts |

## Per-document choice lists: dynamic axes and dynamic values

A spec parameter or axis is ordinarily a fixed, corpus-wide list: every
document is offered the same vocabulary. `docpipe/extraction/spec.py`
defines a second kind for a list that is real but not corpus-wide, on two
levels. `Axis.dynamic` marks one coordinate of a parameter as filled in
per document rather than written in the spec (`spec.py`, the `Axis`
dataclass); `Parameter.vocabulary_dynamic` marks a parameter's own value
the same way, and `_validate_parameter` refuses a spec that gives a
category parameter both a fixed vocabulary and `vocabulary_dynamic` at
once, or gives `vocabulary_dynamic` to a parameter that is not a category
at all (`spec.py`, lines 441 to 465). Either way, the vocabulary key
stays out of `extraction_spec.json` and a profile hook fills it in before
the harvest runs; where no hook fills it, the coordinate degrades to a
plain wording, the glossary's definition of a dynamic list.

This profile uses both mechanisms across the five parameters that carry
a scenario coordinate: each uses at least one, and `scenario_region`
uses both. `scenario_label`'s value is `vocabulary_dynamic`
(`extraction_spec.json`, the `scenario_label` parameter): the model
picks the AR6 run this document documents, from that document's own
list, not from all 1,389. `scenario_region`'s value is
`vocabulary_dynamic` too, picking from a narrowed slice of the OEKG's
249 study regions. A `scenario` axis, carried by the other four
parameters (`scenario_type`, `scenario_abstract`, `scenario_region`,
`scenario_year`, together `SCENARIO_FIELDS` in `kg.py`), is `Axis.dynamic`
instead: it lets each of those rows say which of the document's own
scenarios the value belongs to. Only the axis's nested `kg` sub-block is
byte-identical across all four, fixing the factsheet's class, node and
parent link, a fact `test_the_four_scenario_axes_name_one_and_the_same_factsheet`
pins so that a block drifting on one parameter cannot quietly put its
values on a factsheet of their own; the axis's `evidence` rule and its
`question` wording are not part of that check and differ per parameter,
covered below.

Both lists for one document are computed once, before the harvest starts,
by `profiles/scenarios/extraction.py`'s `document_axes(conn, document_id)`,
which returns a dict keyed `scenario`, `scenario_label` and
`scenario_region` (`extraction.py`, lines 172 to 189). Two builders feed
it. `document_scenarios` reads `Scenarios` joined through
`DocumentScenarios` for this document's id, keyed by the AR6 name itself
rather than by an invented IRI, since that name is the identity the
corpus links against and `kg.py` resolves it the same way
(`extraction.py`, lines 149 to 161); the same dict backs both the
`scenario` axis and the `scenario_label` parameter, so one run identifier
resolves the same way whichever field asks about it. `document_regions`
reads the 249 entries of `regions.json` and keeps only the ones whose
label is mentioned somewhere in this document's own text.

`_document_text` concatenates every row of `Sections.content`,
`Tables.markdown`, `Tables.caption`, `Images.description` and
`Images.caption` for the document (`extraction.py`, lines 98 to 121), so a
country named only in a figure's caption is still quotable. Matching runs
on word boundaries and is casefolded, except for an all-caps label of
four letters or fewer, matched case-sensitively instead: a bare "US" or
"UK" casefolded onto ordinary English prose (the pronoun "us", the
country name "Ukraine") would otherwise be offered as a valid country on
every document of this English-language corpus (`_acronym`, `_mentioned`,
`extraction.py`, lines 124 to 146). The same widening accepts one failure
mode in place of the other: a paper that spells a country only as an
adjective ("Chilean") no longer offers that country as a choice, and the
model falls back to an `out:` sentinel, a visible, counted outcome rather
than a wrong class chosen silently.

Neither list is ever left empty. `document_axes` appends the profile's
`out:` entries to both lists unconditionally, so a publication naming no
scenario, or no country its own text narrows a region list to, still
gets a complete list; otherwise the field reverts to open text, exactly
what a closed list exists to avoid (`extraction.py`, lines 172 to 184).

## The out: sentinels

An `out:` sentinel is a vocabulary entry offered like any real class, but
one whose identifier begins with the literal prefix `out:` and names a
deliberate non-class answer, not a reading the graph can hold. The
prefix is checked in two places that must agree: `NOT_IN_GRAPH = "out:"`
in `profiles/scenarios/extraction.py` (line 56), telling the harvest
prompt what counts as no class, and the same constant again in
`profiles/scenarios/kg.py` (line 252), telling the serializer what it
refuses to mint; `kg.in_graph()` is the one guard every later mint, link
and type decision runs through.

Three families of sentinel exist, plus one entry of a fixed vocabulary that
behaves the same way. `SCENARIO_OUT` offers `out:family`, for a wording
that names a group of runs (a policy family, for example) rather than one
identified run, and `out:not_documented`, for a scenario the paper names
that this document's own AR6 list does not carry (`extraction.py`, lines
83 to 91). `REGION_OUT` offers `out:global` (a worldwide scenario, since
the OEKG's own region list holds only individual countries and no
aggregate), `out:multiregion` (a named grouping, such as a trade bloc,
that the list does not carry as a country) and `out:other` (a spatial
statement fitting neither). An AR6 scenario is global far more often than
national, so without `out:global`, most scenarios would have no matching
entry among the 249 countries at all (`extraction.py`, lines 66 to 76).
Finally, `scenario_type`'s own vocabulary is fixed and corpus-wide rather than
per-document, but carries the same idea as its eighteenth entry,
`out:not_in_list`: the passage names a kind of scenario that none of the
other seventeen OEO classes covers, a finding distinct from the passage
naming no kind at all, for which the vocabulary offers the generic
`scenario` class instead (`extraction_spec.json`, the `scenario_type`
parameter; confirmed as 17 real classes plus this one sentinel by
`test_every_scenario_type_says_what_it_means` and
`test_the_meanings_are_the_terms_own_and_not_a_paraphrase`).

`extraction.py`'s module docstring states the design reasoning directly: a
closed list with no way to decline an answer does not stop a model from
answering, it stops it from answering correctly, since the reply that
comes back is the nearest entry that is not quite right. Before these
sentinels existed, an empty field already read as unmapped, conflating
three things: nothing in the passage fit, the model never looked, or the
reply was cut short. A chosen `out:` entry states exactly one of those,
and the harvest counts it. The harvest renders a choice list as a short
answer token followed by its longer explanation, and the prompt asks for
the token copied character for character, so every sentinel's first
label is short and retypable, its longer gloss placed as an alternate
spelling rather than first (`extraction.py`, lines 58 to 64).

Once chosen, a sentinel is refused a place in the graph outright.
`in_graph()` and `graph_value()` ensure an `out:` value never becomes a
class, an IRI or a link; only the document's own wording, carried
separately as `value_raw`, stands in for it, since the sentinel's own
label describes why nothing fit, not what the document states (`kg.py`,
lines 260 to 271). Every chosen sentinel, together with every
`scenario_label`, `scenario_region` or `scenario_type` row that resolved
no `value_uri`, is counted once into an `out_of_graph` tally, logged per
document and never written as a triple (`kg.py`, lines 592 to 609).
Measured over a corpus run, the model answered with a sentinel 1,171
times for a wording its own document-scoped AR6 list could resolve
without a guess, 347 of those a character-for-character spelling match;
on one document, the wording matched the list's only entry exactly and
the model still answered `out:not_documented` (`kg.py`, lines 318 to 321,
`resolve_wording`'s own docstring; the sentinel is named by
`test_the_list_settles_what_the_model_gave_up_on`,
`tests/test_scenarios_extraction.py`, lines 1093 to 1096). Those readings
are not lost: `resolve_wording()` rescues a link the document's own list
settles unambiguously even where the model gave up, logged on its own
line, separate from the sentinel tally (`kg.py`, lines 706 to 714).

## The graph: one report, one bundle, a factsheet per run

The target is OEKG, on the Open Energy Platform, built by
`profiles/scenarios/kg.py`'s `make_serializer`, called the same way as the
kwp profile's own serializer through `docpipe/extraction/serialize.py`; the
walk shared by both profiles, and the ontology audit that checks a spec
against a pinned snapshot separately from any serialize run, are documented
at [../stages/graph.md](../stages/graph.md), and the harvest fields this
serializer reads are published field by field at
[../contract/scenarios.md](../contract/scenarios.md). This profile's own
half of that audit, `profiles/scenarios/vocabulary.py`, pins 32 ontology
identifiers named in the spec, plus the 249 OEKG study regions, against
the same OEO release the kwp profile's own 58-identifier snapshot uses;
`python -m profiles.scenarios.vocabulary --check` holds a spec run
against the checked-in `vocabulary.json` (`vocabulary.py`, lines 1 to 20;
[../stages/graph.md](../stages/graph.md), lines 315 to 317).

Every IRI is minted under `BASE`, which defaults to
`https://openenergyplatform.org/ontology/oekg/` and can be overridden by
the `OEKG_ID_BASE` environment variable (`kg.py`, line 53).
`mint(collection, name)` derives the local part as a UUIDv5 over a
normalised identifying name, never a random UUIDv4, so two serialize
runs over one document mint byte-identical IRIs (`kg.py`, lines 230 to
235; `test_the_iri_is_a_pure_function_of_the_name`). Where each class of
node lives was read directly off the running OEKG graph over its SPARQL
endpoint, 13,700 triples at the time it was checked (`kg.py`, lines 47
to 49): a study report sits under `publication/`, a scenario factsheet
under `scenario/`, a study region under `region/`, and a scenario
bundle, an author, an organisation and a funder directly under the base
with no path segment at all (`COLLECTIONS`, `kg.py`, lines 59 to 67;
`test_the_individuals_live_where_the_oekg_puts_them`).

One document mints exactly one study report and one scenario bundle. The
report's IRI comes from the resolved title; the bundle's comes from
`study_project_name` where the document names a project, and from the
title again where it does not (`kg.py`, lines 645 to 648). Both carry a
fixed has-uuid triple regardless, since the OEKG mints a UUID on every
node it holds, although that predicate's declared domain names only a
report or a factsheet, not a bundle; `edges()` records the gap with its
own stated reason so the ontology check does not flag it as unexplained
(`kg.py`, lines 181 to 191).

One factsheet is minted per resolved scenario identity. For every
scenario-scope row, `scenario_key()` decides which run, if any, the row
belongs to, against the document's own known-scenario list and a synonym
dict built from whichever rows of the same document already resolved a
run (`kg.py`, lines 339 to 388, 716 to 726); a wording that resolves to
no run still gets its own factsheet, keyed by the wording alone. A
factsheet's `rdfs:label` is the AR6 database's own spelling where a run
was resolved, and the document's own wording is kept alongside as
`dc:acronym`; with no long name known for a run, both carry the same
string, the usual case in this corpus (`kg.py`, lines 850 to 853). Every
factsheet also carries a fixed `OEO_00020517` annotation on top of
whatever `scenario_type` classes the model read off the text
(`IAM_SCENARIO`, `kg.py`, lines 196, 866).

A study region is referenced, never minted. A region the model matched
against the document's own narrowed OEKG list is written as a bare link
to that region's existing IRI, carrying no `rdfs:type` and no
`rdfs:label` of its own, since the individual already exists on the OEKG
under its own type and label, and asserting them again would place a
second label where the shapes allow only one
(`kg.py`, the comment above the region block;
`test_a_region_is_referenced_by_its_existing_oekg_iri`). An `out:global`,
`out:multiregion` or `out:other` choice, or a wording the narrowed list
did not hold, mints no region node at all and is only counted; minting
one would have put a 250th region under `oekg/region/` beside the 249
already pinned (`profiles/scenarios/vocabulary.json`, `regions_count`
249; `test_a_global_scenario_does_not_mint_a_region`;
`test_a_region_the_list_did_not_hold_mints_nothing_and_is_counted`).

Six fields the OEKG shapes allow at most once (`publication_title`,
`publication_date`, `publication_doi`, `publication_abstract`,
`study_project_name`, `study_acronym`, the `SINGLE` tuple, `kg.py`, lines
199 to 200) are settled by `_pick_one()`, which favours the reading the
most sources agree on: first dropping any candidate that is a strict
substring of another (a running header would otherwise outvote a title
on its own title page), then ranking by vote count, whether the reading
was located on its PDF page, and length (`kg.py`, lines 401 to 429).
Runner-up spellings are counted `contested` rather than dropped from the
log. A read-only connection then cross-checks the chosen title, date and
DOI against `DocumentMeta`, filled in by the crawl, not this profile's
own extraction; a disagreement is logged and the crawled value is never
substituted into the graph, since a published value must carry its own
evidence, and the crawl's copy is only the cross-check
(`kg.py`'s module docstring; `_crosscheck`, lines 443 to 459).

Every triple this serializer writes about a value carries, immediately
above it, the passage it was read from. By default that passage is a
flattened Turtle comment (`_evidence_comment`, `kg.py`, lines 519 to 542)
rather than a linked node, since the OEKG's node shapes are currently
declared `sh:closed`, and an unanticipated triple on a report or a
factsheet would invalidate the node it documents. Setting `OEKG_EVIDENCE`
to anything other than `"0"` switches to a linked
`oekgprov:ExtractionEvidence` node per passage instead, described in the
module's own docstring as provisional and ahead of the shapes, so it
stays off by default (`kg.py`, line 467 and the module docstring). Either
branch is followed by one rendered trust line, worded in English
throughout `TRUST_PROSE` (`kg.py`, lines 472 to 480); the full
trust-level and reason vocabulary is published at
[../contract/trust.md](../contract/trust.md). Three of the four scenario
axes, `scenario_type`, `scenario_abstract` and `scenario_year`, hold
their own evidence rule `own`, since a name borrowed from another
section is inference about the scenario, not a reading of it, and only
an axis whose rule is `own` can produce a nonlocal reason in the
rendered trust line. `scenario_region` alone is `local`, since coverage
and the heading naming the scenario list typically sit on neighbouring
pages rather than one passage (`kg.py`, lines 482 to 493; `OWN_EVIDENCE`
is computed once from the spec by `docpipe/extraction/spec.py`'s
`own_evidence()`). The state vocabulary those rules write into, `read`,
`derived`, `unstated` and the rest, is published in full at
[../contract/states.md](../contract/states.md).

## What is refused

A spec that mismatches the two dynamic mechanisms above refuses to load
before any document is touched: a category parameter naming both a fixed
vocabulary and `vocabulary_dynamic`, or a non-category parameter naming
`vocabulary_dynamic` at all, raises `SpecError` naming the offending
field (`docpipe/extraction/spec.py`, lines 441 to 465). A `kg` block
whose class is not an identifier shape, or whose predicate is not a
single token, is refused the same way, at spec load time
(`_validate_kg_ids`, `spec.py`, lines 675 to 708); this rule is shared
with the kwp profile. This profile's own `kg.py` calls that same loader
again, on its own copy of the spec, at import time (`load_spec(_SPEC)`,
`kg.py`, line 494), so a spec broken this way fails to import the whole
serializer before a single document is processed, not partway through a
run. `kg.py`'s own lookup helpers, `_property`, `_name`, `_class` and
`_kg`, raise `KeyError` for a key the spec does not carry rather than
default silently, the narrower guarantee
`test_the_serializer_dies_at_import_if_the_spec_stops_saying_it` pins.

A document whose `publication_title` never resolved is refused whole:
the serializer returns `None` and logs at `INFO` level, before a bundle,
a factsheet or an author node is built (`kg.py`, lines 621 to 623). A
missing `publication_date` or `publication_author` is not refused this
way, only named in the per-document summary line as a missing required
field (`REQUIRED`, `kg.py`, line 210 and lines 619 to 620, 934).

A scenario wording absent from its own quoted passage is refused as an
identity for every scenario-scope parameter alike: `scenario_key()`
returns no identity and no label, and the row contributes no factsheet,
comment or number (`kg.py`, lines 293 to 307, 383 to 387); it used to
mint a factsheet anyway, carrying the invented wording as a stable label
of its own, which this check exists to prevent. A wording that fits more
than one run of the document's own known-scenario list, with none
matching it exactly, is refused as an identity rather than guessed: the
link is dropped, the wording alone becomes the factsheet's key, and rows
the model assigned to different runs land together on that one shared
factsheet, a conflation the module accepts and logs by name rather than
hides (`ambiguous()`, `kg.py`, lines 274 to 290; the merge report, lines
822 to 836).

Every `out:` choice, and every unresolved `scenario_label`,
`scenario_region` or `scenario_type` row, is refused a place in the
graph the same way: no class, no IRI, no link, only a count and a log
line (`kg.py`, lines 592 to 609). A region wording the document's own
narrowed list did not hold is refused identically rather than minted as
a new individual.

One collision is explicitly not refused, unlike the kwp profile's own
identity guard. A second document minting the same study report or
scenario bundle IRI as an earlier one in the same run, a preprint and
its later journal version sharing one title, for example, is only
logged, naming both documents and the shared IRI; both documents'
single-valued triples land on that one shared subject rather than the
second document being dropped whole, the way kwp refuses a duplicate
identity (`kg.py`, lines 645 to 656; the contrast is documented at
[../stages/graph.md](../stages/graph.md)).

## Verification

The picker: `tests/test_scenarios_catalog.py`'s
`test_the_declared_facets_are_all_offered` and
`test_a_publication_is_findable_under_every_scenario_it_documents` hold
the facets to what `catalog.py` and `profile.py` declare above.

The corpus: `tests/test_scenarios_source.py`'s
`test_every_publication_is_its_own_version_group` and
`test_a_renamed_scenario_is_updated_not_duplicated` hold the crawl's DOI
identity and the `Scenarios` upsert to what `source.py` and `store.py`
state above. The extraction spec, the sentinels and the graph are
verified throughout this page by `tests/test_scenarios_extraction.py`,
named at each claim it backs.

## The parameters, from the published contract

Read from `profiles/scenarios/extraction_schema.json` by `scripts/build_docs.py`. Each row is one record kind of the harvest; an axis is a coordinate of that record, with the kind of answer it takes. The full contract, every question and every option, is on [contract/scenarios.md](../contract/scenarios.md).

| parameter | value | axes | graph node |
|---|---|---|---|
| `publication_abstract` | string | `parameter` (one of the spec's parameters) | `scenariobundle` |
| `publication_author` | string | `parameter` (one of the spec's parameters) | `author` |
| `publication_date` | string | `parameter` (one of the spec's parameters) | `studyreport` |
| `publication_doi` | string | `parameter` (one of the spec's parameters) | `studyreport` |
| `publication_title` | string | `parameter` (one of the spec's parameters) | `studyreport` |
| `scenario_abstract` | string | `parameter` (one of the spec's parameters), `scenario` (string) | `scenariofactsheet` |
| `scenario_label` | string | `parameter` (one of the spec's parameters) | `scenariofactsheet` |
| `scenario_region` | string | `parameter` (one of the spec's parameters), `scenario` (string) | `scenariofactsheet` |
| `scenario_type` | string | `parameter` (one of the spec's parameters), `scenario` (string) | `scenariofactsheet` |
| `scenario_year` | string | `parameter` (one of the spec's parameters), `scenario` (string) | `scenariofactsheet` |
| `study_acronym` | string | `parameter` (one of the spec's parameters) | `scenariobundle` |
| `study_funder` | string | `parameter` (one of the spec's parameters) | `funder` |
| `study_organisation` | string | `parameter` (one of the spec's parameters) | `organisation` |
| `study_project_name` | string | `parameter` (one of the spec's parameters) | `scenariobundle` |

[Back to the index](../README.md)
