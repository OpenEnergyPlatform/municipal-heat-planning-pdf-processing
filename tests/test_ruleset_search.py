"""The rules of the search, the calculation, the marking in the PDF, the
catalogue and the front pages decide, read at the time of use (owner
decision 2026-11-11): a step of the flow sets its own value, the
standard gives today's result.

The promises, each with a case that breaks it by construction:

1. The reranker is given as many passages of each kind as `rerank_pool` (or
   `rerank_pool_by_kind`) says WHEN IT ORDERS, AND the rule of a step wins
   over the run's, AND the standard is 100.
2. Sentences are put together as `sentence_fusion` says, in the reranker AND
   in the vector search, from one function.
3. The vector search takes only the kinds of `search_kinds`, only owners in
   the top `sentence_top` of a sentence, and with `search_full_ranking` off
   only as many as asked for.
4. The reranker's model, picture, length and waiting time are the rules'.
5. A calculation waits `code_timeout_s` and is sent again `code_resend`
   times.
6. A quote is placed with `locate_min_score` and `locate_max_lines`.
7. `learn_no_temperature` off leaves a refused temperature an error.
8. The calculation of the KWP profile follows its rules: what counts as an
   amount, when a share is asked, which axes a share looks over, how many
   places a number shows, the qualifier of mixed numbers.
9. The catalogue follows its rules: keys and their order, what it fills,
   what a title hit needs, how many hits, the client name, which flags a
   looked-up row shares, and that it is offline for the run that found it
   so.
10. The front pages and their order, the regions' words and texts, and the
    values a profile's module had as constants follow the rules.
"""
import json
import sqlite3
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from docpipe import rules
from docpipe.extraction.pipeline import DocumentReport
from docpipe.extraction.spec import load as load_spec
from docpipe.inference import code_exec, faiss_store, pdf_locate, rerank
from docpipe.providers import base

from test_compute_step import (GAS, HOMES, OIL, SPEC as KWP_SPEC, TOTAL,
                               amount, share)
from profiles.kwp import compute
from profiles.scenarios import completion, front
from profiles.scenarios import extraction as scenario_extraction
from conftest import step_node

SCENARIO_SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "scenarios"
     / "extraction_spec.json").read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in ("RERANK_BASE_URL", "RERANK_API_KEY", "RERANK_MODEL",
                 "RERANK_POOL", "CODE_EXEC_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    rules.reset()
    completion.OFFLINE.clear()
    base._NO_TEMPERATURE.clear()
    yield
    rules.reset()
    completion.OFFLINE.clear()
    base._NO_TEMPERATURE.clear()


def at(kind: str, **values):
    """What the engine does around a step of *kind* with its own values."""
    return rules.in_step(rules.stepped(step_node(kind), values))


# -- 1, 2, 4: the reranker ----------------------------------------------------

def passage(kind, owner_id, text=""):
    return SimpleNamespace(owner_kind=kind, owner_id=owner_id,
                           text=text or f"{kind} {owner_id}")


class Server:
    def __init__(self, by=None):
        self.by = by or {}
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        results = []
        for i, document in enumerate(body["documents"]):
            text = document if isinstance(document, str) else \
                document["content"][-1]["text"]
            results.append({"index": i, "relevance_score":
                            self.by.get((body["query"], text), 0.0)})
        return {"results": results, "usage": {"prompt_tokens": 1}}


FOUND = [passage("table", 1), passage("table", 2), passage("table", 3),
         passage("section", 4), passage("section", 5)]


def sent(server) -> list:
    return [d if isinstance(d, str) else d["content"][-1]["text"]
            for body in server.bodies for d in body["documents"]]


def test_the_pool_is_read_when_the_search_orders():
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server)
    ranker.order(1, ["q"], FOUND)
    assert len(sent(server)) == 5                       # the standard: 100
    assert rules.get("rerank_pool") == 100
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server)
    with rules.overlaid(rerank_pool=2):
        ranker.order(2, ["q"], FOUND)                   # the same object
    assert sorted(sent(server)) == ["section 4", "section 5", "table 1",
                                    "table 2"]


