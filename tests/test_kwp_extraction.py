"""The kwp extraction profile: spec, prompts, and the MHPKG serializer."""
import re
import sqlite3

import pytest

from docpipe.extraction.queries import expand
from docpipe.extraction.spec import load
from docpipe.extraction.verify import Verified, verify_tuple
from docpipe.profile import load_profile
from profiles.kwp import kg
from profiles.kwp.extraction import SPEC_PATH

SPEC = load(SPEC_PATH)
UUID5 = r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


# --- spec ------------------------------------------------------------------

def test_the_spec_carries_the_mail_parameters_plus_the_equivalent_class():
    """Mirjam's three, and the class a BISKO balance actually reports:
    OEO_00340066 is CO2 alone, while the plans overwhelmingly print
    Treibhausgase in CO2 equivalents, which OEO has as OEO_00140083."""
    assert [p.uri for p in SPEC.parameters] == [
        "OEO_00050016", "OEO_00050018", "OEO_00340066", "OEO_00140083"]


@pytest.mark.parametrize("parameter", SPEC.parameters, ids=lambda p: p.uri)
def test_every_example_verifies_against_its_own_source(parameter):
    """The example doubles as the golden test: a spec whose own few-shot
    would be refused by verify_tuple teaches the model a refusable habit."""
    for raw in parameter.example["tuples"]:
        outcome = verify_tuple(dict(raw), parameter, parameter.example["source"])
        assert isinstance(outcome, Verified), getattr(outcome, "reason", outcome)


@pytest.mark.parametrize("parameter", SPEC.parameters, ids=lambda p: p.uri)
def test_the_examples_teach_exhaustive_extraction(parameter):
    """Every value cell in the example source has its tuple — a few-shot
    that extracts a subset teaches the model to under-harvest, and off-
    vocabulary columns are the lesson, not the exception."""
    import re as re_mod
    from docpipe.extraction.verify import canonical_number
    claimed = {canonical_number(t["value"]) for t in parameter.example["tuples"]}
    quoted_rows = {t["quote"] for t in parameter.example["tuples"]}
    for row in quoted_rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        for cell in cells[1:]:
            if re_mod.fullmatch(r"[\d.,]+", cell):
                assert canonical_number(cell) in claimed, f"{cell} has no tuple"
    outcomes = [verify_tuple(dict(t), parameter, parameter.example["source"])
                for t in parameter.example["tuples"]]
    flags = [f for o in outcomes for f in o.flags]
    assert flags, "the example must exercise the wording machinery at all"


def test_the_examples_show_both_mapping_and_refusing_to_map():
    """The two lessons the few-shot has to teach at once: a wording the class
    list does not contain still gets mapped when it clearly fits, and a label
    that fits no class stays empty instead of being forced into one."""
    flags = [f for parameter in SPEC.parameters
             for t in parameter.example["tuples"]
             for f in verify_tuple(dict(t), parameter,
                                   parameter.example["source"]).flags]
    assert any(f.startswith("mapped:") for f in flags)
    assert any(f.startswith("unmapped:") for f in flags)


# --- prompts ---------------------------------------------------------------

def _profile():
    return load_profile("kwp")


