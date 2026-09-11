## The corpus and its database

`kwp` covers Kommunale Wärmeplanung: heat plans German municipalities
publish under the federal Wärmeplanungsgesetz, sourced from the KWW
register, an Excel sheet the source module filters to rows marked
"abgeschlossen" (completed) that carry a usable PDF link
(`profiles/kwp/source.py:34` to `44`, `load_and_filter_excel`). The corpus
stands at 1,082 documents (`docpipe/extraction/trust.py:208`,
`docpipe/extraction/remap.py:6`). Eleven carry no PDF text layer and are
read page by page by a vision model instead
(`docpipe/store/schema.sql:31` to `37`, `page_text_transcribed`); their
section text is itself a model reading, one reason their harvested values
can never clear the run's top trust level. An earlier, 801-document
snapshot found 184 plans with multi-column pages, so the profile fixes
`column_layout="auto"` rather than leaving layout detection to guess per
page (`profiles/kwp/profile.py:10` to `14`).

One Excel row is one municipality; several rows can point at the same PDF
when several municipalities plan together as a convoy, so the document is
registered once while every row still contributes its own municipality
and metadata (`profiles/kwp/source.py:1` to `6`). Versioning runs on the
core's own, profile-agnostic machinery: documents sharing a `group_key`
are versions of one work, and within a group the newest `published` date
is `is_current` while every older one points at its predecessor through
`supersedes` (`docpipe/store/documents.py:71` to `102`,
`link_document_versions`). The profile sets `group_key` to the register
key, the AGS (Amtlicher Gemeindeschlüssel), as a string; for a convoy plan
the key is the smallest AGS among the sharing municipalities rather than
any one row's own, because that is a property of the group itself, not of
whichever row happens to come first in that year's sheet, which could
otherwise leave a reordered export's two editions of one plan both marked
current (`profiles/kwp/source.py:97` to `113`, `group_keys_by_filename`).
A separate table, `SHARED_FILE_OWNERS`, overrides that rule for four
filenames where the register pastes one municipality's link into
another's row rather than naming a real convoy; the smallest AGS would
name the wrong owner there. An `OrganisationUnit`, the contracting body a
plan names, is not the versioning key: two plans filed under the same
unit but two different AGS stay two separate documents.

The profile's own tables (`profiles/kwp/schema.sql`) sit beside the
core's `Documents`/`DocumentMeta` split. `OrganisationUnits` holds one row
per contracting body, its name and federal state; `Municipalities` one
row per AGS, its unique key, with its name and `OrganisationUnits` link.
`DocumentMeta`, the core's own per-document seam, carries only
`organisation_unit` and `municipality_ags` here. `MunicipalityMeta`,
keyed by AGS and refreshed on every import rather than versioned, carries
29 fields copied from the KWW sheet (`profiles/kwp/config.py`,
`MUNICIPALITY_META_COLUMNS`): the administrative hierarchy, population
and area, the register's own tracking fields, and the link and date used
to fetch the PDF. A column a thinner KWW export drops is left out of that
import rather than written as null, so a value an earlier, fuller export
stored is never quietly erased (`profiles/kwp/source.py:69` to `77`,
`extract_meta`). `--backfill-meta` reruns only this metadata write,
matched by AGS, for municipalities already registered
(`profiles/kwp/source.py:199` to `217`, `backfill_meta`).

## What the profile contributes to each stage

Every attribute below is one seam `docpipe/` or a script asks a profile
for by name, described in general on [profiles](../profiles.md); this
table gives kwp's own answer.

