"""
rules.py: The rules this profile's own code follows beyond the core's
(`docpipe/rules.py`). Their values stand in rules.json beside this file,
the file they start from; `docpipe edit` shows them in their tab.

Author: Felix Vossel
"""
from docpipe.rules import rule

RULES = (
    rule("compute_parts", "flow", "Calculation", "map",
         "The dimensions a number can be split by, each with the entry that "
         "means it is not split, such as a total or the whole municipality. "
         "A sum is asked for over the parts of one of these dimensions when "
         "the plan does not print it. Add a dimension to have its sums asked "
         "for, and remove one to stop it. Decided on 2026-11-07.",
         decided="2026-11-07", where="profiles/kwp/compute.py"),
    rule("compute_least_parts", "flow", "Calculation", "whole",
         "The fewest different parts a group of numbers needs before the run "
         "asks for their sum. A larger number asks only for sums of more "
         "parts. The sum is not asked for either when the plan prints it, or "
         "when the largest of three or more numbers already is the sum of "
         "the others.", least=2, where="profiles/kwp/compute.py (open_sums)"),
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
         least=0, most=0.5, decided="2026-09-23",
         where="profiles/kwp/kg.py (settle), profiles/kwp/compute.py"),
    rule("contested_in_full", "graph", "One number, several occurrences",
         "switch",
         "On: numbers that still disagree about one node after wording, "
         "rounding and trust are compared stay in the full graph, each as a "
         "node of its own marked as contested. Off: they are left out of the "
         "full graph as well. The strict graph leaves them out either way.",
         decided="2026-11-02", where="profiles/kwp/kg.py (settle)"),
)
