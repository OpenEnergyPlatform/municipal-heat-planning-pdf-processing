"""The blocks a drawing of the graph is made of (owner request 2026-11-14,
wish 4): a condition about the reading, steps one after another, Python of
the drawing's own and an address made of parts. Each promise is held by a
case that keeps it and one that breaks it on purpose."""
import pytest

from docpipe.extraction import bricks, conditions, graph, graphblocks
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile

PROFILE = load_profile("kwp")
SPEC = load_spec(PROFILE.component("extraction", "SPEC_PATH"))
QUANTITY = next(uri for uri in SPEC.by_uri["energy_consumption"]
                .axes["quantity"].vocabulary if not uri.startswith("out:"))
PREFIXES = {"oeo": "https://openenergyplatform.org/ontology/oeo/"}


def drawing(boxes=None, arrows=None) -> graph.Drawing:
    return graph.Drawing({
        "prefixes": PREFIXES, "legal_forms": "GmbH",
        "boxes": boxes or [
            {"id": "part", "count": "per_answer", "of": "scenario",
             "among": "value", "table": {"target": {"folder": "target"}},
             "address": {"name": "plan"}},
            {"id": "value", "count": "per_value",
             "of": ["energy_consumption"]}],
        "arrows": arrows or [
            {"from": "sector", "to": "value", "property": "oeo:OEO_1",
             "brick": "answer_class",
             "settings": {"total_class": "OEO_00000128"}}]})


def document(the_drawing=None, facts=None) -> graph.Document:
    writer = graph.Writer(the_drawing or drawing(), spec=SPEC,
                          rules={"base": "https://example.org/"},
                          bricks=bricks.registry(PROFILE))
    doc = graph.Document(writer, "a_plan", [], None)
    doc.facts = facts or {"place": "Musterstadt"}
    return doc


def reading(**given) -> dict:
    row = {"parameter": "energy_consumption", "quantity": QUANTITY,
           "scenario": "target", "year": 2040, "value": 5.0,
           "unit": "GWh", "value_target": 5000.0}
    row.update(given)
    return row


def condition(doc, block, row):
    return doc.writer.call(block, "condition", doc=doc, row=row)


# -- a condition block ----------------------------------------------------------

def test_a_condition_takes_a_reading_where_it_holds():
    block = {"if": {"all": [{"of": "reading", "is": "year", "op": "whole"}]},
             "reason": "year"}
    assert condition(document(), block, reading()) is None


def test_a_condition_leaves_a_reading_out_for_its_reason_from_the_reading():
    block = {"if": {"all": [{"of": "reading", "is": "quantity",
                             "op": "listed"}]},
             "reason": "not_a_class:{quantity|quantity_raw|'?'}"}
    doc = document()
    assert condition(doc, block, reading(quantity="out:potential")) \
        == "not_a_class:out:potential"
    assert condition(doc, block, reading(quantity=None,
                                         quantity_raw="Wärme")) \
        == "not_a_class:Wärme"
    assert condition(doc, block, reading(quantity=None)) == "not_a_class:?"


def test_a_single_key_of_a_reason_is_written_as_python_writes_it():
    block = {"if": {"all": [{"of": "reading", "is": "role", "op": "is",
                             "value": "municipality"}]},
             "reason": "role:{role}"}
    assert condition(document(), block, reading()) == "role:None"


def test_listed_is_an_entry_of_the_list_of_that_dimension_in_the_spec():
    doc, path = document(), "quantity"
    assert graphblocks.listed(doc, reading(), path)
    assert not graphblocks.listed(doc, reading(quantity="out:total"), path)
    assert not graphblocks.listed(doc, reading(quantity="OEO_99999999"), path)


def test_names_is_a_text_whose_words_fold_to_something():
    block = {"if": {"all": [{"of": "reading", "is": "value",
                             "op": "names"}]}, "reason": "unnamed"}
    doc = document()
    assert condition(doc, block, reading(value="Stadtwerke GmbH")) is None
    assert condition(doc, block, reading(value=" – ")) == "unnamed"
    assert condition(doc, block, reading(value=5)) == "unnamed"


