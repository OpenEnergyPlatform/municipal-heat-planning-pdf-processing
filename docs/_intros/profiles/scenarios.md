## The AR6 literature corpus

The scenarios profile targets a different corpus than the kwp profile: not
municipal heat plans but the publications the IPCC AR6 scenario database
cites, staged from a crawl over that citation list, each entry's PDF
placed by hand and the AR6 scenarios it documents becoming the
`DocumentScenarios` link table described next
(`profiles/scenarios/source.py`'s module docstring).
`profiles/scenarios/profile.py` sets `document_noun` to `publication`
and three catalog facets a reader can filter by: publication year, venue,
and the AR6 scenarios a publication documents. It declares no language:
the language of a request and of an answer is that of the profile's
prompts and phrase tables, which is English throughout, as are the
publications. `extraction_spec.json`'s `parameter_question` and every
parameter's label and description are English sentences, the spellings of
its closed lists are the ontology's English alternative labels
(`ALT_LABEL_LANGUAGE = "en"`), and the spec's `_comment` states
that `out:not_in_list`'s meaning is worded in the language of its prompts
(`extraction_spec.json`, lines 40 to 41). The labels are English because
the model copies a label it is offered as the document's wording, and a
German label never stands in an English quote.

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
way an axis coordinate is (`profiles/scenarios/kg.py`, lines 479 to
483). Over the 164-document ar6 harvest the module calls its own, 298 of
11,129 scenario-scope tuples could not be attached to any scenario: 289
because the run's window budget was exhausted, 9 because the paper
itself never states which scenario the value belongs to
(`profiles/scenarios/kg.py`, lines 811 to 819; the full account is at
[../stages/graph.md](../stages/graph.md)).

## What the profile contributes to each stage

Every attribute below is one seam `docpipe/` or a script asks a profile
for by name, described in general on [profiles](../profiles.md); this
table gives this profile's own answer.

| Stage | Module | Attribute | Contributes |
|---|---|---|---|
| File processing | `source.py`, `schema.sql`, `store.py` | `SOURCE`, `DocumentMeta`, `Scenarios`, `DocumentScenarios` | the ar6 crawl as a `Source`, and the profile's tables and upsert helpers |
| Layout detection | `profile.py` | `column_layout` | `"auto"`, a two-column journal or report page read column by column |
| Structure assembly | `preprocessing.py` | `HYPHEN_EXCEPTIONS`, `CAPTION_MAX_WORDS`, `CAPTION_START`, `TITLE_EXCLUDE_PREFIXES`, `DIRECTORY_FIGTAB_WORDS`, `DIRECTORY_TITLE_WORDS`, `BIBLIOGRAPHY_TITLE_WORDS` | English hyphenation, caption length, what opens a caption (a word, a number and a colon), heading and bibliography rules; `DIRECTORY_TITLE_WORDS` is the same four words as the other profiles ("inhalt", "verzeichnis", "contents", "directory"), so no verdict moved |
| Preprocessing, refinement, visuals | `prompts/preprocessing`, `prompts/refinement`, `prompts/visuals` | 1, 3 and 6 prompt ids of its own | page transcription, English artefact repair, table and figure captioning; `visuals/caption_keep` is the built-in profile's, inherited byte for byte |
| Refinement, visuals, page transcription, the answer app | `reading.py` | `PHRASES` | the ten sentences these stages and the chat say to the model when its reply was not the one JSON object (`reading.REQUIRED`), in English, the language of the prompts of the first three; the extraction prompts are German and `extraction.PHRASES` is another table, the harvest's own |
| The picker (app) | `catalog.py`, `profile.py` | `CATALOG`, `facets` | publication labels and names (a name opens each line of the values index) and three filters |
| Extraction | `extraction.py`, `prompts/extraction/*.md` | `SPEC_PATH`, `document_axes`, `document_context`, `FRONT_PAGE_PARAMETERS`, `PHRASES`, `PROMPT_CHECKS`, `NOT_EXTRACTED`, `shapes_files`, `ALT_LABEL_LANGUAGE`, `CONTRACT_LANGUAGE`, 13 prompt ids | the spec (18 parameters, four of them the bundle's tags), the per-document scenario and region lists, the sentences the stage writes to the model and the passages the preflight holds its prompts to, the language (`"en"`) of the core's templates its parts files are put together with, and the harvest's own questions |
| The graph | `kg.py`, `oekg_api.py` | `make_serializer`, `make_study_reader`, `dry_run` | OEKG Turtle, the trust wording, and a dry run of the platform's scenario-bundle API (below) |
| The answer app | `inference.py`, `prompts/inference/*.md` | `PHRASES`, `READOFF_MARKER`, `READOFF_NOTE`, 11 prompt ids of its own | the English chat wording and the answer loop's own prompts; the twelfth, `json_format`, is the built-in profile's, inherited byte for byte, so the text, its hash and the request are what the copy gave |

A run harvests a publication from its survey (owner decisions 2026-11-04,
see [extraction](../stages/extraction.md)): the spec names one group,
`scenario`, read with the value, and English prompts serve it.
`extraction/survey` names per passage the fields the publication states
about itself, its study or its own scenarios. `extraction/read_values`
names the values one per request, with `value`, `value_raw` and quote, and
`extraction/read_text` answers for each value the scenario
it refers to, matched to a run identifier of the document's own list. A
value is what its field asks for and never the answer of a coordinate, so
a scenario's description is what the publication says the scenario assumes,
not the scenario's name (owner decision 2026-11-04), and an author value is
one author's name: a person, or the institution where the publication names
no person. `extraction/comb` looks for a scenario still open in the rest of
the publication. No field of this profile holds numbers, so a table is read
by `read_values` and `read_text` too, as a table is in every profile, and a
field with a list is shown it and answers one entry, or `""` with its wording
in `value_raw`.

Field by field, `extraction/places` asks once per publication which passages
answer which fact and question, with a quote and no value; the search then
reads from that map.

`FRONT_PAGE_PARAMETERS` in `extraction.py` has what a publication says
about itself (title, authors, date, DOI, abstract) asked once more on its
own over the opening of the document, besides wherever else it is read, in
a harvest field by field; a harvest from the survey sends no such request
until a probe has measured whether its survey finds them by itself. Where the
survey named no passage for one of them, the search for it ranks with a
sentence written for this publication from its title as the corpus index
holds it (`document_context`, `DocumentMeta.title`), which finds the title
page; the sentence for any other parameter is written once per run, since a
publication's title pulls it toward the title page (owner decision
2026-11-05, measured on six papers).
The abstract was left out in 132 of 164 publications and the date in 60
when they were only asked among all the other rows. Without a title the serializer writes no
node for a publication: 17 of the 164 publications of the run of 2026-10-22
had none, 14 of them because refinement had dropped the title before the
harvest (a heading with no body, or the heading of a section the model
removed; see [refinement](../stages/refinement.md)), and one because the
model left it out of a crowded request.

Five of the 13 extraction prompts, `rows`, `field`, `frame`, `review` and
`example`, are parts files (see [profiles](../profiles.md), The extraction
prompts): each names its template of the core in its front matter, and
`CONTRACT_LANGUAGE = "en"` in `profiles/scenarios/extraction.py` says that the
templates are the English ones. What scenarios writes itself is its role
(scientific publications on climate and energy scenarios), its examples and
the sentences about its own sources. It words six blocks itself, where the
template's sentence fits it less well. In the rows prompt `invent_figures` says
that what a figure description does not state does not exist, and
`source_kinds` names the kinds of sources, with figure descriptions. In the
field prompt `rows_carry` says what a row carries, an identifier, its source
and its passage and no unit, and `unstated_when` says when the answer is "not
stated": when the passages name no scenario at all. In the review prompt
`row_note` and `field_unit` are its own note on the first reading and its unit
bullet. It leaves out the blocks of the templates it never had a sentence for:
13 blocks of the rows prompt, 7 of the field prompt (`base_years`,
`target_years`, `year_value`, `no_guessing`, `closed_out`, `by_meaning` and `found_next`) and
`field_raw` of the review prompt. The frame and the example prompt leave out and
word nothing. `python scripts/render_prompts.py --what-if` shows each block it
leaves out put back (see [Running the pipeline](../running.md)).

Extraction's `rows`, `field` and `read_values` prompts hold a value's quote to the
piece that carries it, a clause, a list entry, one table cell, not the
whole paragraph: an author list gives one quote per name, and a
title's quote is the title itself. Quoting the whole block for every
author used to make the reply to a crowded title page grow past the
token limit and lose the title, authors, DOI and date together.

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
at all (`spec.py`, lines 431 to 455). Either way, the vocabulary key
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
scenarios the value belongs to.

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
label is mentioned somewhere in this document's own text, and does the
same with the groups of countries in `region_aggregates.json`; a region of
the AR6 database also counts as named by its bare name ("Europe") where the
document names its family ("R10"). A model's own region ("Other Asia",
"OAS" of REMIND) is offered where the document names the model with its
capitals ("REMIND", not "remind") and the region (`_named`). Two offered
groups never share a label (`_one_meaning`): the region of the paper's
model keeps it, and where no such region or two of them carry it, no group
does, so one answer never names two groups. The world, `aggregate:World`,
is always offered. Every entry comes with the ways a paper writes its labels
(`spellings`): "&" and "and" stand for each other ("Middle East and North
Africa" for the World Bank's "Middle East & North Africa"), and a group's
code and name joined as a paper joins them ("LAM (Latin America)", "Latin
America (LAM)", "LAM - Latin America") name the group; a country's labels
are not joined. So the remap maps such a wording too, and the harvest's check
of a wording against the option it names takes it.

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

The copy of the spec these lists fill in goes with every batch of the
document, so the value request, the field requests, the reading and their
checks offer and hold an answer to the same lists the search used. `--review` and
`--recheck` read a harvest file against its own document's lists, and leave
alone, stamp included, a document whose lists cannot be closed.

The fixed kind carries the rest of the list-valued fields: `scenario_type`,
and the four tags the OEKG shapes demand of every bundle,
`study_descriptor` (`OEO_00390071`), `study_sector_division`
(`OEO_00390079`), `study_sector` (`OEO_00020439`) and
`study_technology` (`OEO_00020438`). The sector division is the scheme the
sectors follow (the CRF of the IPCC guidelines, NACE, an energy balance),
and its description says that a sector is never one: in the run that last
asked it, 531 of its 535 answers were a sector. Each tag is a `category`
parameter without axes whose
vocabulary is the shapes' own `sh:in` list for its path, 31, 17, 153 and
43 entries with the OEO label, spellings and definition of each, plus an
`out:not_in_list` entry. The model picks an entry and quotes the passage,
exactly as for `scenario_type`. The lists are written into
`extraction_spec.json` once, not drawn per document, so they can fall
behind the shapes, which `list_problems` (below) reports.

## The out: sentinels

An `out:` sentinel is a vocabulary entry offered like any real class, but
one whose identifier begins with the literal prefix `out:` and names a
deliberate non-class answer, not a reading the graph can hold. The
prefix is one definition, `NOT_IN_GRAPH = "out:"` in
`docpipe/extraction/graphkit.py`, which both profiles' `kg.py` and the
provenance writer import, so the serializer has nothing to keep in step with
another copy; `kg.in_graph()` in `profiles/scenarios/kg.py` (line 257) is the
one guard every later mint, link and type decision runs through, and it refuses
whatever starts with it.

Three families of sentinel exist, plus the last entry of each fixed
vocabulary, which behaves the same way. `SCENARIO_OUT` offers
`out:family`, for a wording that names a group of runs (a policy
family, for example) rather than one identified run: the prompts give it to
any name that fits several runs and none of them exactly, whatever the runs
share, their beginning, their climate target or their variant alone (owner
decision 2026-11-04), and `out:not_documented`, for a scenario the paper names
that this document's own AR6 list does not carry (`extraction.py`, lines
83 to 91). `REGION_OUT` offers `out:multiregion` (a named grouping,
such as a trade bloc, that neither the countries nor the groups carry) and
`out:other` (a spatial statement fitting neither). The world and the
groups of countries are entries of the list (`region_aggregates.json`),
since the OEKG's own region list holds only individual countries and an
AR6 scenario is global far more often than national.
Finally, the fixed vocabularies are corpus-wide rather than per-document,
but carry the same idea as their last entry, `out:not_in_list`. In
`scenario_type` it is the eighteenth: the passage names a kind of
scenario that none of the other seventeen OEO classes covers, a finding
distinct from the passage naming no kind at all, for which the
vocabulary offers the generic `scenario` class instead
(`extraction_spec.json`, the `scenario_type` parameter; confirmed as 17
real classes plus this one sentinel by). Each of the
four bundle tags ends the same way, worded for its own list: a topic,
sector division, sector or technology the text names that no entry
covers.

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
lines 257 to 272). Every chosen sentinel, together with every
`scenario_label`, `scenario_region`, `scenario_type` or bundle tag row
that resolved no `value_uri`, is counted once into an `out_of_graph`
tally, logged per document and never written as a triple (`kg.py`, lines 602 to 620).
Measured over a corpus run, the model answered with a sentinel 1,171
times for a wording its own document-scoped AR6 list could resolve
without a guess, 347 of those a character-for-character spelling match;
on one document, the wording matched the list's only entry exactly and
the model still answered `out:not_documented` (`kg.py`, lines 320 to 323,
`resolve_wording`'s own docstring; the sentinel is named by). Those readings
are not lost: `resolve_wording()` rescues a link the document's own list
settles unambiguously even where the model gave up, logged on its own
line, separate from the sentinel tally (`kg.py`, lines 716 to 727).

## The graph: one report, one bundle, a factsheet per run

The target is OEKG, on the Open Energy Platform, built by
`profiles/scenarios/kg.py`'s `make_serializer`, called the same way as the
kwp profile's own serializer through `docpipe/extraction/serialize.py`; the
walk shared by both profiles, and the ontology audit that checks a spec
against a pinned snapshot separately from any serialize run, are documented
at [../stages/graph.md](../stages/graph.md), and the harvest fields this
serializer reads are published field by field at
[../contract/scenarios.md](../contract/scenarios.md). This profile's own
half of that audit, `profiles/scenarios/vocabulary.py`, pins 280 ontology
identifiers named in the spec, plus the 249 OEKG study regions, against
the OEO release of its last refresh (2.14.0 since 2026-11-04).
`python -m profiles.scenarios.vocabulary --refresh` pulls the OEO
closure, the live study regions and the groups of countries (the AR6
database's R5, R9 and R10 regions and each model's own regions, with the
codes the model's mapping gives them, from IAMconsortium/common-definitions;
the UN's M49 regions from the SDG API; the World Bank's groups of economies,
the European Union and the OECD among them, from its classification
`CLASS.xlsx`, the two also named "EU" and "OECD" as a paper writes them
(`SHORT_FORMS`); and EU28, the World Bank's Union and the United Kingdom, the
one group no source lists, owner decisions 2026-11-04) and the English short
name each region has in the OMG's LCC (`lcc`, its ISO 3166-1 file), rewrites
`vocabulary.json`, `regions.json`, `region_aggregates.json` and
`region_names.json`, and runs the same check `--check` alone runs against
the checked-in snapshot; `region_aliases.json` keeps the hand-written
spellings a document uses that the OEKG's own labels do not, merged in
ahead of the live ones by `merge_regions` (`vocabulary.py`, lines 1 to
26; [../stages/graph.md](../stages/graph.md)). `aggregates` places each
member of a group on an OEKG region by one of its labels, or by a label
with the same words in another order. Accents do not count and the sources'
abbreviations are written out ("St. Lucia", "Lao PDR", `ABBREVIATIONS`); a
name with a comma whose whole words find no label is placed by the words
before the comma where exactly one region's labels hold them all ("Egypt,
Arab Rep.", "Hong Kong SAR, China"), while "Congo, Dem. Rep." is placed by
its whole words, since two regions hold "Congo". A member no label places, a group
label that is a country's and a label two groups share are counted and
printed, never guessed. A model's region needs its labels to be its own
only among the models of one name ("REMIND" and "REMIND-MAgPIE" are one),
since a paper is offered them only where it names the model; every version
of a model defines its regions again, and the newest one is kept.

Every IRI is minted under `BASE`, which defaults to
`https://openenergyplatform.org/ontology/oekg/` and can be overridden by
the `OEKG_ID_BASE` environment variable (`kg.py`, line 55).
`mint(collection, name)` derives the local part as a UUIDv5 over a
normalised identifying name, never a random UUIDv4, so two serialize
runs over one document mint byte-identical IRIs (`kg.py`, lines 233 to
239). Where each class of
node lives was read directly off the running OEKG graph over its SPARQL
endpoint, 13,700 triples at the time it was checked (`kg.py`, lines 49
to 52): a study report sits under `publication/`, a scenario factsheet
under `scenario/`, a study region under `region/`, and a scenario
bundle, an author, an organisation and a funder directly under the base
with no path segment at all (`COLLECTIONS`, `kg.py`, lines 61 to 69).

One document mints exactly one study report and one scenario bundle. The
report's IRI comes from the resolved title; the bundle's comes from
`study_project_name` where the document names a project, and from the
title again where it does not (`kg.py`, `_make_builder`). A node carries
a has-uuid triple where its shape has that path: today the report and the
factsheet, not the bundle, whose `StudyShape` names none (`bind`,
`uuid_on`).

## Written to the shapes

The serializer does not carry the OEKG shapes a second time. When it is
built, `bind(model)` reads them (`docpipe/extraction/shapemodel.py`), from
the file the last `vocabulary --refresh` pulled (`oekg_shapes` in
`vocabulary.SOURCES`, at the head of `production`). Every path the
serializer writes on a report, a bundle or a factsheet (`WRITTEN`) has to
be a property of that class's shape, and the two dates have to be the
`xsd:dateTime` it writes; a path the shapes dropped or retyped raises
`SchemaError` before a document is read, so a run never writes a graph no
validator accepts without saying so. Read off the shapes are which
per-document fields occur at most once (`single`, settled by `_pick_one`
below), which must occur (`required`, reported per document), which nodes
get a uuid, and the class at the end of the author, organisation and funder
edges. Without shapes from a refresh there is no serializer at all. The
same shapes then validate the written graph (`<ttl>.shacl.txt`,
`<ttl>.shacl.json`), and `docpipe.extraction.gate` writes the graph of the
existing harvest before a job starts its model
([../stages/graph.md](../stages/graph.md)). Where the shapes and the
ontology disagree, the shapes win: the region is written with the path the
closed `ScenarioShape` names (owner decision 2026-10-22).

The graph describes the regions and the OEO terms it points at, once per
file and by their own sources (OEKG team, 2026-11-04): a region by the class
the shapes require at the end of its edge (study region, `OEO_00020032`) and
the English short name LCC gives it ("Syrian Arab Republic (the)",
`region_names.json`), an OEO term used as a scenario type or a tag by its
label in the release the snapshot is pinned to, both as plain strings
without a language tag (`node_names`, and the block above `parts` in
`_make_builder`). A region is the LCC country of its own name; one LCC has
renamed since the OEKG minted it is the one country whose short name is
among the region's labels (`region/Macedonia` is North Macedonia), and one
that finds none or two stays unnamed (`vocabulary.region_names`). A node
its source does not name gets no label of ours and is logged. A node the
graph leaves bare is validated together with what the OEKG says about it:
the refresh pulls `rdf:type` and `rdfs:label` (`oekg_context`),
`vocabulary.context()` hands them over and `ontology.with_context` adds
them for every node the graph points at without describing it.
A node several documents describe, an author or a project's bundle, is one
node of the file: its single-valued properties carry the value of the first
document that gave one, and a later document's other reading goes unwritten
(`settles` in `_make_builder`).

The bundle also carries its tags, one triple for each entry the model
picked from the four lists above. `BUNDLE_TAGS` is every category
parameter whose `kg` block names the bundle, read from the spec as
`SCENARIO_FIELDS` is (`kg.py`, lines 211 to 218), and every passage that
named an entry stands above its triple. An `out:` entry or a wording the
list did not hold writes no triple and is counted in `out_of_graph`, as
for a scenario type (`kg.py`, lines 948 to 960). The
picked IRIs travel on in the study dict as `bundle["tags"]`.

One factsheet is minted per resolved scenario identity. For every
scenario-scope row, `scenario_key()` decides which run, if any, the row
belongs to, against the document's own known-scenario list and a synonym
dict built from whichever rows of the same document already resolved a
run (`kg.py`, lines 341 to 390, 729 to 739); a wording that resolves to
no run still gets its own factsheet, keyed by the wording alone. A
factsheet's `rdfs:label` is the AR6 database's own spelling where a run
was resolved, and the document's own wording is kept alongside as
`dc:acronym`; with no long name known for a run, both carry the same
string, the usual case in this corpus (`kg.py`, lines 866 to 869). Every
factsheet also carries a fixed `OEO_00020517` annotation on top of
whatever `scenario_type` classes the model read off the text
(`IAM_SCENARIO`, `kg.py`, lines 199, 882).

A study region is referenced, never minted. A region the model matched
against the document's own narrowed OEKG list is written as a link to
that region's existing IRI, described once by LCC's name for it and never
by the document's wording (above; `kg.py`, the comment above the region
block). A group of countries is
written as a link to each of its members, its passage cited once above
the first (`region_members`). An `out:multiregion` or `out:other`
choice, or a wording the narrowed list did not hold, mints no region
node at all and is only counted; minting
one would have put a 250th region under `oekg/region/` beside the 249
already pinned (`profiles/scenarios/vocabulary.json`, `regions_count`
249).

