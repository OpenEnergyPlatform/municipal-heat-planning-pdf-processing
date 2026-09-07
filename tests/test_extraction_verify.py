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
    claim = {"value": 1036767833, "unit": "kWh/a", "unit_raw": "kWh/a",
             "carrier": "Erdgas",
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
    from docpipe.extraction.verify import numbers_in
    numbers = numbers_in("Der Endenergieverbrauch betrug 2020 45.000 MWh")
    assert {"2020", "45000"} <= numbers
    assert "202045000" not in numbers
    assert "45000" in numbers_in("betrug 45 000 MWh im Jahr")


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def test_a_clean_tuple_passes_and_resolves_its_axes():
    out = verify_tuple(_claim(), _parameter(), SOURCE)
    assert isinstance(out, Verified)
    assert out.tuple["carrier"] == "OEO_00000292", "label became the URI"
    assert out.tuple["value_target"] == pytest.approx(1036767.833)
    assert out.tier == "text_located", "prose is the default owner kind"


def test_a_transposed_digit_is_refused():
    """The whole reason verification exists: the quote is fine, the value
    is not — a VLM or extraction slip swapped two digits."""
    out = verify_tuple(_claim(value=1036767383), _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "does not occur in the quote" in out.reason


def test_a_value_the_source_never_contained_is_refused():
    """The quote may be repaired; the value may not. If the source does not
    hold the number, there is nothing to build evidence out of."""
    out = verify_tuple(_claim(value=999999, quote="Fernwärme | 999.999"),
                       _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "not found in the source" in out.reason


def test_a_retyped_quote_is_rebuilt_from_the_source():
    """The model reads "Heizöl (Dunkelgrau) folgt mit 39.26 GWh/a" and cites
    "Heizöl: 39.26". The finding is true and the citation is not literal.
    Refusing it loses the finding; trusting the wording loses the guarantee.
    So the passage is taken from the source, and the flag says so. Measured on
    the 16-document pilot: 303 of 377 such refusals, against 8 where the value
    was not in the source at all."""
    out = verify_tuple(_claim(quote="Erdgas: 1.036.767.833"),
                       _parameter(), SOURCE)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert "quote_repaired" in out.flags
    assert out.tuple["quote"] in SOURCE
    assert "1.036.767.833" in out.tuple["quote"]


def test_a_value_the_source_holds_twice_is_not_repaired():
    """Repair is only safe where the source leaves no choice. Two occurrences
    mean two possible passages, and picking one would attach the claim to a
    row nobody checked."""
    twice = SOURCE + " | Fernwärme | 1.036.767.833 |"
    out = verify_tuple(_claim(quote="Erdgas: 1.036.767.833"),
                       _parameter(), twice)
    assert isinstance(out, Refusal)
    assert "not found in the source" in out.reason


def test_the_unit_is_a_choice_and_the_spelling_is_evidence():
    """units_accepted is a closed list, so the model picks from it and writes
    the document's own spelling beside it. The spelling is never looked up."""
    out = verify_tuple(_claim(unit="kWh/a", unit_raw="kWh pro Jahr"),
                       _parameter(), SOURCE)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["unit"] == "kWh/a"
    assert out.tuple["unit_raw"] == "kWh pro Jahr"
    assert out.tuple["value_target"] == 1036767.833
    assert not out.flags, "an exact choice needed no judgement"


def test_a_unit_nobody_chose_is_still_read_but_flagged():
    """The fallback while the fleet learns the new field, and a measurement of
    how often it is needed: the spelling is looked up and the tuple says so."""
    claim = _claim(unit_raw="kWh pro Jahr")
    claim.pop("unit", None)
    out = verify_tuple(claim, _parameter(), SOURCE)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["value_target"] == 1036767.833
    assert "unit_not_chosen:kWh pro Jahr" in out.flags


def test_a_unit_of_another_quantity_is_still_refused():
    """Per square metre and per capita are not the same quantity as the total,
    and a normaliser that merged them would put a specific demand into a
    column of absolute ones."""
    for unit in ("kWh/(m²*a)", "kWh/EW", "%"):
        out = verify_tuple(_claim(unit=unit, unit_raw=unit), _parameter(), SOURCE)
        assert isinstance(out, Refusal), unit
        assert "units_accepted" in out.reason


def test_the_model_maps_a_source_wording_onto_a_class():
    """The mapping is the model's job: no plan writes the class names, so an
    exact-string table would drop most of the corpus. The wording it read
    rides along, and the flag makes every such decision reviewable."""
    out = verify_tuple(_claim(carrier="Erdgas", carrier_raw="Gas H"),
                       _parameter(), SOURCE)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["carrier"] == "OEO_00000292"
    assert out.tuple["carrier_raw"] == "Gas H", "how the document said it"
    assert "mapped:carrier:Gas H->OEO_00000292" in out.flags


def test_a_wording_the_spec_already_lists_is_no_decision_and_no_flag():
    out = verify_tuple(_claim(carrier="Erdgas", carrier_raw="Erdgas"),
                       _parameter(), SOURCE)
    assert out.tuple["carrier"] == "OEO_00000292"
    assert not out.flags, "an exact hit needed no judgement"


def test_a_label_that_fits_no_class_keeps_its_wording_instead_of_a_bare_null():
    """'Sonstige' or 'Summe' belong to no class, and the model is told to
    answer null rather than guess. The row still has to say what it saw."""
    out = verify_tuple(_claim(carrier=None, carrier_raw="Sonstige"),
                       _parameter(), SOURCE)
    assert isinstance(out, Verified)
    assert out.tuple["carrier"] is None
    assert out.tuple["carrier_raw"] == "Sonstige"
    assert "unmapped:carrier:Sonstige" in out.flags


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
    out = verify_tuple(_claim(unit="PJ", unit_raw="PJ"), _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "units_accepted" in out.reason


def test_prose_evidence_is_the_top_tier_and_carries_its_rects():
    """Stage 1: the quote sits in the document's own refined text and the
    passage was placed on the page, so a reader can be shown the spot."""
    out = verify_tuple(_claim(), _parameter(), SOURCE,
                       owner_kind="section",
                       locate=lambda quote: [[70.1, 122.4, 520.0, 138.0]])
    assert out.tier == "text_located"
    assert out.rects == [[70.1, 122.4, 520.0, 138.0]]
    assert not out.flags


def test_prose_that_cannot_be_placed_keeps_the_tier_and_says_so():
    """Placing the passage can fail on a page it legitimately belongs to.
    That costs the highlight, not the finding."""
    out = verify_tuple(_claim(), _parameter(), SOURCE,
                       owner_kind="section", locate=lambda quote: None)
    assert out.tier == "text_located"
    assert out.rects is None
    assert "not_located" in out.flags


def test_a_table_is_visual_evidence_however_well_it_reads():
    """Stage 2: a table transcription is a model's reading of a picture.
    Checking a claim against it is model against model, so it never reaches
    the prose tier - a human confirms it by looking at the crop."""
    out = verify_tuple(_claim(), _parameter(), SOURCE, owner_kind="table",
                       locate=lambda quote: [[1, 2, 3, 4]])
    assert out.tier == "visual_source"
    assert out.rects is None, "the crop is the evidence, not a text rectangle"


def test_a_figure_is_visual_evidence_too():
    out = verify_tuple(_claim(quote="Erdgas | 1.036.767.833"), _parameter(),
                       SOURCE, owner_kind="figure")
    assert out.tier == "visual_source"


def test_a_wrong_enum_value_is_refused():
    out = verify_tuple(_claim(scenario="Zielbild"), _parameter(), SOURCE)
    assert isinstance(out, Refusal)
    assert "enum" in out.reason


# ---------------------------------------------------------------------------
# values that are not numbers — an ontology asks for categories and for
# statements of fact, and both are evidenced by the passage they stand in
# ---------------------------------------------------------------------------

def _category_parameter():
    return load({"parameters": [{
        "uri": "MHPO_00020031",
        "label": "Wärmeversorgungsgebietstyp",
        "description": "Der für ein Gebiet ausgewiesene Versorgungstyp, wie "
                       "im Zielszenario des Plans festgelegt.",
        "value_type": "category",
        "vocabulary": {"MHPO_00020032": ["Wärmenetzgebiet", "Wärmenetz"],
                       "MHPO_00020033": ["Einzelversorgungsgebiet"]},
        "axes": {"year": {"type": "int"}},
        "example": {"source": "Das Quartier Nordstadt wird als "
                              "Wärmenetzgebiet ausgewiesen.",
                    "tuples": [{"value": "Wärmenetzgebiet"}]},
    }]}).by_uri["MHPO_00020031"]


CATEGORY_SOURCE = ("Für das Zielszenario 2040 wird das Quartier Nordstadt "
                   "als Wärmenetzgebiet ausgewiesen.")


def test_a_category_value_resolves_to_its_uri():
    out = verify_tuple({"value": "Wärmenetzgebiet", "year": 2040,
                        "quote": "Quartier Nordstadt als Wärmenetzgebiet"},
                       _category_parameter(), CATEGORY_SOURCE)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["value_uri"] == "MHPO_00020032"
    assert out.tier == "text_located"


def test_a_category_wording_the_spec_lacks_is_kept_and_flagged():
    out = verify_tuple({"value": "Prüfgebiet",
                        "quote": "Nordstadt wird als Prüfgebiet geführt"},
                       _category_parameter(),
                       "Die Nordstadt wird als Prüfgebiet geführt.")
    assert isinstance(out, Verified)
    assert out.tuple["value_uri"] is None
    assert out.tuple["value"] == "Prüfgebiet", "the wording survives review"
    assert "unmapped:value:Prüfgebiet" in out.flags


def test_a_category_maps_to_its_class_and_is_evidenced_by_the_wording():
    """The class name almost never appears verbatim in the plan. Checking the
    quote against the class instead of against the wording would refuse every
    mapping the model gets right."""
    out = verify_tuple({"value": "Wärmenetzgebiet",
                        "value_raw": "Wärmeversorgungsgebiet mit Netz",
                        "quote": "Nordstadt: Wärmeversorgungsgebiet mit Netz"},
                       _category_parameter(),
                       "Die Nordstadt: Wärmeversorgungsgebiet mit Netz.")
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["value_uri"] == "MHPO_00020032"
    assert out.tuple["value_raw"] == "Wärmeversorgungsgebiet mit Netz"
    assert "mapped:value:Wärmeversorgungsgebiet mit Netz->MHPO_00020032"         in out.flags


def test_a_category_claim_absent_from_its_quote_is_refused():
    out = verify_tuple({"value": "Einzelversorgungsgebiet",
                        "quote": "Quartier Nordstadt als Wärmenetzgebiet"},
                       _category_parameter(), CATEGORY_SOURCE)
    assert isinstance(out, Refusal)
    assert "does not occur in the quote" in out.reason


def test_a_number_where_the_spec_wants_a_category_is_refused():
    out = verify_tuple({"value": 42, "quote": "Quartier Nordstadt als "
                                              "Wärmenetzgebiet"},
                       _category_parameter(), CATEGORY_SOURCE)
    assert isinstance(out, Refusal)
    assert "non-empty string" in out.reason


def test_a_text_value_needs_no_unit_and_no_vocabulary():
    parameter = load({"parameters": [{
        "uri": "MHPO_00020040",
        "label": "Beschlussfassung",
        "description": "Das Gremium, das den Wärmeplan beschlossen hat, "
                       "wörtlich wie im Dokument benannt.",
        "value_type": "text",
        "axes": {"year": {"type": "int"}},
        "example": {"source": "Der Rat der Stadt hat den Plan beschlossen.",
                    "tuples": [{"value": "Rat der Stadt"}]},
    }]}).by_uri["MHPO_00020040"]
    out = verify_tuple({"value": "Rat der Stadt", "year": 2026,
                        "quote": "Der Rat der Stadt hat den Plan beschlossen"},
                       parameter,
                       "Der Rat der Stadt hat den Plan beschlossen.")
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["value"] == "Rat der Stadt"
    assert "value_target" not in out.tuple, "no unit means no converted value"


def test_a_computed_value_is_backed_by_the_sandbox_output_not_the_quote():
    """A value the pipeline works out cannot stand in the document, so the
    quote proves the INPUTS and the sandbox's printed output proves the
    result. Both are on the tuple; neither is the model's word."""
    source = "Der Gesamtverbrauch liegt bei 604 GWh/a, davon 40 % Fernwärme."
    out = verify_tuple(
        {"value": 241600, "unit": "MWh/a", "computed": True,
         "compute": [{"code": "print(604000 * 0.40)", "stdout": "241600.0",
                      "ok": True}],
         "carrier": "Erdgas", "sector": "Private Haushalte", "year": 2020,
         "scenario": "status_quo", "quote": source},
        _parameter(), source)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert "computed" in out.flags
    assert out.tuple["compute"][0]["code"] == "print(604000 * 0.40)"


def test_a_computed_value_the_sandbox_never_printed_is_refused():
    """Otherwise `computed: true` would be a licence to invent a number."""
    source = "Der Gesamtverbrauch liegt bei 604 GWh/a, davon 40 % Fernwärme."
    out = verify_tuple(
        {"value": 999999, "unit": "MWh/a", "computed": True,
         "compute": [{"code": "print(604000 * 0.40)", "stdout": "241600.0",
                      "ok": True}],
         "carrier": "Erdgas", "sector": "Private Haushalte", "year": 2020,
         "scenario": "status_quo", "quote": source},
        _parameter(), source)
    assert isinstance(out, Refusal)


def test_a_computed_value_still_needs_its_quote_in_the_source():
    out = verify_tuple(
        {"value": 241600, "unit": "MWh/a", "computed": True,
         "compute": [{"code": "x", "stdout": "241600.0", "ok": True}],
         "carrier": "Erdgas", "sector": "Private Haushalte", "year": 2020,
         "scenario": "status_quo", "quote": "steht so nirgends im Dokument"},
        _parameter(), "Der Gesamtverbrauch liegt bei 604 GWh/a.")
    assert isinstance(out, Refusal)
    assert "not found in the source" in out.reason


def test_a_subscript_two_resolves_to_the_class_and_is_not_flagged():
    """End to end for the fold: the plan writes "CO₂-Emissionen" with U+2082,
    the spec lists the digit. Without the fold the axis resolves to nothing
    and the reading is recorded as the model's own judgement call — 132 of
    Kassel's 204 emission readings, over one character.
    """
    parameter = load({"parameters": [{
        "uri": "OEO_00340066",
        "label": "CO2 emission value",
        "description": "Die im Wärmeplan bilanzierte Emissionsmenge je "
                       "Energieträger, Sektor und Jahr.",
        "unit_target": "OEO_00000098",
        "units_accepted": {"t/a": 1.0},
        "axes": {"quantity": {"vocabulary": {
            "OEO_00340066": ["CO2-Emissionen"],
            "OEO_00140083": ["CO2-Äquivalente"]}}},
        "example": {"source": "| Erdgas | 1.234 | t/a |",
                    "tuples": [{"value": 1234, "unit_raw": "t/a"}]},
    }]}).by_uri["OEO_00340066"]
    source = "| CO₂-Emissionen | 1.234 | t/a |"
    out = verify_tuple({"value": 1234, "unit": "t/a", "unit_raw": "t/a",
                        "quantity": "CO₂-Emissionen",
                        "quote": "| CO₂-Emissionen | 1.234 | t/a |"},
                       parameter, source)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    assert out.tuple["quantity"] == "OEO_00340066"
    assert not [f for f in out.flags if f.startswith(("unmapped:", "mapped:"))]


def test_a_bare_amount_says_whether_its_quote_makes_it_a_yearly_one():
    """The year on a tuple is not a label, it is the period the amount is
    integrated over (aggregation OEO_00140070, "sum or integral within a time
    step"). A unit of "GWh" does not say that period, so the passage has to,
    and a graph that writes a year beside a storage capacity has invented it.

    Measured on Kassel: 23 accepted tuples carried a bare GWh or t, 11 of
    them in a sentence saying "pro Jahr", 3 a storage capacity.
    """
    parameter = load({"parameters": [{
        "uri": "OEO_00050016",
        "label": "final energy consumption value",
        "description": "Endenergieverbrauch je Energieträger, Sektor und "
                       "Jahr, wie im Plan bilanziert.",
        "unit_target": "OEO_00050008",
        # A bare amount and a rate, both accepted, as the kwp spec has them:
        # a plan writes "GWh" for a yearly figure as often as "GWh/a".
        "units_accepted": {"kWh": 0.001, "kWh/a": 0.001},
        "axes": {"carrier": {"vocabulary": {"OEO_00000292": ["Erdgas"]}},
                 "sector": {"vocabulary": {"OEO_00000214":
                                           ["Private Haushalte"]}},
                 "year": {"type": "int"},
                 "scenario": {"enum": ["status_quo", "trend", "target",
                                       "unknown"]}},
        "example": {"source": "| Erdgas | 1.036.767.833 | kWh/a in 2020 |",
                    "tuples": [{"value": 1036767833, "unit_raw": "kWh/a"}]},
    }]}).by_uri["OEO_00050016"]
    source = ("Der Waermeverbrauch betrug pro Jahr rund 1.036.767.833 kWh. "
              "Die Speicherkapazitaet liegt bei 203.458.519 kWh.")
    annual = verify_tuple(_claim(unit="kWh", unit_raw="kWh", quote=(
        "Der Waermeverbrauch betrug pro Jahr rund 1.036.767.833 kWh")),
        parameter, source)
    assert isinstance(annual, Verified), getattr(annual, "reason", annual)
    assert "period:annual_in_quote" in annual.flags

    stock = verify_tuple(_claim(value=203458519, unit="kWh", unit_raw="kWh",
                                quote=("Die Speicherkapazitaet liegt bei "
                                       "203.458.519 kWh")),
                         parameter, source)
    assert isinstance(stock, Verified), getattr(stock, "reason", stock)
    assert "period:unstated" in stock.flags

    # A unit that says it itself needs no flag at all.
    stated = verify_tuple(_claim(), _parameter(), SOURCE)
    assert not [f for f in stated.flags if f.startswith("period:")]
