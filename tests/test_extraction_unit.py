"""The unit is a coordinate: one entry of the lists, read with its own passage.

A spelling table used to fold a document's wording onto an entry, and on 641
plans of corpus_m5 it let 3,324 tuples carry an entry their wording
contradicts: "kWh/m²a" filed as kWh/a, "kWp" of a solar plant as a heat load,
"g/kWh" as tonnes a year, "kg" as t with no factor applied. Which entry a
wording means is a reading, made by the model like every other coordinate:
before the parameter, because the entry settles it, and with a passage that
has to carry the wording. What no list holds is refused, with the wording as
the reason, which is where a longer list is written from.

No model, no GPU, no database.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from docpipe.extraction import fields, runner, topup
from docpipe.extraction.pipeline import Row, Source, WorkItem, group_items
from docpipe.extraction.spec import fingerprints, load as load_spec
from docpipe.extraction.verify import Refusal, Verified, verify_tuple

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _spec(name="kwp"):
    return load_spec(json.loads(
        (PROFILES / name / "extraction_spec.json").read_text(encoding="utf-8")))


SPEC = _spec()
ENERGY = SPEC.by_uri["energy_consumption"]
HEAT = SPEC.by_uri["heat_load"]


def test_the_unit_is_one_choice_over_every_numeric_list():
    """One question before the parameter, so its list is every numeric
    parameter's list at once, and beside each entry stands the parameter it
    belongs to: that is the meaning the model decides by."""
    slot = fields.unit_slot(SPEC)
    assert slot.name == fields.UNIT and slot.required and slot.is_closed
    assert slot.question == SPEC.unit_question and slot.question
    listed = {p.uri: set(p.units_accepted) for p in SPEC.parameters
              if p.is_numeric}
    assert {o.label for o in slot.options} == set().union(*listed.values())
    by_label = {o.label: o for o in slot.options}
    assert by_label["kWh/a"].definition == ENERGY.label
    assert by_label["kWh/a"].uri == "kWh/a", "the entry is its own uri"
    # One parameter's list for a stored row that knows its parameter.
    assert {o.label for o in fields.unit_slot(SPEC, HEAT).options} \
        == set(HEAT.units_accepted)
    # A spec without a numeric parameter has nothing to ask.
    assert fields.unit_slot(_spec("scenarios")) is None


def test_a_wording_is_never_looked_up():
    """The factor belongs to an entry, exactly as listed. What a plan's own
    spelling means is the model's reading, not a table's."""
    assert ENERGY.unit_factor("MWh/a") == 1.0
    assert ENERGY.unit_factor("MWh pro Jahr") is None
    assert ENERGY.unit_factor("mwh/a") is None
    assert ENERGY.unit_factor(None) is None
    claim = {"value": 42005, "unit_raw": "MWh/a"}
    assert fields.derive_parameter(SPEC, claim) is None, \
        "a wording alone settles no parameter"
    assert fields.parameter_undecidable(SPEC, claim)
    assert fields.derive_parameter(SPEC, {**claim, "unit": "MWh/a"}) is ENERGY
    assert not fields.parameter_undecidable(SPEC, {**claim, "unit": "MWh/a"})


def test_a_row_whose_unit_no_list_holds_is_refused_with_the_wording():
    """The reason names what the plan wrote: that is the row a longer list is
    written from, and the list is known to be incomplete."""
    text = "| Wohngebaeude | 177 | kWh/m²a |"
    out = verify_tuple({"value": 177, "unit_raw": "kWh/m²a",
                        "unit_state": fields.SAID_UNSTATED, "quote": text},
                       ENERGY, text)
    assert isinstance(out, Refusal)
    assert out.reason.startswith("unit 'kWh/m²a' not in units_accepted (")
    # With no wording at all the noticed one stands in.
    out = verify_tuple({"value": 177, "unit_seen": "kWp",
                        "unit_state": fields.SAID_UNSTATED, "quote": text},
                       HEAT, text)
    assert isinstance(out, Refusal) and "'kWp'" in out.reason


def test_the_period_is_the_chosen_entrys():
    """"450 kWh über das Jahr" is kWh/a because the model read it so; a bare
    entry says the passage stated no period. Nothing looks at the passage a
    second time, and a power has no period to state."""
    text = "Der Verbrauch betrug 450 kWh ueber das Jahr."
    yearly = verify_tuple({"value": 450, "unit": "kWh/a", "unit_raw": "kWh",
                           "unit_state": fields.READ, "quote": text},
                          ENERGY, text)
    assert isinstance(yearly, Verified), getattr(yearly, "reason", yearly)
    assert yearly.tuple["unit"] == "kWh/a" and yearly.tuple["unit_raw"] == "kWh"
    assert not [f for f in yearly.flags if f.startswith("period:")]
    bare = verify_tuple({"value": 450, "unit": "kWh", "unit_raw": "kWh",
                         "unit_state": fields.READ, "quote": text},
                        ENERGY, text)
    assert isinstance(bare, Verified) and "period:unstated" in bare.flags
    power ="| BHKW | 347 | kW |"
    out = verify_tuple({"value": 347, "unit": "kW", "unit_raw": "kW",
                        "unit_state": fields.READ, "quote": power}, HEAT, power)
    assert isinstance(out, Verified)
    assert not [f for f in out.flags if f.startswith("period:")]


def test_the_stamp_carries_the_unit_question_as_its_own_key():
    """Asked once, before the parameter, against every list at once: no
    per-parameter key says this question moved, so it has its own. A
    harvest stamped before it is stale in this key alone."""
    keys = fingerprints(SPEC)
    assert "slot/unit" in keys
    other = _spec()
    other.unit_question = "Welche Einheit steht hier?"
    assert fingerprints(other)["slot/unit"] != keys["slot/unit"]
    assert "slot/unit" not in fingerprints(_spec("scenarios"))
    assert ("slot/unit" in runner.stale(Path("nowhere.stamp.json"), keys))


def _document_batch(text):
    items = [WorkItem(7, None, Source("table", 1, text,
                                      {"document_id": 7, "page": 1}))]
    return group_items(items, max_sources=runner.BATCH_SOURCES)[0]


def _harvester(monkeypatch, rows_reply, unit_answer):
    """The field-wise harvester with both model calls stubbed.

    `unit_answer(row)` is what the model says about a row's unit; every
    other coordinate is answered "not stated", so what these tests see is
    the unit's own path and nothing riding on it.
    """
    asked = []
    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None, bases=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            out = {}
            for slot in slots:
                asked.append(slot.name)
                if slot.name == fields.UNIT:
                    out[slot.name] = {"answers": {r.label: unit_answer(r)
                                                  for r in rows}}
                else:
                    out[slot.name] = {"answers": {
                        r.label: {"value": fields.UNSTATED} for r in rows}}
            return {"fields": out}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    return runner.make_fieldwise_harvester(spec=SPEC, slice_gate={}), asked


def test_the_unit_is_asked_first_and_settles_the_parameter(monkeypatch):
    """The value request names the unit as the passage prints it and no
    more. The entry is read with its own passage, the value request's own
    choice is dropped, and the parameter follows from the entry -- citing
    the passage the unit was read in."""
    text = "| Erdgas | 42.005 | MWh im Jahr 2021 |"
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005,
                              "unit": "MWh", "unit_raw": "MWh im Jahr 2021",
                              "quote": text}],
                  "status": "complete", "need_more": []}
    harvest, asked = _harvester(monkeypatch, rows_reply, lambda row: {
        "value": "MWh/a", "value_raw": "MWh im Jahr 2021", "quote": text})
    row = harvest(_document_batch(text))["tuples"][0]
    assert asked[0] == fields.UNIT, asked
    assert row["unit"] == "MWh/a" and row["unit_state"] == fields.READ
    assert row["unit_raw"] == "MWh im Jahr 2021"
    assert row["unit_quote"] == text and row["unit_source"] == ["table", 1]
    assert row.get("unit_raw_foreign") is True, \
        "the wording does not spell the entry, and that is recorded"
    assert row["parameter"] == ENERGY.uri
    assert row["parameter_state"] == fields.DERIVED
    assert row["parameter_raw"] == "MWh im Jahr 2021"
    assert row["parameter_quote"] == text
    assert "parameter" not in asked, "the entry settled it"


def test_an_entry_answered_in_another_spelling_is_written_as_listed(
        monkeypatch):
    """The answer names an option by any spelling the list folds alike; what
    the row carries is the list's own, because every lookup after this one
    is exact."""
    text = "| Erdgas | 42.005 | MWh/a |"
    rows_reply = {"tuples": [{"source": "Q1", "value": 42005,
                              "unit_raw": "MWh/a", "quote": text}],
                  "status": "complete", "need_more": []}
    harvest, _asked = _harvester(monkeypatch, rows_reply, lambda row: {
        "value": "mwh/a", "value_raw": "MWh/a", "quote": text})
    row = harvest(_document_batch(text))["tuples"][0]
    assert row["unit"] == "MWh/a" and row["parameter"] == ENERGY.uri


def test_a_unit_no_list_holds_stops_the_row_before_any_other_question(
        monkeypatch):
    """The model leaves the value out and gives the wording, as the field
    prompt asks. The row then has no entry, no parameter can take it, and
    nothing else is asked about it: what goes back is refused for the
    wording it carried."""
    text = "| Wohngebaeude | 177 | kWh/m²a |"
    rows_reply = {"tuples": [{"source": "Q1", "value": 177,
                              "unit": "kWh/a", "unit_raw": "kWh/m²a",
                              "quote": text}],
                  "status": "complete", "need_more": []}
    harvest, asked = _harvester(monkeypatch, rows_reply, lambda row: {
        "value_raw": "kWh/m²a"})
    reply = harvest(_document_batch(text))
    row = reply["tuples"][0]
    assert asked == [fields.UNIT], asked
    assert "unit" not in row, "the value request's own choice is gone"
    assert row["unit_state"] == fields.SAID_UNSTATED
    assert row["unit_seen"] == "kWh/m²a"
    assert row["parameter_state"] == fields.OUT_OF_SLICE
    out = verify_tuple(dict(row), ENERGY, text)
    assert isinstance(out, Refusal) and "'kWh/m²a'" in out.reason


def test_a_text_value_is_asked_no_unit(monkeypatch):
    """A planning office has no unit, whatever the value request wrote
    beside it."""
    text = "Bearbeitung durch endura kommunal GmbH"
    rows_reply = {"tuples": [{"source": "Q1", "value": "endura kommunal",
                              "unit": "", "unit_raw": "", "quote": text}],
                  "status": "complete", "need_more": []}
    harvest, asked = _harvester(monkeypatch, rows_reply,
                                lambda row: {"value": fields.UNSTATED})
    row = harvest(_document_batch(text))["tuples"][0]
    assert fields.UNIT not in asked
    assert "unit_state" not in row
    assert row["parameter"] == "planning_organisation"


def test_a_stored_harvest_is_topped_up_parameter_by_parameter():
    """"slot/unit" names one question of the harvest and one coordinate of
    every numeric parameter's rows. The top-up sweeps it per parameter, with
    that parameter's own list, because a stored row knows its parameter."""
    targets = topup.targets_of(SPEC, "slot/unit")
    assert [p.uri for p, _slot in targets] == [
        p.uri for p in SPEC.parameters if p.is_numeric]
    for parameter, slot in targets:
        assert slot.name == fields.UNIT
        assert {o.label for o in slot.options} == set(parameter.units_accepted)
    keys, blocked = topup.actionable(["slot/unit", "slot/parameter"], SPEC)
    assert keys == ["slot/unit"] and blocked == ["slot/parameter"]
    assert topup.targets_of(SPEC, "axis/energy_consumption/carrier")
    assert topup.targets_of(SPEC, "axis/energy_consumption/nothing") == []