| Stage | Module | Attribute | Contributes |
|---|---|---|---|
| File processing | `source.py` | `SOURCE`, `backfill_meta` | the KWW register as a `Source`: filtering, convoy grouping, overrides |
| File processing | `schema.sql`, `store.py` | `OrganisationUnits`, `Municipalities`, `DocumentMeta`, `MunicipalityMeta` | the profile's own tables and their upsert helpers |
| Layout detection | `profile.py` | `column_layout` | `"auto"`, a multi-column page read column by column |
| Structure assembly | `preprocessing.py` | `HYPHEN_EXCEPTIONS`, `CAPTION_MAX_WORDS`, `TITLE_EXCLUDE_PREFIXES`, `DIRECTORY_FIGTAB_WORDS`, `BIBLIOGRAPHY_TITLE_WORDS` | German hyphenation, caption length, title and directory rules |
| Preprocessing (page transcription) | `prompts/preprocessing/page_transcribe.md` | one prompt id | reads a page with no text layer, verbatim, into Markdown |
| Refinement | `prompts/refinement/*.md` | `refine`, `refine_corrections`, `split` | repairs German extraction artefacts, proposes section cuts |
| Visuals | `prompts/visuals/*.md` | seven prompt ids | table transcription, figure description and captions, in German |
| The picker (app) | `catalog.py`, `profile.py` | `CATALOG`, `facets` | plan-centric labels, convoy membership, three filters |
| Extraction | `extraction.py` | `SPEC_PATH`, `SLICE`, `FRAME`, `document_context` | the spec, the slice gate, the frame axes |
| Extraction | `prompts/extraction/*.md` | eight prompt ids | phrase, frame, rows, field, anchors, queries, harvest, review |
| The graph | `kg.py` | `make_serializer` and seven more names | MHPKG Turtle, the coordinate query, the trust wording |
| The answer app | `inference.py` | `PHRASES`, `READOFF_MARKER`, `READOFF_NOTE`, `ROUTE_NOTES` | the German chat wording and the graph route's refusal sentences |
| The answer app | `prompts/inference/*.md`, `prompts/kg/coordinate.md` | 15 plus 1 prompt ids | the answer loop's own prompts and the graph route's closed question |

## The extraction spec

`profiles/kwp/extraction_spec.json` names four parameters. Three are
numeric and share one shape: `energy_consumption`, `emission` and
`heat_load`, each a `float` value carrying its own unit family and landing
on a `value` node in the graph. The fourth, `planning_organisation`, is a
`text` value with no unit at all, landing on an `organisation` node.

| parameter | value type | unit family | unit target | accepted spellings |
|---|---|---|---|---|
| `energy_consumption` | `float` | energy (kWh to TWh) | `OEO_00050008` | 12 |
| `emission` | `float` | mass, CO2 equivalent | `OEO_00010137` | 42 |
| `heat_load` | `float` | power (kW to GW) | `OEO_00390001` | 5 |
| `planning_organisation` | `text` | none | none | none |

`heat_load` is split from the two amounts purely by unit family, and the
spec marks it `integrated=False` (`docpipe/extraction/spec.py:181` to
`187`), the one field that tells a rate apart from an amount stated over
a span; the other two numeric parameters leave `integrated` at its
default of true.

All three numeric parameters share the same five non-quantity axes, each
a closed vocabulary except `year`, a plain integer:

| axis | kind | vocabulary size | of which `out:` |
|---|---|---|---|
| `carrier` | vocabulary | 29 | 2 |
| `sector` | vocabulary | 6 | 1 |
| `scenario` | vocabulary | 4 | 1 |
| `spatial_scope` | vocabulary | 2 | 0 |
| `year` | integer | (not applicable) | (not applicable) |

`quantity` and `aggregation`, the two axes that carry a parameter's own
answer space, differ by parameter, and `heat_load` differs from the two
amounts in how its aggregation is decided:

| parameter | `quantity` size (`out:`) | `aggregation` size (`out:`) | `aggregation` derived |
|---|---|---|---|
| `energy_consumption` | 9 (7) | 5 (0) | yes, from the unit |
| `emission` | 9 (7) | 5 (0) | yes, from the unit |
| `heat_load` | 6 (5) | 4 (0) | no, asked |

An axis or a parameter answer beginning `out:` is a deliberate non-class,
not a gap. The convention is the core's: the sentinel a coordinate
carries when a passage genuinely does not state it is `out:unstated`
(`docpipe/extraction/fields.py:37` to `47`), and a profile's own vocabulary
rides the same prefix so a serializer can refuse every one of them by
shape rather than by a second, hand-kept list
(`profiles/kwp/kg.py:93` to `101`, `is_class`). Most of `quantity`'s own
list is such an entry: a potential rather than a delivered amount, a
share expressed as a percentage, a per-person or per-area figure, and a
residual catch-all, so the model can name what a number really is
instead of forcing it onto the nearest real class; `carrier`, `sector`
and `scenario` offer one or two of the same kind each.

