"""The checks a harvest makes are the ones its owner set, and no others.

A coordinate is taken when its quote stands in a passage that was shown and
the quote carries the answer. Which table a passage belongs to, how far from
the row it stands and which column of a table it heads are the model's
reading, not a rule. Three checks were once built past that without being
asked for, and 33 refusals of the Kassel pilot carried a reason no published
list named. These tests make the next one visible: a new check or a new reason
has to be written into a list here, in the open, before the harvest can make
it.

The same file holds the closure guard. The Kassel pilot failed because the
function that plans a pair read a name which a loop further down had bound to
an int, and nothing but a run on five GPUs said so.

No model, no GPU.
"""
import ast
import re
import symtable
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import (Batch, DocumentReport, Source,
                                         WorkItem, fold_batch, refused_upstream,
                                         route_claims, rows_from_reply)
from docpipe.extraction.schema import DROP_REASONS, REFUSAL_REASONS
from docpipe.extraction.spec import load as load_spec

ROOT = Path(__file__).resolve().parent.parent
EXTRACTION = ROOT / "docpipe" / "extraction"
PIPELINE = EXTRACTION / "pipeline.py"
RUNNER = EXTRACTION / "runner.py"

# The owner's rule, spelled out: the quote stands in a shown source, it is
# long enough to name a place, and the answer stands in it. Nothing else.
AGREED_DROPS = {"quote_not_in_source", "quote_too_short", "answer_not_in_quote"}


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(path, name):
    return next(node for node in ast.walk(_tree(path))
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _constants_under(node, key):
    """Every constant string written under `key`, as a dict key or a keyword."""
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            for k, v in zip(sub.keys, sub.values):
                if (isinstance(k, ast.Constant) and k.value == key
                        and isinstance(v, ast.Constant)):
                    out.add(v.value)
        elif (isinstance(sub, ast.keyword) and sub.arg == key
              and isinstance(sub.value, ast.Constant)):
            out.add(sub.value.value)
    return out


def _refusal_reasons(node):
    """The constant `reason` of every refusal row, which is a dict that also
    carries the claim. The corrections a retry is told have a `reason` too,
    and they are sentences for the model, not reasons for a reader."""
    out = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Dict):
            continue
        keys = {k.value for k in sub.keys if isinstance(k, ast.Constant)}
        if not {"reason", "claim"} <= keys:
            continue
        for k, v in zip(sub.keys, sub.values):
            if (isinstance(k, ast.Constant) and k.value == "reason"
                    and isinstance(v, ast.Constant)):
                out.add(v.value)
    return out


def _spec():
    return load_spec(ROOT / "profiles" / "kwp" / "extraction_spec.json")


def _batch(text="| Erdgas | 17.000 |"):
    return Batch(7, None, [WorkItem(7, None,
                                    Source("table", 5, text, {"page": 5}))])


def _pair():
    return {"scenario": "Zielszenario", "scenario_raw": "Zielszenario",
            "year": 2045}


def _refusal_validator():
    jsonschema = pytest.importorskip("jsonschema")
    from docpipe.extraction.schema import build
    harvest = build(_spec())["harvest"]
    return jsonschema.Draft202012Validator(
        {"$schema": harvest["$schema"], "$defs": harvest["$defs"],
         **harvest["$defs"]["refusal"]})


# ---------------------------------------------------------------------------
# No check nobody agreed to
# ---------------------------------------------------------------------------

def test_a_coordinate_is_dropped_for_the_agreed_reasons_and_no_other():
    """merge_field is where a coordinate reading is refused, and what it
    checks is exactly the owner's rule. A fourth check fails here until
    someone decides it and writes it into AGREED_DROPS."""
    whys = _constants_under(_function(PIPELINE, "merge_field"), "why")
    assert whys == AGREED_DROPS, sorted(whys)
    assert whys <= set(DROP_REASONS), "and the published list names each"


def _whys(node):
    """(refusal reasons, sentinel causes) written as a constant `_why`.

    A sentinel says why a request never came back, and the dict it is
    written in carries `_harvest_failed`; any other `_why` is the reason a
    claim was refused.
    """
    reasons, causes = set(), set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            keys = {k.value for k in sub.keys if isinstance(k, ast.Constant)}
            for k, v in zip(sub.keys, sub.values):
                if (isinstance(k, ast.Constant) and k.value == "_why"
                        and isinstance(v, ast.Constant)):
                    (causes if "_harvest_failed" in keys
                     else reasons).add(v.value)
        elif (isinstance(sub, ast.keyword) and sub.arg == "_why"
              and isinstance(sub.value, ast.Constant)):
            reasons.add(sub.value.value)
    return reasons, causes


