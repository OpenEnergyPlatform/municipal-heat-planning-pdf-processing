"""A turn of the chat does what its drawing says (docpipe/inference/chatflow.py,
owner request 2026-11-14).

1. The drawing the package brings, which both profiles run, has no problem;
   the check names every drawing the run cannot do, at its step: a box the
   library does not have, two steps of one id, a turn that does not start
   with the question or shows nothing, a box whose input no step before it
   gives, a condition about a variable that is not there yet, a setting of
   the wrong kind.
2. The frames do what they say: "if" the first way whose condition holds,
   else the last; "each" its steps for every entry, with the entry under
   its name; "round" at most N times and no longer than its condition
   allows; "together" every way, and what each gave is there after.
3. A route that is in no code is made of blocks alone: the model writes a
   query, the query runs on the graph, the model answers from its rows, and
   the page shows the answer with the rows; the query the graph is asked is
   the one the model wrote.
4. The sidebar offers the routes the drawing branches on.

The proof that the drawing the package brings asks what the chat asked
before, request for request, is the comparison of both versions over a set
of turns, not a test here.
"""
import copy
import json
import types

import pytest

from docpipe.inference import chatflow, llm_client
from docpipe.profile import load_profile


def drawing():
    return copy.deepcopy(chatflow.load(load_profile("kwp")).tree)


def ids_of(said):
    return [(one["id"], one["message"]) for one in said]


@pytest.mark.parametrize("profile", ["kwp", "scenarios"])
def test_the_drawing_the_profiles_run_has_no_problem(profile):
    found = chatflow.load(load_profile(profile))
    assert found.owner == "default"
    assert chatflow.problems(found.tree) == []


def test_a_box_the_library_does_not_have_is_named():
    tree = [{"id": "question", "box": "question"},
            {"id": "x", "box": "telepathy"}, {"id": "show", "box": "show"}]
    assert ids_of(chatflow.problems(tree)) == [
        ("x", "no box 'telepathy' in the chat's library")]


def test_two_steps_of_one_id_and_a_missing_start_are_named():
    tree = [{"id": "show", "box": "show"}, {"id": "show", "box": "show"}]
    said = ids_of(chatflow.problems(tree))
    assert ("show", "two steps are called show") in said
    assert ("show", "a turn starts with the user's question") in said


def test_a_turn_that_shows_nothing_is_named():
    tree = [{"id": "question", "box": "question"}]
    assert ids_of(chatflow.problems(tree)) == [
        (None, "no step shows the answer")]


def test_an_input_no_step_before_gives_is_named():
    tree = [{"id": "question", "box": "question"},
            {"id": "embed", "box": "embed"}, {"id": "show", "box": "show"}]
    assert ids_of(chatflow.problems(tree)) == [
        ("embed", "needs phrase, which no step before it gives")]


def test_an_input_one_way_of_a_branching_does_not_give_is_named():
    tree = [{"id": "question", "box": "question"},
            {"id": "maybe", "if": [{"when": {"all": [
                {"of": "var", "is": "as_json"}]},
                "steps": [{"id": "phrase", "box": "phrase"}]}],
             "else": []},
            {"id": "embed", "box": "embed"}, {"id": "show", "box": "show"}]
    assert ids_of(chatflow.problems(tree)) == [
        ("embed", "needs phrase, which no step before it gives")]


def test_a_condition_about_a_variable_not_there_yet_is_named():
    tree = [{"id": "question", "box": "question"},
            {"id": "early", "if": [{"when": {"all": [
                {"of": "var", "is": "hits", "op": "empty"}]},
                "steps": []}], "else": []},
            {"id": "show", "box": "show"}]
    assert ids_of(chatflow.problems(tree)) == [
        ("early", "the variable hits is not there yet at this place")]


def test_a_setting_of_the_wrong_kind_is_named():
    tree = drawing()
    search = next(n for n in chatflow.walk(tree) if n.get("id") == "search")
    search["set"] = {"top_k": "many", "words": "yes"}
    said = ids_of(chatflow.problems(tree))
    assert ("search", "hits, at most: a number of 0 or more") in said
    assert ("search", "search the words too: on or off") in said


