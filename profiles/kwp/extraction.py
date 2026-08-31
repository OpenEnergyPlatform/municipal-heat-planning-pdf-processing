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
# Measured on the 20-plan draft, of 6,763 harvested tuples the serializer took
# 1,294 and dropped 2,510 for a scenario other than target and 1,554 for a
# quantity the graph does not hold. Both are decided by these two axes.
#
# None means "any class the graph takes", which is every entry that does not
# start with out:. A tuple names the answers that keep the row.
SLICE = {"quantity": None, "scenario": ("target",)}
