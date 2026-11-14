"""The fine blocks of the chat's drawing keep what they promise
(docpipe/inference/chatflow.py, owner request 2026-11-14 evening: "wenn die
Blöcke etwas feiner wären ... Auch schleifen und Logik inklusive Sandbox
berechnung").

1. A loop that runs ahead starts each entry with the variables there when it
   starts, takes the entries in order, and stops at the first entry after
   which its condition holds; what it collects grows as entries are taken.
2. A loop side by side runs each entry with variables of its own; only what
   it collects comes back.
3. A part runs its steps with variables of their own and gives back only
   those it names; one it names that no step inside gives is refused.
4. A tool does not run where it stands; the request beside it calls it when
   its model asks, and a request with no sandbox beside it is not offered
   one.
5. A batch taken keeps the statements whose quote stands in their source and
   counts the rest as dropped; the loop over the batches stops once the
   answer is complete and a statement stood its check.
6. "Join answers" numbers the citations of each later answer on, in the
   marks of its text too; "Join statements" takes out repeats by one request
   only where it is switched on.
7. "A format of your own" asks no model; "Reshaped by the model" asks one
   request with the instruction and keeps the answer where the reply cannot
   be read.
8. The graph route says why where it has no answer: no plan (no request is
   asked), no quantity, scenario or year named, no row, a value without its
   trust line.
9. Every template of the library passes the check where what it takes is
   there, and is refused where it is not.

The proof that the drawing the package brings asks what the chat asked
before, request for request, is the comparison of both versions over a set
of turns (the code before the drawing against this one), not a test here.
"""
import copy
import json
import types

import pytest

from docpipe.inference import answer, chatflow, chunker, kg_route, llm_client


@pytest.fixture(autouse=True)
def no_tokenizer(monkeypatch):
    """The batches are counted without loading a tokenizer."""
    monkeypatch.setattr(chunker, "get_tokenizer", lambda *a, **k: None)