def test_a_step_sets_the_pool_for_itself_and_a_kind_has_its_own():
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server)
    with at("search", rerank_pool=1):
        ranker.order(1, ["q"], FOUND)
    assert sorted(sent(server)) == ["section 4", "table 1"]
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server)
    with at("search", rerank_pool=1, rerank_pool_by_kind={"table": 3}):
        ranker.order(1, ["q"], FOUND)
    assert sorted(sent(server)) == ["section 4", "table 1", "table 2",
                                    "table 3"]
    assert rerank.pool_size("table") == 100             # outside: the run's


def test_the_reranker_of_the_pieces_has_a_pool_of_its_own():
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server,
                             pool_rule="rerank_chunk_pool")
    with rules.overlaid(rerank_pool=1, rerank_chunk_pool=2):
        ranker.order(1, ["q"], FOUND)
    assert len(sent(server)) == 4


def test_sentences_are_fused_as_the_rule_says():
    found = [passage("section", 1), passage("section", 2)]
    by = {("a", "section 1"): 0.9, ("b", "section 1"): 0.0,
          ("a", "section 2"): 0.5, ("b", "section 2"): 0.5}
    first = lambda: [s.owner_id for s in rerank.Reranker(
        base_url="http://x", post=Server(by)).order(1, ["a", "b"], found)]
    assert first() == [1, 2]                            # max: 0.9 beats 0.5
    with rules.overlaid(sentence_fusion="mean"):
        assert first() == [2, 1]                        # 0.5 beats 0.45
    with at("search", sentence_fusion="sum"):
        assert first() == [2, 1]                        # 1.0 beats 0.9
    assert rerank.fused([0.2, 0.6]) == 0.6
    assert rerank.fused([0.2, 0.6], "sum") == pytest.approx(0.8)
    with pytest.raises(ValueError):
        rerank.fused([1], "median")


def test_the_model_the_picture_the_length_and_the_waiting_are_the_rules():
    picture = {"type": "image_url", "image_url": {"url": "data:x"}}
    found = [passage("figure", 1), passage("table", 2)]
    server = Server()
    ranker = rerank.Reranker(base_url="http://x", post=server,
                             image_of=lambda s: picture
                             if s.owner_kind == "figure" else None)
    ranker.order(1, ["q"], found)
    body = server.bodies[0]
    assert body["model"] == rerank.SERVED_MODEL
    assert body["truncate_prompt_tokens"] == -1
    assert isinstance(body["documents"][0], dict)       # figure with picture
    with at("search", rerank_model="other/model", rerank_with_images=False,
            rerank_truncate_tokens=512):
        ranker.order(1, ["q"], found)
    body = server.bodies[1]                 # scored again: another model
    assert body["model"] == "other/model"
    assert body["truncate_prompt_tokens"] == 512
    assert body["documents"] == ["figure 1", "table 2"]


def test_the_server_and_the_key_come_from_the_rules_and_nothing_times_out(
        monkeypatch):
    assert rerank.make_reranker() is None               # no server: none
    with rules.overlaid(rerank_base_url=" http://s/ ", rerank_api_key="k"):
        ranker = rerank.make_reranker()
        assert ranker.base_url == "http://s"
        assert ranker.api_key == "k"
        taken = {}

        def post(url, json, headers, timeout):
            taken.update(url=url, headers=headers, timeout=timeout)
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"results": []})
        import httpx
        monkeypatch.setattr(httpx, "post", post)
        ranker.post({"documents": []})
        assert taken["timeout"] is None    # never gives up waiting
        assert taken["url"] == "http://s/rerank"
        assert taken["headers"] == {"Authorization": "Bearer k"}
    assert not hasattr(rerank, "RERANK_BASE_URL")   # no bridge of old names