def test_answer_of_is_an_answer_of_the_table_of_the_box():
    block = {"if": {"all": [{"of": "reading", "is": "scenario",
                             "op": "answer_of", "value": "part"}]},
             "reason": "scenario:{scenario}"}
    doc = document()
    assert condition(doc, block, reading()) is None
    assert condition(doc, block, reading(scenario="trend")) \
        == "scenario:trend"


def test_term_is_an_identifier_of_a_term_and_whole_a_whole_number():
    facts = graphblocks.facts(document(), reading(unit_target="UO_0000187",
                                                  year="2040"))
    term = {"all": [{"of": "reading", "is": "unit_target", "op": "term"}]}
    whole = {"all": [{"of": "reading", "is": "year", "op": "whole"}]}
    assert conditions.holds(term, facts)
    assert not conditions.holds(whole, facts)
    assert not conditions.holds(term, graphblocks.facts(
        document(), reading(unit_target="kWh")))


def test_the_unit_a_number_was_converted_onto_is_read_from_the_spec():
    doc = document()
    parameter = SPEC.by_uri["energy_consumption"]
    assert graphblocks.value_at(doc, reading(), "unit_target") \
        == parameter.target_of("GWh")
    assert graphblocks.value_at(doc, reading(unit="no such unit"),
                                "unit_target") is None


def test_a_condition_about_what_a_flow_knows_is_no_block_of_the_graph():
    said = conditions.problems(
        {"all": [{"of": "quote", "is": "length", "op": "less",
                  "value": 3}]}, conditions.GRAPH_SUBJECTS)
    assert said
    problems = graph.check(drawing(boxes=[
        {"id": "value", "count": "per_value", "of": ["energy_consumption"],
         "admit": [{"if": {"all": [{"of": "quote", "is": "length",
                                    "op": "less", "value": 3}]},
                    "reason": "short"}]}], arrows=[]), PROFILE, SPEC)
    assert any("not known here" in one for one in problems)


def test_the_flow_offers_no_reading_of_the_graph_and_the_graph_only_those():
    flow = {one["name"] for one in conditions.catalogue()}
    graph_side = {one["name"] for one in conditions.catalogue(graph=True)}
    assert graph_side == {"reading", "fact"}
    assert not flow & graph_side


# -- steps ----------------------------------------------------------------------

def test_each_step_takes_the_value_the_one_before_gave_and_the_last_writes():
    block = {"steps": [{"brick": "remove_words",
                        "settings": {"legal_forms": True}},
                       {"brick": "text", "settings": {"form": "line"}}]}
    found = document().writer.brick(block, "object")
    out = found.run(bricks.Call(doc=document(), value="Stadtwerke Nord GmbH",
                                settings={}))
    assert [value for _term, value in out] == ["Stadtwerke Nord"]


def test_a_chain_whose_last_step_writes_no_object_is_refused():
    block = {"steps": [{"brick": "text"}, {"brick": "lookup"}]}
    with pytest.raises(graph.GraphError):
        document().writer.brick(block, "object")
    problems = graph.check(drawing(arrows=[
        {"from": "sector", "to": "value", "property": "oeo:OEO_1",
         "brick": block}]), PROFILE, SPEC)
    assert any("last step" in one for one in problems)


def test_lookup_gives_what_its_table_says_and_keeps_or_drops_the_rest():
    run = bricks.CORE["lookup"].run
    table = {"table": {"a": "b"}}
    assert run(bricks.Call(value="a", settings=table)) == "b"
    assert run(bricks.Call(value="c", settings=table)) == "c"
    assert run(bricks.Call(value="c", settings={**table,
                                                "otherwise": "drop"})) is None


# -- Python of the drawing ------------------------------------------------------

def test_python_runs_run_of_its_code_with_the_call():
    block = {"python": "def run(call):\n"
                       "    return [(literal(call.value), call.value)]\n"}
    found = document().writer.brick(block, "object")
    assert found.run(bricks.Call(value="x")) == [('"x"', "x")]


