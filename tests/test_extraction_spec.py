"""The extraction spec is the contract everything downstream leans on.

A wrong spec must die at load time naming its field — not three GPU hours
into a batch, and never by silently extracting on a guessed vocabulary.
"""
import pytest

import docpipe.extraction.spec as spec_mod

from docpipe.extraction.spec import Spec, SpecError, load


def _minimal():
    return {"parameters": [{
        "uri": "OEO_00050016",
        "label": "final energy consumption value",
        "description": "Endenergieverbrauch: die vom Endverbraucher bezogene "
                       "Energiemenge je Träger, Sektor und Jahr.",
        "unit_target": "OEO_00050008",
        "units_accepted": {"kWh/a": 0.001, "MWh/a": 1.0, "GWh/a": 1000.0},
        "axes": {
            "carrier": {"vocabulary": {"OEO_00000292": ["Erdgas", "Gas"]}},
            "year": {"type": "int", "required": True},
            "scenario": {"enum": ["status_quo", "trend", "target", "unknown"]},
        },
        "example": {
            "source": "| Erdgas | 126.656.132 | 520.465.057 | 1.036.767.833 | kWh/a |",
            "tuples": [{"value": 126656132, "unit_raw": "kWh/a",
                        "carrier": "OEO_00000292"}],
        },
    }]}


def test_a_valid_spec_loads_and_indexes_by_uri():
    spec = load(_minimal())
    assert isinstance(spec, Spec)
    assert "OEO_00050016" in spec.by_uri
    axis = spec.by_uri["OEO_00050016"].axes["carrier"]
    assert axis.label_to_uri()["erdgas"] == "OEO_00000292"


def test_a_stub_description_is_refused():
    """The description becomes the model's definition of the parameter."""
    bad = _minimal()
    bad["parameters"][0]["description"] = "Endenergie."
    with pytest.raises(SpecError, match=r"description"):
        load(bad)


def test_an_empty_vocabulary_is_refused():
    bad = _minimal()
    bad["parameters"][0]["axes"]["carrier"]["vocabulary"] = {}
    with pytest.raises(SpecError, match=r"axes\.carrier"):
        load(bad)


def test_one_label_may_not_map_to_two_uris():
    """An ambiguous label would make every later match a coin toss."""
    bad = _minimal()
    bad["parameters"][0]["axes"]["carrier"]["vocabulary"]["OEO_99999999"] = ["erdgas"]
    with pytest.raises(SpecError, match=r"already maps"):
        load(bad)


def test_an_axis_is_exactly_one_kind():
    bad = _minimal()
    bad["parameters"][0]["axes"]["carrier"]["type"] = "int"
    with pytest.raises(SpecError, match=r"exactly one"):
        load(bad)


def test_the_example_is_mandatory():
    """It is the prompt's few-shot and the runner's golden test."""
    bad = _minimal()
    del bad["parameters"][0]["example"]
    with pytest.raises(SpecError, match=r"example"):
        load(bad)


def test_an_example_tuple_with_a_foreign_unit_is_refused():
    bad = _minimal()
    bad["parameters"][0]["example"]["tuples"][0]["unit_raw"] = "PJ"
    with pytest.raises(SpecError, match=r"units_accepted"):
        load(bad)


def test_two_spellings_that_normalise_alike_may_not_carry_two_factors():
    """The guard sat in the branch where units is always empty, so it never ran.

    A numeric parameter is the only kind that carries units, so this is where
    the check belongs: "kWh / a" and "kWh/a" are one spelling to the verifier,
    and letting them carry 0.001 and 1000.0 would multiply a value by a million
    depending on which one the document happened to print.
    """
    bad = _minimal()
    bad["parameters"][0]["units_accepted"]["kWh / a"] = 1000.0
    with pytest.raises(SpecError, match=r"same spelling to the verifier"):
        load(bad)


def test_two_spellings_of_one_unit_are_the_point_and_still_load():
    ok = _minimal()
    ok["parameters"][0]["units_accepted"]["kWh / a"] = 0.001
    assert "kWh / a" in load(ok).by_uri["OEO_00050016"].units_accepted


def test_duplicate_parameter_uris_are_refused():
    bad = _minimal()
    bad["parameters"].append(bad["parameters"][0])
    with pytest.raises(SpecError, match=r"duplicate"):
        load(bad)


def test_a_missing_file_names_the_path(tmp_path):
    with pytest.raises(SpecError, match=r"not found"):
        load(tmp_path / "nope.json")