def test_the_embedding_server_waits_as_long_as_the_rule_says(monkeypatch):
    from docpipe.embedding.api import ApiEmbedder
    taken = {}

    def post(url, json, headers, timeout):
        taken["timeout"] = timeout
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"data": [{"embedding": [1.0]}]})
    import httpx
    monkeypatch.setattr(httpx, "post", post)
    embedder = ApiEmbedder(base_url="http://s", api_key="k", model="m",
                           form="messages")
    with rules.overlaid(embed_timeout_s=7):
        embedder.embed([{"text": "a sentence"}])
    assert taken["timeout"] == 7.0
    embedder.embed([{"text": "a sentence"}])        # the standard otherwise
    assert taken["timeout"] == float(rules.get("embed_timeout_s")) != 7.0


# -- 3: the vector search -----------------------------------------------------

def prepared(owners):
    """A prepared document whose vector i belongs to owners[i]."""
    ids = list(range(len(owners)))
    return {"faiss_ids": ids, "owner_of": dict(zip(ids, owners)),
            "rows_per_owner": {}, "index": None}


def fused(scores, positions, owners, **more):
    hits = faiss_store.fuse_prepared(
        None, prepared(owners), np.array(scores, dtype="float32"),
        np.array(positions), more.pop("limit", 0),
        content_fetcher=lambda conn, kind, owner: {"kind": kind, "id": owner},
        **more)
    return [(hit["kind"], hit["id"]) for hit in hits]


OWNERS = [("section", 1), ("table", 2), ("figure", 3)]
# sentence 0 likes vector 0, sentence 1 likes 1 and 2
SCORES = [[0.9, 0.2, 0.1], [0.3, 0.8, 0.7]]
POSITIONS = [[0, 1, 2], [1, 2, 0]]
SCORES1 = [[0.9, 0.2, 0.1], [0.8, 0.7, 0.3]]


def test_the_search_ranks_by_the_best_sentence_as_standard():
    assert fused(SCORES1, POSITIONS, OWNERS) == [
        ("section", 1), ("table", 2), ("figure", 3)]


def test_mean_counts_what_every_sentence_gave_also_below_the_cut():
    # owner A: 0.9 from sentence 0 and 0.0 from 1; owner B: 0.5 and 0.5.
    scores = [[0.9, 0.5], [0.5, 0.0]]
    positions = [[0, 1], [1, 0]]
    owners = [("section", 1), ("section", 2)]
    assert fused(scores, positions, owners) == [("section", 1),
                                                ("section", 2)]
    with rules.overlaid(sentence_fusion="mean", sentence_top=1):
        assert fused(scores, positions, owners) == [("section", 2),
                                                    ("section", 1)]


def test_a_kind_left_out_of_the_search_is_no_hit():
    assert ("figure", 3) in fused(SCORES1, POSITIONS, OWNERS)
    with at("search", search_kinds=["section", "table"]):
        assert fused(SCORES1, POSITIONS, OWNERS) == [("section", 1),
                                                     ("table", 2)]


def test_the_top_of_a_sentence_limits_who_is_a_hit_and_the_caller_wins():
    scores = [[0.9, 0.8, 0.1], [0.2, 0.1, 0.0]]
    positions = [[0, 1, 2], [0, 1, 2]]
    assert len(fused(scores, positions, OWNERS)) == 3
    with rules.overlaid(sentence_top=1):
        assert fused(scores, positions, OWNERS) == [("section", 1)]
        assert len(fused(scores, positions, OWNERS, per_probe_top=2)) == 2


def test_without_the_full_ranking_only_as_many_as_asked_for_are_kept():
    scores = [[0.9, 0.8, 0.1], [0.95, 0.2, 0.1]]
    positions = [[0, 1, 2], [2, 1, 0]]
    got = fused(scores, positions, OWNERS)
    assert ("figure", 3) in got and len(got) == 3
    with rules.overlaid(search_full_ranking=False):
        # one per sentence: section 1 and figure 3; table 2 is out
        assert fused(scores, positions, OWNERS, limit=1) == [
            ("figure", 3)]
        assert sorted(fused(scores, positions, OWNERS, limit=2)) == [
            ("figure", 3), ("section", 1)]
    # with no limit the whole ranking stays, switch or not
    with rules.overlaid(search_full_ranking=False):
        assert len(fused(scores, positions, OWNERS)) == 3


