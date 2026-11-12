"""
What the page of `docpipe edit` is told a step can set for itself
(`editor.flow.step_rules`, owner 2026-11-11: "alles soll anpassbar sein").

The promise: every rule and number a step reads is offered at that step
with its standard and where the run's value comes from, AND nothing a step
does not read is offered there, AND a key's value is never sent. A rule
of the graph file that a step reads is one of them: the step may set it,
and the page offers it there.
"""
import copy
import dataclasses

from docpipe import rules
from docpipe.editor import flow as flow_page
from docpipe.extraction import flow as flow_map
from docpipe.profile import load_profile


def test_a_step_is_offered_what_it_reads_and_nothing_else():
    got = flow_page.step_rules(load_profile("kwp"))
    by_name = {row["name"]: row for row in got["rules"]}
    assert "lines_around" in got["kinds"]["coord"]
    assert "lines_around" not in got["kinds"].get("write", [])
    assert "abbreviations" in got["kinds"]["split"]
    assert "abbreviations" not in got["kinds"]["coord"]
    row = by_name["decimal_mark"]
    assert row["standard"] == ","              # KWP writes German plans
    assert row["standard_from"].endswith("kwp")
    assert by_name["piece_lines"]["source"] == "number"
    # a rule no step reads is the run's: it is not offered at a step
    assert "largest_first" not in by_name


def test_a_key_is_never_sent(monkeypatch):
    real = rules.registry

    def registry(profile=None):
        known = dict(real(profile))
        known["image_max_side"] = dataclasses.replace(
            known["image_max_side"], secret=True)
        return known
    monkeypatch.setattr(rules, "registry", registry)
    got = flow_page.step_rules(load_profile("kwp"))
    by_name = {row["name"]: row for row in got["rules"]}
    row = by_name["image_max_side"]
    assert row["secret"] and row["standard"] is None \
        and row["in_effect"] is None
    # the same rule as it is, not a key: its value is sent
    monkeypatch.setattr(rules, "registry", real)
    shown = {row["name"]: row for row in flow_page.step_rules(
        load_profile("kwp"))["rules"]}["image_max_side"]
    assert shown["standard"] is not None


def test_a_step_may_set_a_rule_of_the_graph_file_it_reads():
    profile = load_profile("kwp")
    tree = copy.deepcopy(flow_map.tree_of(profile))
    box = next(node for node, _frames in flow_map.walk(tree)
               if rules.step_kind(node) == "compute")
    box.setdefault("rules", {})["rounding_tolerance"] = 0.5
    known = flow_map.known_rules(profile)
    assert flow_map.problems(tree, known) == []
    # a name neither file declares is refused as before
    box["rules"] = {"rounding_tolerancx": 0.5}
    said = flow_map.problems(tree, known)
    assert said and "is no rule" in said[0]["message"]
    # a rule of the rules file alone does not know it
    box["rules"] = {"rounding_tolerance": 0.5}
    said = flow_map.problems(tree, rules.registry(profile))
    assert said and "is no rule" in said[0]["message"]


def test_the_page_offers_a_graph_rule_at_the_step_that_reads_it():
    got = flow_page.step_rules(load_profile("kwp"))
    row = {one["name"]: one for one in got["rules"]}["rounding_tolerance"]
    assert "rounding_tolerance" in got["kinds"]["compute"]
    assert "rounding_tolerance" not in got["kinds"].get("coord", [])
    assert row["tab"] == "graph"
    assert got["tabs"]["rounding_tolerance"] == "graph"
    assert row["standard_from"] == "graph.json of kwp"
    assert row["standard"] == row["in_effect"] is not None
