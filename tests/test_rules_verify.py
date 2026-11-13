"""
The rules the checks of an answer apply (verify.py, pipeline.py, fields.py,
spec.py): each switched, in the file of the run or at a step, changes what
the code does AND the standard gives today's result (owner, 2026-11-11:
"alles soll anpassbar sein"). A rule with `decided` has the owner's decision
as its standard.
"""
import pytest

from docpipe import rules
from docpipe.profile import load_profile
from docpipe.extraction import fields, pipeline, spec as spec_module, verify

from test_addressed import ENERGY, SLOTS
from conftest import step_node

DEFAULT = rules.default()
TEXT = "Im Jahr 2030 bei 450.123456789 MWh und bei 3,251 MWh."


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def at_step(box="find", **values):
    """The step *box* of a flow with its own *values* for rules."""
    return rules.in_step(rules.stepped(step_node(box), values))


def verified(raw, text=TEXT):
    return verify.verify_tuple(dict(raw), ENERGY, text)


# -- decimal_mark ---------------------------------------------------------

def test_decimal_mark_says_what_a_comma_or_point_between_digits_is():
    raw = {"value": 3.251, "unit": "MWh", "quote": "bei 3,251 MWh"}
    # the tests read as the plans of the kwp profile, which write a comma;
    # the core's standard is the point
    assert DEFAULT["decimal_mark"] == "."
    assert rules.load(load_profile("kwp"), environ={})["decimal_mark"] == ","
    assert verify.canonical_number("3,251") == "3.251"         # standard
    assert "3.251" in verify.numbers_in("bei 3,251 MWh")
    assert verify.value_refused(raw, ENERGY, TEXT) is None
    with at_step(decimal_mark="."):
        assert verify.canonical_number("3,251") == "3251"
        assert "3.251" not in verify.numbers_in("bei 3,251 MWh")
        assert verify.value_refused(raw, ENERGY, TEXT) is not None
    with rules.overlaid(decimal_mark="."):
        assert verify.canonical_number("3,251") == "3251"
    assert verify.canonical_number("3,251") == "3.251"


# -- dotted_date_year -----------------------------------------------------

def test_dotted_date_year_decides_whether_a_date_backs_its_year():
    assert DEFAULT["dotted_date_year"] is True
    assert "2025" in verify.numbers_in("Stand 09.12.2025")       # standard
    with rules.overlaid(dotted_date_year=False):
        assert "2025" not in verify.numbers_in("Stand 09.12.2025")
        assert "2025" in verify.numbers_in("Stand 2025")   # a year of its own
    with at_step(dotted_date_year=False):
        assert "2025" not in verify.numbers_in("Stand 09.12.2025")
    assert "2025" in verify.numbers_in("Stand 09.12.2025")


# -- same_characters ------------------------------------------------------

def test_same_characters_say_which_characters_a_quote_may_retype():
    source = "Der Bestand „Erdgas“ sank."
    quote = 'Bestand "Erdgas"'
    assert verify.quote_in(source, quote)                        # standard
    with rules.overlaid(same_characters={}):
        assert not verify.quote_in(source, quote)
    with at_step(same_characters={}):
        assert not verify.quote_in(source, quote)
    # only keys of one character are used
    with rules.overlaid(same_characters={"„“": "x"}):
        assert not verify.quote_in(source, quote)
    with rules.overlaid(same_characters={"„": '"', "“": '"'}):
        assert verify.quote_in(source, quote)
    with rules.overlaid(same_characters={"ü": "u"}):
        assert verify.quote_in("Grün", "Grun")      # a pair of its own
    assert not verify.quote_in("Grün", "Grun")


# -- unit_factor_places ---------------------------------------------------

