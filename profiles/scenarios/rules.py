"""
rules.py: The rules this profile's own code follows beyond the core's
(`docpipe/rules.py`). Their values stand in rules.json beside this file,
the file they start from; `docpipe edit` shows them in their tab.

Author: Felix Vossel
"""
from docpipe.rules import rule

RULES = (
    rule("not_extracted", "spec", "Never asked", "table",
         "Properties of the OEKG shapes no field asks for, each left out on "
         "purpose with its reason: the comparison of spec and shapes and the "
         "profile check do not report them. The shape as the compiler names "
         "it, the property by the end of its IRI.",
         columns=("shape", "property", "reason"), empty=True,
         decided="2026-10-05",
         where="docpipe/extraction/preflight.py, docpipe edit (sources)"),
    rule("catalogue_address", "flow", "Catalogue", "text",
         "Where the catalogue that fills a publication's DOI, year and "
         "authors where the paper prints none answers (OpenAlex).",
         decided="2026-11-04", where="profiles/scenarios/completion.py"),
    rule("catalogue_family_names", "flow", "Catalogue", "whole",
         "Family names a hit by title must share with the authors read, at "
         "least, where both sides name as many.", least=1,
         decided="2026-11-05", where="profiles/scenarios/completion.py"),
    rule("catalogue_timeout_s", "flow", "Catalogue", "number",
         "Seconds the catalogue is waited for.", least=1,
         where="profiles/scenarios/completion.py"),
    rule("country_groups", "sources", "Regions", "table",
         "Groups of countries no source lists by country: the key, the ways "
         "its name is written (separated by |), the group it is made of, the "
         "countries joined to it (separated by |) and where it comes from. "
         "Taken at the next refresh of the sources.",
         columns=("key", "labels", "union", "joined", "source"), empty=True,
         decided="2026-11-04", where="profiles/scenarios/vocabulary.py"),
    rule("short_forms", "sources", "Regions", "map",
         "Short forms a paper writes for a group the World Bank lists under a "
         "longer name, its code -> the short forms. Taken at the next refresh.",
         of="texts", empty=True, decided="2026-11-04",
         where="profiles/scenarios/vocabulary.py"),
    rule("name_abbreviations", "sources", "Regions", "map",
         "How the sources abbreviate a country's name, written out before a "
         "member is looked up (\"St. Lucia\", \"Congo, Dem. Rep.\"). Taken "
         "at the next refresh.", empty=True,
         where="profiles/scenarios/vocabulary.py"),
    rule("world_labels", "sources", "Regions", "texts",
         "The ways the whole world is written; it is offered to every "
         "document. Taken at the next refresh.",
         where="profiles/scenarios/vocabulary.py"),
    rule("acronym_most_chars", "sources", "Regions", "whole",
         "Characters a region's name in capitals has at most to be looked "
         "for with its capitals only (\"US\" is no hit in \"thus\").",
         least=0, where="profiles/scenarios/extraction.py"),
    rule("model_region_needs_model", "sources", "Regions", "switch",
         "Whether a model's own region is offered only where the paper names "
         "the model.", decided="2026-11-07",
         where="profiles/scenarios/extraction.py"),
)

# The rules this profile's graph writer (kg.py) follows. Their values stand in
# graph.json beside this file (`docpipe.graphfile`), where `docpipe edit`
# shows them in the Graph tab; a change costs a new writing of the graph from
# the stored harvest, no model.
GRAPH = (
    rule("base", "graph", "Addresses", "text",
         "The address every node of this graph is named under, the OEKG's "
         "own. A setting wins over the file.", env="OEKG_ID_BASE",
         where="profiles/scenarios/kg.py (BASE, mint)"),
    rule("scenario_types_always", "graph", "Scenarios", "texts",
         "The scenario types every factsheet carries besides the ones read "
         "(Mirjam: \"all IAM scenarios get the annotation for now\").",
         empty=True, decided="2026-11-04",
         where="profiles/scenarios/kg.py (factsheet)"),
    rule("evidence_as", "graph", "Evidence", "choice",
         "Where the passage a value was read in goes: Turtle comments above "
         "its triple, or provenance nodes linked to it (ahead of the shapes, "
         "which are closed). A setting wins over the file.",
         choices=("comment", "node"), env="OEKG_EVIDENCE",
         env_flag=("comment", "node"),
         where="profiles/scenarios/kg.py (evidence_for)"),
    rule("front_first_fields", "graph", "One value, several readings",
         "texts",
         "The fields of which a reading on the publication's front pages "
         "wins where the shapes allow one value, before the catalogue's "
         "record and any other reading.", decided="2026-11-05",
         where="profiles/scenarios/front.py, profiles/scenarios/kg.py"),
)