class Made(chatflow.Services):
    """Made-up resources: nothing is searched, the graph is given."""

    words = {"preparing": "", "route_graph": ""}

    def __init__(self, graph=None):
        self._graph = graph

    def graph(self):
        return self._graph, {}


def turn(tree, **start):
    graph = start.pop("graph", None)
    begin = {"question": "Q", "documents": [], "document": {"id": None},
             "scopes": [], "route": "auto", "as_json": False}
    begin.update(start)
    return chatflow.run(tree, begin, Made(graph))


def test_if_takes_the_first_way_that_holds_else_the_last():
    def way(value):
        return {"id": f"set_{value}", "box": "set",
                "set": {"name": "took", "value": value}}
    tree = [{"id": "question", "box": "question"},
            {"id": "pick", "if": [
                {"when": {"all": [{"of": "var", "is": "route", "op": "is",
                                   "value": "graph"}]},
                 "steps": [way("graph")]},
                {"when": {"all": [{"of": "var", "is": "route", "op": "is",
                                   "value": "harvest"}]},
                 "steps": [way("harvest")]}],
             "else": [way("else")]},
            {"id": "show", "box": "show", "set": {"text": "{{took}}"}}]
    assert turn(tree, route="harvest")["message"]["content"] == "harvest"
    assert turn(tree, route="other")["message"]["content"] == "else"


def test_each_round_and_together_do_what_they_say():
    tree = [{"id": "question", "box": "question"},
            {"id": "start", "box": "set",
             "set": {"name": "seen", "value": []}},
            {"id": "loop", "each": "list", "list": "documents", "as": "doc",
             "steps": [{"id": "keep", "box": "merge",
                        "set": {"lists": ["seen", "doc.id"],
                                "into": "seen"}}]},
            {"id": "again", "round": {"most": 5},
             "stop": {"all": [{"of": "var", "is": "round", "op": "at_least",
                               "value": 3}]},
             "steps": [{"id": "count", "box": "set",
                        "set": {"name": "rounds", "from": "round"}}]},
            {"id": "both", "together": [
                {"steps": [{"id": "a", "box": "set",
                            "set": {"name": "a", "value": 1}}]},
                {"steps": [{"id": "b", "box": "set",
                            "set": {"name": "b", "value": 2}}]}]},
            {"id": "show", "box": "show",
             "set": {"text": "{{seen}} {{rounds}} {{a}}{{b}}"}}]
    assert chatflow.problems(tree) == []
    got = turn(tree, documents=[{"id": 7}, {"id": 8}])
    assert got["message"]["content"] == "[7, 8] 3 12"


def test_a_step_with_a_condition_runs_only_when_it_holds():
    tree = [{"id": "question", "box": "question"},
            {"id": "start", "box": "set", "set": {"name": "said",
                                                  "value": "no"}},
            {"id": "maybe", "box": "set", "set": {"name": "said",
                                                  "value": "yes"},
             "when": {"all": [{"of": "var", "is": "as_json"}]}},
            {"id": "show", "box": "show", "set": {"text": "{{said}}"}}]
    assert chatflow.problems(tree) == []
    assert turn(tree, as_json=True)["message"]["content"] == "yes"
    assert turn(tree, as_json=False)["message"]["content"] == "no"
    # what a step that may not run gives, no later step can count on
    tree.insert(2, {"id": "only", "box": "set", "set": {"name": "x",
                                                        "value": 1},
                    "when": {"all": [{"of": "var", "is": "as_json"}]}})
    tree.insert(3, {"id": "use", "box": "set", "set": {"name": "y",
                                                       "from": "x"}})
    assert ("use", "needs x, which no step before it gives") in \
        ids_of(chatflow.problems(tree))


