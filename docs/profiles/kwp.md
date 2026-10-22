# The kwp profile

## The corpus and its database

`kwp` covers Kommunale Wärmeplanung: heat plans German municipalities
publish under the federal Wärmeplanungsgesetz, sourced from the KWW
register, an Excel sheet the source module filters to rows marked
"abgeschlossen" (completed) that carry a usable PDF link
(`profiles/kwp/source.py:34` to `44`, `load_and_filter_excel`). The corpus
stands at 1,082 documents (`docpipe/extraction/trust.py:234`,
`docpipe/extraction/remap.py:6`). Eleven carry no PDF text layer and are
read page by page by a vision model instead
(`docpipe/store/schema.sql:31` to `37`, `page_text_transcribed`); their
section text is itself a model reading, one reason their harvested values
can never clear the run's top trust level. An earlier, 801-document
snapshot found 184 plans with multi-column pages, so the profile fixes
`column_layout="auto"` rather than leaving layout detection to guess per
page (`profiles/kwp/profile.py:15` to `19`).

One Excel row is one municipality; several rows can point at the same PDF
when several municipalities plan together as a convoy, so the document is
registered once while every row still contributes its own municipality
and metadata (`profiles/kwp/source.py:4` to `6`, the module docstring).
Versioning runs on the
core's own, profile-agnostic machinery: documents sharing a `group_key`
are versions of one work, and within a group the newest `published` date
is `is_current` while every older one points at its predecessor through
`supersedes` (`docpipe/store/documents.py:101` to `132`,
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
| Structure assembly | `preprocessing.py` | `HYPHEN_EXCEPTIONS`, `CAPTION_MAX_WORDS`, `CAPTION_START`, `TITLE_EXCLUDE_PREFIXES`, `DIRECTORY_FIGTAB_WORDS`, `DIRECTORY_TITLE_WORDS`, `BIBLIOGRAPHY_TITLE_WORDS` | German hyphenation, caption length, what opens a caption (a word, a number and a colon, as `Tabelle 17:`), title and directory rules (the title words of a table of contents are the profile's: "inhalt", "verzeichnis", "contents", "directory") |
| Preprocessing (page transcription) | `prompts/preprocessing/page_transcribe.md` | one prompt id | reads a page with no text layer, verbatim, into Markdown |
| Refinement | `prompts/refinement/*.md` | `refine`, `refine_corrections`, `split` | repairs German extraction artefacts, proposes section cuts |
| Visuals | `prompts/visuals/*.md` | six prompt ids of its own | table transcription, figure description and captions, in German; `visuals/caption_keep` is the built-in profile's, inherited byte for byte |
| Refinement, visuals, page transcription, the answer app | `reading.py` | `PHRASES` | the ten sentences these stages and the chat say to the model when its reply was not the one JSON object, in English like the prompts of the first three (`reading.REQUIRED`), laid over the built-in profile's |
| The picker (app) | `catalog.py`, `profile.py` | `CATALOG`, `facets` | plan-centric labels, convoy membership, three filters |
| Extraction | `extraction.py` | `SPEC_PATH`, `SLICE`, `FRAME`, `BASE_YEAR`, `TARGET_YEAR`, `document_context`, `PHRASES`, `PROMPT_CHECKS`, `ALT_LABEL_LANGUAGE`, `CONTRACT_LANGUAGE` | the spec, the slice gate, the frame axes, the frame pairs that are the plan's own state and its target, the German sentences the stage writes to the model (the frame request's list of a closed coordinate stands under `"scenarios"`), the passages the preflight holds its prompts to, and the language (`"de"`) of the core's templates its parts files are put together with |
| Extraction | `prompts/extraction/*.md` | nine prompt ids | phrase, anchors and queries as plain files; frame, rows, field, review and example as parts files that name a template of the core (see The prompts) |
| The graph | `kg.py` | `make_serializer` and seven more names | MHPKG Turtle, the coordinate query, the trust wording |
| The answer app | `inference.py` | `PHRASES`, `READOFF_MARKER`, `READOFF_NOTE`, `ROUTE_NOTES` | the German chat wording and the graph route's refusal sentences |
| The answer app | `prompts/inference/*.md`, `prompts/kg/coordinate.md` | 10 plus 1 prompt ids | the answer loop's own prompts and the graph route's closed question |

## The extraction spec

`profiles/kwp/extraction_spec.json` names five parameters. Four are
numeric and share one shape: `energy_consumption`, `emission`, `heat_load`
and `share`, each a `float` value carrying its own unit family and landing
on a `value` node in the graph. The fourth, `planning_organisation`, is a
`text` value with no unit at all, landing on an `organisation` node.

| parameter | value type | unit family | unit target | accepted spellings |
|---|---|---|---|---|
| `energy_consumption` | `float` | energy (kWh to TWh) | `OEO_00050008` | 12 |
| `emission` | `float` | mass, CO2 equivalent | `OEO_00010137` | 48 |
| `heat_load` | `float` | power (kW to GW) | `OEO_00390001` | 5 |
| `share` | `float` | percent | `UO_0000187` | 2 |
| `planning_organisation` | `text` | none | none | none |

`heat_load` is split from the two amounts purely by unit family, and `share`
(Anteil, a part of a whole in percent, `fraction value` as its one class) by
the percent sign; the spec marks both `integrated=False` (`docpipe/extraction/spec.py:131` to
`137`), the flag that tells a rate apart from an amount stated over
a span; the other two numeric parameters leave `integrated` at its
default of true. An integrated parameter's units each say whether they name a
period, `names_period`, and the loader refuses an entry that does not say
(`spec._validate_unit_entry`): of the 12 entries of `energy_consumption` and the
48 of `emission`, 34 say true ("kWh/a") and 26 say false ("kWh"), and the five
of `heat_load` stay bare factors. The verifier flags `period:unstated` from that
statement alone, and it reaches no request and no stamp key, so changing one
costs no re-read.

All four numeric parameters share these five non-quantity axes, each
a closed vocabulary except `year`, a plain integer:

| axis | kind | vocabulary size | of which `out:` |
|---|---|---|---|
| `carrier` | vocabulary | 29 | 2 |
| `sector` | vocabulary | 6 | 1 |
| `scenario` | vocabulary | 4 | 1 |
| `spatial_scope` | vocabulary | 2 | 0 |
| `year` | integer | (not applicable) | (not applicable) |

`energy_consumption`, `emission` and `share` have a sixth, `technology`, a
heat generation technology class (10 entries, 2 of them `out:`); the data
schema leaves it optional, so it is read from the value's own passage alone
and a number the plan does not split by technology is `out:total` and writes
no edge.

`quantity` and `aggregation`, the two axes that carry a parameter's own
answer space, differ by parameter, and `heat_load` differs from the two
amounts in how its aggregation is decided:

| parameter | `quantity` size (`out:`) | `aggregation` size (`out:`) | `aggregation` derived |
|---|---|---|---|
| `energy_consumption` | 9 (7) | 5 (0) | yes, from the unit |
| `emission` | 9 (7) | 5 (0) | yes, from the unit |
| `heat_load` | 6 (5) | 4 (0) | no, asked |
| `share` | 2 (1) | none | no axis |

An axis or a parameter answer beginning `out:` is a deliberate non-class,
not a gap. The convention is the core's: the sentinel a coordinate
carries when a passage genuinely does not state it is `out:unstated`
(`docpipe/extraction/fields.py:38` to `48`), and a profile's own vocabulary
rides the same prefix so a serializer can refuse every one of them by
shape rather than by a second, hand-kept list
(`profiles/kwp/kg.py:95` to `104`, `is_class`). Most of `quantity`'s own
list is such an entry: a potential rather than a delivered amount, a
share expressed as a percentage, a per-person or per-area figure, and a
residual catch-all, so the model can name what a number really is
instead of forcing it onto the nearest real class; `carrier`, `sector`
and `scenario` offer one or two of the same kind each.

`out:total` of `carrier` and `sector` is a number that holds for all entries
together: explicitly summed, or not split by that list in its own table or
sentence. A table split only by building type, say, has no carrier column, and
its numbers are read `out:total` for the carrier; the same holds for the sector
of a table without a sector column, which is not `out:unstated`. The model answers "Summe", quotes the header row or the title of the
table (the sentence itself, for a sentence), and `value_raw` is the word of that
quote it is split by instead, "Gebäudetyp" for example. The owner's two checks
are the only ones, as for every answer: the quote stands in a shown passage and
the wording in the quote. The questions of both axes say so and point to
`known` for what the number already is.

Two of the numeric parameters decide their `aggregation` on their own
rather than asking, carried as the `derived` state
(`docpipe/extraction/fields.py:68` to `75`; [glossary](../glossary.md)):
every unit `energy_consumption` or `emission` accepts names a span, so
their aggregation is always the closed list's integral entry, never asked
(`docpipe/extraction/spec.py:94` to `104`, `Axis.derive`). Before this was
derived, all 452 aggregation answers the model gave for these two
parameters over one plan were that same entry every time, evidenced
only by the unit string the request had itself just handed over
(`docpipe/extraction/spec.py:99` to `101`). `heat_load`'s aggregation is
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

A passage that prints no pair at all is read without one, and its year is
asked per row against the section it stands in. There used to be a
`FRAME_DEFAULT` for this case, the pair such a passage was read under, after
Kassel's Tabelle 3 (CO2 by sector and carrier, no year anywhere) left 35
values without a year. It is gone. It fired only when exactly one pair of the
document matched it, which held for 14 percent of plans and never once in the
corpus_m5 run, 0 of 638 planning calls: a plan states its inventory for one
base year and mentions a handful of others, so several pairs matched and the
branch stood down. More than the count, it wrote a year that does not stand in
the passage, and every value of this corpus says in the plan what it refers
to. Where it says so is the section around the table, which is the first
window the field sweep reads.

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
spec as one block (`docpipe/extraction/spec.py:649` to `674`,
`fingerprints`): one key for the parameter-choice question itself, one
for the unit-choice question and the entries it offers, one per
parameter for its own question, unit list and worked example, one per
category parameter for its closed list of spellings and definitions, and
one per axis for its question, type, derive rule and vocabulary. These are what the extraction stamp compares on a rerun,
described in full on [extraction](../stages/extraction.md).

Every parameter, axis and spelling this spec states today is published
at [contract/kwp.md](../contract/kwp.md); the table below is built from
that same file.

## The prompts

Ten prompt ids belong to extraction and the graph route, kwp's own
wording of each spec question:

| id | loaded | asks for |
|---|---|---|
| `extraction/phrase` | once per document, before any row | the one sentence this document is searched with |
| `extraction/places` | once per document, at its first search | which passages answer which parameters and axes, with a quote and no value; the map the search then reads from |
| `extraction/frame` | once per document, before any row | which scenario and year pairs the plan actually carries |
| `extraction/anchors` | once per run, per question the field sweep asks | six hypothetical sentences a passage stating this coordinate could read |
| `extraction/queries` | once per run, as a plain template list | one retrieval query template per parameter or per vocabulary entry |
| `extraction/rows` | per retrieved window | which values a passage states, without their coordinates |
| `extraction/field` | once per row per coordinate | one axis's own answer, from its closed list or its type |
| `extraction/review` | only under `--review`; excluded from the extraction stamp | a second reading of one value, over a window narrowed to its own passage and the section it stands in |
| `extraction/example` | only under `docpipe compile examples` | which values of one parameter a passage states, to propose the example a spec parameter still lacks |
| `kg/coordinate` | once per chat turn the graph route tries | one closed answer to one coordinate axis, for the SPARQL query |

Five of these ids, `extraction/rows`, `field`, `frame`, `review` and `example`,
are parts files (see [profiles](../profiles.md), The extraction prompts). Each
names its template of the core in its front matter, and
`CONTRACT_LANGUAGE = "de"` in `profiles/kwp/extraction.py` says that the
templates are the German ones. What kwp writes itself is its role (German
municipal heat plans), its examples and the sentences about its own tables. It
words three blocks itself, where the template's sentence fits it less well:
`value_text` of the rows prompt (for a text field, the designation as the plan
writes it, without its legal form), `rows_more` of the field prompt (the rows
carry `known`, the plan's wording of what the row has already been read for,
and `title`, that of its own table or section; the question is about exactly
this number) and `closed_out_text` of the field prompt
(the entries of a closed list that are expressly the opposite of a class, with
kwp's own examples: a sum row or a number the list does not split, a remainder, an expressly unknown value, a
percentage share, a potential). It leaves out the blocks of the templates it
never had a sentence for: 14 blocks of the rows prompt, `rows_source`,
`same_forms`, `by_similarity` and `domain_slot_2` of the field prompt, and
`corpus_language` of the review prompt. The frame and the example prompt leave
out and word nothing. `python scripts/render_prompts.py --what-if` shows each
block it leaves out put back (see [Running the pipeline](../running.md)).

The passages inside the examples of the field prompt are not sentences a plan
could print. Each is a description between `<<` and `>>`, for example
`"quote": "<<Titel der eigenen Tabelle, wörtlich, mit „Ist-Zustand 2022“
darin>>"`, and the prompt says once that such a string describes a place and
is never copied (owner decision 2026-10-06). Measured on the current kwp
harvest, 48,737 dropped answers cited an example sentence of the prompt word
for word as their quote.

`extraction/rows` and `extraction/field` are the pair every value is
read with: one call finds which values a passage states, a second asks
each coordinate as its own question. `extraction/review` is deliberately
outside the set the extraction stamp hashes, because a review only ever
adds a flag and never changes a value, so folding its prompt into the
stamp would report an entire corpus stale the day it is edited.

The profile also carries the full prompt set every other stage's own code
asks for by id: one for preprocessing's page transcription, three for
refinement, seven for visuals (a system and a user prompt each for
tables and figures, plus three caption variants, of which `caption_keep` is
the built-in profile's, inherited byte for byte), and ten for the
answer app, named in one table in `docpipe.inference.llm_client` and read when
first used, under the names they had as module constants
(`docpipe/inference/llm_client.py:66` to `77`, `82` to `103`).

## The knowledge graph

`profiles/kwp/kg.py` turns an accepted harvest into MHPKG Turtle, the
target graph on the Open Energy Platform. It takes its terms from the MHPKG
LinkML data schema (`mhpkg/schema/mhpkg_target_scenario.yaml` of the OEKG
repository): `python -m profiles.kwp.vocabulary --refresh` pulls it each time
into `profiles/kwp/mhpkg_schema.yaml` beside the OEO and MHPO snapshots, the
spec's `kg` blocks name `schema_slot` and `schema_class` instead of a prefix
and predicate, and `profiles/kwp/mhpkg.py` resolves them. A schema term the
pinned OEO or MHPO lacks is written as the schema says and printed by the
vocabulary check as `note mhpkg:`, never a failure. Five namespaces are declared
once, `rdfs`, `xsd`, `obo`, `mhpo` and `oeo`
(`profiles/kwp/kg.py:49` to `55`), and every identifier the serializer
writes is qualified against exactly that header; a predicate whose prefix
the header does not bind raises rather than silently writing Turtle
nobody can load (`kg_name`, `docpipe/extraction/spec.py:683` to `700`).
The full mechanism is on [stages/graph.md](../stages/graph.md); this
section names what is specific to kwp's own graph.

| node | class | minted from |
|---|---|---|
| heat plan | `mhpo:MHPO_00020003` | AGS plus publication date, not from any harvested row |
| municipality | `mhpo:MHPO_00020017` | AGS alone |
| a scenario part (status quo, trend, target) | one of three MHPO classes, from the spec's own scenario map | AGS, publication date and the part's own path segment |
| value | the row's own `quantity` class (`a oeo:<quantity>`); in the strict graph also the schema's value class it falls under | the value identity tuple, below |
| planning organisation | `oeo:OEO_00030022` | the normalised office name |
| a named sub area | the spec's plan-area class | AGS plus the normalised area wording |

The plan node carries its publication date, its planning-organisation
edges, and a `has part` edge to every scenario part with a surviving
value; each part node carries a `has quantity value` edge to every value
node under it. A value node's carrier, sector and technology ride the
schema's own slots (`refers to energy carrier`, `refers to sector`,
`refers to technology`), its year an `xsd:integer` literal on
`has scenario year value`; there are no year nodes. Nine carrier classes
the plans name constantly sit outside OEO's `energy carrier` root for
genuine ontological reasons; they are written all the same and counted. A
number the plan does not split by sector (`out:total`) is written as the
schema's parent energy demand sector, `OEO_00000128`; a total carrier or
technology writes no edge.
A named sub area is linked `part of` the municipality. An organisation
node is written once per run, with the first spelling in harvest
order, even when a later plan in the same run spells the office
differently: a run-level `labelled` set in `make_serializer` keeps a
second `rdfs:label` off the shared node (`profiles/kwp/kg.py:745` to
`750`, `944` to `946`).

The IRI base is `https://openenergyplatform.org/id/mhpkg/`
(`profiles/kwp/kg.py:36`). Every minted collection draws its own UUIDv5
sub-namespace off that base, and minting always uses UUIDv5 over an
identifying name, never UUIDv4 (`profiles/kwp/kg.py:369` to `372`,
`mint`), so two runs over one document produce byte-identical Turtle. The plan
and municipality nodes are not minted at all: their IRIs are built
directly from the register key, `heatplan/AGS_<ags>_<published>` and
`municipality/AGS_<ags>` (`profiles/kwp/kg.py:431` to `433`, `834`). The
inventory part's path segment is `inventoryanalysis`.

A value's identity is a UUIDv5 over its own coordinates joined in order:
the scenario part's IRI, the quantity class, the carrier and sector
classes where they are real OEO classes (`is_class`; a deliberate
`out:` answer or an unmapped wording is left out exactly like an
absent one), the year, the aggregation, and, only for a named sub area,
the normalised area wording (`profiles/kwp/kg.py:452` to `482`,
`_value_iri`). These are the same seven coordinates the schema
repository's own `mint_slice.py` mints: part, quantity, carrier, sector,
year, aggregation and the sub-area, so two runs over one document mint
byte-identical IRIs with no deviation from the published list, which
`mint_slice.py` must apply the same carrier and sector rule to keep
matching (`profiles/kwp/kg.py:6` to `8`, `448` to `452`). The area is left out of a
whole-plan-area value's identity, since one 2040 figure stated under
three different whole-plan-area wordings on three pages of one plan
became three indistinguishable nodes before this rule, 129 of 1,294 value
nodes overall (`profiles/kwp/kg.py:462` to `470`); a named sub area keeps
its wording, since one plan can carry several sub-area tables whose
figures would otherwise collide onto one node instead.

Above each value node, a block of Turtle comments states where it was
read: the wording and quote, the page and its table, figure or section,
whether the aggregation was read or derived, and a trust line rendered
from the same six marks `docpipe/extraction/trust.py` defines for every
profile, in English here, checked against the core's own list at import
(`check_prose`, `profiles/kwp/kg.py:587` to `594`). Comments only, never
triples: MHPKG's shapes are `sh:closed`, and an unanticipated triple
would invalidate the node it documents (`evidence_comment`,
`profiles/kwp/kg.py:645` to `718`).

Each serialize call writes two graphs. `<graph>.ttl` holds everything that
was read, in our classes. `<graph>.strict.ttl` (the profile's
`make_strict_serializer`) holds only the values the data schema takes: a
class the part holds, every required slot, and carrier, sector and technology
from the schema's own lists; a plan with no target-scenario value is left
out. Each refusal is counted as `mhpkg:<reason>` (`class`, `area`,
`no_slot:<slot>`, `missing:<slot>`, `off_list:<slot>`). Both files are
SHACL-validated against the refreshed shapes.

What the serializer refuses, briefly (in full on
[stages/graph.md](../stages/graph.md)): a row failing the quantity,
scenario, spatial scope, year or aggregation gate, quantity checked
first so a row closed on it is never counted against the scenario too;
a document with no resolvable AGS or date; a second document claiming
an already-claimed AGS and date pair; several rows at one value
identity settled by the plan's own wording, by rounding, or by trust
level, only what none of those settles still dropping every claimant;
and a deliberate `out:` or unmapped carrier or sector, which enters
neither the value's identity nor its edge, though the value node still
stands. Trust levels and their closed reason list are on
[contract/trust.md](../contract/trust.md).

## The chat wording and the graph route

`profiles/kwp/inference.py` supplies the German wording the answer app
wraps around every turn. `PHRASES`, 30 keys matching
`docpipe.inference.wording.REQUIRED` exactly, covers the task and history
headings, the code-execution sandbox's own headings, the image read-off
headings, and how a citation names its page, section, table or figure
(`profiles/kwp/inference.py:33` to `80`).
`READOFF_MARKER` and `READOFF_NOTE` mark a value read off a chart image
rather than table text. `make_search_phrase` (see
[inference](../stages/inference.md)) no longer filters the model's anchor
sentence for a refusal or an evaluation; it takes whatever non-empty
phrase the model wrote and falls back to the raw task only on an error or
an empty reply.

What the chat says to the model when a reply was not the one JSON object it asked
for is not in that table. It is `profiles/kwp/reading.py`, `PHRASES`, the ten
sentences of `docpipe.reading.REQUIRED` that refinement, the visuals stage and
page transcription use as well: what was wrong with the reply (no object, text
beside it, a syntax error at a character, a missing key) and the shape that was
asked for. They are English, because the instructions of those stages are
English in this profile and only what the model reads off a German page is
German; so the correction the chat appends to a request is English although its
prompts and its answers are German. The table is laid over the built-in
profile's entry by entry (`profile.layers("reading", "PHRASES")`).

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
(`COORDINATE_AXES`, `profiles/kwp/kg.py:996` to `1003`), `heatplan_iri`,
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
`docpipe/inference/kg_route.py:174` to `216`). The result is a graph
answer, each value carrying its own evidence and trust line, or a
fallback naming which reason applied, cheapest checked first: no plan
costs one SQLite read, no coordinates the closed questions themselves, no
rows one SPARQL query (`answer_from_graph`,
`docpipe/inference/kg_route.py:272` to `305`).
The answer app does not offer this route while no corpus graph exists
(`docpipe/app/app.py`, see [app](../stages/app.md)).

