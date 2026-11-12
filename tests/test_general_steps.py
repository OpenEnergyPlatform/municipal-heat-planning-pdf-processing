"""
The general steps of a flow (owner decision 2026-11-12, plan of the
general blocks): each promise in one sentence, each with a case that breaks
it by construction.

1. A step takes only what a step before it gives.
2. A prompt says each input once: {{key}} stands in the prompt and not in
   the message, {{key.field}} writes one field and the key stays.
3. A loop over a list goes through each entry under its name, and a filter
   keeps the entries its condition holds for.
4. A Python step's outputs become variables, and code without run(inputs)
   is refused.
5. A box of a profile stands only in a flow of its profile.
6. A list question is asked as the list step after its question says.
7. The answer of an own question is kept in its schema's form, and an
   answer the own check refuses is asked again with its sentence.
"""
import copy
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import blocks, flow, general, runner
from docpipe.extraction.addressed import Counts
from docpipe.extraction.engine import Engine, Scope
from docpipe.profile import load_profile

from test_ruleset_flowing import Reading


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def default() -> list:
    return copy.deepcopy(flow.load(None).tree)


def said(drawing: list, profile=None) -> list:
    return [p["message"] for p in flow.problems(drawing, profile=profile)]


def scope_of(**values) -> Scope:
    doc = SimpleNamespace(plan=SimpleNamespace(document_id=1), made={},
                          counts=Counts())
    return Scope(None, True, doc=doc, **values)


# -- 1. what a step takes ---------------------------------------------------------

def test_a_step_takes_only_what_a_step_before_it_gives():
    drawing = default()
    keep = {"id": "tables", "box": "filter", "set": {
        "list": "hits", "into": "tables", "keep": {"all": [
            {"of": "var", "is": "item.kind", "op": "one_of",
             "value": ["table"]}]}}}
    search = {"id": "near_title", "box": "retrieve",
              "set": {"query": "document.title_page", "into": "hits"}}
    at = drawing.index(next(n for n in drawing if n.get("id") == "lists"))
    # the failure by construction: no step before it gives the hits
    drawing.insert(at + 1, keep)
    assert any("takes the search hits" in m for m in said(drawing)),         said(drawing)
    drawing.insert(at + 1, search)
    assert said(drawing) == []


# -- 2. the prompt ----------------------------------------------------------------

def test_a_prompt_says_each_input_once():
    payload = {"question": "Which year?", "field": {"name": "heat demand",
                                                    "means": "x"},
               "passage": {"1": "line"}}
    text, rest = general.in_prompt(
        "Q: {{question}} about {{field.name}}. {{example}}", payload)
    assert text == "Q: Which year? about heat demand. {{example}}"
    # the whole key stands in the prompt only; the key of a field stays
    assert "question" not in rest and "field" in rest and "passage" in rest
    # the failure by construction: a prompt that names no key leaves the
    # message as it is
    assert general.in_prompt("Q.", payload) == ("Q.", payload)


# -- 3. loops over lists and filters ---------------------------------------------

def test_a_loop_over_a_list_and_a_filter_keep_their_entries():
    scope = scope_of()
    general.put(scope, "hits", [{"kind": "table", "n": 1},
                                {"kind": "section", "n": 2},
                                {"kind": "table", "n": 3}])
    items = general.list_items({"list": "hits", "as": "hit"}, scope)
    assert [one[general.PAGE + "hit"]["n"] for one in items] == [1, 2, 3]
    engine = SimpleNamespace(facts=lambda s: general.var_facts(s))
    node = {"id": "f", "box": "filter", "set": {
        "list": "hits", "into": "tables", "keep": {"all": [
            {"of": "var", "is": "item.kind", "op": "one_of",
             "value": ["table"]}]}}}
    general.filter_step(engine, node, scope)
    assert [one["n"] for one in general.get(scope, "tables")] == [1, 3]
    # the failure by construction: the negated condition keeps the rest
    node["set"]["keep"]["all"][0]["not"] = True
    general.filter_step(engine, node, scope)
    assert [one["n"] for one in general.get(scope, "tables")] == [2]


# -- 4. python --------------------------------------------------------------------

