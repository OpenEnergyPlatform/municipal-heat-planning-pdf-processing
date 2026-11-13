"""
rules.py: The rules this profile's own code follows beyond the core's
(`docpipe/rules.py`). Their values stand in rules.json beside this file,
the file they start from; `docpipe edit` shows them in their tab.

Author: Felix Vossel
"""
from docpipe.extraction.readings import RULES as READINGS
from docpipe.rules import rule

RULES = (
    rule("compute_parts", "flow", "Calculation", "map",
         "The dimensions a number can be split by, each with the entry that "
         "means it is not split, such as a total or the whole municipality. "
         "A sum is asked for over the parts of one of these dimensions when "
         "the plan does not print it, and a share looks for its whole over "
         "the same dimensions but the area. Add a dimension to have its "
         "sums and shares asked for, and remove one to stop it. Decided on "
         "2026-11-07.",
         decided="2026-11-07", steps=("compute",),
         where="profiles/kwp/compute.py"),
    rule("computed_same_once", "flow", "Calculation", "choice",
         "On: two calculated rows that come to the same number with the "
         "same coordinates, whichever questions came to it, are one "
         "statement, and one row of it stays. Off: every calculated row "
         "stays, however often the same number was worked out. Decided on "
         "2026-11-03.", choices=("on", "off"),
         decided="2026-11-03", steps=("compute",),
         where="profiles/kwp/compute.py (same)"),
    rule("compute_least_parts", "flow", "Calculation", "whole",
         "The fewest different parts a group of numbers needs before the run "
         "asks for their sum. A larger number asks only for sums of more "
         "parts. The sum is not asked for either when the plan prints it, or "
         "when the largest of the numbers already is the sum of the others.",
         least=2, steps=("compute",),
         where="profiles/kwp/compute.py (open_sums)"),
    rule("sum_printed_least_numbers", "flow", "Calculation", "whole",
         "From how many numbers on the largest of a group counts as the sum "
         "of the others, if it equals them within the rounding, so that the "
         "sum is not asked for again. A larger number checks only larger "
         "groups.", least=2, steps=("compute",),
         where="profiles/kwp/compute.py (holds_its_sum)"),
    rule("shown_number_places", "flow", "Calculation", "whole",
         "The decimal places a number is rounded to where it is shown in a "
         "question in the unit of the question. A smaller number shows "
         "rounder numbers, and the model works from them.",
         least=0, steps=("compute",),
         where="profiles/kwp/compute.py (number)"),
    rule("compute_zero_counts", "flow", "Calculation", "switch",
         "On: a number that is zero is added up and offered as the whole of "
         "a share like any other. Off: zero is a part of nothing and the "
         "whole of nothing, and the rows of it that fill the tables of a "
         "plan are left out.", steps=("compute",),
         where="profiles/kwp/compute.py (additive)"),
    rule("compute_needs_frame", "flow", "Calculation", "switch",
         "On: only a number whose year and scenario were both read is added "
         "up or offered as a whole. Off: numbers without them are offered "
         "too, which can add up numbers of different years.",
         steps=("compute",), where="profiles/kwp/compute.py (additive)"),
    rule("compute_out_quantity_counts", "flow", "Calculation", "switch",
         "On: a number whose quantity is one the graph has no class for yet, "
         "such as a specific value, a saving or a useful energy, is added up "
         "and offered as a whole. Off: such numbers are left out.",
         steps=("compute",), where="profiles/kwp/compute.py (additive)"),
    rule("share_ask_without_whole", "flow", "Calculation", "switch",
         "On: a share is asked for even where no total that fits it is "
         "known; the request may find its whole in the plan and take it. "
         "Off: such a share is not asked for. Decided on 2026-11-05.",
         decided="2026-11-05", steps=("compute",),
         where="profiles/kwp/compute.py (open_shares)"),
    rule("compute_mixed_qualifier", "flow", "Calculation", "text",
         "The precision a worked-out number gets when the numbers it is "
         "worked out from are printed with different precision, such as one "
         "with \"ca.\" and one without. It is an entry of the list of the "
         "qualifier. Decided on 2026-11-06.",
         decided="2026-11-06", steps=("compute",),
         where="profiles/kwp/compute.py (qualified)"),
    rule("frame_axes", "spec", "Frame", "texts",
         "The coordinates a document has once, such as its scenario and its "
         "year, in the order they are named. They are found once for each "
         "document, before any value, and every value is asked for one of "
         "the pairs found. Empty: every coordinate is asked for each row.",
         empty=True, where="profiles/kwp/extraction.py (FRAME)"),
    rule("alt_label_language", "spec", "Defaults where the spec says nothing",
         "choice",
         "The language of the ontology's alternative labels that the "
         "vocabulary of the profile keeps: the words its spec is held "
         "against. Used when the vocabulary is fetched again.",
         choices=("de", "en"), where="profiles/kwp/extraction.py"),
    rule("contract_language", "prompts", "Defaults where the prompt says "
         "nothing", "choice",
         "The language of the core's contract text, which is put into the "
         "prompts of the profile that name a template. It has to be the "
         "language the profile's own prompts are in.",
         choices=("de", "en"), where="profiles/kwp/extraction.py"),
    rule("prompt_checks", "prompts", "Defaults where the prompt says "
         "nothing", "table",
         "The wordings the check before the run holds the profile's prompts "
         "to. Each row gives what is checked, the prompt, the wording and "
         "whether it has to be there (yes) or must not be (no). The prompts "
         "are in the profile's language, so the wording is too. Empty: no "
         "check beyond the ones the run makes by itself.",
         columns=("what", "prompt", "passage", "required"), empty=True,
         where="profiles/kwp/extraction.py"),
)

# The rules this profile's graph writer (kg.py) follows. Their values stand in
# graph.json beside this file (`docpipe.graphfile`), where `docpipe edit`
# shows them in the Graph tab; a change costs a new writing of the graph from
# the stored harvest, no model.
GRAPH = (
    rule("base", "graph", "Addresses (IRIs)", "text",
         "The address (IRI) every node of this graph is named under. "
         "Changing it renames every node and costs a new writing of the "
         "graph from the stored harvest, no model.",
         where="profiles/kwp/kg.py (BASE, mint)"),
    rule("rounding_tolerance", "graph", "One number, several occurrences",
         "number",
         "How far apart two occurrences of one number may lie, as a share of "
         "the larger, and still count as one rounded statement, such as "
         "\"rund 1,6 Mio. MWh\" next to a table's 1.626.000. The more "
         "precise one wins. A larger share merges more numbers and may merge "
         "numbers that really differ. 0 merges only equal numbers. The "
         "calculation uses the same share to tell equal numbers and printed "
         "sums.",
         least=0, most=0.5, decided="2026-09-23", steps=("compute",),
         where="profiles/kwp/kg.py (settle), profiles/kwp/compute.py"),
    rule("contested_in_full", "graph", "One number, several occurrences",
         "switch",
         "On: numbers that still disagree about one node after wording, "
         "rounding and trust are compared stay in the full graph, each as a "
         "node of its own marked as contested. Off: they are left out of the "
         "full graph as well. The strict graph leaves them out either way.",
         decided="2026-11-02", where="profiles/kwp/kg.py (settle)"),
) + READINGS