# What the verifier read off the spelling of each of the 60 entries of the two
# amounts, before the spec said it itself: the entries that name a period. The
# list is written out here and read from nowhere, so the spec's statements are
# held to what the pattern said and not to themselves.
NAMES_A_PERIOD = {
    "energy_consumption": {
        "kWh/a", "MWh/a", "GWh/a", "Mio. kWh/a", "TWh/a",
    },
    "emission": {
        "Tonnen CO2 im Jahr", "Tonnen CO2 jährlich", "Tonnen CO2 pro Jahr",
        "Tonnen CO2eq/a", "Tonnen pro Jahr", "t CO2-eq./a", "t CO2-eq/a",
        "t CO2-Äq./a", "t CO2-Äq/a", "t CO2-Äquivalente/a", "t CO2/a",
        "t CO2e/a", "t CO2eq/a", "t/a", "t/a CO2eq", "tCO2/a", "Tsd. t/a",
        "kt CO2 pro Jahr", "kt CO2-Äq./a", "kt CO2/a", "kt CO2eq/a", "kt/a",
        "kt/a CO2", "Mio. t CO2/a", "Mio. t CO2eq/a", "Mt/a", "kg/a",
        "kg CO2/a", "kg CO2eq/a",
    },
}
PASSAGE = "Der Wert betrug 450 Einheiten im Berichtsjahr."


