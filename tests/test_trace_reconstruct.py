"""A run can be read back from its trace (owner decision 2026-11-14: "sodass
eigentlich alles rekonstruierbar ist"): every request is numbered and one
asked again names the one it follows; every search writes its vector
places, its reranker and the pieces it takes under one number, and the
requests that show those pieces name the search and each piece's place;
what became of each find is written with the request it answers; a request
asked again says why and how long it waited; the head of a document's trace
says what the run is and blanks what authenticates."""
import json
from types import SimpleNamespace

import jsonschema
import pytest

from docpipe import rules
from docpipe.extraction import fields, runner, schema, trace
from docpipe.extraction.addressed import Reader
from docpipe.extraction.pipeline import Source
from docpipe.inference import rerank

from test_addressed import ENERGY, SPEC, TABLE, Model, in_order, plan_of


@pytest.fixture
def traced(tmp_path, monkeypatch):
    monkeypatch.setenv("EXTRACT_TRACE", "1")
    rules.reset()
    monkeypatch.setattr(trace, "_root", None)
    monkeypatch.setattr(trace, "_name_of", None)
    trace.set_head(None)
    trace.open_trace(tmp_path, lambda document_id: f"plan{document_id}")
    yield tmp_path
    trace.close()
    trace.set_head(None)
    trace._thread.exchange = None
    trace._thread.requests = {}


def events(directory, name="plan7", kind=None):
    trace.flush()
    out = [e for e in trace.lines(trace.path_of(directory, name))
           if e.get("t") != trace.PIECE]
    return [e for e in out if kind is None or e["t"] == kind]


ASKED = {"attempt": 1, "prompt_tokens": 10, "completion_tokens": 2}


def test_requests_are_numbered_and_one_asked_again_names_the_one_it_follows(
        traced):
    trace.event("coord_ask", 7, parameter="energy", coordinate="year",
                value="R1", owner=3, **ASKED)
    trace.event("coord_ask", 7, parameter="energy", coordinate="year",
                value="R2", owner=3, **ASKED)
    trace.event("follow_ask", 7, parameter="energy", coordinate="year",
                value="R1", owner=3, asked="coord", **ASKED)
    trace.event("follow_ask", 7, parameter="energy", coordinate="year",
                value="R1", owner=3, asked="coord", **ASKED)
    trace.event("coord_ask", 7, parameter="energy", coordinate="year",
                value="R2", owner=3, picture="A", **ASKED)
    first, second, follow, again, picture = events(traced)
    assert [e["rid"] for e in (first, second, follow, again, picture)] == [
        1, 2, 3, 4, 5]
    # a follow-up follows its own value's request, the next one the
    # follow-up before it, the same request with a picture its request
    assert (follow["of"], again["of"], picture["of"]) == (1, 3, 2)
    # the failures by construction: a request asked the first time follows
    # nothing, and a follow-up of a value never asked follows nothing
    assert "of" not in first and "of" not in second
    trace.event("follow_ask", 7, parameter="energy", coordinate="year",
                value="R9", owner=3, asked="coord", **ASKED)
    assert "of" not in events(traced)[-1]
    # another document counts from 1 again
    trace.event("coord_ask", 8, **ASKED)
    assert events(traced, "plan8")[0]["rid"] == 1
    for event in events(traced):
        jsonschema.validate(event, schema.trace_schema())


def hit(kind, owner_id, score):
    return {"owner_kind": kind, "owner_id": owner_id, "score": score}