def test_every_reason_a_claim_is_refused_for_is_a_published_one():
    """`_why` rides on a claim the harvester refused, `reason` on the refusal
    row. 33 refusals of the Kassel pilot carried a reason no list named, and
    the schema check could only count them."""
    from docpipe.extraction.schema import build
    written, causes = set(), set()
    for path in (PIPELINE, RUNNER):
        tree = _tree(path)
        reasons, found = _whys(tree)
        written |= reasons | _refusal_reasons(tree)
        causes |= found
    assert {"passage is not of this pair", "text value not in its quote",
            "claim names no source"} <= written, "the scan looks elsewhere"
    for reason in sorted(written):
        assert any(re.match(p, reason) for p in REFUSAL_REASONS), reason
    claim = build(_spec())["harvest"]["$defs"]["refusal"]["properties"]["claim"]
    assert causes <= set(claim["properties"]["_why"]["enum"]), sorted(causes)


def test_no_axis_carries_a_rule_about_where_its_passage_stands():
    """The evidence rule is gone from every spec and from the slots."""
    for path in sorted(ROOT.glob("profiles/*/extraction_spec.json")):
        assert '"evidence"' not in path.read_text(encoding="utf-8"), path
    assert not hasattr(fields.Slot(name="x", kind=fields.NUMBER), "evidence")


# ---------------------------------------------------------------------------
# A refused claim keeps the reason it was refused for
# ---------------------------------------------------------------------------

def test_only_a_claim_with_a_reason_and_no_failure_mark_counts_as_refused():
    """`fold_batch` refuses what the harvester already refused, under that
    reason. A sentinel carries a `_why` too, and it is left to the resume."""
    assert refused_upstream({"value": 1, "_why": "passage is not of this pair"})
    assert not refused_upstream({"_harvest_failed": True, "_why": "unreachable"})
    assert not refused_upstream({"value": 1, "quote": "| Erdgas | 17.000 |"})
    assert not refused_upstream({"value": 1, "_why": ""})
    assert not refused_upstream("not a claim")


def test_a_claim_refused_for_its_pair_keeps_that_reason_through_the_fold():
    """Verified a second time, 631 of Kassel's claims came out as "claim names
    no parameter of the spec" instead of saying why they were refused, and 33
    of them carried a key the schema does not know."""
    claim = {"value": 17000, "unit": "kWh/a", "quote": "| Erdgas | 17.000 |",
             "_why": "passage is not of this pair"}
    report = DocumentReport(document_id=7)
    fold_batch(_batch(), {"tuples": [claim]}, report)
    assert report.tuples == []
    [refusal] = report.refusals
    assert refusal["reason"] == "passage is not of this pair"
    assert "_why" not in refusal["claim"]
    assert refusal["owner"] == ["table", 5]
    assert _refusal_validator().is_valid({"kind": "refusal", **refusal})


def test_a_request_that_never_came_back_is_not_a_row_and_keeps_its_cause():
    """A sentinel carries a source label, and it used to be routed like a
    claim: under a pair its passage did not print its cause was overwritten,
    and anywhere else it became a row whose coordinates were paid for."""
    slots = fields.frame_slots(_spec(), ("scenario", "year"))
    for frame in (None, _pair()):
        batch = _batch()
        batch.frame = frame
        sentinel = {"_harvest_failed": True, "_why": "unreachable",
                    "source": "Q1"}
        rows, orphans = rows_from_reply(batch, {"tuples": [sentinel]}, slots)
        assert rows == [], frame
        assert orphans == [sentinel], frame
        assert orphans[0]["_why"] == "unreachable"


def test_with_no_row_left_the_harvester_hands_back_the_reasons(monkeypatch):
    """Every claim of this request comes from a passage that does not print
    its pair, so no row is left to sweep. What goes back is what
    `rows_from_reply` made of the claims and not the raw claims: verified
    again, 598 of Kassel's came out as "claim names no parameter of the
    spec"."""
    reply = {"tuples": [{"source": "Q1", "value": 17000, "unit": "kWh/a",
                         "unit_raw": "kWh/a", "quote": "| Erdgas | 17.000 |"}],
             "status": "complete", "need_more": []}
    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: reply))
    monkeypatch.setattr(runner, "make_field_asker",
                        lambda image_root=None: (lambda *a, **kw: None))
    spec = _spec()
    harvest = runner.make_fieldwise_harvester(
        spec=spec, slice_gate={},
        frame_axes=fields.frame_slots(spec, ("scenario", "year")))
    batch = _batch()
    batch.frame = _pair()
    out = harvest(batch)
    assert [c.get("_why") for c in out["tuples"]] == [
        "passage is not of this pair"]
    assert out["status"] == "complete"
    report = DocumentReport(document_id=7)
    fold_batch(batch, out, report)
    assert [r["reason"] for r in report.refusals] == [
        "passage is not of this pair"]