def test_a_python_step_gives_its_outputs():
    scope = scope_of()
    general.put(scope, "a", 40)
    general.put(scope, "b", 600)
    node = {"id": "p", "box": "python", "set": {
        "code": "def run(inputs):\n"
                "    return {'share': inputs['a'] * inputs['b'] / 100}\n",
        "inputs": ["a", "b"], "outputs": ["share"], "lasting": True}}
    general.python_step(None, node, scope)
    assert scope.get("doc").made["share"] == 240
    # the failure by construction: code without run(inputs)
    assert "run(inputs)" in general.python_problem("x = 1")


# -- 5. the boxes of a profile -------------------------------------------------------

def test_a_box_of_a_profile_stands_only_in_its_profiles_flow():
    scenarios = load_profile("scenarios")
    drawing = copy.deepcopy(flow.load(scenarios).tree)
    assert said(drawing, scenarios) == []
    # the failure by construction: the same drawing as a heat plan's
    assert any("is a step of the profile scenarios" in m
               for m in said(drawing, load_profile("kwp")))
    offered = {box["type"] for box in
               blocks.catalogue(load_profile("kwp"))["boxes"]}
    assert "quantity" in offered and "works" not in offered


# -- 6. the home of the list question ----------------------------------------------

def test_a_list_question_is_asked_as_its_list_step_says():
    tree = [{"id": "finds", "box": "find"},
            {"id": "finds_list", "box": "list", "rules": {"max_tokens": 99}},
            {"id": "own", "box": "coord"}]
    homes = runner.attached_homes(tree)
    assert homes[("finds", "list")]["id"] == "finds_list"
    # the failure by construction: a question without such a step, and a
    # list step switched off, stand for nothing
    assert ("own", "list") not in homes
    tree[1]["off"] = True
    assert runner.attached_homes(tree) == {}


# -- 7. an own question ----------------------------------------------------------------

class Asked(Reading):
    """A reader whose model answers an own question from a list of
    replies, and notes what each follow-up said was wrong."""

    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.asked, self.followed = [], []

    def ask_own(self, prompt, payload, document_id, shape, example, counts,
                /, **noted):
        self.asked.append((prompt, payload, example))
        return self.replies.pop(0)

    def follow_own(self, prompt, payload, document_id, shape, example, reply,
                   what, counts, /, **noted):
        self.followed.append(what)
        return self.replies.pop(0)

    def follow_ups(self):
        return 1


def run_ask(replies, with_check: bool):
    drawing = default()
    ask = {"id": "ask_year", "box": "ask", "set": {
        "prompt": {"text": "Which year does {{question}} name?"},
        "inputs": [{"key": "question", "from": "q", "show": "text"}],
        "reply": {"type": "object", "properties": {
            "year": {"type": "integer"}}, "required": ["year"]},
        "into": {"var": "jahr"}}}
    check = {"id": "late", "box": "check", "set": {
        "name": "late", "sentence": "The year is 1990 or later.",
        "refuse": {"all": [{"of": "var", "is": "jahr.year", "op": "less",
                            "value": 1990}]}}}
    at = drawing.index(next(n for n in drawing if n.get("id") == "lists"))
    given = {"id": "q_set", "box": "set",
             "set": {"name": "q", "value": "the table"}}
    drawing[at + 1:at + 1] = [given, ask] + ([check] if with_check else [])
    reader = Asked(replies)
    engine = Engine(reader, drawing)
    scope = scope_of()
    general.put(scope, "q", "the table")
    general.ask_step(engine, ask, scope)
    return reader, scope


def test_an_own_question_keeps_its_answer_and_asks_again_what_its_check_refuses():
    reader, scope = run_ask([{"year": 1985}, {"year": 2021}], True)
    assert general.get(scope, "jahr.year") == 2021
    assert reader.followed == [[{"why": "The year is 1990 or later."}]]
    prompt, payload, example = reader.asked[0]
    # the input stands in the prompt, the example has the schema's form
    assert "question" not in general.in_prompt(prompt["text"], payload)[1]
    assert example == {"year": 0}
    # the failure by construction: without the check the first answer stays
    reader, scope = run_ask([{"year": 1985}], False)
    assert general.get(scope, "jahr.year") == 1985 and reader.followed == []
