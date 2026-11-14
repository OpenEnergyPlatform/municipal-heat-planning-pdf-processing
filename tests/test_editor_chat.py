"""The drawing of the chat in the editor (docpipe/editor/chatpage.py, owner
request 2026-11-14).

1. The page gets the drawing the profile runs, with the chat's library, the
   variables there before each step and the routes it branches on.
2. A check writes nothing and says every reason, each at its step; a prompt
   the profile does not have is one of them.
3. A save writes the profile's own file, only for a drawing the run can do,
   only where the file is as the page loaded it, and removes it where the
   drawing is the one the profile inherits.
4. A try sends nothing: every request is answered in its own form and
   named by the step that asked it, no reranker and no sandbox is asked.
5. A route of blocks alone is tried as it is drawn.
"""
from __future__ import annotations

import copy
import dataclasses
import socket
from pathlib import Path

import pytest

from docpipe import providers
from docpipe.editor import chatpage, server
from docpipe.extraction import general
from docpipe.inference import (chatflow, chunker, code_exec, llm_client,
                               rerank)
from docpipe.profile import load_profile


@pytest.fixture
def profile(tmp_path):
    """scenarios with a folder of its own, still extending default."""
    home = tmp_path / "scenarios"
    home.mkdir()
    return dataclasses.replace(load_profile("scenarios"), home=home)


def make_app(tmp_path, profile) -> server.App:
    """The editor on *profile*, its spec copied into the profile's own
    folder, where the editor may read it."""
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    app = server.App(profile, None, root)
    if app.spec_path:
        own = Path(profile.package_dir) / Path(app.spec_path).name
        own.write_bytes(Path(app.spec_path).read_bytes())
        app.spec_path = own
    return app


def ids_of(report) -> list:
    return [(one["id"], one["message"]) for one in report["errors"]]


def test_the_page_gets_the_drawing_the_profile_runs(tmp_path, profile):
    app = make_app(tmp_path, profile)
    status, shown = app.call("GET", "/api/chat", {}, None)
    assert status == 200
    assert shown["tree"] == chatflow.load(profile).tree
    assert not shown["exists"] and shown["base"] is None
    assert shown["starts_from"] == "default"
    assert shown["inherited_tree"] == shown["tree"]
    assert shown["problems"] == []
    kinds = {box["type"] for box in shown["library"]["boxes"]}
    assert {"ask", "format_json", "format_template", "merge_answers",
            "ask_batch", "graph_query", "choose", "show"} <= kinds
    assert {"each", "part", "together"} <= set(shown["library"]["frames"])
    assert {one["name"] for one in shown["library"]["templates"]} >= {
        "statements", "harvest", "graph", "compare", "compute"}
    assert shown["library"]["each"].keys() == {"list"}
    assert shown["routes"] == ["graph", "harvest", "documents"]
    assert "inference/choose_way" in shown["prompt_ids"]
    # what is there before a step: the search sentence before the embedding,
    # and not yet the hits it is searched for
    assert "phrase" in shown["available"]["embed"]
    assert "hits" not in shown["available"]["embed"]
    assert "hits" in shown["available"]["found"]


def test_a_check_writes_nothing_and_says_every_reason(tmp_path, profile):
    app = make_app(tmp_path, profile)
    tree = copy.deepcopy(chatflow.load(profile).tree)
    tree.insert(1, {"id": "odd", "box": "telepathy"})
    status, report = app.call("POST", "/api/chat/check", {}, {"tree": tree})
    assert status == 200 and not report["ok"]
    assert ("odd", "no box 'telepathy' in the chat's library") in \
        ids_of(report)
    assert "text" not in report
    assert not chatflow.path_of(profile).exists()
    # the failure by construction: the drawing as it is has no reason
    status, report = app.call("POST", "/api/chat/check", {}, {})
    assert report["ok"] and report["writes"] == "unchanged"


def own_step(prompt: str) -> dict:
    return {"id": "own", "box": "ask", "set": {
        "prompt": prompt, "into": "reply",
        "schema": {"type": "object", "required": ["answer"],
                   "properties": {"answer": {"type": "string"}}}}}


