## The corpus and its database

`kwp` covers Kommunale Wärmeplanung: heat plans German municipalities
publish under the federal Wärmeplanungsgesetz, sourced from the KWW
register, an Excel sheet the source module filters to rows marked
"abgeschlossen" (completed) that carry a usable PDF link
(`profiles/kwp/source.py:34` to `44`, `load_and_filter_excel`). The corpus
stands at 1,082 documents (`docpipe/extraction/trust.py:248`,
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
| Refinement, visuals, page transcription, the answer app | `prompts/reading/phrases.json` | ten sentences | the ten sentences these stages and the chat say to the model when its reply was not the one JSON object, in English like the prompts of the first three (`reading.REQUIRED`), laid over the built-in profile's |
| The picker (app) | `catalog.py`, `profile.py` | `CATALOG`, `facets` | plan-centric labels and names (a name opens each line of the values index), convoy membership, three filters |
| Extraction | `extraction.py` | `SPEC_PATH`, `FRAME`, `SPAN_MARKS`, `document_context`, `PROMPT_CHECKS` (empty), `ALT_LABEL_LANGUAGE`, `CONTRACT_LANGUAGE` | the spec (its `plan_fields` block holds what a plan settles for all its values and its own years: its settings, base year and target year, each a name, a meaning and a search sentence, the two years with `of`, the pairs of the frame that are the plan's own state and its target), the frame axes, the marks a value stated for a span of years takes on each of its rows (`out:approximate`), and the language (`"de"`) of the core's templates its parts files are put together with |
| Extraction | `prompts/extraction/phrases.json` | 55 sentences | the German sentences the stage writes to the model outside its prompts (the list of a closed coordinate in a refused pair stands under `"scenarios"`), laid over the built-in profile's |
| Extraction | `prompts/extraction/*.md` | 13 prompt ids | phrase and anchors as plain files; review and example as parts files that name a template of the core; `compute`; and the eight prompts of the harvest, `transcribe`, `find`, `docfield`, `coord`, `search`, `list`, `check` and `follow` (see The prompts) |
| The graph | `kg.py` | `make_serializer` and seven more names | MHPKG Turtle, the coordinate query, the trust wording |
| The answer app | `inference.py` | `READOFF_MARKER`, `READOFF_NOTE`, `ROUTE_NOTES` | the marker of a value read off a chart and the graph route's refusal sentences |
| The answer app | `prompts/inference/phrases.json` | 32 sentences | the German chat wording |
| The answer app | `prompts/inference/*.md`, `prompts/kg/coordinate.md` | 12 plus 1 prompt ids | the answer loop's own prompts and the graph route's closed question |

## The extraction spec

`profiles/kwp/extraction_spec.json` names six parameters. Five are
numeric and share one shape: `energy_consumption`, `emission`, `heat_load`,
`share` and `building_count`, each a `float` value carrying its own unit
family and landing on a `value` node in the graph. The last,
`planning_organisation`, is a `text` value with no unit at all, landing on an
`organisation` node, or, where its one axis `role` says the organisation is the
plan's own municipality, on that municipality's node (see
[The knowledge graph](#the-knowledge-graph)).

| parameter | value type | unit family | unit target | accepted spellings |
|---|---|---|---|---|
| `energy_consumption` | `float` | energy (kJ to PJ, kWh to TWh) | `OEO_00050008` | 22 |
| `emission` | `float` | mass, CO2 equivalent, emission factor (g CO2/kWh) | `OEO_00010137` | 68 |
| `heat_load` | `float` | power (kW to GW, kWel, MWel, kWp, MWp) | `OEO_00390001` | 9 |
| `share` | `float` | percent | `UO_0000187` | 2 |
| `building_count` | `float` | a count of buildings | `UO_0000189` | 1 |
| `planning_organisation` | `text` | none | none | none |

`heat_load` is split from the two amounts purely by unit family, `share`
(Anteil, a part of a whole in percent, `fraction value` as its one class) by
the percent sign, and `building_count` (MHPO's `building count`, owner
decision 2026-11-03) by its one unit, `Gebäude`; the spec marks all three
`integrated=False` (`docpipe/extraction/spec.py:131` to `137`), the flag that
tells a rate or a stock apart from an amount stated over a span; the other two
numeric parameters leave `integrated` at its default of true. The MHPKG schema
holds no building count yet, so the strict graph leaves it out, and the
compute step, which adds only amounts over a span, does not sum it. An
integrated parameter's units each say whether they name a
period, `names_period`, and the loader refuses an entry that does not say
(`spec._validate_unit_entry`): of the 22 entries of `energy_consumption` and the
68 of `emission`, 39 say true ("kWh/a") and 51 say false ("kWh"), and the
entries of `heat_load` and `building_count` stay bare factors. The verifier
flags `period:unstated` from that
statement alone, and it reaches no request and no stamp key, so changing one
costs no re-read.

All five numeric parameters share these five non-quantity axes, each
a closed vocabulary except `year`, a plain integer:

| axis | kind | vocabulary size | of which `out:` |
|---|---|---|---|
| `carrier` | vocabulary | 137 | 2 |
| `sector` | vocabulary | 17 | 2 |
| `scenario` | vocabulary | 3 | 0 |
| `spatial_scope` | vocabulary | 2 | 0 |
| `year` | integer | (not applicable) | (not applicable) |

All five have a sixth, `technology`, a
heat generation technology class (12 entries, 2 of them `out:`); the data
schema leaves it optional, so it is read from the value's own passage alone
and a number the plan does not split by technology is `out:total` and writes
no edge.

The spec demands no more than the ontology (OEO) and the graph schema (MHPKG)
demand. The closed lists offer every class under OEO's energy carrier (126),
plus the declared heat classes outside that root, for `carrier`; every class
under sector (15) and `out:other` for `sector`; every class under heat
generation technology (10, coal and combustion based added) for `technology`.
An entry new to a list has a German label and the OEO definition verbatim, and
no spellings. `energy_consumption` offers energy value and all its subclasses
(energy consumption value, gross inland, gross national electricity, electrical
energy amount, import and export, energy storage content and capacity, areal
energy density); `emission` adds emission value, greenhouse gas emission value
and emission factor value, and the parameter's brief and description name an emission factor, the
emission per unit of activity ("g CO2/kWh"); `heat_load` adds power rating, power capacity,
declared net and nameplate capacity, block size and areal power density, with
instantaneous in its aggregation list; `share` offers every fraction value
subclass and efficiency value, and a share of buildings, areas or costs is a
share. `energy_consumption` also accepts kJ, MJ, GJ, TJ and PJ, with or without
"/a", converted into MWh.

`quantity` and `aggregation`, the two axes that carry a parameter's own
answer space, differ by parameter, and `heat_load` differs from the two
amounts in how its aggregation is decided:

| parameter | `quantity` size (`out:`) | `aggregation` size (`out:`) | `aggregation` derived |
|---|---|---|---|
| `energy_consumption` | 29 (3) | 5 (0) | yes, from the unit where no answer is read |
| `emission` | 11 (6) | 5 (0) | yes, from a unit that converts onto the parameter's own unit where no answer is read; asked only otherwise |
| `heat_load` | 24 (2) | 5 (0) | no, asked |
| `share` | 16 (1) | none | no axis |
| `building_count` | 1 (0), derived from the unit where no answer is read | 5 (0) | yes, from the unit (instantaneous) where no answer is read |

An axis or a parameter answer beginning `out:` is a deliberate non-class,
not a gap. The convention is the core's: the sentinel a coordinate
carries when a passage genuinely does not state it is `out:unstated`
(`docpipe/extraction/fields.py:38` to `48`), and a profile's own vocabulary
rides the same prefix so a serializer can refuse every one of them by
shape rather than by a second, hand-kept list
(`profiles/kwp/kg.py:95` to `104`, `is_class`). Much of `quantity`'s own
list that is left is such an entry: a share expressed as a percentage, a
per-person or per-area figure, a cumulative, avoided or captured emission, and
a residual catch-all, so the model can name what a number really is instead of
forcing it onto the nearest real class; `carrier` and `sector` offer two of
the same kind each (`out:total`, `out:other`), `scenario` none.
A potential is a class: the energy and the power list offer OEO's thirteen,
potential, flow and stock potential, and the theoretical, technological,
economic, developable and sustainable kind of each, and the model takes the
kind the plan prints. Because one of them can be an energy or a power, the
graph writes a value in the unit its number was converted onto (`kg.unit_of`),
the entry's own target (`kg.target_of`) else its parameter's, and only where
that is an ontology identifier: OEO 2.14 and live OEO dev have no unit for
"g CO2/kWh", so an emission factor is read and converted in the harvest and
reaches the graph once the ontology has one, as useful energy and generation
did until 2026-11-07 (owner decision 2026-11-07). A number whose
printed unit is no entry of its parameter's list is read and flagged
`unmapped:unit:<print>`, has no `value_target`, is no input of the compute step
and stays out of the graph until the list grows and a top-up asks the unit again
(owner decision 2026-11-07). A number read off a figure's image has the reading
in the node's evidence comment in place of a quote.

`out:total` of `carrier` and `sector` is a number that holds for all entries
together: explicitly summed, or not split by that list in its own table or
sentence. A table split only by building type, say, has no carrier column, and
its numbers are read `out:total` for the carrier; the same holds for the sector
of a table without a sector column, which is not `out:unstated`. The model answers "Summe", quotes the header row or the title of the
table (the sentence itself, for a sentence), and `value_raw` is the word of that
quote it is split by instead, "Gebäudetyp" for example. The owner's two checks
are the only ones, as for every answer: the quote stands in a shown passage and
the wording in the quote. The questions of both axes say so.

Two of the numeric parameters take their `aggregation` from the unit where no
request read it, carried as the `derived` state
(`docpipe/extraction/fields.py:68` to `75`; [glossary](../glossary.md)): every
unit `energy_consumption` or `emission` accepts that converts onto the
parameter's own unit names a span, so the closed list's integral entry is the
fallback. It is asked first, like every coordinate (owner decision 2026-11-07:
asked, and derived only as the fallback), and the unit's entry is written only
where nothing read it (`Axis.derive`, `fields.derives`, `fields.apply_derived`;
the run does it once the coordinates were asked): a plan that names a span
states a mean over years, and a mean is a mean (owner decision 2026-11-07), which
the model reads. For the 20 emission-factor units ("g CO2/kWh", "kg CO2/MWh",
"kg CO2/GJ", ...) it is never derived: an entry of `units_accepted` may name its
own `"target"`, the unit its factor converts onto where that is not
`unit_target` (`Parameter.target_of`), and an emission factor is no annual
amount, so `fields.derived_by_unit` leaves it to the model (owner decision
2026-11-07). Before this was
derived, all 452 aggregation answers the model gave for these two
parameters over one plan were that same entry every time, evidenced
only by the unit string the request had itself just handed over. `heat_load`'s aggregation is
not derived, since a watt is not integrated over a span the way a
watt-hour is: this axis is asked instead, with evidence allowed one page
away, and a peak load can come back distinct from an average one.

The frame is the pair of coordinates that dates a value, `FRAME = ("scenario",
"year")` (`profiles/kwp/extraction.py`). A plan states its scenario containers
and its reference years in headings and column headers, not inside every cell,
and since 2026-11-08 no step reads that pair once for a document, a table or a
section and projects it onto rows: each value is asked its scenario and its
year for itself, in a request of its own for each, with the headings up to its place
and the title page beside its place (owner decision 2026-11-07), and a
year no step found is asked last with the plan's base and target years (see
[extraction](../stages/extraction.md)). Before the frame existed, the year axis
alone produced 1,849 refusals against zero readings, because every retrieval
window after the first excluded the one source that could carry the year.

A value whose passage prints no scenario or year is asked them like any other,
its year against the section it stands in. There used to be a
`FRAME_DEFAULT` for this case, the pair such a passage was read under, after
Kassel's Tabelle 3 (CO2 by sector and carrier, no year anywhere) left 35
values without a year. It is gone. It fired only when exactly one pair of the
document matched it, which held for 14 percent of plans and never once in the
corpus_m5 run, 0 of 638 planning calls: a plan states its inventory for one
base year and mentions a handful of others, so several pairs matched and the
branch stood down. More than the count, it wrote a year that does not stand in
the passage, and every value of this corpus says in the plan what it refers
to. Where it says so is the text around the table: the reading shows 1000 characters of
the plan's text before the table and 1000 after it, and the titles of the
sections before it.

The profile has no slice. `SLICE`, `READ_IN_FULL` and `kept_quantities()` were
deleted from `profiles/kwp/extraction.py` on 2026-11-10 (owner decision): no step
read them, since the harvest has no slice gate (owner decision 2026-11-04), so
every value is asked all its coordinates and the graph keeps what it holds. No
coordinate of a plan closes a row. The only thing that does is a coordinate with
an entry a value must have, the spec's `keep` at a coordinate (`fields.kept`,
`fields.closed`; the scenarios spec uses it for `work`), which gives the state
`out_of_slice`. Every entry beginning `out:` stays out of the graph. The
graph serializes all three plan parts the ontology names, scenario included (see
[The knowledge graph](#the-knowledge-graph)).

Five parameters carry a `brief`, one paragraph on what a value of them is
(`energy_consumption`, `emission`, `heat_load`, `share`, `building_count`); the
requests of the harvest show it, and a field asked once of a document is shown by its full description
(`"definition": "full"` on the `context` group in `groups` is still in the spec,
and no request of the flow consults it). `planning_organisation` keeps its description. The entries of the
closed lists carry their English ontology definition, and a `gloss`, one German
line written once from it, which a request shows as the entry's meaning instead;
the entries that already have a short German definition keep it (owner decision
2026-11-05). The classification questions are one line per rule, and the texts
the model reads name an entry as the list shows it ("Summe"), not by an
internal key such as `out:total`; `out:unstated` stays.

Every question a run asks carries its own fingerprint, so a resumed run
can tell exactly which question changed rather than treating the whole
spec as one block (`docpipe/extraction/spec.py:649` to `674`,
`fingerprints`): one key for the parameter-choice question itself, one
for the unit-choice question and the entries it offers, one per
parameter for its own question, brief, unit list and worked example, one per
category parameter for its closed list of spellings and definitions, and
one per axis for its question, type, derive rule and vocabulary. These are what the extraction stamp compares on a rerun,
described in full on [extraction](../stages/extraction.md).

Every parameter, axis and spelling this spec states today is published
at [contract/kwp.md](../contract/kwp.md); the table below is built from
that same file.

## The prompts

14 prompt ids belong to extraction and the graph route, kwp's own
wording of each spec question:

| id | loaded | asks for |
|---|---|---|
| `extraction/phrase` | once per document and field, before any row, and once per document, field, coordinate and wording of a value for a search for an open coordinate (parts `with: question`, `with: headings`) | the sentence this document is searched with, as the plan would print it |
| `extraction/anchors` | no request of the run; its text still enters the stamp's `anchors` key and the preflight reads it | six hypothetical sentences a passage stating this coordinate could read, written for the field-by-field flow |
| `extraction/review` | only under `--review`; excluded from the extraction stamp | a second reading of one value, over a window narrowed to its own passage and the section it stands in |
| `extraction/example` | only under `docpipe compile examples` | which values of one parameter a passage states, to propose the example a spec parameter still lacks |
| `extraction/compute` | once per question the compute step asks | one number the plan does not print, written as Python over the numbers already read; it may read on in the plan with the tools of the plan's text, and for a share take its whole from a passage and quote what the chosen whole is; one conversation per question, what it fetched, a number it took and its code's output each following the answer that asked for them |
| `extraction/transcribe` | once per figure and run where the figure has an image, kept under the harvest | the figure written as `{"caption": [...], "numbers": [...]}`, lines that can be read without the image: the caption is its title, a line for each axis with its unit and the names on it and each legend entry, the numbers a line for each number with what it stands for, copied as printed; a number the image only draws is marked as read off; a figure's lines are what a value read from it is checked against (trust level C) |
| `extraction/find` | once per field and piece, no history, without tools | every value of the field in the piece (at most `piece_lines` lines, a number of the flow, a table's title and head with every piece), as `{"found": [{"at", "words"}]}` (with the entry's number where the field has a list): each value its address, the cell in a line that "|" divides, else the line, and its words character for character; an empty list says the piece holds none; the field is shown by its `brief`; the prompt shows two example replies, one with a find and one with none |
| `extraction/docfield` | once per field a document has once (`planning_organisation`), and for the plan's settings and years | the field's values in the title page and the pieces a search finds best for the field's sentence, the run's budget of them (`search_pieces`, `listed_field_factor` times that for a field with a list), `search_per_request` to a request (numbers of the flow), as the same list of finds |
| `extraction/coord` | once per value and coordinate, no history | one coordinate for the one value, in the order of the spec's groups (`number`, `frame`, `context`): the address of the line that says it and its words, or 0; the request shows the value's own place (a table row with its title and head, else the sentences beside it), the headings up to it under `H`, the title page under `T` and the plan's settings under `F`; a coordinate that may name several things answers a list `found` |
| `extraction/search` | once per round of the search for a coordinate the value's own place does not state | the same answer for the pieces a search finds (the pieces beside the value's first in one request, then the budget of `search_pieces` by kind, `search_per_request` to a request, numbers of the flow), each under a letter, with `more` to fetch the next or previous piece, a table or figure, the pieces a pattern stands in or those closest to a sentence |
| `extraction/list` | once per document, field, coordinate and wording | the number of the entry of a closed list the words mean, 0 for none; the list shows what each entry means (`gloss`), never how this plan named it before; a list of more than `list_meanings` entries (a number of the flow) whose entries name groups is asked group first, and a find that names an entry's number needs no list request; the plan's years are chosen with it too |
| `extraction/check` | once per find of the search from another passage than the value's own | whether the line is about this value, as `{"about": "yes"\|"no"}`; on "no" the find is dropped |
| `extraction/follow` | each time an answer that did not hold is asked again (as often as the flow says) | the words that follow the request the answer was for, with the answer and what did not hold under `what`: answer once more in the same form, leave out what no shown line supports |
| `kg/coordinate` | once per chat turn the graph route tries | one closed answer to one coordinate axis, for the SPARQL query |

Two of these ids, `extraction/review` and `example`, are parts files (see
[profiles](../profiles.md), The extraction prompts). Each names its template of
the core in its front matter, and `CONTRACT_LANGUAGE = "de"` in
`profiles/kwp/extraction.py` says that the templates are the German ones. What
kwp writes itself is its role (German municipal heat plans), its examples and the
sentences about its own tables. It leaves out the block `corpus_language` of the
review prompt, which it never had a sentence for; the example prompt leaves out
and words nothing. `python scripts/render_prompts.py --what-if` shows each block
it leaves out put back (see [Running the pipeline](../running.md)).

`extraction/find` and `extraction/coord` are the two every value is read with:
`find` finds the values of a parameter in a piece, and `coord` asks each
coordinate of one as its own question; every request is its own prompt and one
message, no conversation, and the marked `with` parts of a prompt are told only to
a request whose message carries the key (see [extraction](../stages/extraction.md),
What a request shows). `extraction/review` is deliberately outside the set the extraction
stamp hashes, because a review only ever
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
| planning organisation | `oeo:OEO_00030022` | the normalised office name of a row with role `planner`; a row with role `municipality` mints none |
| a named sub area | the spec's plan-area class | AGS plus the normalised area wording |

`planning_organisation` (label "Planerstellende Organisation") has one axis,
`role`, `planner` or `municipality`, read from its own passage in the `context`
group. A `municipality` row links `has_organisation` to the plan's municipality
node and mints no organisation, since MHPKG does not count a municipality acting
as planning authority as a second entity; planners are minted as before.

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
`no_slot:<slot>`, `missing:<slot>`, `off_list:<slot>`). A class outside the schema
stays in the full graph and the strict graph refuses it under those reasons. A
value without `aggregation` is written without that edge, never set to a year's
sum, and the strict graph refuses it as `missing:<slot>` where the schema's class
requires one; a value without `spatial_scope` is kept in the full graph and
refused by the strict one as `area`. Both files are
SHACL-validated against the refreshed shapes.

What the serializer refuses, briefly (in full on
[stages/graph.md](../stages/graph.md)): a row failing the quantity,
scenario, year or aggregation-list gate, or a number without `value_target`
(`unit_unlisted:<unit_raw>`) or converted onto a unit the ontology lacks
(`unit_not_in_ontology:<target>`), or whose spatial scope is neither the
municipality nor a named sub area, quantity checked
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
wraps around every turn. Its sentences are the file
`profiles/kwp/prompts/inference/phrases.json`: 32 keys matching
`docpipe.inference.wording.REQUIRED` exactly, covering the task and history
headings, the code-execution sandbox's own headings, the image read-off
headings, and how a citation names its page, section, table or figure.
`READOFF_MARKER` and `READOFF_NOTE` mark a value read off a chart image
rather than table text. `make_search_phrase` (see
[inference](../stages/inference.md)) no longer filters the model's anchor
sentence for a refusal or an evaluation; it takes whatever non-empty
phrase the model wrote and falls back to the raw task only on an error or
an empty reply.

What the chat says to the model when a reply was not the one JSON object it asked
for is not in that file. It is `profiles/kwp/prompts/reading/phrases.json`, the ten
sentences of `docpipe.reading.REQUIRED` that refinement, the visuals stage and
page transcription use as well: what was wrong with the reply (no object, text
beside it, a syntax error at a character, a missing key) and the shape that was
asked for. They are English, because the instructions of those stages are
English in this profile and only what the model reads off a German page is
German; so the correction the chat appends to a request is English although its
prompts and its answers are German. The file is laid over the built-in
profile's entry by entry (`phrases.table`, `docpipe/phrases.py`).

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