def _claim_in(unit):
    return {"value": 450, "unit": unit, "unit_raw": unit,
            "unit_state": fields.READ, "quote": PASSAGE}


def _flags_of(parameter, unit):
    out = verify_tuple(_claim_in(unit), parameter, PASSAGE)
    assert isinstance(out, Verified), getattr(out, "reason", out)
    return [f for f in out.flags if f.startswith("period:")]


def test_the_spec_says_for_each_of_the_60_entries_what_the_pattern_said():
    """34 entries name a period and 26 are plain amounts. Each entry of the
    kwp spec carries that statement, held here to the list above and not to
    anything read off the spelling."""
    entries = 0
    for uri, named in NAMES_A_PERIOD.items():
        parameter = SPEC.by_uri[uri]
        assert named <= set(parameter.units_accepted), \
            f"{uri}: a listed entry is gone from the spec"
        for unit in parameter.units_accepted:
            entries += 1
            assert parameter.names_period(unit) is (unit in named), \
                f"{uri}: {unit!r} says something else than it did"
    assert entries == 60
    assert sum(len(named) for named in NAMES_A_PERIOD.values()) == 34


def test_the_flag_of_every_entry_is_what_it_was():
    """period:unstated on exactly the 26 plain entries, through the verifier
    and not through the statement alone. A power is not an amount over a
    span, and none of its five entries is flagged."""
    plain = 0
    for uri, named in NAMES_A_PERIOD.items():
        parameter = SPEC.by_uri[uri]
        for unit in parameter.units_accepted:
            flags = _flags_of(parameter, unit)
            assert flags == ([] if unit in named else ["period:unstated"]), \
                (uri, unit, flags)
            plain += bool(flags)
    assert plain == 26
    assert HEAT.integrated is False and len(HEAT.units_accepted) == 5
    for unit in HEAT.units_accepted:
        assert _flags_of(HEAT, unit) == [], unit


