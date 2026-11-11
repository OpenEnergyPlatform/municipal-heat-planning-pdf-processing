"""
rules.py: The rules this profile's own code follows beyond the core's
(`docpipe/rules.py`). Their values stand in rules.json beside this file,
the file they start from; `docpipe edit` shows them in their tab.

Author: Felix Vossel
"""
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
         decided="2026-11-04", where="profiles/scenarios/completion.py"),
    rule("catalogue_family_names", "flow", "Catalogue of publications",
         "whole",
         "The fewest family names a catalogue hit found by title must share "
         "with the authors read, where both name that many. A larger number "
         "accepts a hit only when more authors agree and rejects more wrong "
         "hits. 1 accepts a hit with one matching author. Decided on "
         "2026-11-05.", least=1,
         decided="2026-11-05", where="profiles/scenarios/completion.py"),
    rule("catalogue_timeout_s", "flow", "Catalogue of publications", "number",
         "The seconds the catalogue is waited for per request. A larger "
         "number waits longer for a slow catalogue. A smaller number gives "
         "up sooner.", least=1,
         where="profiles/scenarios/completion.py"),
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
    rule("model_region_needs_model", "sources", "Regions", "switch",
         "On: a model's own region is offered to a document only when the "
         "paper names that model and the region. Off: it is offered whenever "
         "the paper names the region. Off finds more regions but also "
         "regions of a model the paper never uses. Decided on 2026-11-07.",
         decided="2026-11-07",
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
)