The per-document fields the OEKG shapes allow at most once (today
`publication_title`, `publication_date`, `publication_doi`,
`publication_abstract`, `study_project_name` and `study_acronym`, read off
the shapes by `bind`) are settled by `_pick_one()`, which favours the reading the
most sources agree on: first dropping any candidate that is a strict
substring of another (a running header would otherwise outvote a title
on its own title page), then ranking by vote count, whether the reading
was located on its PDF page, and length (`kg.py`, lines 393 to 421).
For the title, the date and the DOI a reading on page 1 or on the first
page the title was read on, the title page behind a cover, goes first
however often other readings agree (`FRONT_FIELDS`, `_front_first`, owner
decision 2026-11-05): a chapter that presents other studies prints their
titles, publishers and years, and the field descriptions say that only the
document's own count. The survey and the value reading say the same of a
passage that presents, reviews or compares another work, beside a reference
list, a footnote and a citation (`survey.md`, `read_values.md`). Runner-up spellings are counted `contested` rather
than dropped from the log. A read-only connection then cross-checks the chosen title, date and
DOI against `DocumentMeta`, filled in by the crawl, not this profile's
own extraction; a disagreement is logged and the crawled value is never
substituted into the graph, since a published value must carry its own
evidence, and the crawl's copy is only the cross-check
(`kg.py`'s module docstring; `_crosscheck`, lines 452 to 468).

What the paper does not print of its DOI and year, often an authors'
manuscript, and its authors where the text yields none at all, the run
looks up in OpenAlex, whose records are CC0 (`completion.py`, owner
decisions 2026-11-04). After a document's fold a program, no model, finds
the record by the first of three keys that finds one: the DOI the corpus
index holds for the document (`DocumentMeta.doi`, read from the run's
database, which `runner.make_completer` hands the profile; the crawl's copy
is the key here, never the value), the DOI the harvest read, then the title the
harvest read. The index's DOI goes first: it belongs to this very file,
while a DOI read off the page can be one the paper cites, such as a
dataset's (one of 48 records in a measurement on run m6). A record a DOI finds is taken as it is; one the title finds
counts only where two of its authors' family names stand among the authors
read, one where either side names one author. The DOI, the year and the
authors then become rows of `publication_doi`, `publication_date` and
`publication_author`, the year as the parameter defines it and the full
date in the record. Each row quotes the read value the record was found
with, the printed DOI, else the title, carries the record (`catalogue`) and
is a D for the reason `catalogue`; the graph names the record and its key
above the triple. A value the paper prints goes first. The first time the
catalogue cannot be reached at all, the run asks it no more (`OFFLINE`),
and every later document says so in its trace at once.

An author is a person the document names as its author; where it names no
person, the institution it names as its own author or issuer (owner
decision 2026-11-04: OEO's `author` is a role of an agent, a person or an
organisation, and the OEKG shape asks only for that class).

Every triple this serializer writes about a value carries, immediately
above it, the passage it was read from. By default that passage is a
flattened Turtle comment (`_evidence_comment`, `kg.py`, lines 514 to 537)
rather than a linked node, since the OEKG's node shapes are currently
declared `sh:closed`, and an unanticipated triple on a report or a
factsheet would invalidate the node it documents. Setting `OEKG_EVIDENCE`
to anything other than `"0"` switches to a linked
`oekgprov:ExtractionEvidence` node per passage instead, described in the
module's own docstring as provisional and ahead of the shapes, so it
stays off by default (`kg.py`, line 459 and the module docstring). Either
branch is followed by one rendered trust line, worded in English
throughout `TRUST_PROSE` (`kg.py`, lines 464 to 471); the full
trust-level and reason vocabulary is published at
[../contract/trust.md](../contract/trust.md). The state vocabulary a coordinate ends in,
`read`, `derived`, `unstated` and the rest, is published in full at
[../contract/states.md](../contract/states.md).

## The OEKG scenario-bundle API: a dry run

The Open Energy Platform takes a scenario bundle through a REST API
(`POST /api/v0/scenario-bundles/`), as one JSON body holding the bundle,
its study reports and its scenarios, not as the Turtle `make_serializer`
writes. The server mints every identifier itself, so a body carries none
of ours, and it holds the assembled bundle against the OEKG shapes before
it writes anything: a create is judged strictly, so one missing value
refuses the whole bundle, and a key the API does not name is refused as
well. The shapes demand of a bundle at least one tag of each of the four
kinds above, each from a fixed list, and exactly one label and one
acronym; of a scenario at least one scenario type. The acronym is unique
over there and the only way to find a bundle again.

`profiles/scenarios/oekg_api.py` asks what the API would say to a harvest,
without asking it. `kg.py` reads a document once, in `_make_builder`;
`make_serializer` returns the Turtle from that pass and `make_study_reader`
the same decisions as a plain `study` dict (which title won, which
spellings are one author, which rows are one scenario, which tags were
picked), so the body and the Turtle cannot disagree about a document. `merge` and `form_acronyms`
then make one study per bundle of them, as described below. `body` builds
the create body from that, with no identifier of ours, the tags under the API's
own keys `descriptors`, `sector_divisions`, `sectors` and `technologies`,
each with every entry the model picked and not the first alone
(`TAG_KEYS`), and no key
for a value the harvest lacks, since the refusal for the missing key is the
finding.
`schema_problems` holds it against `ScenarioBundleCreate`, the request
schema of the platform's OpenAPI description, and adds the keys the schema
does not name, which it would let through. `graph` builds a model
of the bundle as the server would hold it after the create, and
`shape_problems` asks the shapes about it through `pyshacl`.
`list_problems` compares the spec's choice lists, `scenario_type` and the
four tags, with the shapes' `sh:in` lists for their paths: a class the
shapes dropped would be harvested and then refused, and one they gained
could never be chosen.
`acronym_problems` compares acronyms, without case, across the harvest
and, with `--live`, with the platform's public bundle list.

The report counts bundles, not documents and not nodes: the scenarios of
one bundle that lack the same thing are one finding about that bundle. `--write` writes one
request per bundle as JSONL, with its problems and the harvest files it
was read from, the leading one first.

Nothing is ever sent. The module builds no call that writes, and `--live`
is one GET of the public list, followed page by page. The two
inputs, the platform's OpenAPI description and the shapes file, are the
`SOURCES` of `oekg_api.py`, pulled through `docpipe/upstream.py` at the
head of their branch; the shapes source is the profile's own
(`vocabulary.SOURCES["oekg_shapes"]`), so the dry run and the Turtle are
held to one file, and the bodies are read with the paths of the shapes they
are checked against. Each names a `reviewed` commit, for the shapes the
one the platform pins its validator to, and every run prints whether the
file has moved since: a
verdict against shapes that moved is a verdict about another validator.
They are locked in a file of their own (`LOCK`, not the profile's), so a
harvest run's `vocabulary --refresh` does not come to depend on the API
description:

```bash
python -m profiles.scenarios.oekg_api OUT DB --refresh
python -m profiles.scenarios.oekg_api OUT DB --write bodies.jsonl
python -m profiles.scenarios.oekg_api OUT DB --live
```

`OUT` is the harvest directory and `DB` the corpus database. Without
`--refresh` the files of the last refresh are used, and `--openapi` and
`--shapes` name local copies instead. Exit 0 is a report, whatever it
says. Exit 2 is a run that could not be made: no harvest, no database,
no API description or no shapes. The
database is required because the reading falls back to an empty AR6 list
without it, and the bodies then name other scenarios.

The shape verdict is a model of the server, built from its documentation
and not from its code. It assumes that the server mints a uuid on every
study report and every scenario, that a contact, organisation, funder or
author sent with a label alone is minted with that label, and that a
region, a tag or a scenario type sent as an IRI is a node that already
exists over there with its own type and label. Where the model is wrong
the verdict is, and only a real create settles it. It also covers only the
keys `body` writes: the API takes more (energy carriers, contacts and
more), and `graph()` raises on a body carrying one rather than return a
verdict over half a body.
Which properties of the shapes the profile leaves out on purpose, the contact
person, the study's energy carrier tag and the interacting region among them,
and why, is `extraction.NOT_EXTRACTED`; `docpipe preflight` warns about any
other property that nobody asks.
The acronym comparison ignores case and outer spaces, which may be
narrower than the platform's own rule.

A body is not the Turtle in another syntax in three places, each on
purpose.

The first is one bundle per project. The Turtle mints a bundle from its
label, so two papers of one project are one bundle with two reports there,
while the body of each paper alone would make two bundles of one study.
`merge` joins the documents whose bundle label is the same (compared
through `kg.normalise`, as the Turtle mints it) into one request with
several study reports. The oldest paper leads: its spelling labels the
bundle and its abstract is the bundle's, of which the shapes allow one;
the acronym is the one most of the documents give, and the tags,
organisations and funders of the others are added to its own, two
spellings of one name counting once. Documents
are deliberately not joined on a shared acronym. A harvest pairs a
project's name with another project's acronym often enough, a paper thanks
two projects, that joining on it would chain unrelated papers into one
bundle; such a pair stays two bundles and is reported for its acronym.

The second is a formed acronym. The platform demands one, and a bundle no
document gives one would be refused for that alone. `form_acronyms` names
it after the first author and the year of its leading paper, `Riahi-2021`;
two that come out the same are told apart by a number, in the order of
their documents, which keeps a name the same from one run over a harvest
to the next. That name is made, not read: the entry says so in `formed`,
the report counts how many, and a paper without an author or a date gets
none and stays refused.

The third is the missing IAM annotation. The Turtle types every factsheet
an IAM scenario (`OEO_00020517`, above). The platform's list of scenario
types does not hold that class yet and refuses a create for it, so the
body leaves it out (`NOT_YET_LISTED`); a factsheet with no other type then
has none and is refused for that instead.

The study region is no longer one of them: the Turtle and the body both
write `has study region` (`OEO_00020220`), the path the closed scenario
shape names, the body onto a node of class study region (`oekg_api.py`,
the comment above `API_STUDY_REGION`).

## What is refused

A spec that mismatches the two dynamic mechanisms above refuses to load
before any document is touched: a category parameter naming both a fixed
vocabulary and `vocabulary_dynamic`, or a non-category parameter naming
`vocabulary_dynamic` at all, raises `SpecError` naming the offending
field (`docpipe/extraction/spec.py`, lines 431 to 455). A `kg` block
whose class is not an identifier shape, or whose predicate is not a
single token, is refused the same way, at spec load time
(`_validate_kg_ids`, `spec.py`, lines 702 to 741); this rule is shared
with the kwp profile. This profile's own `kg.py` calls that same loader
again, on its own copy of the spec, at import time (`load_spec(_SPEC)`,
`kg.py`, line 477), so a spec broken this way fails to import the whole
serializer before a single document is processed, not partway through a
run. `kg.py`'s own lookup helpers, `_property`, `_name`, `_class` and
`_kg`, raise `KeyError` for a key the spec does not carry rather than
default silently.

A document whose `publication_title` never resolved is refused whole:
the serializer returns `None` and logs at `INFO` level, before a bundle,
a factsheet or an author node is built (`kg.py`, lines 632 to 634). Any
other field the shapes demand on the report or the bundle, a date, an
author, an acronym or one of the tags, is not refused this way, only
named in the per-document summary line as a missing required field
(`bind`, `required`); the bundle's label never is, since it falls back to
the title (`FALLBACK`).

A scenario wording absent from its own quoted passage is refused as an
identity for every scenario-scope parameter alike: `scenario_key()`
returns no identity and no label, and the row contributes no factsheet,
comment or number (`kg.py`, lines 295 to 309, 385 to 389); it used to
mint a factsheet anyway, carrying the invented wording as a stable label
of its own, which this check exists to prevent. A wording that fits more
than one run of the document's own known-scenario list, with none
matching it exactly, is refused as an identity rather than guessed: the
link is dropped, the wording alone becomes the factsheet's key, and rows
the model assigned to different runs land together on that one shared
factsheet, a conflation the module accepts and logs by name rather than
hides (`ambiguous()`, `kg.py`, lines 276 to 292; the merge report, lines
837 to 851).

Every `out:` choice, and every unresolved `scenario_label`,
`scenario_region`, `scenario_type` or bundle tag row, is refused a place
in the graph the same way: no class, no IRI, no link, only a count and a log
line (`kg.py`, lines 602 to 620). A region wording the document's own
narrowed list did not hold is refused identically rather than minted as
a new individual.

One collision is explicitly not refused, unlike the kwp profile's own
identity guard. A second document minting the same study report or
scenario bundle IRI as an earlier one in the same run, a preprint and
its later journal version sharing one title, for example, is only
logged, naming both documents and the shared IRI; both documents'
single-valued triples land on that one shared subject rather than the
second document being dropped whole, the way kwp refuses a duplicate
identity (`kg.py`, lines 660 to 666; the contrast is documented at
[../stages/graph.md](../stages/graph.md)).