## The parameters, from the published contract

Read from `profiles/kwp/extraction_schema.json` by `scripts/build_docs.py`. Each row is one record kind of the harvest; an axis is a coordinate of that record, with the kind of answer it takes. The full contract, every question and every option, is on [contract/kwp.md](../contract/kwp.md).

| parameter | value | axes | graph node |
|---|---|---|---|
| `emission` | number | `aggregation` (5 options), `carrier` (29 options), `parameter` (one of the spec's parameters), `quantity` (9 options), `scenario` (4 options), `sector` (6 options), `spatial_scope` (2 options), `technology` (10 options), `unit` (48 options), `year` (integer) | `value` |
| `energy_consumption` | number | `aggregation` (5 options), `carrier` (29 options), `parameter` (one of the spec's parameters), `quantity` (9 options), `scenario` (4 options), `sector` (6 options), `spatial_scope` (2 options), `technology` (10 options), `unit` (12 options), `year` (integer) | `value` |
| `heat_load` | number | `aggregation` (4 options), `carrier` (29 options), `parameter` (one of the spec's parameters), `quantity` (6 options), `scenario` (4 options), `sector` (6 options), `spatial_scope` (2 options), `unit` (5 options), `year` (integer) | `value` |
| `planning_organisation` | string | `parameter` (one of the spec's parameters) | `organisation` |
| `share` | number | `carrier` (29 options), `parameter` (one of the spec's parameters), `quantity` (2 options), `scenario` (4 options), `sector` (6 options), `spatial_scope` (2 options), `technology` (10 options), `unit` (2 options), `year` (integer) | `value` |

[Back to the index](../README.md)
