"""
rules.py: The rules this profile's own code follows beyond the core's
(`docpipe/rules.py`). Their values stand in rules.json beside this file,
the file they start from; `docpipe edit` shows them in their tab.

Author: Felix Vossel
"""
from docpipe.extraction.readings import FRONT_RULES, RULES as READINGS
from docpipe.rules import rule

RULES = (
    rule("not_extracted", "spec", "Never asked", "table",
         "Properties of the OEKG shapes that no field asks for, each left "
         "out on purpose with its reason. The comparison of Spec and shapes "
         "and the profile check do not report them. Give the shape by the "
         "name the compiler gives it and the property by the end of its IRI. "
         "Remove a row to have the property reported as missing again.",
         columns=("shape", "property", "reason"), empty=True,
         decided="2026-10-05",
         where="docpipe/extraction/preflight.py, docpipe edit (sources)"),
    rule("catalogue_address", "flow", "Catalogue of publications", "text",
         "The address of the catalogue (OpenAlex) that fills in a "
         "publication's DOI, year and authors when the paper prints none. "
         "Change it to use another catalogue that answers the same way. "
         "Decided on 2026-11-04.",
         decided="2026-11-04",
         steps=("catalogue",),
         where="profiles/scenarios/completion.py"),
    rule("catalogue_family_names", "flow", "Catalogue of publications",
         "whole",
         "The fewest family names a catalogue hit found by title must share "
         "with the authors read. A larger number accepts a hit only when "
         "more authors agree and rejects more wrong hits. 1 accepts a hit "
         "with one matching author. Where a paper or a hit names fewer "
         "authors than this, the next rule decides. Decided on 2026-11-05.",
         least=1,
         decided="2026-11-05",
         steps=("catalogue",),
         where="profiles/scenarios/completion.py"),
    rule("catalogue_fewer_authors_suffice", "flow",
         "Catalogue of publications", "switch",
         "On: where the paper or the hit names fewer authors than the number "
         "of family names above, all of the authors it does name have to "
         "agree, so a paper with one author is found by that one. Off: the "
         "number is kept as it is, and a paper or a hit with fewer authors "
         "is never accepted by its title. Decided on 2026-11-05.",
         decided="2026-11-05",
         steps=("catalogue",),
         where="profiles/scenarios/completion.py"),
    rule("catalogue_user_agent", "flow", "Catalogue of publications", "text",
         "The name the run gives itself when it asks the catalogue. Empty: "
         "a generic client name. A value of the machine: it is set at the "
         "start or in the project file, never in a file of the profile.",
         empty=True, machine=True,
         steps=("catalogue",),
         where="profiles/scenarios/completion.py"),
    rule("catalogue_key_order", "flow", "Catalogue of publications", "texts",
         "The keys the catalogue is asked for a publication with, in this "
         "order, and the first record any of them finds is the one taken: "
         "the DOI the corpus index holds for the document (index_doi), the "
         "DOI the reading found (doi) and the title (title). The index's DOI "
         "goes first because it belongs to this very file, while a DOI read "
         "off the page can be one the paper cites. Remove a key to never "
         "ask with it. Decided on 2026-11-04.",
         choices=("index_doi", "doi", "title"), decided="2026-11-04",
         steps=("catalogue",),
         where="profiles/scenarios/completion.py (complete)"),
    rule("catalogue_fills", "flow", "Catalogue of publications", "texts",
         "The values of a publication the catalogue fills in where its front "
         "pages give none: its DOI, its year and its authors. Remove one to "
         "never fill it in. Decided on 2026-11-04.", empty=True,
         choices=("publication_doi", "publication_date",
                  "publication_author"), decided="2026-11-04",
         steps=("catalogue", "write"),
         where="profiles/scenarios/completion.py (complete)"),
    rule("catalogue_inherited_flags", "flow", "Catalogue of publications",
         "texts",
         "The remarks of the row a value was found with that a looked-up "
         "value shares with it: those that speak about the row's quote, not "
         "about its own reading. Empty: none is shared.", empty=True,
         steps=("catalogue",),
         where="profiles/scenarios/completion.py (row_of)"),
    rule("catalogue_stop_when_offline", "flow", "Catalogue of publications",
         "switch",
         "On: when the catalogue cannot be reached at all, the run does not "
         "ask it again; each later document of the same run says so at once "
         "instead of waiting out the time. Off: every document tries again. "
         "A new run always tries again.",
         steps=("catalogue",),
         where="profiles/scenarios/completion.py (offline)"),
    rule("catalogue_hits_taken", "flow", "Catalogue of publications",
         "whole",
         "How many hits of the title search are looked at. The first of "
         "them whose authors agree is taken; where none does, the first hit "
         "is taken and then refused. 1: only the first hit counts.",
         least=1,
         steps=("catalogue",),
         where="profiles/scenarios/completion.py (search_hits)"),
    rule("catalogue_title_hit_needs_authors", "flow",
         "Catalogue of publications", "switch",
         "On: a record found by the title is taken only when its authors "
         "agree with the ones read (see the number of family names above); "
         "a record found by its DOI is taken as it is. Off: the first hit of "
         "the title is taken whoever wrote it. Decided on 2026-11-05.",
         decided="2026-11-05",
         steps=("catalogue",),
         where="profiles/scenarios/completion.py"),
    rule("name_word_least_letters", "flow", "Catalogue of publications",
         "whole",
         "How many letters a part of a person's name has to have to count "
         "when the authors the paper names are compared with the catalogue's. "
         "A larger number leaves out initials and short parts of a name.",
         least=1,
         steps=("catalogue",),
         where="profiles/scenarios/completion.py (words, family)"),
    rule("catalogue_timeout_s", "flow", "Catalogue of publications", "number",
         "The seconds the catalogue is waited for per request. A larger "
         "number waits longer for a slow catalogue. A smaller number gives "
         "up sooner.", least=1,
         steps=("catalogue",), where="profiles/scenarios/completion.py"),
    rule("country_groups", "sources", "Regions", "table",
         "Groups of countries that no source lists country by country. Each "
         "row gives the key, the ways the group's name is written (separated "
         "by |), the group it is based on, the countries added to it "
         "(separated by |) and its source. A group has the members of its "
         "base group and the added countries. Used at the next fetch of the "
         "sources.",
         columns=("key", "labels", "union", "joined", "source"), empty=True,
         decided="2026-11-04", where="profiles/scenarios/vocabulary.py"),
    rule("short_forms", "sources", "Regions", "map",
         "Short forms a paper writes for a group that the World Bank lists "
         "under a longer name, as its code -> the short forms. Each short "
         "form becomes another way the group's name is found in a paper. "
         "Used at the next fetch of the sources.",
         of="texts", empty=True, decided="2026-11-04",
         where="profiles/scenarios/vocabulary.py"),
    rule("name_abbreviations", "sources", "Regions", "map",
         "How the sources abbreviate a word of a country's name, written out "
         "before a member is looked up, such as \"St. Lucia\" or \"Congo, "
         "Dem. Rep.\". Add a pair when a member of a group is not found "
         "under its name. Used at the next fetch of the sources.", empty=True,
         where="profiles/scenarios/vocabulary.py"),
    rule("world_labels", "sources", "Regions", "texts",
         "The ways the whole world is written, such as \"global\". The world "
         "is offered as a region for every document, and each of these "
         "labels finds it. Add a label a paper uses for the world. Used at "
         "the next fetch of the sources.",
         where="profiles/scenarios/vocabulary.py"),
    rule("acronym_most_chars", "sources", "Regions", "whole",
         "A region's name in capitals that is no longer than this many "
         "characters is matched by its capitals only, so \"US\" is not found "
         "in \"thus\". A larger number treats longer names in capitals the "
         "same way. 0 matches every name regardless of its capitals.",
         least=0, where="profiles/scenarios/extraction.py"),
    rule("region_whole_words", "sources", "Regions", "switch",
         "On: the name of a region counts as named in a paper only as a "
         "whole word, so Niger is not found in Nigeria, India not in "
         "Indiana. Off: a name counts wherever its letters stand, which "
         "offers regions the paper never names.",
         where="profiles/scenarios/extraction.py"),
    rule("region_search_texts", "sources", "Regions", "texts",
         "The texts of a document that are searched for the regions it "
         "names: its sections, tables, the captions of tables, the "
         "descriptions of images and their captions. Remove one to leave it "
         "out. A region named only in a text that is left out is not "
         "offered.",
         choices=("sections", "tables", "table captions",
                  "image descriptions", "image captions"),
         where="profiles/scenarios/extraction.py (_document_text)"),
    rule("model_region_needs_model", "sources", "Regions", "switch",
         "On: a model's own region is offered to a document only when the "
         "paper names that model and the region. Off: it is offered whenever "
         "the paper names the region. Off finds more regions but also "
         "regions of a model the paper never uses. Decided on 2026-11-07.",
         decided="2026-11-07",
         where="profiles/scenarios/extraction.py"),
    rule("alt_label_language", "spec", "Defaults where the spec says nothing",
         "choice",
         "The language of the ontology's alternative labels that the "
         "vocabulary of the profile keeps: the words its spec is held "
         "against. Used when the vocabulary is fetched again.",
         choices=("de", "en"), where="profiles/scenarios/extraction.py"),
    rule("contract_language", "prompts", "Defaults where the prompt says "
         "nothing", "choice",
         "The language of the core's contract text, which is put into the "
         "prompts of the profile that name a template. It has to be the "
         "language the profile's own prompts are in.",
         choices=("de", "en"), where="profiles/scenarios/extraction.py"),
    rule("prompt_checks", "prompts", "Defaults where the prompt says "
         "nothing", "table",
         "The wordings the check before the run holds the profile's prompts "
         "to. Each row gives what is checked, the prompt, the wording and "
         "whether it has to be there (yes) or must not be (no). The prompts "
         "are in the profile's language, so the wording is too. Empty: no "
         "check beyond the ones the run makes by itself.",
         columns=("what", "prompt", "passage", "required"), empty=True,
         where="profiles/scenarios/extraction.py"),
)