def test_a_search_writes_its_vector_places_reranker_and_pieces_under_one_number(
        traced):
    hits = [hit("table", 30, 0.9), hit("section", 20, 0.8),
            hit("table", 31, 0.7), hit("table", 32, 0.6),
            hit("section", 21, 0.5)]
    sources = [SimpleNamespace(owner_kind=h["owner_kind"],
                               owner_id=h["owner_id"], text="t")
               for h in hits]
    # a reranker whose server scores a passage by its number
    reranker = rerank.Reranker(base_url="http://x", model="m", post=lambda body: {
        "results": [{"index": i, "relevance_score": float(len(d))}
                    for i, d in enumerate(body["documents"])]})
    with rules.overlaid(trace_vector_places=2, rerank_pool=1, rerank_drawn=1,
                        rerank_drawn_from=3), \
            trace.searching(7, sentences=["Der Plan sagt es."]) as sid:
        runner.trace_vector(7, ["Der Plan sagt es."], {("section", 99)},
                            hits, None, 0.0)
        reranker.order(7, ["Der Plan sagt es."], sources)
        chunks = [SimpleNamespace(key=("table", 32, 0), owner=("table", 32)),
                  SimpleNamespace(key=("section", 77, 1),
                                  owner=("section", 77))]
        from docpipe.extraction import addressed
        addressed.trace_pick(7, chunks, chunks)
    with trace.searching(7, sentences=["Ein anderer Satz."]) as other:
        pass
    search, vector, ranked, pick, second = events(traced)
    assert (search["sid"], vector["sid"], ranked["sid"], pick["sid"]) == (
        sid, sid, sid, sid)
    # a second search has a number of its own
    assert second["sid"] == other == sid + 1
    # the vector places of each kind, best first, as many as the rule says,
    # and how many of each kind it ranked; what it left out as taken
    assert vector["places"] == {"table": [[30, 0.9], [31, 0.7]],
                                "section": [[20, 0.8], [21, 0.5]]}
    assert vector["of_kind"] == {"table": 3, "section": 2}
    assert vector["excluded"] == [["section", 99]]
    # the pool: the best of each kind and one drawn from places 2 to 3 of
    # the tables; the sections have no place after their best to draw
    # from up to 3 but 21; each scored, in the order the scores make
    drawn = {tuple(d) for d in ranked["drawn"]}
    assert drawn in ({("table", 31), ("section", 21)},
                     {("table", 32), ("section", 21)})
    assert len(ranked["order"]) == 4 and ranked["rest"] == 1
    assert ranked["pairs"]["scored"] == 4
    # a piece taken says its place in the search and where its passage
    # stood among the tables of the vector search; the failure by
    # construction: a passage the vector search never ranked has no place
    assert pick["pieces"] == [["table", 32, 0, 1, 3],
                              ["section", 77, 1, 2, None]]
    for event in events(traced):
        jsonschema.validate(event, schema.trace_schema())


def test_a_request_of_a_search_names_the_search_and_its_pieces_places(traced):
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 10 + i}) for i in range(12)]
    model = Model(
        find=lambda p, n: {"found": [{"at": "3.2", "words": "1.200"}]}
        if n.get("owner") == 3 else {"found": []})
    reader = Reader(SPEC, model.asks(), in_order, budget=6)
    reader(plan_of(TABLE, *many), [ENERGY])
    found = [n for _, n in model.of("search")
             if n.get("coordinate") == "year" and n.get("shows") == "found"]
    assert found
    picks = {e["sid"]: e for e in events(traced, kind="pick")}
    for noted in found:
        # the search the request's pieces come from is in the trace, and
        # each piece's place there is its place in what the search took
        pick = picks[noted["sid"]]
        place = {tuple(p[:3]): p[3] for p in pick["pieces"]}
        for kind, owner, index, sid, at in noted["pieces"]:
            assert sid == noted["sid"]
            assert at == list(place).index((kind, owner, index)) + 1
        # every letter it shows names a passage and its lines
        assert all(len(run) == 5 for runs in noted["blocks"].values()
                   for run in runs)
    # the failure by construction: the request beside the value takes no
    # search's pieces and names none
    near = [n for _, n in model.of("search") if n.get("shows") == "near"]
    assert near and all("sid" not in n for n in near)


def test_what_became_of_each_find_is_written_with_the_request_it_answers(
        traced):
    model = Model(find=lambda p, n: {"found": [
        {"at": "9.2", "words": "1.200"}, {"at": "3.2", "words": "1.200"}]}
        if n.get("owner") == 3 else {"found": []})
    trace.event("find_ask", 7, owner=3, **ASKED)
    reader = Reader(SPEC, model.asks(), in_order)
    reader(plan_of(TABLE), [ENERGY])
    (finds, *_) = [e for e in events(traced, kind="finds")
                   if e["stage"] == "values"]
    assert finds["of"] == 1
    bad, good = finds["entries"]
    # the address that names no shown line is refused with its reason, the
    # one that does names its passage and line and holds
    assert (bad["held"], bad["why"]) == (False, "not_an_address")
    assert good["held"] and good["place"][:3] == ["table", 3, 3]
    for event in events(traced):
        jsonschema.validate(event, schema.trace_schema())