def test_python_without_run_is_refused():
    assert graphblocks.python_problem("x = 1\n")
    problems = graph.check(drawing(arrows=[
        {"from": "sector", "to": "value", "property": "oeo:OEO_1",
         "brick": {"python": "x = 1\n"}}]), PROFILE, SPEC)
    assert any("run(call)" in one for one in problems)


# -- any block as Python --------------------------------------------------------
#
# The promise, in one sentence: a condition written as Python gives nothing
# where the condition holds and its reason where it does not, AND steps
# written as Python give what the chain of their steps gives, each step with
# its settings, a step of Python as well as a brick.

def as_python(block, kind) -> dict:
    code = graphblocks.python_block(block, kind, bricks.registry(PROFILE),
                                    graph.python_space(PROFILE))
    assert code
    return {"python": code}


def chained(block, value):
    found = document().writer.brick(block, "object")
    return found.run(bricks.Call(doc=document(), value=value, settings={}))


def test_a_condition_as_python_gives_what_the_condition_gives():
    block = {"if": {"all": [{"of": "reading", "is": "quantity",
                             "op": "listed"}]},
             "reason": "not_a_class:{quantity|quantity_raw|'?'}"}
    doc, py = document(), as_python(block, "condition")
    rows = (reading(), reading(quantity="out:potential"),
            reading(quantity=None, quantity_raw="Wärme"))
    assert [condition(doc, py, row) for row in rows] \
        == [condition(doc, block, row) for row in rows] \
        == [None, "not_a_class:out:potential", "not_a_class:Wärme"]
    # the failure by construction: the test turned round
    spoiled = {"python": py["python"].replace("if conditions.holds",
                                              "if not conditions.holds")}
    assert [condition(doc, spoiled, row) for row in rows] \
        != [condition(doc, block, row) for row in rows]


def test_steps_as_python_give_what_the_chain_gives():
    block = {"steps": [{"brick": "remove_words",
                        "settings": {"legal_forms": True}},
                       {"brick": "text", "settings": {"form": "line"}}]}
    py = as_python(block, "object")
    values = ("Stadtwerke Nord GmbH", "Gemeinde Musterstadt")
    assert [chained(py, v) for v in values] \
        == [chained(block, v) for v in values]
    assert [value for _term, value in chained(py, values[0])] \
        == ["Stadtwerke Nord"]
    # the failure by construction: the settings of the first step lost
    spoiled = {"python": py["python"].replace("{'legal_forms': True}", "{}")}
    assert chained(spoiled, values[0]) != chained(block, values[0])


def test_a_step_of_python_stays_its_own_code_in_the_chain():
    block = {"steps": [{"python": "def run(call):\n"
                                  "    return call.value.upper()\n"},
                       {"brick": "text", "settings": {"form": "line"}}]}
    py = as_python(block, "object")
    assert chained(py, "nord") == chained(block, "nord")
    assert [value for _term, value in chained(py, "nord")] == ["NORD"]
    # the failure by construction: the step of Python left out
    spoiled = {"python": py["python"].replace("return call.value.upper()",
                                              "return call.value")}
    assert chained(spoiled, "nord") != chained(block, "nord")


def test_no_block_of_the_kind_has_no_python_for_the_page():
    from docpipe.editor import graphpage
    said = graphpage.python_of_block(
        PROFILE, {"steps": [{"brick": "text"}, {"brick": "lookup"}]},
        "object")
    assert said == {"python": ""}
    said = graphpage.python_of_block(
        PROFILE, {"steps": [{"brick": "remove_words"},
                            {"brick": "text"}]}, "object")
    assert "def run(call):" in said["python"]


# -- an address made of parts -------------------------------------------------

def parts(doc, the_parts, row, label=""):
    box = doc.writer.drawing.box["value"]
    return graphblocks.parts_name(doc, box, the_parts, None, row, label)


def test_an_absent_part_refuses_the_address_or_is_empty_or_left_out():
    doc, row = document(), reading()
    assert parts(doc, [{"of": "technology"}], row) is None
    assert parts(doc, [{"of": "technology", "absent": "empty"}], row) == [""]
    assert parts(doc, [{"of": "year"}, {"of": "technology",
                                        "absent": "omit"}], row) == ["2040"]


