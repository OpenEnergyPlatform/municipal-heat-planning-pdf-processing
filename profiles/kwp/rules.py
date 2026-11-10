"""
rules.py: The rules this profile's own code follows beyond the core's
(`docpipe/rules.py`). Their values stand in rules.json beside this file,
the file they start from; `docpipe edit` shows them in their tab.

Author: Felix Vossel
"""
from docpipe.rules import rule

RULES = (
    rule("compute_parts", "flow", "Calculation", "map",
         "The coordinates a number can be split over, each with the entry "
         "that says it is not split there (a total, the whole "
         "municipality); a sum is asked for over the parts of one of them.",
         decided="2026-11-07", where="profiles/kwp/compute.py"),
    rule("compute_least_parts", "flow", "Calculation", "whole",
         "Different parts a group needs at least before its sum is asked "
         "for.", least=2, where="profiles/kwp/compute.py (open_sums)"),
)

# The rules this profile's graph writer (kg.py) follows. Their values stand in
# graph.json beside this file (`docpipe.graphfile`), where `docpipe edit`
# shows them in the Graph tab; a change costs a new writing of the graph from
# the stored harvest, no model.
GRAPH = (
    rule("base", "graph", "Addresses", "text",
         "The address every node of this graph is named under.",
         where="profiles/kwp/kg.py (BASE, mint)"),
    rule("rounding_tolerance", "graph", "One number, several readings",
         "number",
         "How far apart two readings of one number may lie, as a share of "
         "the larger, and still be one rounded statement of it (\"rund 1,6 "
         "Mio. MWh\" beside a table's 1.626.000); the more precise reading "
         "wins. The calculation holds its sums to the same share.",
         least=0, most=0.5, decided="2026-09-23",
         where="profiles/kwp/kg.py (settle), profiles/kwp/compute.py"),
    rule("contested_in_full", "graph", "One number, several readings",
         "switch",
         "Whether numbers that still dispute a node after wording, rounding "
         "and trust stay in the full graph, each a node of its own marked as "
         "contested; the strict graph leaves them out either way.",
         decided="2026-11-02", where="profiles/kwp/kg.py (settle)"),
)
