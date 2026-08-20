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
    assert out.tier == "text_located", "prose is the default owner kind"


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
    out = verify_tuple(_claim(unit_raw="PJ"), _parameter(), SOURCE)
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