class Model:
    """Answers each request in turn and keeps what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.sent.append(kw)
        said = self.replies.pop(0)
        content = said if isinstance(said, str) else json.dumps(said)
        choice = types.SimpleNamespace(
            message=types.SimpleNamespace(content=content, reasoning=None,
                                          refusal=None),
            finish_reason="stop")
        return types.SimpleNamespace(choices=[choice], usage=None)

    def text(self, at: int) -> str:
        content = self.sent[at]["messages"][-1]["content"]
        return content if isinstance(content, str) else " ".join(
            part.get("text", "") for part in content if isinstance(part, dict))


class Place(chatflow.Services):
    """A corpus of nothing, a recorded sandbox and a graph that is given."""

    words = {"preparing": "", "route_graph": ""}

    def __init__(self, sandbox=None, hooks=None, plan=None, graph=None):
        self.ran = []
        self._sandbox = sandbox
        self._hooks = hooks
        self._plan = plan
        self._graph = graph

    def corpus(self, image):
        return answer.Corpus(conn=None, index=None, id_to_pos={},
                             embed=lambda item: ([0.0], False))

    def sandbox(self):
        if self._sandbox is None:
            return None

        def run(code, context):
            self.ran.append((code, context))
            return self._sandbox
        return run

    def kg_hooks(self):
        return self._hooks

    def kg_plan(self, document_id):
        return self._plan

    def graph(self):
        return self._graph


def turn(tree, place=None, **start):
    begin = {"question": "Wie hoch war der Verbrauch?", "documents": [],
             "document": {"id": 7}, "scopes": [], "route": "auto",
             "as_json": False}
    begin.update(start)
    return chatflow.run(tree, begin, place or Place())


def ids_of(said):
    return [(one["id"], one["message"]) for one in said]


QUESTION = {"id": "question", "box": "question"}
SHOW = {"id": "show", "box": "show"}


def setv(ident, name, value):
    return {"id": ident, "box": "set", "set": {"name": name, "value": value}}


def python(ident, code, inputs, outputs):
    return {"id": ident, "box": "python",
            "set": {"code": code, "inputs": inputs, "outputs": outputs}}


# -- 1. ahead, 2. side by side, 3. part -------------------------------------------

def test_a_loop_ahead_starts_with_what_was_taken_and_stops_in_order():
    loop = {"id": "loop", "each": "list", "list": "numbers", "as": "n",
            "run": "ahead", "collect": {"from": "seen", "into": "seens"},
            "steps": [python("look", "def run(inputs):\n"
                                     "    return {'seen': [inputs['n'], "
                                     "len(inputs['seens'])]}\n",
                             ["n", "seens"], ["seen"])],
            "stop": {"all": [{"of": "var", "is": "seens.count",
                              "op": "at_least", "value": 3}]}}
    tree = [QUESTION, setv("numbers", "numbers", [1, 2, 3, 4, 5]), loop,
            {**SHOW, "set": {"text": "{{seens}}"}}]
    assert chatflow.problems(tree) == []
    # each entry saw what the entries before it had given when it started,
    # and the entries after the third were not taken
    assert json.loads(turn(tree)["message"]["content"]) == [
        [1, 0], [2, 1], [3, 2]]
    del loop["stop"]
    assert len(json.loads(turn(tree)["message"]["content"])) == 5


def test_a_loop_side_by_side_keeps_each_entry_to_itself():
    loop = {"id": "loop", "each": "list", "list": "documents", "as": "doc",
            "run": "side_by_side", "collect": {"from": "mine", "into": "ids"},
            "steps": [{"id": "mine", "box": "set",
                       "set": {"name": "mine", "from": "doc.id"}}]}
    tree = [QUESTION, loop, {**SHOW, "set": {"text": "{{ids}}|{{mine}}"}}]
    assert chatflow.problems(tree) == []
    documents = [{"id": 7}, {"id": 8}]
    assert turn(tree, documents=documents)["message"]["content"] == \
        "[7, 8]|"
    # one after another in the turn's own variables, the last one stays
    loop["run"] = "in_turn"
    assert turn(tree, documents=documents)["message"]["content"] == \
        "[7, 8]|8"


def test_a_part_gives_back_only_what_it_names():
    part = {"id": "part", "part": {"gives": ["a"]},
            "steps": [setv("a", "a", 1), setv("b", "b", 2)]}
    tree = [QUESTION, part, {**SHOW, "set": {"text": "{{a}}|{{b}}"}}]
    assert chatflow.problems(tree) == []
    assert turn(tree)["message"]["content"] == "1|"
    part["part"]["gives"] = ["a", "c"]
    assert ("part", "gives back c, which no step inside it gives") in \
        ids_of(chatflow.problems(tree))


def test_a_loop_side_by_side_cannot_stop_and_collects_both_names():
    loop = {"id": "loop", "each": "list", "list": "documents", "as": "doc",
            "run": "side_by_side", "collect": {"from": "mine"},
            "stop": {"all": [{"of": "var", "is": "doc"}]}, "steps": []}
    said = [message for _id, message in
            ids_of(chatflow.problems([QUESTION, loop, SHOW]))]
    assert "a loop side by side runs every entry at once and has nothing " \
           "to stop" in said
    assert "a loop collects a variable of each entry (from) into a list " \
           "(into)" in said


# -- 4. tools, 5. batches ---------------------------------------------------------

def hit(i, text):
    return {"owner_kind": "table" if i == 1 else "section",
            "owner_id": 100 + i, "title": f"Titel {i}", "text": text,
            "page_number": 3 + i, "image_path": None,
            "section_number": f"2.{i}", "section_title": f"Abschnitt {i}",
            "document_id": 7, "score": 1.0 - i / 10}


TEXTS = ["Der Endenergieverbrauch der Gemeinde betrug 2022 rund 450 GWh.",
         "| Energieträger | 2022 |\n| Erdgas | 120 GWh |"]


def batch_drawing(tools=True, hits=None, context_tokens=None):
    inside = [{"id": "ask_batch", "box": "ask_batch"}]
    if tools:
        inside += [{"id": "sandbox", "box": "compute",
                    "set": {"runs": "asked", "inputs": ["batch.tables"]}},
                   {"id": "crop", "box": "crop"}]
    pack = {"id": "pack", "box": "pack"}
    if context_tokens:
        pack["set"] = {"context_tokens": context_tokens}
    return [QUESTION,
            setv("hits", "hits", hits or [hit(0, TEXTS[0]), hit(1, TEXTS[1])]),
            pack,
            {"id": "batches", "each": "list", "list": "batches",
             "as": "batch", "run": "ahead",
             "stop": {"all": [{"of": "var", "is": "complete"},
                              {"of": "var", "is": "statements",
                               "op": "empty", "not": True}]},
             "steps": inside},
            {"id": "assemble", "box": "assemble"}, SHOW]


def stated(index, quote, complete=True):
    return {"statements": [{"statement": "Der Verbrauch lag bei 450 GWh.",
                            "basis": "text", "index": index,
                            "quote": quote}], "complete": complete}


def test_the_sandbox_beside_a_request_runs_what_its_model_writes(
        monkeypatch):
    model = Model({"action": "python", "code": "print(120 * 2)"},
                  stated(0, TEXTS[0][:40]))
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    place = Place(sandbox={"ok": True, "stdout": "240", "stderr": "",
                           "error": None})
    tree = batch_drawing()
    assert chatflow.problems(tree) == []
    got = turn(tree, place)
    # the tool did not run where it stands: it ran once, with the model's
    # code and the tables of the batch
    assert place.ran == [("print(120 * 2)", {"tables": [
        {"caption": "Titel 1", "markdown": TEXTS[1]}]})]
    assert "240" in model.text(1)
    assert got["result"]["compute"][0]["code"] == "print(120 * 2)"


def test_a_request_with_no_sandbox_beside_it_is_offered_none(monkeypatch):
    hint = llm_client._prompt("inference/compute_hint")
    model = Model(stated(0, TEXTS[0][:40]))
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    place = Place(sandbox={"ok": True, "stdout": "", "stderr": "",
                           "error": None})
    turn(batch_drawing(tools=False), place)
    assert hint not in model.text(0)
    assert place.ran == []
    model = Model(stated(0, TEXTS[0][:40]))
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    turn(batch_drawing(tools=True), place)
    assert hint in model.text(0)


def two_batches():
    return [hit(0, TEXTS[0] + " " * 10 + "x" * 3000),
            hit(2, "Die Wärmeplanung wurde 2024 erstellt. " + "y" * 3000)]


def test_a_batch_keeps_only_statements_whose_quote_stands(monkeypatch):
    model = Model(stated(0, TEXTS[0][:40], complete=False),
                  stated(1, "Dieser Satz steht in keiner Quelle", False))
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    got = turn(batch_drawing(hits=two_batches(), context_tokens=900))
    assert len(model.sent) == 2
    assert got["result"]["statements_shown"] == 1
    assert got["result"]["statements_dropped"] == 1
    assert got["result"]["n_batches"] == 2


def test_the_batches_stop_once_a_checked_answer_is_complete(monkeypatch):
    model = Model(stated(0, TEXTS[0][:40], complete=True))
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    turn(batch_drawing(hits=two_batches(), context_tokens=900))
    assert len(model.sent) == 1
    # complete, but no statement stood its check: the next batch is asked
    model = Model(stated(0, "Dieser Satz steht in keiner Quelle", True),
                  stated(1, "Die Wärmeplanung wurde 2024 erstellt", True))
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    got = turn(batch_drawing(hits=two_batches(), context_tokens=900))
    assert len(model.sent) == 2
    assert got["result"]["statements_shown"] == 1


# -- 6. joining, 7. formats ---------------------------------------------------------

def cited(n, page):
    return {"n": n, "page": page, "quote": f"q{n}", "visual": False}


def test_answers_joined_one_after_another_number_their_citations_on():
    tree = [QUESTION,
            setv("a", "first", {"answer": "x [1]", "citations": [cited(1, 4)]}),
            setv("b", "second", {"answer": "y [1]\nz [2]",
                                 "citations": [cited(1, 5), cited(2, 6)]}),
            {"id": "join", "box": "merge_answers",
             "set": {"answers": ["first", "second"]}}, SHOW]
    assert chatflow.problems(tree) == []
    got = turn(tree)
    assert got["message"]["content"] == "x [1]\n\ny [2]\nz [3]"
    assert [(c["n"], c["page"]) for c in got["message"]["citations"]] == [
        (1, 4), (2, 5), (3, 6)]


def test_answers_joined_by_the_model_keep_the_numbers(monkeypatch):
    model = Model({"answer": "x und y [1] [2]"})
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    tree = [QUESTION, setv("a", "first", {"answer": "x [1]",
                                          "citations": [cited(1, 4)]}),
            setv("b", "second", {"answer": "y [1]",
                                 "citations": [cited(1, 5)]}),
            {"id": "join", "box": "merge_answers",
             "set": {"answers": ["first", "second"], "how": "model"}}, SHOW]
    got = turn(tree)
    assert len(model.sent) == 1
    assert json.loads(model.text(0).split("\n\n", 1)[1])["answers"] == [
        "x [1]", "y [2]"]
    assert got["message"]["content"] == "x und y [1] [2]"
    assert [c["n"] for c in got["message"]["citations"]] == [1, 2]


def statement(text, n):
    return {"text": text, "owner_kind": "section", "owner_id": n,
            "quote": text, "run": None, "visual": False, "computed": False,
            "hit": {"owner_kind": "section", "owner_id": n, "page": n}}


def test_statements_joined_take_out_repeats_only_where_switched_on(
        monkeypatch):
    model = Model({"repeats": [{"statement": 3, "of": 1}]})
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    tree = [QUESTION, setv("a", "one", [statement("450 GWh", 1)]),
            setv("b", "two", [statement("120 GWh Erdgas", 2),
                              statement("rund 450 GWh", 3)]),
            {"id": "join", "box": "merge_statements",
             "set": {"lists": ["one", "two"]}},
            {"id": "assemble", "box": "assemble"}, SHOW]
    assert chatflow.problems(tree) == []
    got = turn(tree)
    assert len(model.sent) == 1
    assert [s["text"] for s in got["result"]["statements"]] == [
        "450 GWh", "120 GWh Erdgas"]
    tree[3]["set"]["repeats"] = False
    model = Model()
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    got = turn(tree)
    assert model.sent == []
    assert len(got["result"]["statements"]) == 3


def test_a_format_of_your_own_asks_no_model(monkeypatch):
    model = Model()
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    tree = [QUESTION, setv("a", "answer_text", "450 GWh"),
            setv("b", "citations", [{"n": 1, "title": "Tabelle 3"},
                                    {"n": 2, "title": "Abschnitt 2"}]),
            {"id": "own", "box": "format_template",
             "set": {"text": "{{answer_text}}\nQuellen:\n{{citations}}"}},
            SHOW]
    got = turn(tree)
    assert got["message"]["content"] == \
        "450 GWh\nQuellen:\n[1] Tabelle 3\n[2] Abschnitt 2"
    assert model.sent == []


def test_reshaped_by_the_model_keeps_the_answer_it_cannot_read(monkeypatch):
    tree = [QUESTION, setv("a", "answer", "x [1]"),
            {"id": "reshape", "box": "format_model",
             "set": {"instruction": "höchstens drei Stichpunkte"}}, SHOW]
    assert chatflow.problems(tree) == []
    model = Model({"answer": "- x [1]"})
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    got = turn(tree)
    assert "höchstens drei Stichpunkte" in model.text(0)
    assert got["message"]["content"] == "- x [1]"
    model = Model(*["kein JSON"] * 6)
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    got = turn(tree)
    assert got["message"]["content"] == "x [1]"
    del tree[2]["set"]["instruction"]
    assert ("reshape", "the model needs the instruction how to reshape the "
                       "answer") in ids_of(chatflow.problems(tree))


# -- 8. the graph -------------------------------------------------------------------

class Hooks:
    query = "SELECT ?value WHERE { ?n ?p ?value . ##CONSTRAINTS## }"
    axes = ("quantity", "year")
    spec = None
    prompt = None
    notes = {reason: reason for reason in kg_route.REASONS}

    def bindings(self, coordinates):
        return "", {"YEAR": ("literal", coordinates.get("year"))}


def graph_route():
    drawing = chatflow.load(None).tree
    route = next(n for n in drawing if n.get("id") == "route")
    steps = next(way["steps"] for way in route["if"]
                 if way["when"]["all"][0].get("value") == "graph")
    return [QUESTION, *copy.deepcopy(steps)]


def test_the_graph_route_says_why_it_has_no_answer(monkeypatch):
    coordinates = {"quantity": "http://q/1", "year": 2022}
    monkeypatch.setattr(kg_route, "to_coordinates",
                        lambda task, spec, axes, ask: dict(coordinates))
    rows = [{"value": "http://v/1"}]
    monkeypatch.setattr(kg_route, "run_query",
                        lambda graph, text, bindings: [dict(r) for r in rows])
    comments = {"http://v/1": ["# Zitat", "# Vertrauen: A"]}
    tree = graph_route()
    assert chatflow.problems(tree) == []

    def reason(plan="http://plan/7", lines=comments):
        got = turn(tree, Place(hooks=Hooks(), plan=plan,
                               graph=("G", lines)), route="graph")
        return got["vars"]["graph"].get("reason")

    assert reason() is None
    assert reason(plan=None) == "no_plan"
    rows.clear()
    assert reason() == "no_rows"
    rows.append({"value": "http://v/1"})
    # a value without its trust line is not shown as one the run stands
    # behind
    assert reason(lines={}) == "no_trust"
    coordinates.pop("quantity")
    coordinates.pop("year")
    assert reason() == "no_coordinates"


def test_no_plan_in_the_graph_asks_the_model_nothing(monkeypatch):
    model = Model()
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    asked = []
    monkeypatch.setattr(kg_route, "to_coordinates",
                        lambda *a: asked.append(a) or {})
    got = turn(graph_route(), Place(hooks=Hooks(), plan=None,
                                    graph=("G", {})), route="graph")
    assert got["vars"]["graph"]["reason"] == "no_plan"
    assert asked == [] and model.sent == []


# -- 9. templates -------------------------------------------------------------------

def placed(template, before):
    """The default drawing with *template* put into the documents' way
    after the step *before*, its ids made its own as the page does."""
    drawing = copy.deepcopy(chatflow.load(None).tree)
    taken = {node["id"] for node in chatflow.walk(drawing)}
    steps = copy.deepcopy(template["steps"])
    for node in chatflow.walk(steps):
        while node["id"] in taken:
            node["id"] += "_2"
        taken.add(node["id"])
    lists = [drawing] + [way for node in chatflow.walk(drawing)
                         for way in chatflow.ways_of(node)]
    for way in lists:
        for at, one in enumerate(way):
            if one.get("id") == before:
                way[at + 1:at + 1] = steps
                return drawing
    raise LookupError(before)


@pytest.mark.parametrize("template", chatflow.templates(),
                         ids=lambda one: one["name"])
def test_a_template_passes_where_what_it_takes_is_there(template):
    assert chatflow.problems(placed(template, "assemble")) == []


def test_a_template_where_what_it_takes_is_not_there_is_refused():
    statements = next(one for one in chatflow.templates()
                      if one["name"] == "statements")
    said = ids_of(chatflow.problems(placed(statements, "question")))
    assert any(message == "goes through batches, which no step before it "
                          "gives" for _id, message in said)
