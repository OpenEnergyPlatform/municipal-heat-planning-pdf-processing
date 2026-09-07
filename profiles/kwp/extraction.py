"""Extraction stage wiring: where the kwp spec and its anchors live."""
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")
# The value anchors, frozen. They are not written by the model but taken from
# sections of an earlier full run that really produced a value, because a
# hypothetical sentence only guesses how the corpus writes and these are how it
# writes. Measured against the model's own: 18.0% of the prose values in the
# top 10 sections instead of 11.0%. The axis anchors are still written per run.
ANCHORS_PATH = Path(__file__).with_name("extraction_anchors.json")

# Which coordinates decide whether a value belongs in the graph at all, in the
# order they are asked, and which answers keep the row. They are asked FIRST
# and alone: a row that falls out here costs three requests instead of eight.
# Measured on the 20-plan draft, of 6,763 harvested tuples the serializer
# dropped 1,554 for a quantity the graph does not hold.
#
# THE SCENARIO NO LONGER GATES. It did, and it was the bigger half: 2,510 of
# those 6,763 tuples were dropped for being a status quo, a trend or a
# potential rather than the target scenario, and dropping them was a decision
# about the graph rather than about the plan. MHPO names all three
# (aggregated inventory analysis MHPO_00020005, aggregated potential analysis
# MHPO_00020006) and OEO names the reference scenarios, so a heat plan's
# inventory belongs in the graph as much as its target does and the row has
# to be asked its coordinates to get there.
#
# What still gates is the quantity, and only through its out: entries: those
# are deliberate non-classes the model chose (a share, a specific figure, a
# generation amount), and no ontology term is waiting for them.
#
# None means "any class the graph takes", which is every entry that does not
# start with out:. A tuple names the answers that keep the row.
SLICE = {"quantity": None}