def test_a_prompt_the_profile_does_not_have_is_named(tmp_path, profile):
    app = make_app(tmp_path, profile)
    tree = [{"id": "question", "box": "question"},
            own_step("inference/no_such_prompt"),
            {"id": "show", "box": "show", "set": {"text": "{{reply}}"}}]
    status, report = app.call("POST", "/api/chat/check", {}, {"tree": tree})
    assert ("own", "the profile has no prompt inference/no_such_prompt") \
        in ids_of(report)
    # the failure by construction: a prompt it has, and a text of its own
    for prompt in ("inference/choose_way", "Answer the question."):
        tree[1] = own_step(prompt)
        status, report = app.call("POST", "/api/chat/check", {},
                                  {"tree": tree})
        assert report["ok"], (prompt, report["errors"])


def test_a_save_writes_the_profiles_own_file_and_a_save_back_removes_it(
        tmp_path, profile):
    app = make_app(tmp_path, profile)
    inherited = chatflow.load(profile).tree
    tree = copy.deepcopy(inherited)
    search = next(n for n in chatflow.walk(tree) if n.get("id") == "search")
    search["set"] = {"top_k": 5}
    status, told = app.call("POST", "/api/chat/save", {},
                            {"base": None, "tree": tree})
    path = chatflow.path_of(profile)
    assert told["saved"] and told["writes"] == "created"
    assert chatflow.parse(path.read_bytes()) == tree
    assert told["base"] == server.sha256(path.read_bytes())
    assert chatflow.load(profile).tree == tree
    # the failure by construction: a file that moved is not written over
    status, moved = app.call("POST", "/api/chat/save", {},
                             {"base": "0" * 64, "tree": inherited})
    assert not moved["saved"] and moved["reason"] == "moved"
    assert chatflow.parse(path.read_bytes()) == tree
    status, back = app.call("POST", "/api/chat/save", {},
                            {"base": told["base"], "tree": inherited})
    assert back["writes"] == "removed" and not path.exists()


def test_a_save_of_a_drawing_the_run_cannot_do_writes_nothing(tmp_path,
                                                              profile):
    app = make_app(tmp_path, profile)
    tree = [{"id": "question", "box": "question"},
            {"id": "embed", "box": "embed"}, {"id": "show", "box": "show"}]
    status, told = app.call("POST", "/api/chat/save", {},
                            {"base": None, "tree": tree})
    assert not told["saved"] and told["reason"] == "invalid"
    assert "needs phrase" in told["message"]
    assert not chatflow.path_of(profile).exists()


@pytest.fixture
def sent(monkeypatch):
    """Every way out is shut and counted: a connection, the model's
    client, the reranker and the sandbox. A way out that is taken is noted
    and fails as an unreachable server fails."""
    taken: list = []

    def refuse(name):
        def shut(*_a, **_k):
            taken.append(name)
            raise ConnectionError(f"{name} was asked")
        return shut

    monkeypatch.setattr(socket.socket, "connect", refuse("socket"))
    monkeypatch.setattr(socket, "create_connection", refuse("socket"))
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setattr(providers, "client", refuse("model"))
    monkeypatch.setattr(rerank, "make_reranker", refuse("reranker"))
    monkeypatch.setattr(code_exec, "run_code", refuse("sandbox"))
    monkeypatch.setattr(code_exec, "is_enabled", lambda: True)
    # The tokenizer that counts the batches is loaded as the chat loads it,
    # from the cache or the hub, and carries nothing of the plan; here it is
    # the one of a machine without it, the chat's own estimate.
    monkeypatch.setattr(chunker, "_TOKENIZER", None)
    monkeypatch.setattr(chunker, "_TOKENIZER_TRIED", True)
    return taken


def test_a_try_sends_nothing_and_names_each_request_by_its_step(
        tmp_path, profile, sent):
    app = make_app(tmp_path, profile)
    status, tried = app.call("POST", "/api/chat/try", {}, {
        "question": "Wie hoch ist der Wärmebedarf?", "route": "documents"})
    assert status == 200, tried
    assert tried["error"] is None
    ran = [one["id"] for one in tried["steps"]]
    assert ran[:4] == ["question", "phrase", "embed", "search"]
    assert "show" in ran
    asked = {one["request"]: one["step"] for one in tried["requests"]}
    assert asked["search_phrase_reply"] == "phrase"
    assert all(one["step"] for one in tried["requests"])
    assert tried["passages"] >= 1 and tried["searched"]
    assert isinstance(tried["message"]["content"], str)
    assert sent == []