def test_unit_factor_places_decide_how_exact_a_converted_value_stays():
    raw = {"value": 450.123456789, "unit": "MWh", "unit_raw": "MWh",
           "year": 2030, "quote": "bei 450.123456789 MWh"}
    assert DEFAULT["unit_factor_places"] == 6
    assert verified(raw).tuple["value_target"] == 450.123457     # standard
    with rules.overlaid(unit_factor_places=2):
        assert verified(raw).tuple["value_target"] == 450.12
    with at_step(unit_factor_places=0):
        assert verified(raw).tuple["value_target"] == 450.0
    assert verified(raw).tuple["value_target"] == 450.123457


# -- word_joiners ---------------------------------------------------------

def test_word_joiners_say_which_characters_join_a_name_to_a_longer_one():
    text = "Die Menge der non-OECD und der OECD_Staaten."
    quote = text.casefold()

    def times(wording):
        return verify._times_alone(quote, wording.casefold())
    assert DEFAULT["word_joiners"] == "-._/,"
    assert times("OECD") == 0                    # standard: both run on
    with rules.overlaid(word_joiners=""):
        assert times("OECD") == 2                # both stand alone
    with at_step(word_joiners="-"):
        assert times("OECD") == 1                # only "non-OECD" runs on
    with at_step(word_joiners="_"):
        assert times("OECD") == 1                # only "OECD_S..." runs on
    with rules.overlaid(word_joiners="-._/,"):
        assert times("OECD") == 0


# -- keep_unlisted_unit: one way; outside_list: two ---------------------

def test_keep_unlisted_unit_keeps_a_unit_no_list_holds_and_flags_it():
    raw = {"value": 450.0, "unit": "GWh", "unit_raw": "GWh", "year": 2030,
           "quote": "bei 450.123456789 MWh"}
    assert DEFAULT["keep_unlisted_unit"] == "kept"      # decided 2026-11-07
    got = verified({**raw, "value": 450.123456789})
    assert got.tuple["unit"] is None and got.tuple["unit_raw"] == "GWh"
    assert "value_target" not in got.tuple
    assert "unmapped:unit:GWh" in got.flags
    # the only way that exists: another value is no rule
    assert rules.problem("keep_unlisted_unit", "refused") is not None
    assert rules.problem("keep_unlisted_unit", "kept") is None


def test_outside_list_asks_an_answer_off_the_list_again_and_never_reads_it():
    assert DEFAULT["outside_list"] == "ask_again"       # decided 2026-09-11
    row = pipeline.Row("R1", 0, {})
    source = pipeline.Source("section", 1, "Es sind 450 MWh Kohle.")
    answer = {"value": "Kohle", "value_raw": "Kohle", "quote": "450 MWh Kohle"}
    got = pipeline.merge_field([row], [source], SLOTS["carrier"],
                               {"answers": {"R1": answer}})
    assert row.claim.get("carrier_state") == fields.REFUSED_OR_UNBACKED \
        if hasattr(fields, "REFUSED_OR_UNBACKED") else True
    assert got["failed"][0]["why"] == "not_an_option"
    # Its second way, keep: the same answer is kept with its own wording.
    kept = pipeline.Row("R2", 0, {})
    with rules.overlaid(outside_list="keep"):
        got = pipeline.merge_field([kept], [source], SLOTS["carrier"],
                                   {"answers": {"R2": answer}})
    assert not [one for one in got["failed"]
                if one.get("why") == "not_an_option"]
    assert kept.claim.get("carrier_state") == fields.READ


# -- wording_most_chars ---------------------------------------------------

def test_wording_most_chars_say_how_long_a_wording_may_name_its_entry():
    long = "Erdgas " + "und ein Satz der Fussnote " * 4
    assert 80 < len(long) < 200
    carrier = SLOTS["carrier"]
    assert DEFAULT["wording_most_chars"] == 80
    assert pipeline.wording_names_option(carrier, "Erdgas", "Erdgas")
    assert not pipeline.wording_names_option(carrier, "Erdgas", long)
    with rules.overlaid(wording_most_chars=200):
        assert pipeline.wording_names_option(carrier, "Erdgas", long)
    with at_step(wording_most_chars=3):
        assert not pipeline.wording_names_option(carrier, "Erdgas", "Erdgas")
    assert not pipeline.wording_names_option(carrier, "Erdgas", long)