def test_a_class_part_writes_only_a_class_of_its_family_with_its_prefix():
    doc = document()
    part = {"of": "quantity", "form": "class", "prefix": "oeo",
            "family": "OEO_", "absent": "empty"}
    assert parts(doc, [part], reading()) == [PREFIXES["oeo"] + QUANTITY]
    assert parts(doc, [part], reading(quantity="UO_0000187")) == [""]


def test_out_total_becomes_the_class_the_arrow_writes_for_it():
    doc = document()
    part = {"of": "sector", "total": True, "form": "class", "prefix": "oeo",
            "absent": "empty"}
    assert parts(doc, [part], reading(sector="out:total")) \
        == [PREFIXES["oeo"] + "OEO_00000128"]
    assert parts(doc, [dict(part, total=False)],
                 reading(sector="out:total")) == [""]


def test_a_part_counts_only_when_its_condition_holds():
    doc = document()
    part = {"of": "spatial_scope_raw", "form": "fold", "absent": "empty",
            "when": {"all": [{"of": "reading", "is": "spatial_scope",
                              "op": "is", "value": "sub_area"}]}}
    named = reading(spatial_scope_raw="Nord-Ost")
    assert parts(doc, [part], dict(named, spatial_scope="sub_area")) \
        == [doc.fold("Nord-Ost")]
    assert parts(doc, [part], dict(named, spatial_scope="municipality")) \
        == [""]


def test_the_wording_and_the_answer_s_address_are_parts_too():
    doc = document()
    the_parts = [{"from": "answer_address", "box": "part", "of": "scenario"},
                 {"from": "wording", "absent": "omit"}]
    assert parts(doc, the_parts, reading(), "split") \
        == ["https://example.org/target/plan", "split"]
    assert parts(doc, the_parts, reading()) \
        == ["https://example.org/target/plan"]


def test_a_part_from_nowhere_is_refused_by_the_check():
    assert graphblocks.part_problem({"from": "elsewhere"}, set(), {})
    assert graphblocks.part_problem({"from": "answer_address", "of": "x",
                                     "box": "none"}, set(), {})
    assert graphblocks.part_problem({"of": "year"}, set(), {}) is None


# -- the name of a block --------------------------------------------------------

def test_a_block_goes_by_its_brick_else_by_the_preset_it_was_put_in_from():
    assert graphblocks.name_of("text") == "text"
    assert graphblocks.name_of({"brick": "text", "settings": {}}) == "text"
    assert graphblocks.name_of({"preset": "short_name",
                                "python": "def run(call): ..."}) \
        == "short_name"
    assert graphblocks.name_of({"python": "def run(call): ..."}) is None


def test_every_preset_put_in_keeps_its_name():
    for profile_name in ("kwp", "scenarios"):
        for preset in bricks.presets(load_profile(profile_name)):
            assert preset["block"]["preset"] == preset["name"]


def test_the_body_finds_its_arrow_by_the_preset_its_block_came_from():
    from profiles.scenarios import kg
    assert kg.terms().P_SCENARIO_ACRONYM == "dc:acronym"
    with pytest.raises(StopIteration):
        kg.property_of("scenario_label", "scenario", "no_such_preset")


# -- the shipped drawings ---------------------------------------------------------

def test_every_preset_is_a_block_the_check_takes():
    for profile_name in ("kwp", "scenarios"):
        profile = load_profile(profile_name)
        known = bricks.registry(profile)
        for preset in bricks.presets(profile):
            block = preset["block"]
            if preset["kind"] == "address":
                assert all(graphblocks.part_problem(one, set(), {"part": {}})
                           is None for one in block["from"])
                continue
            graphblocks.resolve(block, preset["kind"], known,
                                graph.python_space(profile))


def test_the_shipped_drawings_check_clean():
    for profile_name in ("kwp", "scenarios"):
        profile = load_profile(profile_name)
        assert graph.check(graph.load_drawing(profile), profile) == []