class Recorder:
    """The model: answers each request in turn and keeps what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.sent.append(kw)
        content = json.dumps(self.replies.pop(0))
        choice = types.SimpleNamespace(
            message=types.SimpleNamespace(content=content, reasoning=None,
                                          refusal=None),
            finish_reason="stop")
        return types.SimpleNamespace(choices=[choice], usage=None)


GRAPH = """@prefix ex: <http://example.org/> .
ex:plan1 ex:consumption 450 .
ex:plan2 ex:consumption 380 .
"""
QUERY = ("SELECT ?plan ?value WHERE { ?plan <http://example.org/consumption> "
         "?value } ORDER BY ?plan")


def sparql_route():
    """A route no code has: the model writes the query, the graph answers,
    the model reads the rows."""
    return [
        {"id": "question", "box": "question"},
        {"id": "write", "box": "ask", "set": {
            "prompt": "Write one SPARQL query for the question: "
                      "{{question}}",
            "schema": {"type": "object", "required": ["query"],
                       "properties": {"query": {"type": "string"}}},
            "into": "query"}},
        {"id": "run", "box": "graph_query",
         "set": {"query": "query.query", "into": "rows"}},
        {"id": "read", "box": "ask", "set": {
            "prompt": "Answer the question {{question}} from the rows.",
            "inputs": ["rows"],
            "schema": {"type": "object", "required": ["answer"],
                       "properties": {"answer": {"type": "string"}}},
            "into": "reply"}},
        {"id": "show", "box": "show",
         "set": {"text": "{{reply.answer}}", "values": ["rows"]}},
    ]


def test_a_route_of_blocks_alone_asks_the_graph_what_the_model_wrote(
        monkeypatch):
    from docpipe.inference import kg_route
    graph, _comments = kg_route.load_graph_from_text(GRAPH)
    model = Recorder([{"query": QUERY},
                      {"answer": "plan1 450, plan2 380"}])
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    asked = []
    real = kg_route.run_query
    monkeypatch.setattr(kg_route, "run_query", lambda g, text, b: (
        asked.append(text), real(g, text, b))[1])
    tree = sparql_route()
    assert chatflow.problems(tree) == []
    got = turn(tree, question="Wie hoch ist der Verbrauch?", graph=graph)
    assert asked == [QUERY]
    rows = [{"plan": "http://example.org/plan1", "value": "450"},
            {"plan": "http://example.org/plan2", "value": "380"}]
    assert got["message"]["content"] == "plan1 450, plan2 380"
    assert got["message"]["extra"] == [{"name": "rows", "value": rows}]
    assert len(model.sent) == 2
    first = model.sent[0]["messages"][-1]["content"]
    assert "Wie hoch ist der Verbrauch?" in first
    assert json.dumps(rows) in model.sent[1]["messages"][-1]["content"]
    assert model.sent[1]["response_format"]["json_schema"]["name"] == \
        "own_reply"


def test_a_query_that_finds_nothing_shows_no_rows(monkeypatch):
    from docpipe.inference import kg_route
    graph, _comments = kg_route.load_graph_from_text(GRAPH)
    nothing = QUERY.replace("consumption", "emission")
    model = Recorder([{"query": nothing}, {"answer": "keine Werte"}])
    monkeypatch.setattr(llm_client, "get_client", lambda: model)
    got = turn(sparql_route(), graph=graph)
    assert got["message"]["extra"] == [{"name": "rows", "value": []}]
    assert got["message"]["content"] == "keine Werte"


def test_a_route_whose_query_no_step_writes_is_refused():
    tree = [step for step in sparql_route() if step["id"] != "write"]
    assert ("run", "needs query, which no step before it gives") in \
        ids_of(chatflow.problems(tree))


def test_the_sidebar_offers_the_routes_the_drawing_branches_on():
    assert chatflow.routes_in(drawing()) == ["graph", "harvest",
                                             "documents"]
    tree = drawing()
    route = next(n for n in tree if n.get("id") == "route")
    route["if"].append({"when": {"all": [
        {"of": "var", "is": "route", "op": "one_of",
         "value": ["sparql"]}]}, "steps": sparql_route()[1:]})
    assert chatflow.routes_in(tree) == ["graph", "harvest", "sparql",
                                        "documents"]


def test_list_and_table_are_written_without_a_model():
    shown = [{"text": "450 GWh im Jahr 2022", "citation": 1},
             {"text": "Erdgas | 120 GWh", "citation": 2}]
    assert chatflow._as_list(shown) == ("- 450 GWh im Jahr 2022 [1]\n"
                                        "- Erdgas | 120 GWh [2]")
    table = chatflow._as_table(shown, [{"n": 1, "page": 4},
                                       {"n": 2, "page": None}])
    assert table.splitlines()[2:] == ["| 1 | 450 GWh im Jahr 2022 | 4 |",
                                      "| 2 | Erdgas \\| 120 GWh |  |"]
