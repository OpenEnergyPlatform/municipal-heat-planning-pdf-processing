"""The gate between a model's claimed tuples and the extraction output.

Same philosophy as the corrections applier: everything is checked against
material the model does not control, refusals carry a named reason, and
nothing is repaired by guessing.
"""
import pytest

from docpipe.extraction.spec import load
from docpipe.extraction.verify import (Refusal, Verified, canonical_number,
                                       verify_tuple)


def _parameter():
    return load({"parameters": [{
        "uri": "OEO_00050016",
        "label": "final energy consumption value",
        "description": "Endenergieverbrauch je Energieträger, Sektor und "
                       "Jahr, wie im Plan bilanziert.",
        "unit_target": "OEO_00050008",
        "units_accepted": {"kWh/a": 0.001, "MWh/a": 1.0},
        "axes": {
            "carrier": {"vocabulary": {"OEO_00000292": ["Erdgas"],
                                       "OEO_00000211": ["Heizöl", "Heizoel"]}},
            "sector": {"vocabulary": {"OEO_00000214": ["Private Haushalte"]}},
            "year": {"type": "int"},
            "scenario": {"enum": ["status_quo", "trend", "target", "unknown"]},
        },
        "example": {"source": "| Erdgas | 1.036.767.833 | kWh/a in 2020 |",
                    "tuples": [{"value": 1036767833, "unit_raw": "kWh/a"}]},
    }]}).by_uri["OEO_00050016"]


SOURCE = ("| Energieträger | Private Haushalte | | Erdgas | 1.036.767.833 | "
          "| Heizöl | 203.458.519 |")


def _claim(**overrides):
    claim = {"value": 1036767833, "unit_raw": "kWh/a", "carrier": "Erdgas",
             "sector": "Private Haushalte", "year": 2020,
             "scenario": "status_quo",
             "quote": "Erdgas | 1.036.767.833"}
    claim.update(overrides)
    return claim


# ---------------------------------------------------------------------------
# number canonicalisation — the digit-exact backbone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1.036.767.833", "1036767833"),    # German grouping
    ("1,036,767.8", "1036767.8"),       # international
    ("1.234,5", "1234.5"),              # German decimal
    ("1.234", "1234"),                  # lone separator + 3 digits = grouping
    ("1.234,567", "1234.567"),          # mixed kinds: rightmost is decimal
    ("1,234.567", "1234.567"),
    ("1.036.767,833", "1036767.833"),   # 3 decimal digits, still decimal
    ("45 000", "45000"),                # space grouping
    ("42", "42"),
    (1036767833, "1036767833"),
    (1234.50, "1234.5"),
    ("nicht Zahl", None),
])
def test_canonical_number(raw, expected):
    assert canonical_number(raw) == expected


def test_adjacent_numbers_never_merge_into_one_token():
    """'betrug 2020 45.000 MWh' is a year and a value, not 202045000; a
    merged token would refuse the correct claim of 45000."""
    from docpipe.extraction.verify import _numbers_in
    numbers = _numbers_in("Der Endenergieverbrauch betrug 2020 45.000 MWh")
    assert {"2020", "45000"} <= numbers
    assert "202045000" not in numbers
    assert "45000" in _numbers_in("betrug 45 000 MWh im Jahr")


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def test_a_clean_tuple_passes_and_resolves_its_axes():
    out = verify_tuple(_claim(), _parameter(), SOURCE)
    assert isinstance(out, Verified)
    assert out.tuple["carrier"] == "OEO_00000292", "label became the URI"
    assert out.tuple["value_target"] == pytest.approx(1036767.833)
    assert out.tier == "source_only"


def test_a_transposed_digit_is_refused():
    """The whole reason verification exists: the quote is fine, the value
    is not — a VLM or extraction slip swapped two digits."""
    out = verify_tuple(_claim(value=1036767383), _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "does not occur in the quote" in out.reason


def test_a_quote_the_source_never_contained_is_refused():
    out = verify_tuple(_claim(quote="Fernwärme | 999.999"), _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "not found in the source" in out.reason


def test_an_unknown_label_is_kept_but_flagged_not_refused():
    """Out-of-vocabulary is a mapping gap to review, not model misconduct;
    refusing would silently shrink the harvest for every wording variant."""
    out = verify_tuple(_claim(carrier="Klärgas",
                              quote="Erdgas | 1.036.767.833"),
                       _parameter(), SOURCE)
    assert isinstance(out, Verified)
    assert out.tuple["carrier"] is None
    assert out.tuple["carrier_raw"] == "Klärgas", "the raw label survives"
    assert "unmapped:carrier:Klärgas" in out.flags


def test_a_foreign_unit_is_refused():
    out = verify_tuple(_claim(unit_raw="PJ"), _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "units_accepted" in out.reason


def test_the_pdf_lookup_upgrades_the_tier():
    out = verify_tuple(_claim(), _parameter(), SOURCE,
                       pdf_text=lambda: "Erdgas 1 036 767 833 kWh/a")
    assert out.tier == "pdf_verified"


def test_a_scan_without_text_stays_source_only():
    out = verify_tuple(_claim(), _parameter(), SOURCE, pdf_text=lambda: None)
    assert out.tier == "source_only"


def test_a_pdf_with_different_digits_stays_source_only():
    """The case the tier exists for: the transcription says one thing, the
    PDF another. Not refused — exported with the weaker tier, checkable."""
    out = verify_tuple(_claim(), _parameter(), SOURCE,
                       pdf_text=lambda: "Erdgas 1.036.767.999")
    assert out.tier == "source_only"


def test_readoff_is_its_own_tier():
    out = verify_tuple(_claim(quote="Erdgas | 1.036.767.833"), _parameter(),
                       SOURCE, readoff=True)
    assert out.tier == "readoff"


def test_a_wrong_enum_value_is_refused():
    out = verify_tuple(_claim(scenario="Zielbild"), _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "enum" in out.reason
