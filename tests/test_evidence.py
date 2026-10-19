"""The owner's two checks, for a value and for every coordinate: the quote
stands in a passage that was shown, and the answer stands in the quote; and a
quote long enough to name a place. Plus the closed-list rule (`not_an_option`)
and the base year read by the plan's word for it."""
import json
from pathlib import Path

import pytest

from docpipe.extraction import fields
from docpipe.extraction.pipeline import Row, Source, answer_in_quote, merge_field
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import (Refusal, Verified, canonical_number,
                                       numbers_in, quote_in, verify_tuple)

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
PARAMETER = SPEC.by_uri["energy_consumption"]
SLOTS = {slot.name: slot for slot in fields.axis_slots(PARAMETER)}
CARRIER, YEAR = SLOTS["carrier"], SLOTS["year"]
UNIT = next(iter(PARAMETER.units_accepted))


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("written, decimal, read", [
    ("1.036.767,8", ",", "1036767.8"),
    ("1,036,767.8", ".", "1036767.8"),
    ("1.234", ",", "1234"),
    ("3,251", ",", "3.251"),
    ("3,251", ".", "3251"),
    ("126 656 132", ",", "126656132"),
    (126656132, ",", "126656132"),
    (0.5, ",", "0.5"),
    ("12a", ",", None),
])
def test_a_number_has_one_spelling_whatever_wrote_it(written, decimal, read):
    assert canonical_number(written, decimal) == read


def test_a_dated_year_is_in_its_quote():
    assert "2025" in numbers_in("Stand 09.12.2025")


# ---------------------------------------------------------------------------
# The value: verify_tuple
# ---------------------------------------------------------------------------

SOURCE = ("Endenergieverbrauch nach Energieträgern\n"
          "| Erdgas | 126.656.132 | 520.465.057 |")
QUOTE = "| Erdgas | 126.656.132 | 520.465.057 |"


def claim(**over):
    return {"value": 126656132, "unit": UNIT, "unit_raw": UNIT,
            "quote": QUOTE, **over}


def test_a_value_whose_quote_stands_in_its_source_and_holds_it_is_kept():
    got = verify_tuple(claim(), PARAMETER, SOURCE, owner_kind="table")
    assert isinstance(got, Verified)
    assert got.tuple["parameter"] == "energy_consumption"


def test_typographic_marks_and_spacing_do_not_make_a_second_sentence():
    assert quote_in("Der „Bestand“ – 2020", 'Der "Bestand" - 2020')
    assert quote_in("holzige<br>Festbrennstoffe  12", "holzige Festbrennstoffe 12")
    assert not quote_in("Der Bestand 2020", "Der Bestand 2021")


@pytest.mark.parametrize("over", [
    {"value": 999},                                   # not in the quote
    {"quote": "| Erdgas |"},                          # too short
    {"quote": "| Heizöl | 126.656.132 | 520.465.057 |",  # not in the source
     "value": 777},
    {"unit": "Liter"},                                # not an accepted unit
    {"value": "viel"},                                # not a number
])
def test_a_value_that_fails_either_check_is_refused(over):
    assert isinstance(verify_tuple(claim(**over), PARAMETER, SOURCE,
                                   owner_kind="table"), Refusal)


def test_a_computed_value_needs_the_run_that_printed_it():
    """The quote proves the inputs; the sandbox output proves the result."""
    computed = claim(value=647121189, computed=True,
                     compute=[{"stdout": "647121189\n"}])
    assert isinstance(verify_tuple(computed, PARAMETER, SOURCE,
                                   owner_kind="table"), Verified)
    unprinted = dict(computed, compute=[{"stdout": "1\n"}])
    assert isinstance(verify_tuple(unprinted, PARAMETER, SOURCE,
                                   owner_kind="table"), Refusal)
    said = dict(computed, computed="ja")
    assert isinstance(verify_tuple(said, PARAMETER, SOURCE,
                                   owner_kind="table"), Refusal)


# ---------------------------------------------------------------------------
# A coordinate: answer_in_quote
# ---------------------------------------------------------------------------

def test_a_year_is_its_own_digits_and_not_a_grouped_magnitude():
    assert answer_in_quote(YEAR, 2022, None, "Bilanzjahr 2022: 450 MWh")
    assert not answer_in_quote(YEAR, 2022, None, "Verbrauch 2.022 MWh")
    assert answer_in_quote(YEAR, 2022, None, "Stand 31.12.2022")


def test_a_choice_stands_in_its_quote_under_any_listed_spelling():
    option = next(o for o in CARRIER.options if o.synonyms)
    spelling = option.synonyms[0]
    assert answer_in_quote(CARRIER, option.label, None,
                           f"Verbrauch {spelling} 12 MWh")
    assert not answer_in_quote(CARRIER, option.label, None, "Verbrauch 12 MWh")


