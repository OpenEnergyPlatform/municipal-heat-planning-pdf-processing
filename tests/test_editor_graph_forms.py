"""
test_editor_graph_forms.py: one step of steps in the Graph tab of
`docpipe edit` in its other form (docpipe/editor/ui/src/graph/forms.ts),
behind the switch "A brick" / "Python" each step has.

The promise, in one sentence: a step shown in its own form is the step as it
is; a brick step shown as Python, once stored, makes its steps do what they
did, with the brick's own code AND its settings AND how often it is called
AND what it writes, and is a new step where the server sent no code; a Python
step shown as a brick is a brick not yet chosen; a brick named alone is the
same brick; showing a form never changes the step. Each has a case that
breaks it by construction.

The module is the page's own TypeScript, run by node with its types
stripped; the tests are skipped where node cannot do that.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from docpipe.editor import graphpage
from docpipe.extraction import bricks, graph, graphblocks
from docpipe.extraction.bricks import Call
from docpipe.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "editor_graph_forms_driver.mjs"
NODE = shutil.which("node")


def _strips_types() -> bool:
    if NODE is None:
        return False
    done = subprocess.run([NODE, "-p", "process.features.typescript"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0 and done.stdout.strip() in ("strip",
                                                            "transform")


pytestmark = pytest.mark.skipif(not _strips_types(),
                                reason="no node that strips TypeScript types")

KWP = load_profile("kwp")
# The bricks as the page gets them, each with its own logic as Python.
BRICKS = graphpage.bricks_of(KWP)
REGISTRY = bricks.registry(KWP)
SPACE = graph.python_space(KWP)
STEP_PYTHON = "def run(call):\n    return call.value\n"

# The unit of a number in the kwp drawing: a class, prefixed by its family.
UNIT = {"brick": "answer_class",
        "settings": {"prefix_by_family": {"OEO_": "oeo", "UO_": "obo"}}}
# A step called once per node.
NAMED = {"brick": "template", "settings": {"text": "heat plan of {place}"}}
OWN = {"python": "def run(call):\n    return call.value\n",
       "settings": {"pattern": "x"}, "per": "node"}


def run_node(jobs):
    done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def show(cases, broken=None, given=BRICKS):
    """What each (step, form) is shown as: {"out", "step", "form"}."""
    return run_node([{"op": "shown", "step": step, "form": form,
                      "bricks": given, "broken": broken}
                     for step, form in cases])


class Doc:
    """What the sample calls of the steps ask of a document."""
    prefixes = {"oeo": "https://example.org/oeo/", "obo": "https://obo/"}
    legal_forms = "GmbH"
    facts = {"place": "Kassel"}

    def count(self, what, name=""):
        pass


def chain(steps):
    return graphblocks.resolve({"steps": steps}, "object", REGISTRY, SPACE)


def same_steps(before, after) -> list:
    """Where the chain *after* does not do what *before* did."""
    a, b = chain(before), chain(after)
    out = []
    if (a.per, a.writes) != (b.per, b.writes):
        out.append(f"called {b.per} writing {b.writes!r}, not {a.per} "
                   f"writing {a.writes!r}")
    for value in ("UO_0000276", "OEO_00000132", "BFO_0000051", "words"):
        one, two = (x.run(Call(doc=Doc(), value=value)) for x in (a, b))
        if one != two:
            out.append(f"{value}: {two!r}, not {one!r}")
    return out


def test_a_step_in_its_own_form_is_shown_as_it_is():
    def problems(broken=None):
        got = show([(UNIT, "brick"), (OWN, "python")], broken)
        return [f"{want} shown as {g['out']}"
                for want, g in zip((UNIT, OWN), got) if g["out"] != want]

    assert problems() == []
    assert problems("always_new")


def test_a_brick_step_as_python_does_what_the_brick_did():
    def problems(broken=None):
        got = show([(UNIT, "python"), (NAMED, "python")], broken)
        out = []
        for step, g in zip((UNIT, NAMED), got):
            if g["form"] != "python":
                out.append(f"{step} shown as {g['out']}")
                continue
            out += same_steps([step], [g["out"]])
        return out

    assert problems() == []
    # The brick's own code is what is shown.
    code = {b["name"]: b["python"] for b in BRICKS}
    got = show([(UNIT, "python")])[0]["out"]
    assert got["python"] == code["answer_class"] and got["python"]
    assert got["settings"] == UNIT["settings"]
    # Each part it carries is needed.
    assert any("UO_0000276" in p for p in problems("no_settings"))
    assert any("called row" in p for p in problems("no_per"))
    assert any("writing ''" in p for p in problems("no_writes"))


def test_a_brick_without_code_shows_as_a_new_step():
    without = [dict(b, python="") if b["name"] == "answer_class" else b
               for b in BRICKS]

    def problems(broken=None):
        got = show([(UNIT, "python")], broken, without)[0]
        if got["out"].get("python") != STEP_PYTHON:
            return [f"shown as {got['out']}"]
        return [graphblocks.python_problem(got["out"]["python"])] \
            if graphblocks.python_problem(got["out"]["python"]) else []

    assert problems() == []
    assert problems("no_new_step")


def test_a_python_step_as_a_brick_is_a_brick_not_yet_chosen():
    def problems(broken=None):
        got = show([(OWN, "brick")], broken)[0]
        return [] if (got["out"], got["form"]) == ({"brick": ""}, "brick") \
            else [f"shown as {got['out']} ({got['form']})"]

    assert problems() == []
    assert problems("keeps_code")


def test_a_brick_named_alone_is_the_same_brick():
    def problems(broken=None):
        alone, full = show([("answer_class", "python"),
                            ({"brick": "answer_class"}, "python")], broken)
        return [] if alone["out"] == full["out"] \
            else [f"{alone['out']} against {full['out']}"]

    assert problems() == []
    assert problems("name_alone_unknown")


def test_showing_a_form_never_changes_the_step():
    steps = [UNIT, NAMED, OWN, "answer_class"]

    def problems(broken=None):
        cases = [(copy.deepcopy(step), form) for step in steps
                 for form in ("brick", "python")]
        got = show(cases, broken)
        return [f"{step} became {g['step']}" for (step, _), g
                in zip(cases, got) if g["step"] != step]

    assert problems() == []
    assert problems("mutate")