def test_routing_a_reply_twice_routes_it_the_same_way():
    """The runner routes every reply once for the next batch's prior and once
    to fold it. The first pass used to pop the labels in place, and the fold
    then routed by the quote alone, which for a quote two passages share is
    the first of them."""
    shared = "| Erdgas | 17.000 |"
    batch = Batch(7, None, [WorkItem(7, None, Source("table", 1, shared, {})),
                            WorkItem(7, None, Source("table", 2, shared, {}))])
    tuples = [{"source": "Q2", "value": 17000, "quote": shared}]
    first, _ = route_claims(batch, tuples)
    second, _ = route_claims(batch, tuples)
    assert [len(c) for c in first] == [len(c) for c in second] == [0, 1]
    assert tuples[0]["source"] == "Q2", "the reply is left as it was"


# ---------------------------------------------------------------------------
# No closure reads a name that is bound again after it
# ---------------------------------------------------------------------------

_OWN_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
              ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_COMPREHENSIONS = ("listcomp", "setcomp", "dictcomp", "genexpr")


def _bindings(scope, name):
    """Lines where `name` is bound in this scope itself, nested scopes left
    out."""
    lines, stack = [], list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            if node.name == name:
                lines.append(node.lineno)
            continue
        if isinstance(node, _OWN_SCOPE):
            continue
        if (isinstance(node, ast.Name) and node.id == name
                and isinstance(node.ctx, ast.Store)):
            lines.append(node.lineno)
        stack.extend(ast.iter_child_nodes(node))
    return lines


def late_bound(path):
    """(line, closure, name) for every name a nested function reads from the
    function around it, where that function binds the name again below the
    closure or inside a loop the closure is defined in."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    parent = {child: node for node in ast.walk(tree)
              for child in ast.iter_child_nodes(node)}
    defs: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[(node.name, node.lineno)] = node
        elif isinstance(node, ast.Lambda):
            defs.setdefault(("lambda", node.lineno), node)
    found = []

    def visit(table):
        for child in table.get_children():
            if (table.get_type() == "function"
                    and child.get_type() == "function"
                    and child.get_name() not in _COMPREHENSIONS):
                outer = defs.get((table.get_name(), table.get_lineno()))
                inner = defs.get((child.get_name(), child.get_lineno()))
                if outer is not None and inner is not None:
                    loops, node = [], parent.get(inner)
                    while node is not None and node is not outer:
                        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                            loops.append(node)
                        node = parent.get(node)
                    for symbol in child.get_symbols():
                        if not symbol.is_free():
                            continue
                        name = symbol.get_name()
                        later = [line for line in _bindings(outer, name)
                                 if line > inner.lineno]
                        looped = any(_bindings(loop, name) for loop in loops)
                        if later or looped:
                            found.append((inner.lineno, child.get_name(),
                                          name))
            visit(child)

    visit(symtable.symtable(source, str(path), "exec"))
    return found


def test_no_closure_in_the_extraction_package_reads_a_name_bound_after_it():
    """`plan` read `index`, the FAISS index, when it ran, and the pair loop
    below it had bound `index` to a pair number by then: pairs 8, 9 and 10 of
    the Kassel pilot were planned against an int, and the job failed after
    half an hour on five GPUs."""
    found = {path.name: late_bound(path)
             for path in sorted(EXTRACTION.glob("*.py"))}
    assert not any(found.values()), {k: v for k, v in found.items() if v}


def test_the_closure_guard_sees_the_bug_it_is_there_for(tmp_path):
    """A guard that finds nothing proves nothing until it has found this."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def main(items):\n"
        "    index = object()\n"
        "    def plan(pair):\n"
        "        return index, pair\n"
        "    for index, pair in enumerate(items):\n"
        "        plan(pair)\n"
        "    handlers = []\n"
        "    for item in items:\n"
        "        handlers.append(lambda: item)\n"
        "    return handlers\n", encoding="utf-8")
    assert {(name, var) for _line, name, var in late_bound(bad)} == {
        ("plan", "index"), ("lambda", "item")}


def test_a_line_break_inside_a_table_cell_is_whitespace_to_the_check():
    """A transcription wraps a long cell label with <br>. Read as text,
    "holzige Festbrennstoffe" never stood in its own quote: on Kassel six
    carriers stayed open and three value pairs collided in the graph."""
    from docpipe.extraction.verify import flat, quote_in
    cell = "| holzige<br>Festbrennstoffe | 7 | 0 |"
    assert quote_in(cell, "holzige Festbrennstoffe")
    assert flat("sonstige biogene<br/>Festbrennstoffe") == (
        "sonstige biogene Festbrennstoffe")
    assert not quote_in(cell, "fossile Festbrennstoffe")