def test_query_templates_expand_for_every_parameter():
    from docpipe import prompts
    prompt = prompts.load("extraction/queries", _profile())
    templates = [line for line in prompt.text.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
    assert templates
    for parameter in SPEC.parameters:
        probes = expand(templates, parameter)
        assert len(probes) > len(templates), "the carrier axis must fan out"
        assert len(set(probes)) == len(probes)
        assert not any("{" in p for p in probes)


def test_the_harvest_prompt_states_the_contract():
    from docpipe import prompts
    prompt = prompts.load("extraction/harvest", _profile())
    assert prompt.meta.get("max_tokens")
    for needle in ('"tuples"', '"quote"', '"unit_raw"', '"indicator_label_raw"',
                   '"carrier_raw"', 'classes'):
        assert needle in prompt.text, f"prompt never names {needle}"


# --- IRI minting against the published reference ---------------------------

def test_value_minting_matches_the_schema_repo_reference():
    """mint_slice.py's exact coordinate string must yield its exact UUID —
    proves the whole uuid5 chain, namespace derivation included. Their
    kassel_valid.ttl carries a878a3a1-… instead, which mint_slice.py cannot
    produce from any plausible coordinate variant: a stale hand-typed UUID
    on the schema side, reported, not reproduced."""
    heatplan = f"{kg.BASE}heatplan/AGS_06611000_2024-03-15"
    coordinates = "|".join([heatplan, f"{kg.OEO}OEO_00050016",
                            f"{kg.OEO}OEO_00000292", "2030",
                            f"{kg.OEO}OEO_00140070"])
    assert kg.mint("value", coordinates).endswith(
        "78153046-c4c2-5cae-a61c-56c70e57e5a5")


def test_normalise_and_organisation_minting_match_the_reference():
    for label in ("Kassel Wärme Ingenieurbüro",
                  "  kassel   wärme  ingenieurbüro  ",
                  "Kassel Wärme Ingenieurbüro GmbH"):
        assert kg.mint("organisation", kg.normalise(label)).endswith(
            "2d4f4ae8-ea0f-575c-9a76-8dcf377042af"), label
    stripped = kg.mint("organisation", kg.normalise("Kassel Warme Ingenieurburo"))
    assert not stripped.endswith("2d4f4ae8-ea0f-575c-9a76-8dcf377042af")


# --- indicator mapping (D6) -------------------------------------------------

def test_unclear_beats_accept_and_no_label_is_unclear():
    assert kg.accepted_indicator("OEO_00050016", "Endenergieverbrauch")
    assert not kg.accepted_indicator("OEO_00050016", "Endenergiebedarf")
    assert not kg.accepted_indicator(
        "OEO_00050016", "witterungskorrigierter Endenergieverbrauch")
    assert not kg.accepted_indicator("OEO_00050016", None)


def test_a_greenhouse_gas_label_belongs_to_the_equivalent_class():
    """The split that decides whether the emissions parameter yields anything:
    a THG or CO2-Äq label is a CO2 equivalent, and only a plain CO2 label is
    OEO's CO2 emission value."""
    for label in ("THG-Emissionen", "Treibhausgasemissionen",
                  "CO2-Äquivalente", "CO2e"):
        assert kg.accepted_indicator("OEO_00140083", label), label
        assert not kg.accepted_indicator("OEO_00340066", label), label
    assert kg.accepted_indicator("OEO_00340066", "CO2-Emissionen")
    assert not kg.accepted_indicator("OEO_00140083", "CO2-Emissionen")
    assert not kg.accepted_indicator("OEO_00140083", "THG-Vermeidung")


# --- serializer -------------------------------------------------------------

def _database(tmp_path):
    db = tmp_path / "kwp.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                published TEXT, is_current INTEGER);
        CREATE TABLE DocumentMeta (document INTEGER, municipality_ags TEXT);
        CREATE TABLE Municipalities (ags TEXT, name TEXT);
        INSERT INTO Documents VALUES (857, 'waermeplan_kassel_20240315.pdf',
                                      '2024-03-15', 1);
        INSERT INTO DocumentMeta VALUES (857, '06611000');
        INSERT INTO Documents VALUES (858, 'waermeplan_kassel_alt.pdf',
                                      '2024-03-15', 0);
        INSERT INTO DocumentMeta VALUES (858, '06611000');
        INSERT INTO Municipalities VALUES ('06611000', 'Kassel');
    """)
    conn.commit()
    conn.close()
    return db


def _row(**overrides):
    row = {"kind": "tuple", "parameter": "OEO_00050016", "value": 241000,
           "value_target": 241.0, "unit_raw": "kWh/a",
           "carrier": "OEO_00000292", "sector": None, "year": 2030,
           "scenario": "target", "spatial_scope": "municipality",
           "indicator_label_raw": "Endenergieverbrauch",
           "tier": "pdf_verified", "provenance": {"document_id": 857}}
    row.update(overrides)
    return row


def test_the_serializer_emits_only_the_target_scenario_slice(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(),
        _row(scenario="status_quo"),
        _row(spatial_scope="sub_area"),
        _row(indicator_label_raw="Endenergiebedarf"),
        _row(year=None),
    ])
    assert f"<{kg.BASE}heatplan/AGS_06611000_2024-03-15>" in ttl
    assert re.search(rf"{kg.BASE}value/{UUID5}", ttl)
    assert '"241.0"^^xsd:float' in ttl
    assert '"2030"^^xsd:integer' in ttl
    assert "oeo:OEO_00000523 oeo:OEO_00000292" in ttl
    assert ttl.count("a oeo:OEO_00050016") == 1, "the four skipped rows never arrive"
    assert "Kommunale Wärmeplanung Kassel 2024" in ttl


def test_a_carrier_oeo_does_not_call_a_carrier_is_counted_out(tmp_path):
    """`covers energy carrier` has range `energy carrier`, and district heating
    is a heat transfer, not one. The value is kept in the harvest and left out
    of the TTL rather than asserted against the range."""
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(carrier="OEO_00000132"),          # Fernwärme
        _row(carrier="OEO_00000139", value_target=5.0),   # Strom
        _row(),                                # Erdgas, the one that survives
    ])
    assert ttl.count("a oeo:OEO_00050016") == 1
    assert "OEO_00000132" not in ttl and "OEO_00000139" not in ttl


def test_a_value_conflict_on_one_coordinate_drops_every_claimant(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    ttl = serializer("waermeplan_kassel_20240315", [
        _row(), _row(value_target=242.0), _row(),
        _row(sector="OEO_00000214", value_target=99.0),
    ])
    assert ttl.count("a oeo:OEO_00050016") == 1, "only the sectored value survives"
    assert '"99.0"^^xsd:float' in ttl and '"241.0"' not in ttl


def test_documents_without_target_tuples_or_identity_yield_none(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    assert serializer("waermeplan_kassel_20240315",
                      [_row(scenario="status_quo")]) is None
    assert serializer("unknown_plan", [_row()]) is None


def test_a_second_document_claiming_the_same_identity_is_refused(tmp_path):
    """A stale duplicate harvest (register-link rename) mints the same value
    IRIs; merging it would put two magnitudes on one node."""
    serializer = kg.make_serializer(_database(tmp_path))
    assert serializer("waermeplan_kassel_20240315", [_row()]) is not None
    assert serializer("waermeplan_kassel_alt",
                      [_row(value_target=999.0,
                            provenance={"document_id": 858})]) is None


def test_the_prefix_block_is_emitted_once_per_run(tmp_path):
    serializer = kg.make_serializer(_database(tmp_path))
    first = serializer("waermeplan_kassel_20240315", [_row()])
    second = serializer("waermeplan_kassel_20240315", [_row()])
    assert first.startswith("@prefix rdfs:")
    assert "@prefix" not in second