def test_a_subscript_two_is_the_same_spelling_as_the_digit():
    """A plan prints "CO₂-Emissionen" with U+2082; every spec, schema and
    ontology writes it with the digit. Casefold alone leaves the two strings
    different, so 132 of Kassel's 204 emission readings were recorded as the
    model's own judgement call over one character — and a reply that answers
    with the document's spelling resolves to no class at all.
    """
    from docpipe.extraction.spec import fold_label
    raw = _minimal()
    axes = raw["parameters"][0]["axes"]
    axes["carrier"] = {"vocabulary": {"OEO_00340066": ["CO2-Emissionen"]}}
    axis = load(raw).parameters[0].axes["carrier"]
    table = axis.label_to_uri()
    assert table[fold_label("CO₂-Emissionen")] == "OEO_00340066"
    assert table[fold_label("co2-emissionen")] == "OEO_00340066"
    # It folds the two spellings and nothing else: a label that differs in a
    # real character stays a different label.
    assert fold_label("CO2 Emissionen") not in table
    assert fold_label("CO2-Emissionen je Kopf") not in table


def test_two_spellings_of_one_label_may_not_map_to_two_classes():
    """The same fold, on the guard side: "CO₂-Emissionen" under one class and
    "CO2-Emissionen" under another is the coin toss the load-time check
    exists to refuse, and casefold alone let it through."""
    raw = _minimal()
    raw["parameters"][0]["axes"]["carrier"] = {"vocabulary": {
        "OEO_00340066": ["CO2-Emissionen"],
        "OEO_00140083": ["CO₂-Emissionen"]}}
    with pytest.raises(SpecError) as excinfo:
        load(raw)
    assert "already maps to" in str(excinfo.value)


def test_an_entry_may_carry_what_it_means_and_a_list_still_loads():
    """Two spec forms, one meaning. The list is the short form and stays the
    common one; the object adds the sentence the list could not carry."""
    raw = _minimal()
    raw["parameters"][0]["axes"]["carrier"] = {"vocabulary": {
        "OEO_00000292": {"label": "Erdgas", "spellings": ["Gas"],
                         "definition": "Natural gas is a gas mixture."},
        "OEO_00000211": ["Heizöl", "Öl"]}}
    axis = load(raw).parameters[0].axes["carrier"]
    assert axis.vocabulary == {"OEO_00000292": ["Erdgas", "Gas"],
                               "OEO_00000211": ["Heizöl", "Öl"]}
    assert axis.definitions == {
        "OEO_00000292": "Natural gas is a gas mixture."}
    assert axis.label_to_uri()["gas"] == "OEO_00000292"


@pytest.mark.parametrize("entry,message", [
    ({"spellings": ["Gas"]}, "needs a label"),
    ({"label": "", "spellings": []}, "needs a label"),
    ({"label": "Erdgas", "spellings": "Gas"}, "spellings must be a list"),
    ({"label": "Erdgas", "definition": "  "}, "definition must be a sentence"),
])
def test_a_broken_entry_object_dies_at_load_time_naming_its_field(entry,
                                                                  message):
    raw = _minimal()
    raw["parameters"][0]["axes"]["carrier"] = {
        "vocabulary": {"OEO_00000292": entry}}
    with pytest.raises(SpecError) as excinfo:
        load(raw)
    assert message in str(excinfo.value)


# ---------------------------------------------------------------------------
# Fingerprints
#
# The stamp was one sha over the whole spec file, so one new energy carrier
# made all 1.082 documents stale at once: about 93 GPU hours to re-read a
# corpus over a word. The ontology this spec is written against keeps moving,
# so that bill would come again and again. These hold what a per-parameter and
# per-axis fingerprint has to answer to -- and, just as important, what it
# must not.
# ---------------------------------------------------------------------------
def _spec_of(**overrides):
    parameter = {
        "uri": "energy", "label": "Endenergie",
        "description": "Endenergieverbrauch je Energietraeger, Sektor und "
                       "Jahr, wie im Plan bilanziert.",
        "value_type": "float", "unit_target": "kWh",
        "units_accepted": {"kWh/a": 0.001, "MWh/a": 1.0},
        "example": {
            "source": "| Erdgas | 42.005 | MWh/a | im Jahr 2020 |",
            "tuples": [{"value": 42005, "unit_raw": "MWh/a",
                        "carrier": "Erdgas", "year": 2020}]},
        "axes": {"carrier": {"question": "Welcher Traeger?",
                             "evidence": "own", "required": True,
                             "vocabulary": {"oeo:1": {"label": "Erdgas",
                                                      "spellings": ["Gas"],
                                                      "definition": "Ein Gas."}}},
                 "year": {"question": "Welches Jahr?", "type": "int"}},
    }
    parameter.update(overrides)
    return spec_mod.load({"parameters": [parameter]})


