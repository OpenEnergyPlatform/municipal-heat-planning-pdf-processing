"""A text answer stands in its quote itself, a parameter's value AND a
coordinate's answer, and a wording written beside it does not stand in for
it; a choice from a list is still backed by the document's wording beside
it (owner decisions 2026-11-04). The example of a list a profile closes per
document is read as the run reads it, with the list closed.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
from pathlib import Path

from docpipe.extraction import fields
from docpipe.extraction.pipeline import answer_in_quote
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import value_in_quote


def spec_of(profile):
    return load_spec(json.loads(
        (Path(__file__).resolve().parent.parent / "profiles" / profile
         / "extraction_spec.json").read_text(encoding="utf-8")))


SCENARIOS = spec_of("scenarios")
ABSTRACT = SCENARIOS.by_uri["scenario_abstract"]
SECTOR = SCENARIOS.by_uri["study_sector"]
KWP = spec_of("kwp")
SLOTS = {slot.name: slot for slot in fields.axis_slots(KWP.by_uri["emission"])}

QUOTE = "In climate policy dimension, there are three; baseline, 2.6 W and 2.0 W."


def test_a_text_value_stands_in_its_quote_itself():
    # A description the model wrote, with the passage's word beside it.
    written = {"value": "a scenario of another study", "value_raw": "baseline"}
    assert not value_in_quote(written, ABSTRACT, QUOTE)
    assert value_in_quote({"value": "baseline, 2.6 W and 2.0 W",
                           "value_raw": "anything"}, ABSTRACT, QUOTE)


def test_a_choice_is_backed_by_the_wording_beside_it():
    label = next(iter(SECTOR.vocabulary.values()))[0]
    assert label.casefold() not in QUOTE.casefold()
    assert value_in_quote({"value": label, "value_raw": "climate policy"},
                          SECTOR, QUOTE)
    assert not value_in_quote({"value": label, "value_raw": "transport"},
                              SECTOR, QUOTE)


def test_a_text_coordinate_stands_in_its_quote_itself():
    subject, carrier = SLOTS["subject"], SLOTS["carrier"]
    assert subject.kind == fields.TEXT and carrier.kind == fields.CHOICE
    quote = "Der Wärmebedarf der Wohngebäude liegt bei 300 GWh."
    assert not answer_in_quote(subject, "residential heat demand",
                               "Wärmebedarf", quote)
    assert answer_in_quote(subject, "Wärmebedarf der Wohngebäude", None,
                           quote)
    entry = next(iter(carrier.options))
    assert answer_in_quote(carrier, entry, "Wärmebedarf", quote)


def test_a_list_entry_read_as_free_text_does_not_stand_in_its_quote():
    quote = "In the NDC scenario, emissions peak before 2030."
    free = fields.Slot(name="scenario", kind=fields.TEXT)
    assert not answer_in_quote(free, "NDC_2030", "the NDC scenario", quote)