def test_a_statement_moved_by_hand_moves_the_flag():
    """The same claims against a spec that says "MWh/a" names no period and
    "MWh" names one: the flag follows the statement and not the spelling, so
    the two entries swap, and the entries nobody touched keep theirs."""
    raw = json.loads((PROFILES / "kwp" / "extraction_spec.json").read_text(
        encoding="utf-8"))
    units = next(p for p in raw["parameters"]
                 if p["uri"] == "energy_consumption")["units_accepted"]
    units["MWh/a"]["names_period"] = False
    units["MWh"]["names_period"] = True
    parameter = load_spec(raw).by_uri["energy_consumption"]
    assert _flags_of(parameter, "MWh/a") == ["period:unstated"]
    assert _flags_of(parameter, "MWh") == []
    assert _flags_of(parameter, "GWh/a") == []
    assert _flags_of(parameter, "GWh") == ["period:unstated"]


def _flipped(spec_name="kwp"):
    """The spec with every statement the other way round, nothing else moved."""
    raw = json.loads((PROFILES / spec_name / "extraction_spec.json")
                     .read_text(encoding="utf-8"))
    for parameter in raw["parameters"]:
        for entry in (parameter.get("units_accepted") or {}).values():
            if isinstance(entry, dict) and "names_period" in entry:
                entry["names_period"] = not entry["names_period"]
    return load_spec(raw)