def test_a_new_option_moves_its_own_axis_and_nothing_else():
    """The whole point: a carrier added to the list must open the carrier
    coordinate, not the year, not the parameter, and not another parameter."""
    before = spec_mod.fingerprints(_spec_of())
    after = spec_mod.fingerprints(_spec_of(axes={
        "carrier": {"question": "Welcher Traeger?", "evidence": "own",
                    "required": True,
                    "vocabulary": {"oeo:1": {"label": "Erdgas",
                                             "spellings": ["Gas"],
                                             "definition": "Ein Gas."},
                                   "oeo:2": {"label": "Klaergas"}}},
        "year": {"question": "Welches Jahr?", "type": "int"}}))
    changed = [k for k in before if before[k] != after[k]]
    assert changed == ["axis/energy/carrier"]
    assert set(before) == set(after)


@pytest.mark.parametrize("field,value", [
    ("question", "Welcher Energietraeger steht in dieser Zeile?"),
    ("evidence", "any"),
    ("required", False),
])
def test_everything_the_model_sees_is_in_the_axis_fingerprint(field, value):
    """A fingerprint that ignores the question is a fingerprint that says a
    document read under another question is still current."""
    axes = {"carrier": {"question": "Welcher Traeger?", "evidence": "own",
                        "required": True, "vocabulary": {"oeo:1": ["Erdgas"]}},
            "year": {"question": "Welches Jahr?", "type": "int"}}
    before = spec_mod.fingerprints(_spec_of(axes=axes))
    moved = {**axes, "carrier": {**axes["carrier"], field: value}}
    after = spec_mod.fingerprints(_spec_of(axes=moved))
    assert before["axis/energy/carrier"] != after["axis/energy/carrier"], field
    assert before["axis/energy/year"] == after["axis/energy/year"]


def test_a_spelling_and_a_definition_are_part_of_the_question():
    """Both reach the model: the spellings are what a plan may write, the
    definition is what the term means. A run under a different one is a
    different reading."""
    base = {"carrier": {"question": "q", "vocabulary": {
                "oeo:1": {"label": "Erdgas", "spellings": ["Gas"],
                          "definition": "Ein Gas."}}}}
    first = spec_mod.fingerprints(_spec_of(axes=base))["axis/energy/carrier"]
    spelling = spec_mod.fingerprints(_spec_of(axes={"carrier": {
        "question": "q", "vocabulary": {"oeo:1": {
            "label": "Erdgas", "spellings": ["Gas", "Methan"],
            "definition": "Ein Gas."}}}}))["axis/energy/carrier"]
    meaning = spec_mod.fingerprints(_spec_of(axes={"carrier": {
        "question": "q", "vocabulary": {"oeo:1": {
            "label": "Erdgas", "spellings": ["Gas"],
            "definition": "Ein anderes Gas."}}}}))["axis/energy/carrier"]
    assert len({first, spelling, meaning}) == 3


def test_the_written_order_of_a_list_is_not_part_of_the_question():
    """The offered list is a set, and so is the set of options and the set of
    axes. A fingerprint that moves when someone sorts the JSON differently
    marks the corpus stale for nothing, and a signal that fires for nothing
    is a signal everyone learns to ignore."""
    one = spec_mod.fingerprints(_spec_of(axes={"carrier": {
        "question": "q", "vocabulary": {"oeo:1": ["Erdgas", "Gas", "Methan"]}}}))
    other = spec_mod.fingerprints(_spec_of(axes={"carrier": {
        "question": "q", "vocabulary": {"oeo:1": ["Methan", "Gas", "Erdgas"]}}}))
    assert one == other

    # Same options, written in the other order. A hash over the dict as it
    # happens to be built would differ, and every document would be stale
    # after a reformat of the spec file.
    first = spec_mod.fingerprints(_spec_of(axes={"carrier": {
        "question": "q", "vocabulary": {"oeo:1": ["Erdgas"],
                                        "oeo:2": ["Klaergas"]}}}))
    second = spec_mod.fingerprints(_spec_of(axes={"carrier": {
        "question": "q", "vocabulary": {"oeo:2": ["Klaergas"],
                                        "oeo:1": ["Erdgas"]}}}))
    assert first == second

    # And the parameter, whose own fields are written in whatever order the
    # profile keeps them in.
    assert (spec_mod.fingerprints(_spec_of())["parameter/energy"]
            == spec_mod.fingerprints(_spec_of(
                units_accepted={"MWh/a": 1.0, "kWh/a": 0.001}))["parameter/energy"])