def test_a_request_asked_again_says_why_and_how_long_it_waited(traced,
                                                              monkeypatch):
    monkeypatch.setattr(runner, "retry_wait", lambda attempt, transport: (
        7.5 if transport else 0.25))
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    class Unavailable(Exception):
        status_code = 503
    failures = runner.Failures(7, where="coord")
    assert failures.failed(Unavailable("the server is busy"))
    failures.wait(1)
    failures.answered()
    failures.fault()
    failures.wait(2)
    server, form = events(traced, kind="retry")
    assert (server["what"], server["why"], server["wait_s"]) == (
        "coord", "server", 7.5)
    assert (form["why"], form["wait_s"], form["attempt"]) == ("form", 0.25, 2)
    for event in events(traced):
        jsonschema.validate(event, schema.trace_schema())


def test_the_head_says_what_the_run_is_and_blanks_what_authenticates(
        traced, tmp_path):
    secret = "sk-not-for-the-trace"
    trace.set_head(lambda: {
        "code": "abc", "rules": trace.blanked(
            {"llm_api_key": secret, "rerank_pool": 15, "rerank_api_key": "",
             "catalogue_user_agent": "docpipe",
             # the failures by construction: rules whose names hold "key"
             # and "token" but say no secret, an address with a password,
             # and a name no rule defines that ends as a secret's does
             "max_tokens": 4096, "repeat_key": "parameter",
             "llm_base_url": "http://user:pw-not-for-the-trace@host:8000/v1",
             "OEP_API_TOKEN": "tok-not-for-the-trace"})})
    trace.open_trace(tmp_path / "again", lambda d: f"plan{d}")
    trace.event("asked", 7, requests={})
    trace.close()
    path = trace.path_of(tmp_path / "again", "plan7")
    head = next(e for e in trace.lines(path) if e["t"] == "run")
    pieces = trace.pieces_of(list(trace.lines(path)))
    held = head["rules"] if "piece" not in head["rules"] \
        else json.loads(pieces[head["rules"]["piece"]])
    assert head["code"] == "abc"
    assert held["llm_api_key"] == held["OEP_API_TOKEN"] == trace.BLANKED
    # what does not authenticate stays whole, whatever its name holds, and
    # an empty key stays empty
    assert held["rerank_pool"] == 15 and held["rerank_api_key"] == ""
    assert held["catalogue_user_agent"] == "docpipe"
    assert (held["max_tokens"], held["repeat_key"]) == (4096, "parameter")
    # an address keeps its host, port and path
    assert held["llm_base_url"] == "http://***@host:8000/v1"
    # no key and no password is anywhere in the file
    import gzip
    written = gzip.open(path, "rt", encoding="utf-8").read()
    for kept_out in (secret, "pw-not-for-the-trace", "tok-not-for-the-trace"):
        assert kept_out not in written


def test_a_round_says_how_many_turns_it_ran_and_why_it_ended(traced):
    from docpipe.extraction.engine import Engine, Scope
    engine = Engine.__new__(Engine)
    turns = []

    def run_steps(steps, scope):
        turns.append(scope.get("round"))
        if scope.get("round") == 3:
            scope.used_up()
    engine.run_steps = run_steps
    engine.holds = lambda condition, scope: False
    scope = Scope(None, True, plan=SimpleNamespace(document_id=7))
    node = {"id": "r1", "round": {"most": 5}}
    engine.run_node(node, scope)
    (step,) = events(traced, kind="step")
    assert (step["node"], step["kind"], step["turns"], step["ended"]) == (
        "r1", "round", 3, "used_up")
    # the failure by construction: a round that never uses its supply up
    # runs its most turns and says so
    engine.run_steps = lambda steps, scope: None
    engine.run_node({"id": "r2", "round": {"most": 2}}, scope)
    assert events(traced, kind="step")[-1]["ended"] == "most"
    for event in events(traced):
        jsonschema.validate(event, schema.trace_schema())