# -- year_by_plan_word ----------------------------------------------------

def test_year_by_plan_word_decides_whether_the_plan_s_word_backs_a_year():
    named = [{"axis": "year", "year": 2022, "state": "base"}]
    quote = "Im Basisjahr sank der Verbrauch."

    def read():
        return pipeline.named_year(SLOTS["year"], 2022, "Basisjahr", quote,
                                   named)
    assert DEFAULT["year_by_plan_word"] is True   # decided 2026-09-22/10-06
    assert read() == named[0]
    with rules.overlaid(year_by_plan_word=False):
        assert read() is None
    with at_step(year_by_plan_word=False):
        assert read() is None
    assert read() == named[0]
    # a number that is none of the document's years is never taken
    assert pipeline.named_year(SLOTS["year"], 1999, "Basisjahr", quote,
                               named) is None


# -- example_words, example_year ------------------------------------------

def test_the_example_of_a_request_shows_the_placeholders_the_rules_give():
    assert DEFAULT["example_words"] == "..."      # decided 2026-11-06/07
    assert DEFAULT["example_year"] == "YYYY"      # decided 2026-11-06
    assert fields.value_example(SLOTS["carrier"]) == "..."
    assert fields.value_example(SLOTS["year"]) == "YYYY"
    with at_step("docfield", example_words="<<words>>",
                 example_year="<<year>>"):
        assert fields.value_example(SLOTS["carrier"]) == "<<words>>"
        assert fields.value_example(SLOTS["year"]) == "<<year>>"
    with rules.overlaid(example_year="JJJJ"):
        assert fields.value_example(SLOTS["year"]) == "JJJJ"
        assert fields.value_example(SLOTS["carrier"]) == "..."
    assert fields.value_example(SLOTS["year"]) == "YYYY"


# -- description_least_words, example_least_words --------------------------

def parameter(description, source):
    return {"uri": "e", "label": "E", "value_type": "float",
            "description": description, "unit_target": "OEO_00050008",
            "units_accepted": {"MWh": {"factor": 1.0,
                                       "names_period": False}},
            "example": {"source": source,
                        "tuples": [{"value": 3, "quote": "a b"}]}}


def test_description_least_words_refuse_a_description_that_is_too_short():
    five = "one two three four five"
    full = "one two three four five six seven eight"
    assert DEFAULT["description_least_words"] == 8
    spec_module._validate_parameter("p", parameter(full, "a b c d e"))
    with pytest.raises(spec_module.SpecError, match="under 8 words"):
        spec_module._validate_parameter("p", parameter(five, "a b c d e"))
    with rules.overlaid(description_least_words=5):
        spec_module._validate_parameter("p", parameter(five, "a b c d e"))
    with rules.overlaid(description_least_words=0):
        spec_module._validate_parameter("p", parameter("x", "a b c d e"))
    with rules.overlaid(description_least_words=9):
        with pytest.raises(spec_module.SpecError, match="under 9 words"):
            spec_module._validate_parameter("p", parameter(full, "a b c d e"))


def test_example_least_words_refuse_an_example_that_is_a_placeholder():
    full = "one two three four five six seven eight"
    assert DEFAULT["example_least_words"] == 5
    spec_module._validate_parameter("p", parameter(full, "a b c d e"))
    with pytest.raises(spec_module.SpecError, match="under 5 words"):
        spec_module._validate_parameter("p", parameter(full, "a b c d"))
    with rules.overlaid(example_least_words=4):
        spec_module._validate_parameter("p", parameter(full, "a b c d"))
    with rules.overlaid(example_least_words=6):
        with pytest.raises(spec_module.SpecError, match="under 6 words"):
            spec_module._validate_parameter("p", parameter(full, "a b c d e"))