# The rules this profile's graph writer (kg.py) follows. Their values stand in
# graph.json beside this file (`docpipe.graphfile`), where `docpipe edit`
# shows them in the Graph tab; a change costs a new writing of the graph from
# the stored harvest, no model.
GRAPH = (
    rule("base", "graph", "Addresses (IRIs)", "text",
         "The address (IRI) every node of this graph is named under, the "
         "OEKG's own. Changing it renames every node and costs a new writing "
         "of the graph from the stored harvest, no model. A setting of the "
         "run overrides the file.",
         env="OEKG_ID_BASE",
         where="profiles/scenarios/kg.py (BASE, mint)"),
    rule("scenario_types_always", "graph", "Scenarios", "texts",
         "The scenario types, as ontology IDs, that every scenario carries "
         "besides the ones read; for now every IAM scenario gets "
         "OEO_00020517. Add a type to give it to every scenario. Empty: a "
         "scenario carries only the types read. Decided on 2026-11-04.",
         empty=True, decided="2026-11-04",
         where="profiles/scenarios/kg.py (factsheet)"),
    rule("evidence_as", "graph", "Evidence", "choice",
         "Where the place a value was read from goes in the graph. Comment: "
         "Turtle comments above its triple, which the closed shapes accept. "
         "Node: provenance nodes linked to the value, which go beyond the "
         "shapes. A setting of the run overrides the file.",
         choices=("comment", "node"), env="OEKG_EVIDENCE",
         env_flag=("comment", "node"),
         where="profiles/scenarios/kg.py (evidence_for)"),
    rule("front_first_fields", "graph", "One value, several occurrences",
         "texts",
         "The fields for which a value read on the publication's front pages "
         "wins where the shapes allow only one value. The record of the "
         "catalogue comes next, then any other occurrence. Remove a field to "
         "treat all its occurrences alike. Decided on 2026-11-05.",
         decided="2026-11-05",
         where="profiles/scenarios/front.py, profiles/scenarios/kg.py"),
) + FRONT_RULES + READINGS
