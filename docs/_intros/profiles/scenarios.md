## The scenario literature corpus

The scenarios profile targets a different corpus than the kwp profile: not
municipal heat plans but publications on climate and energy scenarios,
staged from a crawl over a list of publications, each entry's PDF placed by
hand (`profiles/scenarios/source.py`'s module docstring). Nothing is taken
from outside the papers about the scenarios a publication documents: what a
publication says about its scenarios is read from the publication alone.
`profiles/scenarios/profile.py` sets `document_noun` to `publication`
and two catalog facets a reader can filter by: publication year and venue.
It declares no language:
the language of a request and of an answer is that of the profile's
prompts and sentence files, which is English throughout, as are the
publications. `extraction_spec.json`'s `parameter_question` and every
parameter's label and description are English sentences, the spellings of
its closed lists are the ontology's English alternative labels
(`ALT_LABEL_LANGUAGE = "en"`), and the spec's `_comment` states
that `out:not_in_list`'s meaning is worded in the language of its prompts.
The labels are English because
the model copies a label it is offered as the document's wording, and a
German label never stands in an English quote.

The corpus's own schema carries this identity in one table, applied by
`profiles/scenarios/schema.sql` after the core schema. `DocumentMeta` holds
one row per document with `doi`, `title`, `year`, `venue` and `is_oa`,
filled from the crawl rather than from this profile's own extraction; the
graph stage's cross-check against these columns is covered below.

Trust is graded per document as in kwp: a document whose
`page_text_transcribed` in the database is above zero had pages a model
read because the PDF had no text there, and every value of it gets the
reason `page_transcribed` and at best level B
(`trust.transcribed_documents`, read once per serialization in
`profiles/scenarios/kg.py`). A database without the column, or a document
whose pages nobody looked at, has none. The graph stage's
account of scenario-scope tuples that could not be attached to any scenario
is at [../stages/graph.md](../stages/graph.md).

## What the profile contributes to each stage

Every attribute below is one seam `docpipe/` or a script asks a profile
for by name, described in general on [profiles](../profiles.md); this
table gives this profile's own answer.

| Stage | Module | Attribute | Contributes |
|---|---|---|---|
| File processing | `source.py`, `schema.sql`, `store.py` | `SOURCE`, `DocumentMeta` | the crawl as a `Source`, and the profile's table and upsert helper |
| Layout detection | `profile.py` | `column_layout` | `"auto"`, a two-column journal or report page read column by column |
| Structure assembly | `preprocessing.py` | `HYPHEN_EXCEPTIONS`, `CAPTION_MAX_WORDS`, `CAPTION_START`, `TITLE_EXCLUDE_PREFIXES`, `DIRECTORY_FIGTAB_WORDS`, `DIRECTORY_TITLE_WORDS`, `BIBLIOGRAPHY_TITLE_WORDS` | English hyphenation, caption length, what opens a caption (a word, a number and a colon), heading and bibliography rules; `DIRECTORY_TITLE_WORDS` is the same four words as the other profiles ("inhalt", "verzeichnis", "contents", "directory"), so no verdict moved |
| Preprocessing, refinement, visuals | `prompts/preprocessing`, `prompts/refinement`, `prompts/visuals` | 1, 3 and 6 prompt ids of its own | page transcription, English artefact repair, table and figure captioning; `visuals/caption_keep` is the built-in profile's, inherited byte for byte |
| Refinement, visuals, page transcription, the answer app | `prompts/reading/phrases.json` | ten sentences | the ten sentences these stages and the chat say to the model when its reply was not the one JSON object (`reading.REQUIRED`), in English, the language of the prompts of the first three; `prompts/extraction/phrases.json` is another file, the harvest's own |
| The picker (app) | `catalog.py`, `profile.py` | `CATALOG`, `facets` | publication labels and names (a name opens each line of the values index) and two filters |
| Extraction | `extraction.py`, `prompts/extraction/*.md`, `prompts/extraction/phrases.json` | `SPEC_PATH`, `document_axes`, `document_context`, `PROMPT_CHECKS`, `shapes_files`, `ALT_LABEL_LANGUAGE`, `CONTRACT_LANGUAGE`, 14 prompt ids | the spec (18 parameters, four of them the bundle's tags; its `plan_fields` block holds what a publication settles for all its values, its `works` block the field that finds other works, and the key `beside` of `scenario_region` the entries the region list always has), the per-document region list (the regions a publication names), the 46 sentences the stage writes to the model outside its prompts (the file), the language (`"en"`) of the core's templates its parts files are put together with, and the harvest's own questions |
| The graph | `kg.py`, `oekg_api.py` | `make_serializer`, `make_study_reader`, `dry_run` | OEKG Turtle, the trust wording, and a dry run of the platform's scenario-bundle API (below) |
| The answer app | `inference.py`, `prompts/inference/*.md`, `prompts/inference/phrases.json` | `READOFF_MARKER`, `READOFF_NOTE`, 32 sentences, 11 prompt ids of its own | the English chat wording and the answer loop's own prompts; the twelfth, `json_format`, is the built-in profile's, inherited byte for byte, so the text, its hash and the request are what the copy gave |

A run harvests a publication piece by piece (owner decisions 2026-11-04,
2026-11-08, see [extraction](../stages/extraction.md)): the spec names three
groups, `work`, `year_kind` and `scenario`, each a coordinate of its own, and
English prompts serve it. The publication is cut into pieces of at most `piece_lines`
numbered lines (a number of the flow, which the profile inherits from the default), its figures are written once per run into a caption and numbers
(`extraction/transcribe`), and every piece is read for every parameter, the
publication's own fields (title, authors, date) and its study or its own
scenarios included, in the order a reranker gives the pieces for each
parameter. `extraction/find` asks for all values of a parameter in a piece as
addresses and words, what the publication states for itself and not what it
attributes to other works unless the field asks for them;
`extraction/docfield` asks the fields a publication has once, the thirteen spec
parameters marked `once_per_document` (title, authors, date, DOI, abstract, the
study's organisation, funder, project name and acronym, and the four study fields:
descriptor, sector division, sector and technology), once per publication
with its title page and the best pieces of a budget (`search_pieces`, `listed_field_factor`
times that for a field with a list); and `extraction/coord` answers for each
value, in a request of its own and with no history, each coordinate: the work it
belongs to, the kind of year where it is one, and the scenario it refers to by
the name the publication prints, each as the address of the line that says it and
its words. What does not hold is asked again, as often as the flow says, in a request of its own
(`extraction/follow`, owner decision 2026-11-08). The value of `scenario_label`
and the `scenario` axis are `merged: "scenario"` in the spec (owner decisions
2026-11-06, see [extraction](../stages/extraction.md)): a scenario is read as
free text, the name as the publication prints it, and a value the publication
states for several scenarios is one row per name. Where the words name a group
without naming its scenarios, such as a study with several scenarios or all of
them, the `names` request answers the numbers of the scenarios of the
publication's list they stand for (below), and each is a row holding the words
under the entry "several scenarios" beside the names, with its scenario under
`scenario_means` (owner decision 2026-11-08, replacing that of 2026-11-07, by
which such a value went to no search, made no row per scenario and reached no
scenario of the graph). The reason of the first decision stays: on one paper 120
of 301 values ended "unstated", the publication's word that it does not say, and
each of 25 of them, drawn at random, was stated for such a group, while the
search walked the whole publication for each and found no single scenario (at
least 900 requests, 11.3 M prompt tokens). A field takes the members of a group
unless its spec says `"takes_group": false`, as `scenario_abstract` does. A
value is what its field asks for and never the answer of a coordinate, so a
scenario's description is what the publication says the scenario assumes, not the
scenario's name (owner decision 2026-11-04), and an author value is one author's
name: a person, or the institution where the publication names no person.
`extraction/search` looks for a coordinate the value's own place does not state,
first in the pieces beside the value's and then in the budget of pieces
(`search_pieces`, a number of the flow) a search finds for a sentence as the publication would print the answer, which
`extraction/phrase` writes in a request of its own; it ends `unstated` only after
every piece of the publication was shown, and `exhausted` where the budget ends
first. A find quoted from another passage than the value's own is checked first by
`extraction/check`, which asks whether the line is about this value (owner
decision 2026-11-07). No field of this profile holds numbers, so a table is read
by `find` and `coord` too, as a table is in every profile, and a field with a list
is asked with its list in the `find` and `docfield` requests and the reply names
the entry's number, or `""` with its wording in `value_raw`; a find that names a
group is asked in a list request of its own (`extraction/list`).

The profile has no number coordinates (no unit, `what`, `qualifier` and no
conversion), so a value is asked three coordinates at most. As in kwp (see
[extraction](../stages/extraction.md)), the spec's `plan_fields` block names what a publication
settles for all its values (the key `settings` only, no years), asked once per
publication as a field a document has once, and every request about a value shows
it under `F`; a value only a figure's image shows is read from the lines the
figure was written into (caption and numbers), trust level C. The spec's `works` block names the field that finds the
works a publication presents, compares or cites beside itself (below).

The search that orders a publication's pieces for a parameter ranks with a
sentence the model writes for this publication from the parameter and the
publication's title as the corpus index holds it (`document_context`,
`DocumentMeta.title`), for every parameter (owner decision 2026-11-09).
The abstract was left out in 132 of 164 publications and the date in 60
when they were only asked among all the other rows. Without a title the serializer writes no
node for a publication: 17 of the 164 publications of the run of 2026-10-22
had none, 14 of them because refinement had dropped the title before the
harvest (a heading with no body, or the heading of a section the model
removed; see [refinement](../stages/refinement.md)), and one because the
model left it out of a crowded request.

Two of the 14 extraction prompts, `review` and `example`, are parts files (see
[profiles](../profiles.md), The extraction prompts): each names its template of
the core in its front matter, and `CONTRACT_LANGUAGE = "en"` in
`profiles/scenarios/extraction.py` says that the templates are the English ones.
What scenarios writes itself is its role (scientific publications on climate and
energy scenarios), its examples and the sentences about its own sources. It words
two blocks of the review prompt itself, where the template's sentence fits it
less well: `row_note` is its own note on the first reading and `field_unit` its
unit bullet. It leaves out `field_raw` of the review prompt, which it never had a
sentence for; the example prompt leaves out and words nothing. `python
scripts/render_prompts.py --what-if` shows each block it leaves out put back (see
[Running the pipeline](../running.md)).

The `find` and `docfield` prompts hold a value's words to the piece that carries
it, a clause, a list entry, one table cell, not the whole paragraph: an author
list gives one entry per name, and a title's words are the title itself. Quoting
the whole block for every author used to make the reply to a crowded title page
grow past the token limit and lose the title, authors, DOI and date together.

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
at all (`spec.py`, `_validate_parameter`). Either way, the vocabulary key
stays out of `extraction_spec.json` and a profile hook fills it in before
the harvest runs; where no hook fills it, the coordinate degrades to a
plain wording, the glossary's definition of a dynamic list.

This profile uses the second mechanism once: `scenario_region`'s value is
`vocabulary_dynamic` (`extraction_spec.json`, the `scenario_region`
parameter), picking from a narrowed slice of the OEKG's 249 study regions.
A scenario is not a list at all, apart from two entries beside the names: the
`scenario` axis lists `out:status_quo` under `"beside"` (label "status quo",
spelling "historical"), a value of a past or the current year,
measured, observed or balanced, which belongs to no scenario, as KWP's closed
list has "Bestand", and `out:several` (label "several scenarios", spelling "all
scenarios"), a value stated for several scenarios that the text shown does not
name one by one, which goes to each scenario of the publication's list that the
`names` request finds these words stand for, and to none where it finds none
(owner decisions 2026-11-07 and 2026-11-08, `addressed.SEVERAL`); the `names`
request shows them with what each means (`Axis.beside`, see
[extraction](../stages/extraction.md)). The value of `scenario_label` and the
`scenario` axis of the other four parameters (`scenario_type`,
`scenario_abstract`, `scenario_region`, `scenario_year`, together
`SCENARIO_FIELDS` in `kg.py`) are free text marked `merged: "scenario"`,
the name as the publication prints it, with its quote. `Axis.merged` and
`Parameter.merged` are allowed on a free-text axis or a free-text value
only (`spec.py`, `_validate_parameter` and the axis parser refuse them
anywhere else), and which
entry of the publication's list of scenarios a name is, is asked while the
publication is read, by `addressed.Reader.name_of` (below).

Two coordinates say whether a value is a value of its field at all (spec key
`"keep"`, owner decisions 2026-11-07, see [extraction](../stages/extraction.md)):
`year_kind` of `scenario_year`, "scenario year" with the OEO definition of
scenario year and scenario horizon or "other year", and `work` of the
thirteen `publication_*` and `study_*` fields, "this publication" or "another
work" the publication presents, compares, reviews or cites. Each is asked
first and backed by the words of its quote. A value read with the other entry
is asked nothing further, and stays out of the graph, as does one whose entry
stayed open (`kg.held_back`). A row the catalogue fills (`completion.row_of`) is a
copy of the row it was found with and carries its work.

The list for one document is computed once, before the harvest starts,
by `profiles/scenarios/extraction.py`'s `document_axes(conn, document_id)`,
which returns a dict keyed `scenario_region`. `document_regions`
reads the 249 entries of `regions.json` and keeps only the ones whose
label is mentioned somewhere in this document's own text, and does the
same with the groups of countries in `region_aggregates.json`. A model's own region ("Other Asia",
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
`Images.caption` for the document (`_document_text`, `extraction.py`), so a
country named only in a figure's caption is still quotable. Matching runs
on word boundaries and is casefolded, except for an all-caps label of
four letters or fewer, matched case-sensitively instead: a bare "US" or
"UK" casefolded onto ordinary English prose (the pronoun "us", the
country name "Ukraine") would otherwise be offered as a valid country on
every document of this English-language corpus (`_acronym`, `_mentioned`,
`extraction.py`). The same widening accepts one failure
mode in place of the other: a paper that spells a country only as an
adjective ("Chilean") no longer offers that country as a choice, and the
model falls back to an `out:` sentinel, a visible, counted outcome rather
than a wrong class chosen silently.

The list is never left empty. `document_axes` appends the profile's
`out:` entries to it unconditionally, so a publication naming no
country its own text narrows the region list to still gets a complete list; otherwise the field reverts to open text, exactly
what a closed list exists to avoid (`extraction.py`).

The copy of the spec this list fills in goes with every batch of the
document, so the value request, the field requests, the reading and their
checks offer and hold an answer to the same list the search used. `--review` and
`--recheck` read a harvest file against its own document's list, and leave
alone, stamp included, a document whose list cannot be closed.

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
another copy; `kg.in_graph()` in `profiles/scenarios/kg.py` is the
one guard every later mint, link and type decision runs through, and it refuses
whatever starts with it.

One family of sentinel exists, plus the last entry of each fixed
vocabulary, which behaves the same way. A scenario has none: it is read as
the name the publication prints, so there is no list for it to fall outside.
The key `beside` of the parameter `scenario_region` in the spec offers `out:multiregion` (a named grouping,
such as a trade bloc, that neither the countries nor the groups carry) and
`out:other` (a spatial statement fitting neither). The run appends them after the regions a
document names (`runner.fill_dynamic_axes`), so the list exists also where a
document names none. The world and the
groups of countries are entries of the list (`region_aggregates.json`),
since the OEKG's own region list holds only individual countries and a
scenario is global far more often than national.
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
spelling rather than first (`extraction.py`).

Once chosen, a sentinel is refused a place in the graph outright.
`in_graph()` and `graph_value()` ensure an `out:` value never becomes a
class, an IRI or a link; only the document's own wording, carried
separately as `value_raw`, stands in for it, since the sentinel's own
label describes why nothing fit, not what the document states (`kg.py`). Every chosen sentinel, together with every
`scenario_region`, `scenario_type` or bundle tag row
that resolved no `value_uri`, is counted once into an `out_of_graph`
tally, logged per document and never written as a triple (`kg.py`).

## Names: which names are one scenario

A publication calls one scenario by several names ("the Zero Carbon
scenario" in a sentence, "LCEO Zero Carbon" in a table, an abbreviation in a
figure), and one name can stand for several ("the EC LTS scenarios"). The
reading takes each as printed (`merged`, above) and asks what it means while the
publication is read (`addressed.Names`, `addressed.Reader.name_of`, prompt
`extraction/names`, owner decisions 2026-11-08; trace event `names_ask`). The
publication keeps a list of its scenarios built piece by piece, and a list of the
works it presents beside itself whose first entry is the publication; an entry
belongs to the work its value was read for. A name is asked against the list so far: the
request shows the name, the lines it stands in, its work and the list, and answers
the number of the entry, "new" where the list holds none for it, or 0 where the
words name no such thing (a source note, a year, a number, a sentence): no entry is
made, the row stays read with an empty `scenario_means` or `value_means` and the
graph makes no scenario of it (`scenario_names` in `kg.py`, owner decision
2026-11-09); a new name whose work stayed open is an entry of no work. The entries
beside the names (`out:status_quo`, `out:several`) stand first with what each
means. A name is an entry where both name the same thing, a short and a long form
of one scenario, the same work cited twice; the same name in another work is
another entry, and nothing is merged by its spelling. Each name is asked once per
document, work and wording, and the values whose own names build the list are asked
first. This replaces the naming step of before 2026-11-08, which asked once the
publication was folded, in two steps (a request over all names and one per name
against its nearest by embedding): a probe on one paper had asked each of 240 names
against all 240, 4.4 M input tokens growing with the square of the names, and an
answer that listed the name itself plus its spellings was read as "stands for
several scenarios", so that about 210 of 1,406 rows with a read scenario sat on a
wrong one.

Where the field takes groups (the default) the words of several scenarios give the
numbers of every scenario they stand for, and each is a row of its own. An
answer that is one of the entries beside the names alone keeps that entry and no
scenario. A number that is none of the list is asked again (`name_not_listed`).
Each row keeps the name it was read as and gets the entries of the list it means
under `<coordinate>_means` (`scenario_means`), or `value_means` for its own value
(`scenario_label`). The harvest schema declares `_means` only for merged slots, and
the keys join the evidence and slot key lists that carry a coordinate with the row
(`runner._EVIDENCE`, `topup.SLOT_KEYS`, and the keys `verify` drops with an
unbacked coordinate). A top-up pass does not run the names again, as it does not
run the compute step again. The harvest no longer writes `value_short`, which
marked a short name of its scenario; the graph still reads it from older harvests.

## Works beside the publication

A publication presents, compares, reviews or cites other works, and a value may be
about one of them. Before any value is read, `extraction/work` asks every piece once
which shown lines name another work whose results the lines of the piece state
(`found`) and which line shows that the rest are this publication's own (`own`, an
address or 0); the `works` block of the spec names the field and the details of a
work. Each name is asked against the list of works with the `names` request; each
new work is then asked at its own line for its title, its organisation, its year
and its short name (`works.fields` of the spec), side by side, one `coord` request each
(owner decisions 2026-11-08, h, and 2026-11-09). Those values are values of that
work, with `work` "another work" and the work's name under `work_means`; the
harvest keeps them, the graph does not (`kg.held_back`, since the `work`
coordinate keeps this publication only). A value's own work: a find whose lines
cover the value's line gives that work (a find in a heading, a table's title or
head or a figure's caption covers the whole piece), else the `own` line gives this
publication, else the value asks its work as a choice from the list of works in a
`coord` request (reply entry, address, words); 0, or an entry without a line,
leaves it `unstated`, and a work is never searched. Only the 13 publication and
study fields and the scenario name have a `work` coordinate.

## The graph: one report, one bundle, a factsheet per scenario

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
closure, the live study regions and the groups of countries (the R5, R9 and R10
regions and each model's own regions, with the
codes the model's mapping gives them, from IAMconsortium/common-definitions;
the UN's M49 regions from the SDG API; the World Bank's groups of economies,
the European Union and the OECD among them, from its classification
`CLASS.xlsx`, the two also named "EU" and "OECD" as a paper writes them
(the rule `short_forms` of `rules.json`); and EU28, the World Bank's Union and the United Kingdom, the
one group no source lists, owner decisions 2026-11-04) and the English short
name each region has in the OMG's LCC (`lcc`, its ISO 3166-1 file), rewrites
`vocabulary.json`, `regions.json`, `region_aggregates.json` and
`region_names.json`, and runs the same check `--check` alone runs against
the checked-in snapshot; `region_aliases.json` keeps the hand-written
spellings a document uses that the OEKG's own labels do not, merged in
ahead of the live ones by `merge_regions` (`vocabulary.py`; [../stages/graph.md](../stages/graph.md)). `aggregates` places each
member of a group on an OEKG region by one of its labels, or by a label
with the same words in another order. Accents do not count and the sources'
abbreviations are written out ("St. Lucia", "Lao PDR", the rule `name_abbreviations` of `rules.json`); a
name with a comma whose whole words find no label is placed by the words
before the comma where exactly one region's labels hold them all ("Egypt,
Arab Rep.", "Hong Kong SAR, China"), while "Congo, Dem. Rep." is placed by
its whole words, since two regions hold "Congo". A member no label places, a group
label that is a country's and a label two groups share are counted and
printed, never guessed. A model's region needs its labels to be its own
only among the models of one name ("REMIND" and "REMIND-MAgPIE" are one),
since a paper is offered them only where it names the model; every version
of a model defines its regions again, and the newest one is kept.

Every IRI is minted under `BASE`, the graph rule `base` of
`profiles/scenarios/graph.json` (`https://openenergyplatform.org/ontology/oekg/`);
the setting `OEKG_ID_BASE` wins over the file, applied in `graphfile.load`
(`Rule.env`, `docpipe/rules.py`).
`mint(collection, name)` derives the local part as a UUIDv5 over a
normalised identifying name, never a random UUIDv4, so two serialize
runs over one document mint byte-identical IRIs (`mint`). Where each class of
node lives was read directly off the running OEKG graph over its SPARQL
endpoint, 13,700 triples at the time it was checked (the comment above `COLLECTIONS`): a study report sits under `publication/`, a scenario factsheet
under `scenario/`, a study region under `region/`, and a scenario
bundle, an author, an organisation and a funder directly under the base
with no path segment at all (`COLLECTIONS`).

One document mints exactly one study report and one scenario bundle. The
report's IRI comes from the resolved title; the bundle's comes from
`study_project_name` where the document names a project, and from the
title again where it does not (`kg.py`, `_make_builder`). That title only
keys the IRI: the bundle is labelled with the study's name the document
prints and with nothing where it prints none (owner decision 2026-11-07). A node carries
a has-uuid triple where its shape has that path: today the report and the
factsheet, not the bundle, whose `StudyShape` names none (`bind`,
`uuid_on`).

## Written to the shapes

The serializer does not carry the OEKG shapes a second time. When it is
built, `bind(model)` reads them (`docpipe/extraction/shapemodel.py`), from
the file the last `vocabulary --refresh` pulled (`oekg_shapes` in
the profile's `sources.json`, at the head of `production`). Every path the
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
`SCENARIO_FIELDS` is (`kg.py`), and every passage that
named an entry stands above its triple. An `out:` entry or a wording the
list did not hold writes no triple and is counted in `out_of_graph`, as
for a scenario type (`_make_builder`). The
picked IRIs travel on in the study dict as `bundle["tags"]`.

One factsheet is minted per scenario. For every row of a scenario-scope
parameter, `scenario_names()` in `kg.py` gives the scenarios the row belongs
to: those its name means (`value_means` for a `scenario_label` row,
`scenario_means` for any other), else the scenario of its own name as
printed. A name that does not stand in its own quote mints nothing, and the
row contributes no factsheet, comment or number. A row whose scenario is the
`out:status_quo` entry hangs on no scenario: it is counted under "not in the
graph by choice" and not under "no scenario to hang them on", and its year or
region becomes no scenario's year or region. A name of several scenarios
stands for each of them, so one row lands on several factsheets. A
factsheet's `rdfs:label` is the name the scenario is called by; its
`dc:acronym` is the short name the document prints for it, as a row marked
`value_short` says it (written by the naming step of harvests before
2026-11-08, none now, owner decision 2026-11-07), and the scenario's own name
where there is none (`kg.py`, the factsheet block of
`_make_builder`). Every factsheet
also carries a fixed `OEO_00020517` annotation (`graph.json` rule `scenario_types_always`, read as `kg.ALWAYS_TYPES`; owner
decision 2026-11-06: kept) on top of whatever `scenario_type` classes the
model read off the text.

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
was located on its PDF page, and length (`_pick_one`).
For the title, the authors, the date and the DOI a reading on page 1 or on
the first page the title was read on, the title page behind a cover, goes
first however often other readings agree; where no front page gives one,
the value looked up in the catalogue (below) goes next, and only then a
reading anywhere else (`front.py`: `FRONT_FIELDS`, `in_order`, owner
decisions 2026-11-05). A row looked up keeps the page of the reading it was
found with, so it is known by its flag `catalogue` and never counts as read
on a front page. A chapter that presents other studies prints their titles,
authors, publishers and years, a reference list the DOIs it cites, and the
field descriptions say that only the document's own count. The authors are
those of the first of these that names any, each name a node whose evidence
is every reading of it, wherever it stands. The reading of values says the same of a
passage that presents, reviews or compares another work, beside a reference
list, a footnote and a citation (the `find` prompt). Runner-up spellings are counted `contested` rather
than dropped from the log. A read-only connection then cross-checks the chosen title, date and
DOI against `DocumentMeta`, filled in by the crawl, not this profile's
own extraction; a disagreement is logged and the crawled value is never
substituted into the graph, since a published value must carry its own
evidence, and the crawl's copy is only the cross-check
(`kg.py`'s module docstring; `_crosscheck`).

What the paper's front pages do not print of its DOI and year, often an
authors' manuscript, and its authors where they name none, the run looks up
in OpenAlex, whose records are CC0 (`completion.py`, owner decisions
2026-11-04). A field read only elsewhere is looked up too, since a chapter
on other studies and a reference list print other works' values; one read
on a front page, or looked up already, is not (owner decision 2026-11-05). After a document's fold a program, no model, finds
the record by the first of three keys that finds one: the DOI the corpus
index holds for the document (`DocumentMeta.doi`, read from the run's
database, which `runner.make_completer` hands the profile; the crawl's copy
is the key here, never the value), the DOI the harvest read, then the title the
harvest read, the DOI and the title of the front pages where they were read
there. The index's DOI goes first: it belongs to this very file,
while a DOI read off the page can be one the paper cites, such as a
dataset's (one of 48 records in a measurement on run m6). A record a DOI finds is taken as it is; one the title finds
counts only where two of its authors' family names stand among the authors
read, those of the front pages where it read any there, one where either
side names one author. The DOI, the year and the
authors then become rows of `publication_doi`, `publication_date` and
`publication_author`, the year as the parameter defines it and the full
date in the record. Each row quotes the read value the record was found
with, the printed DOI, else the title, carries the record (`catalogue`) and
is a D for the reason `catalogue`; the graph names the record and its key
above the triple. A value the paper prints on a front page goes first. The first time the
catalogue cannot be reached at all, the run asks it no more (`OFFLINE`),
and every later document says so in its trace at once.

An author is a person the document names as its author; where it names no
person, the institution it names as its own author or issuer (owner
decision 2026-11-04: OEO's `author` is a role of an agent, a person or an
organisation, and the OEKG shape asks only for that class).

Every triple this serializer writes about a value carries, immediately
above it, the passage it was read from. By default that passage is a
flattened Turtle comment (`_evidence_comment`)
rather than a linked node, since the OEKG's node shapes are currently
declared `sh:closed`, and an unanticipated triple on a report or a
factsheet would invalidate the node it documents. The graph rule
`evidence_as` of `profiles/scenarios/graph.json` says which (`"comment"`,
the value there, or `"node"`); the setting `OEKG_EVIDENCE` (a flag: 1 =
node, 0 = comment) wins over the file, applied in `graphfile.load`.
`"node"` switches to a linked
`oekgprov:ExtractionEvidence` node per passage instead, described in the
module's own docstring as provisional and ahead of the shapes, so the file
keeps it off (`EVIDENCE` in `kg.py`, and the module docstring). Either
branch is followed by one rendered trust line, worded in English
throughout `TRUST_PROSE` (`kg.py`). The line carries
`corroborated` where a second passage prints the same value; one passage
read twice counts once, whatever its quotes (owner decision 2026-11-05). The full
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

The dry run follows the profile's graph file (`graph_file_on`, the
argument `made` of `dry_run`) as the written graph does, on the bundle as
the platform would hold it. A class the file does not write leaves the body
with its items. A constraint whose effect is "leave out the value" takes
the item at fault, the bundle where the fault is the bundle's; "leave out
the paper" takes the bundle; "stop" is reported and leaves the body whole.
Addresses are the platform's to mint, so the file's address rules ask
nothing here. An entry the file leaves out has no body and carries what the
file did (`graph_file`), and the report says how many bundles the file
leaves out.

The report counts bundles, not documents and not nodes: the scenarios of
one bundle that lack the same thing are one finding about that bundle. `--write` writes one
request per bundle as JSONL, with its problems and the harvest files it
was read from, the leading one first.

Nothing is ever sent. The module builds no call that writes, and `--live`
is one GET of the public list, followed page by page. The two
inputs, the platform's OpenAPI description and the shapes file, are the
sources of `oekg_api.py`, pulled through `docpipe/upstream.py` at the
head of their branch; the shapes source is the profile's own
(`oekg_shapes` of its `sources.json`), so the dry run and the Turtle are
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
database is required because the study reader opens it, for the cross-check
against `DocumentMeta`.

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
and why, is the rule `not_extracted` (`rules.json`, declared in `rules.py`); `docpipe preflight` warns about any
other property that nobody asks.
The acronym comparison ignores case and outer spaces, which may be
narrower than the platform's own rule.

A body is not the Turtle in another syntax in three places, each on
purpose.

The first is one bundle per project. The Turtle mints a bundle from its
label, so two papers of one project are one bundle with two reports there,
while the body of each paper alone would make two bundles of one study.
`merge` joins the documents whose bundle key is the same (the project's
name, else the title, compared through `kg.normalise`, as the Turtle mints
it) into one request with several study reports. The oldest paper leads:
its spelling of the project's name labels the bundle (no label where no
paper prints one) and its abstract is the bundle's, of which the shapes allow one;
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
body leaves it out (`NOT_YET_LISTED`); so is every type of the graph rule
`scenario_types_always`, the IAM scenario being the only one today. A
factsheet with no other type then has none and is refused for that instead.

The study region is no longer one of them: the Turtle and the body both
write `has study region` (`OEO_00020220`), the path the closed scenario
shape names, the body onto a node of class study region (`oekg_api.py`,
the comment above `API_STUDY_REGION`).

## What is refused

A spec that mismatches the two dynamic mechanisms above refuses to load
before any document is touched: a category parameter naming both a fixed
vocabulary and `vocabulary_dynamic`, or a non-category parameter naming
`vocabulary_dynamic` at all, raises `SpecError` naming the offending
field (`_validate_parameter`, `docpipe/extraction/spec.py`). A `kg` block
whose class is not an identifier shape, or whose predicate is not a
single token, is refused the same way, at spec load time
(`_validate_kg_ids`, `spec.py`); this rule is shared
with the kwp profile. This profile's own `kg.py` calls that same loader
again, on its own copy of the spec, at import time (`load_spec(_SPEC)`,
`kg.py`), so a spec broken this way fails to import the whole
serializer before a single document is processed, not partway through a
run. `kg.py`'s own lookup helpers, `_property`, `_name`, `_class` and
`_kg`, raise `KeyError` for a key the spec does not carry rather than
default silently.

A document whose `publication_title` never resolved is refused whole:
the serializer returns `None` and logs at `INFO` level, before a bundle,
a factsheet or an author node is built (`_make_builder`). Any
other field the shapes demand on the report or the bundle, a date, an
author, an acronym or one of the tags, is not refused this way, only
named in the per-document summary line as a missing required field
(`bind`, `required`); so is the bundle's label where the document prints
no study name, since nothing stands in for it (owner decision 2026-11-07).

A scenario name absent from its own quoted passage is refused as an
identity for every scenario-scope parameter alike: `scenario_names()`
returns no name, and the row contributes no factsheet, comment or number
(`kg.py`); it used to mint a factsheet anyway, which this check exists to
prevent. Rows whose names the `names` request answered with one name land on that
scenario's factsheet, and a name of several scenarios on each of theirs, so
two names the model took for one scenario are one factsheet and a wrong answer
there is the model's, written under the names it was shown.

Every `out:` choice, and every unresolved `scenario_region`,
`scenario_type` or bundle tag row, is refused a place
in the graph the same way: no class, no IRI, no link, only a count and a log
line (`kg.py`). A region wording the document's own
narrowed list did not hold is refused identically rather than minted as
a new individual.

One collision is explicitly not refused, unlike the kwp profile's own
identity guard. A second document minting the same study report or
scenario bundle IRI as an earlier one in the same run, a preprint and
its later journal version sharing one title, for example, is only
logged, naming both documents and the shared IRI; both documents'
single-valued triples land on that one shared subject rather than the
second document being dropped whole, the way kwp refuses a duplicate
identity (`_make_builder`; the contrast is documented at
[../stages/graph.md](../stages/graph.md)).
