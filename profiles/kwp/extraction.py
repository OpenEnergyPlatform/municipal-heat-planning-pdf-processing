"""Extraction stage wiring: where the kwp spec and its anchors live."""
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")
# The value anchors, frozen. They are not written by the model but taken from
# sections of an earlier full run that really produced a value, because a
# hypothetical sentence only guesses how the corpus writes and these are how it
# writes. Measured against the model's own: 18.0% of the prose values in the
# top 10 sections instead of 11.0%. The axis anchors are still written per run.
ANCHORS_PATH = Path(__file__).with_name("extraction_anchors.json")