Two of the numeric parameters decide their `aggregation` on their own
rather than asking, carried as the `derived` state
(`docpipe/extraction/fields.py:67` to `74`; [glossary](../glossary.md)):
every unit `energy_consumption` or `emission` accepts names a span, so
their aggregation is always the closed list's integral entry, never asked
(`docpipe/extraction/spec.py:144` to `154`, `Axis.derive`). Before this was
derived, all 452 aggregation answers the model gave for these two
parameters over one plan were that same entry every time, evidenced
only by the unit string the request had itself just handed over
(`docpipe/extraction/spec.py:149` to `153`). `heat_load`'s aggregation is
not derived, since a watt is not integrated over a span the way a
watt-hour is: this axis is asked instead, with evidence allowed one page
away, and a peak load can come back distinct from an average one.

The frame is the pair of coordinates found once per document rather than
once per row: `FRAME = ("scenario", "year")`
(`profiles/kwp/extraction.py:73`). A plan states its scenario containers
and its reference years in headings and column headers, not inside every
cell, so the run reads that pair first and projects every combination it
found onto the rows that follow, rather than asking each row to name its
own scenario and year again; not a cross product, since a plan with a
target scenario for four years and one inventory year contributes five
pairs, not twenty (`profiles/kwp/extraction.py:60` to `72`). Before the
frame existed, the year axis alone produced 1,849 refusals against zero
readings, because every retrieval window after the first excluded the one
source that could carry the year.

`FRAME_DEFAULT = {"scenario": "status_quo"}` (`profiles/kwp/extraction.py:80`)
is the pair a passage is read under when it names no part of any pair the
frame found, neither a scenario nor a year: an inventory table that never
states either. It is used only when a document has exactly one such pair,
an owner decision made after Kassel's Tabelle 3 (CO2 by sector and carrier,
no year anywhere) left 35 values without one.