def test_a_try_that_would_send_is_caught(profile, sent):
    """The failure by construction of the test above: the same turn
    without the made-up model, and with the resources of the chat page,
    takes the ways out."""
    hits = [{"owner_kind": "section", "owner_id": 1, "text": "450 GWh",
             "title": "", "page_number": 1, "image_path": None,
             "document_id": 0, "score": 1.0}]
    services = chatpage.TryServices(profile, hits, "Example plan")
    services.reranker = chatflow.Services.reranker.__get__(services)
    services.sandbox = chatflow.Services.sandbox.__get__(services)
    start = {"question": "Wie hoch ist der Wärmebedarf?", "documents": [],
             "document": {"id": 0}, "scopes": list(chatpage.TRY_SCOPES),
             "route": "documents", "as_json": False}
    tree = copy.deepcopy(chatflow.load(profile).tree)
    found = next(n for n in chatflow.walk(tree) if n.get("id") == "found")
    found["if"][0]["steps"].insert(0, {"id": "order", "box": "rerank"})
    with pytest.raises(ConnectionError):
        chatflow.run(tree, start, services)
    assert {"model", "reranker"} <= set(sent)


def test_a_route_of_blocks_alone_is_tried_as_drawn(tmp_path, profile,
                                                   sent):
    pytest.importorskip("pyoxigraph")
    schema_query = {"type": "object", "required": ["query"],
                    "properties": {"query": {"type": "string"}}}
    schema_answer = {"type": "object", "required": ["answer"],
                     "properties": {"answer": {"type": "string"}}}
    tree = [{"id": "question", "box": "question"},
            {"id": "write", "box": "ask", "set": {
                "prompt": "Write one SPARQL query for {{question}}",
                "schema": schema_query, "into": "query"}},
            {"id": "run", "box": "graph_query",
             "set": {"query": "query.query", "into": "rows"}},
            {"id": "read", "box": "ask", "set": {
                "prompt": "Answer {{question}} from the rows.",
                "inputs": ["rows"], "schema": schema_answer,
                "into": "reply"}},
            {"id": "show", "box": "show",
             "set": {"text": "{{reply.answer}}", "values": ["rows"]}}]
    app = make_app(tmp_path, profile)
    status, tried = app.call("POST", "/api/chat/try", {}, {
        "tree": tree, "question": "Wie hoch ist der Verbrauch?"})
    assert status == 200 and tried["error"] is None, tried
    assert [one["id"] for one in tried["steps"]] == [
        "question", "write", "run", "read", "show"]
    assert [one["step"] for one in tried["requests"]] == ["write", "read"]
    assert tried["requests"][0]["reply"] == {"query": ""}
    assert "Wie hoch ist der Verbrauch?" in tried["requests"][0]["prompt"]
    assert tried["message"]["content"] == ""
    assert tried["message"]["extra"] == [{"name": "rows", "value": []}]
    assert sent == []
    # the answers of the example of their form: "..." is no query, and the
    # try says so at the step that ran it
    status, tried = app.call("POST", "/api/chat/try", {}, {
        "tree": tree, "question": "Wie hoch ist der Verbrauch?",
        "mode": "example"})
    assert tried["requests"][0]["reply"] == general.example_of(schema_query)
    assert tried["steps"][-1]["id"] == "run"
    assert tried["steps"][-1]["gave"]["error"].startswith("SyntaxError")
    assert tried["error"].startswith("SyntaxError")


def test_a_try_of_a_drawing_the_run_cannot_do_is_refused(tmp_path, profile,
                                                         sent):
    app = make_app(tmp_path, profile)
    tree = [{"id": "question", "box": "question"}]
    status, said = app.call("POST", "/api/chat/try", {},
                            {"tree": tree, "question": "Q"})
    assert status == 400 and "no step shows the answer" in said["error"]
    status, said = app.call("POST", "/api/chat/try", {}, {"question": " "})
    assert status == 400 and "needs a question" in said["error"]


def test_the_answer_that_names_nothing_has_every_key_empty():
    schema = {"type": "object", "properties": {
        "statements": {"type": "array"}, "complete": {"type": "boolean"},
        "action": {"enum": ["python", "image"]}, "id": {"type": "string"},
        "n": {"type": "integer"}}}
    assert chatpage.nothing(schema) == {"statements": [], "complete": False,
                                        "action": "image", "id": "", "n": 0}