# -- 5, 6, 7: the calculation, the marking, the temperature -------------------

def sandbox(monkeypatch, answers):
    calls = []

    def urlopen(request, timeout):
        calls.append(timeout)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(answer).encode()
        return Reply()
    monkeypatch.setattr(code_exec.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(code_exec.config, "CODE_EXEC_URL", "http://sb/run")
    return calls


def test_a_calculation_waits_as_long_as_the_rule_says(monkeypatch):
    calls = sandbox(monkeypatch, [{"ok": True}, {"ok": True}, {"ok": True}])
    code_exec.run_code("1")
    assert calls == [45.0]
    with at("compute", code_timeout_s=9):
        code_exec.run_code("1")
    assert calls[-1] == 9.0
    code_exec.run_code("1", timeout=3)
    assert calls[-1] == 3.0                    # the caller's wins


def test_a_failed_calculation_is_sent_again_as_often_as_the_rule_says(
        monkeypatch):
    fail = urllib.error.URLError("down")
    calls = sandbox(monkeypatch, [fail, fail, fail])
    assert code_exec.run_code("1")["ok"] is False
    assert len(calls) == 1                              # today: never
    with at("compute", code_resend=2):
        assert code_exec.run_code("1")["ok"] is False
    assert len(calls) == 4                      # the one before, 1 + 2 more
    calls = sandbox(monkeypatch, [fail, {"ok": True, "stdout": "2"}])
    with at("compute", code_resend=2):
        assert code_exec.run_code("1")["ok"] is True
    assert len(calls) == 2                      # stops at the first success
    # Code that failed is not the sandbox's failure: it is not sent again,
    # and the answer does not say the sandbox failed.
    broken = {"ok": False, "stderr": "NameError", "exit_code": 1}
    calls = sandbox(monkeypatch, [broken, broken, broken])
    with at("compute", code_resend=2):
        out = code_exec.run_code("x")
    assert len(calls) == 1 and not out.get("sandbox")
    calls = sandbox(monkeypatch, [fail])
    assert code_exec.run_code("1")["sandbox"] is True


WORDS = [(10, 10, 40, 20, "Der", 0, 0, 0), (45, 10, 90, 20, "Wert", 0, 0, 1),
         (10, 30, 60, 40, "lautet", 0, 1, 0),
         (65, 30, 100, 40, "120", 0, 1, 1)]


def test_a_quote_is_placed_by_the_score_and_the_lines_of_the_rules(
        monkeypatch):
    import sys
    import types
    # rapidfuzz is not needed to see what the rules decide: a stand-in that
    # scores every alignment 80 and spans the whole page
    fuzz = types.SimpleNamespace(partial_ratio_alignment=lambda quote, text:
                                 SimpleNamespace(score=80, dest_start=0,
                                                 dest_end=len(text)))
    monkeypatch.setitem(sys.modules, "rapidfuzz",
                        types.SimpleNamespace(fuzz=fuzz))
    monkeypatch.setattr(pdf_locate, "_MISSING", "")
    assert len(pdf_locate.rects_from_words(WORDS, "a quote")) == 2
    with at("write", locate_min_score=81):
        assert pdf_locate.rects_from_words(WORDS, "a quote") is None
    with at("write", locate_min_score=80):
        assert pdf_locate.rects_from_words(WORDS, "a quote") is not None
    with at("write", locate_max_lines=1):
        assert len(pdf_locate.rects_from_words(WORDS, "a quote")) == 1
    assert len(pdf_locate.rects_from_words(WORDS, "a quote",
                                           max_lines=1)) == 1
    assert pdf_locate.rects_from_words(WORDS, "a quote",
                                       min_score=90) is None
    with rules.overlaid(locate_match="partial_ratio"):
        assert pdf_locate.rects_from_words(WORDS, "a quote")


class Refused(Exception):
    status_code = 400


def test_a_refused_temperature_is_learned_unless_the_rule_is_off():
    exc = Refused("temperature is not supported by this model")
    with at("find", learn_no_temperature=False):
        assert base.refused_temperature("p", "m", exc) is False
        assert base.sends_temperature("p", "m")
    assert base.refused_temperature("p", "m", exc) is True
    assert not base.sends_temperature("p", "m")


# -- 8: the calculation of the KWP profile ------------------------------------

def questions(*rows):
    return [(q.kind, sorted(n.value for n in q.numbers))
            for q in compute.questions(list(rows), KWP_SPEC)]


def test_a_sum_needs_as_many_parts_as_the_rule_says():
    rows = [amount(120, GAS), amount(80, OIL)]
    assert [kind for kind, _ in questions(*rows)] == ["sum"]
    with at("compute", compute_least_parts=3):
        assert questions(*rows) == []


def test_a_group_holds_its_sum_from_as_many_numbers_as_the_rule_says():
    parts = [{"value_target": 120.0}, {"value_target": 80.0},
             {"value_target": 200.0}]
    assert compute.holds_its_sum(parts) is True
    with at("compute", sum_printed_least_numbers=4):
        assert compute.holds_its_sum(parts) is False


def test_the_rounding_of_a_step_decides_what_is_the_same_number():
    a, b = {"value_target": 100.0}, {"value_target": 104.0}
    assert compute.same_number(a, b) is False
    with at("compute", rounding_tolerance=0.1):
        assert compute.same_number(a, b) is True


def test_zero_the_frame_and_an_out_quantity_count_only_where_the_rules_say():
    zero = amount(0, GAS)
    assert not compute.additive(zero, KWP_SPEC)
    with at("compute", compute_zero_counts=True):
        assert compute.additive(zero, KWP_SPEC)
    unframed = {**amount(5, GAS), "year_state": "unstated"}
    assert not compute.additive(unframed, KWP_SPEC)
    with at("compute", compute_needs_frame=False):
        assert compute.additive(unframed, KWP_SPEC)
    out = {**amount(5, GAS), "quantity": "out:specific"}
    assert not compute.additive(out, KWP_SPEC)
    with at("compute", compute_out_quantity_counts=True):
        assert compute.additive(out, KWP_SPEC)


def test_a_share_without_a_total_is_asked_unless_the_rule_says_not():
    alone = share(21, OIL, HOMES)
    assert [kind for kind, _ in questions(alone)] == ["share"]
    with at("compute", share_ask_without_whole=False):
        assert questions(alone) == []


def test_a_share_looks_for_its_whole_over_the_axes_of_the_parts_rule():
    # An axis the rule adds is asked for shares too: the share names a
    # sector its total does not carry.
    assert compute.split_axes() == ("carrier", "sector", "technology")
    parts = dict(rules.get("compute_parts", "kwp"))
    del parts["technology"]
    with at("compute", compute_parts=parts):
        assert compute.split_axes() == ("carrier", "sector")
    with at("compute", compute_parts={**parts, "building": "out:total"}):
        assert compute.split_axes() == ("carrier", "sector", "building")


def test_numbers_are_shown_with_the_places_of_the_rule():
    row = {**amount(1234567, GAS), "parameter": "energy_consumption"}
    row["value_target"] = 1.0 / 3.0 * 1000
    shown = compute.number(row, KWP_SPEC, "GWh/a").value
    assert shown == round(row["value_target"] / 1000.0, 6)
    with at("compute", shown_number_places=2):
        assert compute.number(row, KWP_SPEC, "GWh/a").value == 0.33


def test_mixed_qualifiers_take_the_entry_of_the_rule():
    exact = {"qualifier": "out:unstated", "qualifier_state": "unstated"}
    approx = {"qualifier": "out:ca", "qualifier_raw": "ca.",
              "qualifier_quote": "ca. 3", "qualifier_state": "read"}
    row = compute.qualified({}, [exact, approx])
    assert row["qualifier"] == "out:approximate"
    with at("compute", compute_mixed_qualifier="out:about"):
        assert compute.qualified({}, [exact, approx])["qualifier"] == \
            "out:about"


# -- 9: the catalogue ---------------------------------------------------------

TITLE = "Socio-economic factors and future challenges of 1.5 goal"
DOI = "10.1080/17583004.2018.1477374"


def read_row(parameter, value, page=1):
    return {"parameter": parameter, "parameter_state": "read",
            "value": value, "value_raw": value, "quote": value,
            "work": "work:this_publication", "work_state": "read",
            "tier": "text_located",
            "provenance": {"document_id": 4, "page": page,
                           "owner_kind": "section", "owner_id": 1}}


def record(*authors):
    return {"id": "https://openalex.org/W1", "doi": f"https://doi.org/{DOI}",
            "display_name": "T", "publication_year": 2018,
            "publication_date": "2018-06-11",
            "authorships": [{"author": {"display_name": a}}
                            for a in authors]}


def report_of(*rows):
    report = DocumentReport(document_id=4)
    report.tuples.extend(rows)
    return report


def test_a_hit_is_accepted_by_as_many_authors_as_the_rule_says():
    hit = record("Jingyu Liu", "Shinichiro Fujimori")
    read = ["Jing-Yu Liu*", "Shinichiro Fujimori1"]
    assert completion.accepted(hit, read) is True
    with at("write", catalogue_family_names=3):
        # fewer authors than three: all of them agree, as today
        assert completion.accepted(hit, read) is True
        with rules.overlaid(catalogue_fewer_authors_suffice=False):
            assert completion.accepted(hit, read) is False
    one = record("Jingyu Liu")
    assert completion.accepted(one, ["Jingyu Liu"]) is True
    with rules.overlaid(catalogue_fewer_authors_suffice=False):
        assert completion.accepted(one, ["Jingyu Liu"]) is False
        assert completion.accepted(hit, read) is True       # two agree


def test_a_name_word_has_the_letters_of_the_rule():
    assert completion.words("Li Wu Kim") == {"li", "wu", "kim"}
    with rules.overlaid(name_word_least_letters=3):
        assert completion.words("Li Wu Kim") == {"kim"}
        assert completion.family("Jingyu Li") == "jingyu"


def test_the_keys_are_asked_in_the_order_and_only_those_of_the_rule():
    rows = [read_row("publication_title", TITLE),
            read_row("publication_doi", "10.1/read")]
    asked = []

    def by_doi(doi):
        asked.append(("doi", doi))
        return None

    def by_title(title):
        asked.append(("title", title))
        return None
    run = lambda: completion.complete(
        report_of(*rows), SCENARIO_SPEC, fetch=by_title, fetch_doi=by_doi,
        catalogue_doi="10.1/index")
    run()
    assert [k for k, _ in asked] == ["doi", "doi", "title"]
    assert [v for _, v in asked][:2] == ["10.1/index", "10.1/read"]
    asked.clear()
    with rules.overlaid(catalogue_key_order=["title", "doi"]):
        run()
    assert [k for k, _ in asked] == ["title", "doi"]
    asked.clear()
    with rules.overlaid(catalogue_key_order=["title"]):
        run()
    assert asked == [("title", TITLE)]


def test_the_catalogue_fills_what_the_rule_names():
    rows = [read_row("publication_title", TITLE),
            read_row("publication_author", "Jingyu Liu"),
            read_row("publication_author", "Shinichiro Fujimori")]
    hit = record("Jingyu Liu", "Shinichiro Fujimori")
    report = report_of(*rows)
    outcome = completion.complete(report, SCENARIO_SPEC,
                                  fetch=lambda title: hit)
    assert set(outcome["filled"]) == {"publication_doi",
                                      "publication_date"}
    report = report_of(*rows)
    with rules.overlaid(catalogue_fills=["publication_doi"]):
        outcome = completion.complete(report, SCENARIO_SPEC,
                                      fetch=lambda title: hit)
    assert outcome["filled"] == ["publication_doi"]
    with rules.overlaid(catalogue_fills=[]):
        assert completion.complete(report_of(*rows), SCENARIO_SPEC,
                                   fetch=lambda title: hit) is None


def test_a_title_hit_needs_its_authors_only_where_the_rule_says():
    rows = [read_row("publication_title", TITLE),
            read_row("publication_author", "Somebody Else"),
            read_row("publication_author", "Another One")]
    stranger = record("Jingyu Liu", "Shinichiro Fujimori")
    refused = completion.complete(report_of(*rows), SCENARIO_SPEC,
                                  fetch=lambda title: stranger)
    assert refused["outcome"] == "authors"
    with rules.overlaid(catalogue_title_hit_needs_authors=False):
        taken = completion.complete(report_of(*rows), SCENARIO_SPEC,
                                    fetch=lambda title: stranger)
    assert taken["outcome"] == "taken"


def test_a_looked_up_row_shares_the_flags_of_the_rule():
    anchor = {**read_row("publication_title", TITLE),
              "flags": ["not_located", "other"]}
    row = completion.row_of(anchor, "publication_doi", DOI, record(), (
        "title", TITLE), [])
    assert row["flags"] == ["not_located", "catalogue"]
    with rules.overlaid(catalogue_inherited_flags=["other"]):
        row = completion.row_of(anchor, "publication_doi", DOI, record(), (
            "title", TITLE), [])
    assert row["flags"] == ["other", "catalogue"]


def test_the_title_search_looks_at_the_hits_and_names_the_client(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen.update(url=request.full_url, agent=request.get_header(
            "User-agent"), timeout=timeout)
        raise urllib.error.URLError("stop")
    monkeypatch.setattr(completion.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.URLError):
        completion.search_hits("a title")
    assert "per_page=1" in seen["url"] and seen["agent"] == "docpipe"
    with rules.overlaid(catalogue_hits_taken=3,
                        catalogue_user_agent="my-client",
                        catalogue_timeout_s=5):
        with pytest.raises(urllib.error.URLError):
            completion.search_hits("a title")
    assert "per_page=3" in seen["url"] and seen["agent"] == "my-client"
    assert seen["timeout"] == 5


def test_the_first_hit_whose_authors_agree_is_taken(monkeypatch):
    wrong, right = record("A Stranger"), record("Jingyu Liu")
    monkeypatch.setattr(completion, "search_hits",
                        lambda title: [wrong, right])
    monkeypatch.setattr(completion, "search", lambda title: wrong)
    assert completion._by_title("t", ["Jingyu Liu"]) is wrong
    with rules.overlaid(catalogue_hits_taken=2):
        assert completion._by_title("t", ["Jingyu Liu"]) is right
        assert completion._by_title("t", ["Nobody"]) is wrong


def down(title):
    raise urllib.error.URLError("unreachable")


def test_the_catalogue_is_offline_for_the_run_and_not_for_the_process():
    rows = [read_row("publication_title", TITLE)]
    assert completion.complete(report_of(*rows), SCENARIO_SPEC,
                               fetch=down)["outcome"] == "offline"
    asked = []

    def fetch(title):
        asked.append(title)
        return None
    # the same run: not asked again
    assert completion.complete(report_of(*rows), SCENARIO_SPEC,
                               fetch=fetch)["outcome"] == "offline"
    assert asked == []
    # a run that starts afterwards asks again
    rules.reset()
    assert completion.complete(report_of(*rows), SCENARIO_SPEC,
                               fetch=fetch)["outcome"] == "no_hit"
    assert asked == [TITLE]


def test_the_catalogue_is_asked_again_when_the_rule_says_not_to_stop():
    rows = [read_row("publication_title", TITLE)]
    with rules.overlaid(catalogue_stop_when_offline=False):
        assert completion.complete(report_of(*rows), SCENARIO_SPEC,
                                   fetch=down)["outcome"] == "offline"
        asked = []
        assert completion.complete(
            report_of(*rows), SCENARIO_SPEC,
            fetch=lambda t: asked.append(t))["outcome"] == "no_hit"
        assert asked == [TITLE]


# -- 10: the front pages, the regions, the constants of a profile -------------

def graph_rules(tmp_path, monkeypatch, **values):
    """Read the graph rules with *values* laid over the files."""
    from docpipe import graphfile
    file = tmp_path / "graph.json"
    file.write_text(json.dumps({"rules": values}), encoding="utf-8")
    monkeypatch.setenv(graphfile.ENV, str(file))
    graphfile.reset()


def test_the_front_pages_and_their_order_follow_the_rules(tmp_path,
                                                          monkeypatch):
    from docpipe import graphfile
    rows = [read_row("publication_title", "t", page=3)]
    on_front = read_row("publication_doi", "a", page=1)
    elsewhere = read_row("publication_doi", "b", page=9)
    looked = {**read_row("publication_doi", "c", page=9),
              "flags": ["catalogue"]}
    every = [elsewhere, on_front, looked]
    try:
        graphfile.reset()
        assert front.front_pages(rows) == {1, 3}
        assert front.in_order(every, {1}) == [on_front]
        assert front.in_order([elsewhere], {1}) == [elsewhere]
        graph_rules(tmp_path, monkeypatch, front_pages_rule="first page")
        assert front.front_pages(rows) == {1}
        graph_rules(tmp_path, monkeypatch, front_pages_rule="title page")
        assert front.front_pages(rows) == {3}
        assert front.front_pages([]) == {1}
        graph_rules(tmp_path, monkeypatch,
                    front_order=["catalogue", "front", "any"])
        assert front.in_order(every, {1}) == [looked]
        graph_rules(tmp_path, monkeypatch, front_order=["front"])
        assert front.in_order([elsewhere], {1}) == []
    finally:
        monkeypatch.delenv(graphfile.ENV, raising=False)
        graphfile.reset()
    assert front.FRONT_FIELDS == front.front_fields()


def test_a_region_is_a_whole_word_unless_the_rule_says_otherwise():
    labels = ["Niger"]
    assert scenario_extraction._mentioned("from Nigeria", labels) is False
    assert scenario_extraction._mentioned("from Niger.", labels) is True
    with rules.overlaid(region_whole_words=False):
        assert scenario_extraction._mentioned("from Nigeria", labels) is True


def test_the_texts_searched_for_regions_are_those_of_the_rule():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE Sections (id INTEGER, document INTEGER, content TEXT);
        CREATE TABLE Tables (id INTEGER, section INTEGER, markdown TEXT,
                             caption TEXT);
        CREATE TABLE Images (id INTEGER, section INTEGER, description TEXT,
                             caption TEXT);
        INSERT INTO Sections VALUES (1, 4, 'sec');
        INSERT INTO Tables VALUES (1, 1, 'tab', 'tabcap');
        INSERT INTO Images VALUES (1, 1, 'imgdesc', 'imgcap');
    """)
    text = scenario_extraction._document_text
    assert text(conn, 4).split("\n") == ["sec", "tab", "tabcap", "imgdesc",
                                         "imgcap"]
    with rules.overlaid(region_search_texts=["image captions", "sections"]):
        assert text(conn, 4).split("\n") == ["imgcap", "sec"]
    with rules.overlaid(region_search_texts=[]):
        assert text(conn, 4) == ""


def test_the_constants_of_a_profile_are_its_rules_when_asked(monkeypatch):
    from profiles.kwp import extraction as kwp
    assert kwp.FRAME == ("scenario", "year")
    assert kwp.ALT_LABEL_LANGUAGE == "de" and kwp.CONTRACT_LANGUAGE == "de"
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")   # the run's profile
    rules.reset()
    assert scenario_extraction.ALT_LABEL_LANGUAGE == "en"
    assert scenario_extraction.CONTRACT_LANGUAGE == "en"
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    rules.reset()
    assert kwp.PROMPT_CHECKS == ()
    with rules.overlaid(frame_axes=["year"], prompt_checks=[
            {"what": "w", "prompt": "p", "passage": "x",
             "required": "yes"},
            {"what": "w", "prompt": "p", "passage": "y",
             "required": "no"}]):
        assert kwp.FRAME == ("year",)
        assert kwp.PROMPT_CHECKS == (("w", "p", "x", True),
                                     ("w", "p", "y", False))
    with pytest.raises(AttributeError):
        kwp.NO_SUCH_THING