def test_the_axes_are_not_in_the_parameter_fingerprint():
    """Otherwise every axis change is a parameter change and the split buys
    nothing: the parameter key would move whenever any coordinate did, which
    is the corpus-wide staleness this whole thing exists to avoid."""
    before = spec_mod.fingerprints(_spec_of())
    # Three ways an axis can move: its question, its offered list, and one
    # more axis existing at all. None of them is the parameter's business.
    for axes in (
        {"carrier": {"question": "eine ganz andere Frage", "evidence": "own",
                     "required": True,
                     "vocabulary": {"oeo:1": {"label": "Erdgas",
                                              "spellings": ["Gas"],
                                              "definition": "Ein Gas."}}},
         "year": {"question": "Welches Jahr?", "type": "int"}},
        {"carrier": {"question": "Welcher Traeger?", "evidence": "own",
                     "required": True,
                     "vocabulary": {"oeo:1": {"label": "Erdgas",
                                              "spellings": ["Gas"],
                                              "definition": "Ein Gas."},
                                    "oeo:2": {"label": "Klaergas"}}},
         "year": {"question": "Welches Jahr?", "type": "int"}},
        {"carrier": {"question": "Welcher Traeger?", "evidence": "own",
                     "required": True,
                     "vocabulary": {"oeo:1": {"label": "Erdgas",
                                              "spellings": ["Gas"],
                                              "definition": "Ein Gas."}}},
         "year": {"question": "Welches Jahr?", "type": "int"},
         "sector": {"question": "Welcher Sektor?",
                    "vocabulary": {"oeo:9": ["Haushalte"]}}},
    ):
        after = spec_mod.fingerprints(_spec_of(axes=axes))
        assert before["parameter/energy"] == after["parameter/energy"], axes
        assert (before["axis/energy/carrier"] != after["axis/energy/carrier"]
                or "sector" in axes), axes


def test_a_unit_or_an_example_moves_the_parameter():
    """Both are in the request: the accepted units are the answer space of
    the unit field, and the example is what the model imitates."""
    before = spec_mod.fingerprints(_spec_of())["parameter/energy"]
    units = spec_mod.fingerprints(
        _spec_of(units_accepted={"MWh/a": 1.0}))["parameter/energy"]
    example = spec_mod.fingerprints(_spec_of(
        example={"source": "| Heizoel | 17.300 | MWh/a | 2020 |",
                 "tuples": [{"value": 17300, "unit_raw": "MWh/a",
                             "carrier": "Erdgas", "year": 2020}]}
    ))["parameter/energy"]
    assert len({before, units, example}) == 3


def test_a_fingerprint_is_the_same_on_the_next_run():
    """It is compared against a file written hours or weeks earlier. A hash
    that depends on dict order or on id() would mark everything stale once
    and teach everyone to pass --force-stale by reflex."""
    assert spec_mod.fingerprints(_spec_of()) == spec_mod.fingerprints(_spec_of())
    for value in spec_mod.fingerprints(_spec_of()).values():
        assert len(value) == 64 and value == value.lower()


def test_the_two_fingerprints_are_independent_of_each_other():
    """`fingerprints` is the interface, but the split is the point, so both
    halves are named here: a parameter's fingerprint and its axes' are
    computed from disjoint parts and one is never derived from the other."""
    spec = _spec_of()
    parameter = spec.parameters[0]
    axis = parameter.axes["carrier"]
    of_parameter = spec_mod.parameter_fingerprint(parameter)
    of_axis = spec_mod.axis_fingerprint(axis)
    assert of_parameter != of_axis
    assert len(of_parameter) == len(of_axis) == 64
    keys = spec_mod.fingerprints(spec)
    assert keys["parameter/energy"] == of_parameter
    assert keys["axis/energy/carrier"] == of_axis


def test_value_fingerprint_is_empty_for_a_parameter_with_no_list():
    """The key only exists where there is an answer space to name. An empty
    string for every numeric parameter would put a key in the stamp that
    stands for nothing and can never go stale."""
    assert spec_mod.value_fingerprint(_spec_of().parameters[0]) == ""
    assert "value/energy" not in spec_mod.fingerprints(_spec_of())