The slice gate decides, before any other coordinate is asked, whether a
row belongs in this run's graph at all: `SLICE = {"quantity": None}`
(`profiles/kwp/extraction.py:28`). `None` means any real class the graph
takes, every entry that does not begin `out:`. Asking this axis first and
alone is cheaper when a row fails it, three requests spent rather than
eight, and on a 20-plan draft it dropped 1,554 of 6,763 harvested tuples
for a quantity the graph does not hold. Scenario used to gate too, the
larger half of that loss: 2,510 of the 6,763 were dropped for being a
status quo, a trend or a potential reading rather than the target
scenario, a decision about what the graph could hold rather than what
the plan said. The gate
no longer includes scenario, because the ontology names all three plan
parts and the graph now serializes all three
(`profiles/kwp/extraction.py:7` to `24`; see
[The knowledge graph](#the-knowledge-graph)).

Every question a run asks carries its own fingerprint, so a resumed run
can tell exactly which question changed rather than treating the whole
spec as one block (`docpipe/extraction/spec.py:618` to `640`,
`fingerprints`): one key for the parameter-choice question itself, one per
parameter for its own question, unit list and worked example, one per
category parameter for its closed list of spellings and definitions, and
one per axis for its question, type, derive rule and vocabulary. These are what the extraction stamp compares on a rerun,
described in full on [extraction](../stages/extraction.md).

Every parameter, axis and spelling this spec states today is published
at [contract/kwp.md](../contract/kwp.md); the table below is built from
that same file.

## The prompts

Nine prompt ids belong to extraction and the graph route, kwp's own
wording of each spec question:

| id | loaded | asks for |
|---|---|---|
| `extraction/phrase` | once per document, before any row | the one sentence this document is searched with |
| `extraction/frame` | once per document, before any row | which scenario and year pairs the plan actually carries |
| `extraction/anchors` | once per run, per question the field sweep asks | six hypothetical sentences a passage stating this coordinate could read |
| `extraction/queries` | once per run, as a plain template list | one retrieval query template per parameter or per vocabulary entry |
| `extraction/rows` | per retrieved window, the default field-wise contract | which values a passage states, without their coordinates |
| `extraction/field` | once per row per coordinate, the field-wise contract | one axis's own answer, from its closed list or its type |
| `extraction/harvest` | per retrieved window, only when `EXTRACT_FIELDWISE=0` | a whole tuple at once, coordinates included |
| `extraction/review` | only under `--review`; excluded from the extraction stamp | a second reading of one value, over a window narrowed to its own passage and the section it stands in |
| `kg/coordinate` | once per chat turn the graph route tries | one closed answer to one coordinate axis, for the SPARQL query |

`extraction/rows` and `extraction/field` are the field-wise pair that
replaces the whole-tuple `extraction/harvest` request by default
(`EXTRACT_FIELDWISE` defaults to on, `docpipe/extraction/runner.py:154`):
one call finds which values a passage states, a second asks each
coordinate as its own question. `extraction/review` is deliberately
outside the set the extraction stamp hashes, because a review only ever
adds a flag and never changes a value, so folding its prompt into the
stamp would report an entire corpus stale the day it is edited.

The profile also carries the full prompt set every other stage's own code
asks for by id: one for preprocessing's page transcription, three for
refinement, seven for visuals (a system and a user prompt each for
tables and figures, plus three caption variants), and fifteen for the
answer app, bound as module-level constants when `docpipe.inference.llm_client`
is imported (`docpipe/inference/llm_client.py:49` to `78`, `265`,
`432` to `436`). `test_a_profile_provides_every_prompt_the_core_loads` and
`test_a_profile_carries_no_prompt_nobody_loads`
(`tests/test_architecture.py`) hold this set to what the core actually
asks for by name, in both directions.

## The knowledge graph

`profiles/kwp/kg.py` turns an accepted harvest into MHPKG Turtle, the
target graph on the Open Energy Platform. Five namespaces are declared
once, `rdfs`, `xsd`, `obo`, `mhpo` and `oeo`
(`profiles/kwp/kg.py:38` to `44`), and every identifier the serializer
writes is qualified against exactly that header; a predicate whose prefix
the header does not bind raises rather than silently writing Turtle
nobody can load (`kg_name`, `docpipe/extraction/spec.py:646` to `662`).
The full mechanism is on [stages/graph.md](../stages/graph.md); this
section names what is specific to kwp's own graph.

| node | class | minted from |
|---|---|---|
| heat plan | `mhpo:MHPO_00020003` | AGS plus publication date, not from any harvested row |
| municipality | `mhpo:MHPO_00020017` | AGS alone |
| a scenario part (status quo, trend, target) | one of three MHPO classes, from the spec's own scenario map | AGS, publication date and the part's own path segment |
| value | the row's own `quantity` class (`a oeo:<quantity>`) | the value identity tuple, below |
| planning organisation | `oeo:OEO_00030022` | the normalised office name |
| a named sub area | the spec's plan-area class | AGS plus the normalised area wording |
| year | the spec's year class | the calendar year itself, not minted |

The plan node carries its publication date, its planning-organisation
edges, and a `has part` edge to every scenario part with a surviving
value; each part node carries a `has quantity value` edge to every value
node under it. A value node's carrier, sector and year all ride one
shared predicate, `obo:IAO_0000136 is about`, the one predicate this
graph's header binds that declares no `rdfs:range`; nine carrier classes
the plans name constantly sit outside OEO's `energy carrier` root for
genuine ontological reasons, and reaching them through a range-bound
predicate instead once cost 51 of 244 value nodes their carrier edge in
the kwp pilot (`tests/test_kwp_extraction.py`,
`test_a_carrier_oeo_does_not_call_a_carrier_keeps_its_edge_and_is_counted`).
A named sub area is linked `part of` the municipality.

The IRI base is `https://openenergyplatform.org/id/mhpkg/`
(`profiles/kwp/kg.py:32`). Every minted collection draws its own UUIDv5
sub-namespace off that base, and minting always uses UUIDv5 over an
identifying name, never UUIDv4 (`profiles/kwp/kg.py:342` to `366`,
`mint`), so two runs over one document produce byte-identical Turtle
(`tests/test_kwp_extraction.py`,
`test_value_minting_matches_the_schema_repo_reference` and
`test_normalise_and_organisation_minting_match_the_reference`). The plan
and municipality nodes are not minted at all: their IRIs are built
directly from the register key, `heatplan/AGS_<ags>_<published>` and
`municipality/AGS_<ags>` (`profiles/kwp/kg.py:426` to `428`, `687`). A
year IRI is likewise unminted, one node per calendar year, keyed by the
year itself (`profiles/kwp/kg.py:332` to `339`).

A value's identity is a UUIDv5 over its own coordinates joined in order:
the scenario part's IRI, the quantity class, the carrier and sector
classes where present, the year, the aggregation, and, only for a named
sub area, the normalised area wording (`profiles/kwp/kg.py:447` to `472`,
`_value_iri`). This departs on purpose from the schema repository's own
published coordinate list, adding the sector, because this corpus carries
several sectors per carrier and year that list would otherwise collide
onto one node (`profiles/kwp/kg.py:4` to `9`). The area is left out of a
whole-plan-area value's identity, since one 2040 figure stated under
three different whole-plan-area wordings on three pages of one plan
became three indistinguishable nodes before this rule, 129 of 1,294 value
nodes overall (`profiles/kwp/kg.py:457` to `460`); a named sub area keeps
its wording, since one plan can carry several sub-area tables whose
figures would otherwise collide onto one node instead.

Above each value node, a block of Turtle comments states where it was
read: the wording and quote, the page and its table, figure or section,
whether the aggregation was read or derived, and a trust line rendered
from the same six marks `docpipe/extraction/trust.py` defines for every
profile, in English here, checked against the core's own list at import
(`check_prose`, `profiles/kwp/kg.py:478` to `486`). Comments only, never
triples: MHPKG's shapes are `sh:closed`, and an unanticipated triple
would invalidate the node it documents (`profiles/kwp/kg.py:496` to
`745`).

What the serializer refuses, briefly (in full on
[stages/graph.md](../stages/graph.md)): a row failing the scenario,
spatial scope, year, quantity or aggregation gate; a document with no
resolvable AGS or date; a second document claiming an already-claimed
AGS and date pair; two rows at one value identity stating different
magnitudes, both dropped; and a deliberate `out:` or unstated carrier or
sector, which writes no class edge though the value node still stands.
Trust levels and their closed reason list are on
[contract/trust.md](../contract/trust.md).

## The chat wording and the graph route

`profiles/kwp/inference.py` supplies the German wording the answer app
wraps around every turn. `PHRASES`, 29 keys matching
`docpipe.inference.wording.REQUIRED` exactly, covers the task and history
headings, JSON parse-error recovery, the code-execution sandbox's own
headings, the image read-off headings, and how a citation names its page,
section, table or figure (`profiles/kwp/inference.py:33` to `78`).
`READOFF_MARKER` and `READOFF_NOTE` mark a value read off a chart image
rather than table text. `make_search_phrase` (see
[inference](../stages/inference.md)) no longer filters the model's anchor
sentence for a refusal or an evaluation; it takes whatever non-empty
phrase the model wrote and falls back to the raw task only on an error or
an empty reply.

`ROUTE_NOTES` words the five reasons `docpipe.inference.kg_route` can give
for not answering from the graph at all: no graph loaded, no plan node for
this document, no coordinate the question named, no matching row, or a
matching row with no trust line (`profiles/kwp/inference.py:10` to `27`),
checked against the core's own five-token list when the app builds its
graph-route hooks at start-up (`docpipe/inference/kg_route.py:52` to `57`,
`80` to `92`).

`kg.py` supplies the other half of what the route needs
(`docpipe/inference/kg_route.py:66` to `78`, the `Hooks` dataclass): a
SPARQL template (`VALUE_QUERY`), the five axes a question may fix, in
order, `(scenario, quantity, carrier, sector, year)`
(`COORDINATE_AXES`, `profiles/kwp/kg.py:831` to `839`), `heatplan_iri`,
`value_bindings`, `label_of`, and the same `TRUST_PROSE` the serializer
writes with. `spatial_scope` is left out because the graph has no edge
yet from a value to its area; `aggregation` is left out because the route
returns it rather than constraining on it, so a peak load and an annual
total can sit in one answer with their own label telling them apart.
Building the hooks loads the `kg/coordinate` prompt once
(`docpipe/inference/kg_route.py:122`).

A chat turn that tries the route resolves the open document to its plan
IRI, asks each coordinate axis as one closed question through
`kg/coordinate`, and queries the graph only once one of three deciding
axes, quantity, scenario or year, has an answer: a carrier alone would
name every reading of every year (`docpipe/inference/kg_route.py:61`,
`275` to `276`). An answer outside the spec's own list leaves that axis
unbound rather than guessed at (`to_coordinates`,
`docpipe/inference/kg_route.py:174` to `204`). The result is a graph
answer, each value carrying its own evidence and trust line, or a
fallback naming which reason applied, cheapest checked first: no plan
costs one SQLite read, no coordinates the closed questions themselves, no
rows one SPARQL query (`answer_from_graph`,
`docpipe/inference/kg_route.py:260` to `293`).
The answer app does not offer this route while no corpus graph exists
(`scripts/inference_app/app.py:347` to `349`, see
[app](../stages/app.md)).

## Verification

Versioning and the picker:
`tests/test_kwp_source.py`'s `test_a_convoy_is_grouped_by_its_smallest_ags`,
`test_the_row_order_does_not_decide_the_group`,
`test_a_new_edition_of_a_convoy_shares_the_group_of_the_old_one` and
`test_the_override_filename_decides_the_grouping` hold the AGS-keyed
grouping to what this page describes; `tests/test_kwp_catalog.py`'s
`test_the_register_decides_who_a_convoy_covers` and
`test_a_pasted_link_does_not_hand_a_plan_to_another_municipality` hold the
picker's own reading of the same register.

Loading and the seams:
`tests/test_profile.py`'s `test_kwp_profile_loads_and_names_itself`;
`tests/test_every_profile_loads.py`'s `test_a_profile_loads_every_config_module`
and `test_a_profile_states_a_usable_context_budget`; and
`tests/test_architecture.py`'s
`test_a_profile_provides_every_component_the_core_requires`, parametrized
over every shipped profile including `kwp`.

The extraction spec:
`tests/test_kwp_extraction.py`'s
`test_every_example_verifies_against_its_own_source`,
`test_the_examples_teach_exhaustive_extraction`,
`test_query_templates_expand_for_every_parameter`,
`test_a_power_is_its_own_parameter_split_by_unit_family`,
`test_the_power_class_is_the_one_the_unit_implies`,
`test_the_aggregation_of_a_power_is_asked_and_not_derived`,
`test_instantaneous_is_not_offered_for_a_power`,
`test_the_units_of_the_two_numeric_parameters_share_no_spelling`,
`test_the_two_quantity_questions_are_not_the_same_text` and
`test_where_a_coordinates_passage_stands_is_no_warning`.

The graph:
`test_value_minting_matches_the_schema_repo_reference`,
`test_one_heat_plan_comes_out_as_the_published_example`,
`test_every_plan_part_the_ontology_names_is_serialized`,
`test_a_value_conflict_on_one_coordinate_drops_every_claimant` and
`test_a_second_document_claiming_the_same_identity_is_refused`, the full
account on [stages/graph.md](../stages/graph.md).

The ontology snapshot:
`tests/test_kwp_vocabulary.py`'s
`test_the_snapshot_names_the_ontology_it_was_built_from`,
`test_the_spec_passes_the_pinned_ontology` and
`test_a_spec_the_ontology_disagrees_with_is_named`.

The graph route:
`tests/test_kg_route.py`'s `test_the_answer_space_is_the_specs_own_list`,
`test_a_synonym_resolves_through_the_axis_not_by_string_match`,
`test_unstated_leaves_the_axis_unbound`,
`test_an_out_class_is_never_bound_as_a_coordinate`,
`test_every_reason_the_route_gives_is_reached`,
`test_every_fallback_reason_has_a_sentence` and
`test_a_route_note_nobody_worded_stops_the_route_being_built`.