def test_the_statement_enters_no_stamp_key(tmp_path):
    """A stamp written under the spec is current under the spec with every
    statement inverted: not one key of the stamp moves. A unit entry added
    to a list is a changed question, and the same comparison says so."""
    flipped = _flipped()
    assert fingerprints(flipped) == fingerprints(SPEC)
    stamp = tmp_path / "doc.stamp.json"
    stamp.write_text(json.dumps(runner._stamp_current("sha-a", "", SPEC)),
                     encoding="utf-8")
    assert runner.stale(stamp, runner._stamp_current("sha-b", "", flipped)) \
        == []

    raw = json.loads((PROFILES / "kwp" / "extraction_spec.json").read_text(
        encoding="utf-8"))
    next(p for p in raw["parameters"] if p["uri"] == "energy_consumption")[
        "units_accepted"]["PWh/a"] = {"factor": 1e9, "names_period": True}
    assert runner.stale(stamp, runner._stamp_current(
        "sha-a", "", load_spec(raw))) == ["parameter/energy_consumption",
                                          "slot/unit"]


def test_the_statement_is_in_no_request(monkeypatch):
    """Every request body the unit, the parameter and each axis send, down to
    the response format, is the same bytes under the inverted spec. A
    recording client stands where the model would be."""
    def bodies(spec):
        sent: list = []

        def create(**kwargs):
            sent.append(json.dumps(kwargs, sort_keys=True, default=str,
                                   ensure_ascii=False))
            message = SimpleNamespace(content=json.dumps({"answers": {}}))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message)],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        monkeypatch.setattr(runner, "_client", lambda: client)
        ask = runner.make_field_asker()
        text = "| Erdgas | 42.005 | MWh/a |"
        shown = [Source("table", 1, text, {"document_id": 7, "page": 1})]
        rows = [Row("R1", 0, {"value": 42005, "unit_raw": "MWh/a",
                              "quote": text})]
        slots = [fields.parameter_slot(spec), fields.unit_slot(spec)]
        for parameter in spec.parameters:
            slots.extend(fields.axis_slots(parameter))
            if parameter.is_numeric:
                slots.append(fields.unit_slot(spec, parameter))
        for slot in slots:
            ask(shown, rows, [slot])
        sent.append(json.dumps(runner._quantities_payload(spec),
                               sort_keys=True, ensure_ascii=False))
        sent.extend(json.dumps(runner._parameter_payload(p), sort_keys=True,
                               ensure_ascii=False) for p in spec.parameters)
        return sent

    before, after = bodies(SPEC), bodies(_flipped())
    assert len(before) > 20
    assert after == before
    assert any("MWh/a" in body for body in before), \
        "the unit list does reach the request, so equality is not vacuous"
    assert not any("names_period" in body for body in before)