def test_a_given_wording_must_stand_in_the_quote_itself():
    option = CARRIER.options[0]
    assert not answer_in_quote(CARRIER, option.label, "Kohlekraft",
                               "Verbrauch Erdgas 12 MWh")


# ---------------------------------------------------------------------------
# A coordinate: merge_field
# ---------------------------------------------------------------------------

SHOWN = [Source("table", 1, "Tabelle 3: Endenergie im Bilanzjahr 2022\n"
                            "| Erdgas | 12 | MWh |", {"document_id": 7}),
         Source("section", 2, "Das Basisjahr der Planung ist 2021.",
                {"document_id": 7})]


def rows(*labels):
    return [Row(label=label, item_index=0, claim={"value": 12})
            for label in labels]


def state(row, slot):
    return row.claim.get(f"{slot.name}_state")


def test_a_backed_answer_is_read_with_its_quote_and_source():
    got = rows("R1")
    merge_field(got, SHOWN, YEAR, {"answers": {"R1": {
        "value": 2022, "quote": "Endenergie im Bilanzjahr 2022"}}})
    assert state(got[0], YEAR) == fields.READ
    assert got[0].claim["year"] == 2022
    assert got[0].claim["year_source"] == ["table", 1]


@pytest.mark.parametrize("answer", [
    {"value": 2022, "quote": "Endenergie im Bilanzjahr 2022 laut Anhang"},
    {"value": 2030, "quote": "Endenergie im Bilanzjahr 2022"},
    {"value": 2022, "quote": "2022"},
    {"value": "2020-2022", "quote": "Endenergie im Bilanzjahr 2022"},
])
def test_an_answer_that_fails_a_check_is_never_read(answer):
    got = rows("R1")
    merge_field(got, SHOWN, YEAR, {"answers": {"R1": answer}})
    assert state(got[0], YEAR) == fields.UNBACKED
    assert "year" not in got[0].claim


def test_an_answer_off_a_closed_list_is_never_read_and_keeps_its_wording():
    got = rows("R1")
    merge_field(got, SHOWN, CARRIER, {"answers": {"R1": {
        "value": "Teilgebiet", "quote": "| Erdgas | 12 | MWh |"}}})
    assert state(got[0], CARRIER) == fields.UNBACKED
    assert got[0].claim["carrier_seen"] == "Teilgebiet"


def test_unstated_needs_no_passage():
    got = rows("R1")
    merge_field(got, SHOWN, CARRIER, {"answers": {"R1": {
        "value": fields.UNSTATED}}})
    assert state(got[0], CARRIER) == fields.SAID_UNSTATED


def test_one_group_answers_many_rows_and_a_read_coordinate_stays_read():
    got = rows("R1", "R2")
    got[1].claim.update(year=2021, year_state=fields.READ)
    merge_field(got, SHOWN, YEAR, {"groups": [{
        "rows": ["R1", "R2", "R9"], "value": 2022,
        "quote": "Endenergie im Bilanzjahr 2022"}]})
    assert got[0].claim["year"] == 2022
    assert got[1].claim["year"] == 2021, "the first backed reading stands"


def test_a_year_named_by_the_plans_word_is_read_from_the_frame():
    """'Basisjahr' without its number: read when the number is a base year
    of the frame, cited from the frame and linked to the row's passage."""
    base = [{"axis": "year", "year": 2021, "state": "base", "index": 0,
             "quote": "Das Basisjahr der Planung ist 2021.",
             "source": ["section", 2]}]
    got = rows("R1")
    merge_field(got, SHOWN, YEAR, {"answers": {"R1": {
        "value": 2021, "value_raw": "Basisjahr",
        "quote": "Das Basisjahr der Planung ist 2021."}}}, bases=base)
    assert state(got[0], YEAR) == fields.READ

    table = [Source("table", 3, "Wärmebedarf im Basisjahr | 12 | MWh |",
                    {"document_id": 7})]
    linked = rows("R1")
    merge_field(linked, table, YEAR, {"answers": {"R1": {
        "value": 2021, "value_raw": "Basisjahr",
        "quote": "Wärmebedarf im Basisjahr"}}}, bases=base)
    assert state(linked[0], YEAR) == fields.READ
    assert linked[0].claim["year_source"] == ["section", 2]
    assert linked[0].claim["year_link_source"] == ["table", 3]

    other = rows("R1")
    merge_field(other, table, YEAR, {"answers": {"R1": {
        "value": 2019, "value_raw": "Basisjahr",
        "quote": "Wärmebedarf im Basisjahr"}}}, bases=base)
    assert state(other[0], YEAR) == fields.UNBACKED, "2019 is no base year"