def test_a_category_parameters_definitions_are_part_of_its_question():
    """The meaning reaches the model when it picks, exactly as an axis's
    does. Left out of the fingerprint, a term whose definition was rewritten
    leaves every stamped document current -- the drift the key exists to
    catch, in the one answer space that is not an axis."""
    def _category(vocabulary):
        return spec_mod.load({"parameters": [{
            "uri": "scenario_type", "label": "Art des Szenarios",
            "description": "Die Art eines Szenarios, gewaehlt aus der Liste "
                           "der Klassen, die dieses Feld zulaesst.",
            "value_type": "category", "vocabulary": vocabulary, "axes": {},
            "example": {"source": "Das Zielszenario beschreibt den "
                                  "angestrebten Zustand im Jahr 2045.",
                        "tuples": [{"value": "Zielszenario"}]},
        }]})

    bare = _category({"oeo:target": ["Zielszenario"]})
    meant = _category({"oeo:target": {"label": "Zielszenario",
                                      "definition": "Ein Szenario mit Ziel."}})
    other = _category({"oeo:target": {"label": "Zielszenario",
                                      "definition": "Etwas ganz anderes."}})
    keys = [spec_mod.value_fingerprint(s.parameters[0])
            for s in (bare, meant, other)]
    assert len(set(keys)) == 3, "spelling and meaning both decide"
    # And the parameter itself does not move with its list.
    assert (spec_mod.parameter_fingerprint(meant.parameters[0])
            == spec_mod.parameter_fingerprint(other.parameters[0]))


def _two(question=None, label="Treibhausgasemissionen", second=True):
    """A spec that offers one parameter or two, with the one line that asks
    which of them a number belongs to."""
    energy = {
        "uri": "energy", "label": "Endenergie",
        "description": "Endenergieverbrauch je Energietraeger, Sektor und "
                       "Jahr, wie im Plan bilanziert.",
        "value_type": "float", "unit_target": "kWh",
        "units_accepted": {"kWh/a": 0.001, "MWh/a": 1.0},
        "example": {"source": "| Erdgas | 42.005 | MWh/a | im Jahr 2020 |",
                    "tuples": [{"value": 42005, "unit_raw": "MWh/a"}]},
        "axes": {},
    }
    emission = {**energy, "uri": "emission", "label": label,
                "unit_target": "t", "units_accepted": {"t CO2-Aeq/a": 1.0},
                "description": "Treibhausgasemissionen je Traeger und Jahr, "
                               "wie im Plan bilanziert.",
                "example": {"source": "| Erdgas | 8.400 | t CO2-Aeq/a |",
                            "tuples": [{"value": 8400,
                                        "unit_raw": "t CO2-Aeq/a"}]}}
    body = {"parameters": [energy] + ([emission] if second else [])}
    if question:
        body["parameter_question"] = question
    return spec_mod.load(body)


def test_the_question_that_belongs_to_no_parameter_has_a_key_of_its_own():
    """Which quantity a number is, is asked like every other coordinate: one
    question, one closed list, one quote. Its list is the parameters
    themselves, so nothing per parameter can carry it.

    It is also the only key that can see a parameter DISAPPEAR. Every other
    key is written from what the spec still has and the stamp is compared
    against those, so a dropped parameter would leave every document reading
    current while the model now chooses from a shorter list. That mattered
    the moment `stale` stopped comparing the sha of the whole file, which was
    what used to catch it.
    """
    asked = "Welche Kennzahl steht in dieser Zeile?"
    base = spec_mod.parameter_slot_fingerprint(_two(asked))

    # The wording of the question.
    assert base != spec_mod.parameter_slot_fingerprint(
        _two("Welche Groesse ist hier gemeint?"))
    # A label, because that is what the model picks from.
    assert base != spec_mod.parameter_slot_fingerprint(
        _two(asked, label="CO2-Emissionen"))
    # The list itself.
    dropped = spec_mod.fingerprints(_two(asked, second=False))
    assert dropped["slot/parameter"] != base
    assert not [k for k in dropped
                if k.startswith(("parameter/", "value/", "axis/"))
                and k not in spec_mod.fingerprints(_two(asked))], (
        "and no per-parameter key reports it, which is why this one exists")


def test_a_parameters_description_is_not_in_the_slot_key():
    """It is in `parameter/<uri>`, where the question that shows it is. Two
    keys moving for one edit says nothing about which coordinate to redo, and
    a slot key that moves with everything is the whole-file sha again."""
    asked = "Welche Kennzahl steht in dieser Zeile?"
    wordier = _two(asked)
    wordier.parameters[0].description = ("Endenergieverbrauch je Traeger, "
                                         "anders gesagt und laenger.")
    assert (spec_mod.parameter_slot_fingerprint(wordier)
            == spec_mod.parameter_slot_fingerprint(_two(asked)))
    assert (spec_mod.parameter_fingerprint(wordier.parameters[0])
            != spec_mod.parameter_fingerprint(_two(asked).parameters[0]))
