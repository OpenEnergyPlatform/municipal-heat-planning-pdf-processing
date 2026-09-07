"""answer_question against a stubbed corpus — the turn without any UI."""
import json
from contextlib import contextmanager

import pytest

from docpipe.inference import answer, compare, config


class _Hit(dict):
    pass


def _hit(idx, kind="section", owner=1, text="Der Wärmebedarf betrug 100 GWh.",
         document_id=1):
    # `text` is the key db.fetch_owner_content fills and chunker.format_hit
    # reads; `content` is kept because a hit carries both in the wild.
    return {"owner_kind": kind, "owner_id": owner, "content": text, "text": text,
            "title": "T", "document_id": document_id, "page_number": 1,
            "image_path": None}


@pytest.fixture
def corpus():
    return answer.Corpus(conn=None, index=None, id_to_pos={},
                         embed=lambda item: ([0.0] * 4, False),
                         resolve_image=lambda p: None)


def test_no_hits_returns_an_empty_answer(monkeypatch, corpus):
    monkeypatch.setattr(answer.llm_client, "make_search_phrase", lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.faiss_store, "retrieve", lambda *a, **k: [])
    out = answer.answer_question("Frage?", corpus, 1, [config.SCOPE_TEXT])
    assert out["answer"] is None and out["n_hits"] == 0 and out["phrase"] == "p"


def test_grounded_answer_carries_its_citation(monkeypatch, corpus):
    monkeypatch.setattr(answer.llm_client, "make_search_phrase", lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.faiss_store, "retrieve", lambda *a, **k: [_hit(0)])
    monkeypatch.setattr(answer.llm_client, "answer_from_sources", lambda *a, **k: {
        "found": True, "complete": True, "answer": "100 GWh.",
        "supports": [{"index": 0, "quote": "Der Wärmebedarf betrug 100 GWh."}]})
    monkeypatch.setattr(answer.llm_client, "grounded_quote", lambda q, it: q)

    out = answer.answer_question("Wärmebedarf?", corpus, 1, [config.SCOPE_TEXT])
    assert out["answer"] == "100 GWh."
    assert out["n_findings"] == 1
    assert out["citations"][0]["quote"].startswith("Der Wärmebedarf")


def test_an_ungrounded_answer_is_refused(monkeypatch, corpus):
    """Sources were found, but nothing could be quoted → no answer at all."""
    monkeypatch.setattr(answer.llm_client, "make_search_phrase", lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.faiss_store, "retrieve", lambda *a, **k: [_hit(0)])
    monkeypatch.setattr(answer.llm_client, "answer_from_sources", lambda *a, **k: {
        "found": True, "complete": True, "answer": "Frei erfunden.",
        "supports": [{"index": 0, "quote": "steht so nirgends"}]})
    monkeypatch.setattr(answer.llm_client, "grounded_quote", lambda q, it: None)

    out = answer.answer_question("Frage?", corpus, 1, [config.SCOPE_TEXT])
    assert out["answer"] is None and out["citations"] == []


def test_recheck_excludes_what_earlier_turns_read(monkeypatch, corpus):
    seen = {}
    monkeypatch.setattr(answer.llm_client, "make_search_phrase", lambda *a, **k: ("p", True))

    def _retrieve(conn, index, pos, doc, types, vec, k, exclude=None):
        seen["exclude"] = exclude
        return []
    monkeypatch.setattr(answer.faiss_store, "retrieve", _retrieve)

    history = [{"examined": [["section", 1], ["table", 7]], "recheck": False}]
    out = answer.answer_question("Schau noch mal", corpus, 1, [config.SCOPE_TEXT],
                                 history=history)
    assert seen["exclude"] == {("section", 1), ("table", 7)}
    assert out["recheck"] and out["n_excluded"] == 2


def test_visual_scopes_ask_for_a_caption_style_anchor():
    assert answer.scopes_are_visual([config.SCOPE_FIGURES_VL])
    assert not answer.scopes_are_visual([config.SCOPE_TEXT, config.SCOPE_FIGURES_VL])


def test_progress_is_optional_and_silent_by_default(monkeypatch, corpus):
    """The core must not require a UI to report into."""
    labels = []
    monkeypatch.setattr(answer.llm_client, "make_search_phrase", lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.faiss_store, "retrieve", lambda *a, **k: [])

    @contextmanager
    def _spy(label):
        labels.append(label)
        yield

    answer.answer_question("Frage?", corpus, 1, [config.SCOPE_TEXT])          # no progress
    answer.answer_question("Frage?", corpus, 1, [config.SCOPE_TEXT], progress=_spy)
    assert labels                                                        # got reported


# ---------------------------------------------------------------------------
# One question, several documents (compare.py)
#
# The comparison is the one thing on that screen no citation backs -- it is
# written from the finished answers alone. So what these tests hold is the
# boundary: every document keeps its own retrieval, and the comparison call
# never sees a source passage.
# ---------------------------------------------------------------------------
DOCS = [(1, "Kassel"), (2, "Leipzig"), (3, "Rottweil")]

SECRET = "Der Waermebedarf betrug 100 GWh."   # a source passage, never a payload


def _turns(monkeypatch, said):
    """One stubbed turn per document; `said` is {document_id: answer or None}.

    The documents are asked in order, so the retrieval stub can record which
    one is running and the answer stub can reply for it.
    """
    where = {}
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.llm_client, "grounded_quote",
                        lambda q, it: q)

    def _retrieve(conn, index, pos, doc, types, vec, k, exclude=None):
        where["doc"] = doc
        return [_hit(0, text=SECRET, document_id=doc)] if said.get(doc) else []
    monkeypatch.setattr(answer.faiss_store, "retrieve", _retrieve)

    def _from_sources(task, items, **kw):
        answer_text = said.get(where["doc"])
        if not answer_text:
            return {"found": False, "complete": True}
        return {"found": True, "complete": True, "answer": answer_text,
                "supports": [{"index": 0, "quote": SECRET}]}
    monkeypatch.setattr(answer.llm_client, "answer_from_sources",
                        _from_sources)
    return where


def test_every_selected_document_gets_its_own_row_and_its_own_retrieval(
        monkeypatch, corpus):
    """A joint retrieval over five plans hands every top-k slot to the plan
    that wrote the longest chapter, and the others then look silent. So each
    document is asked on its own: one retrieval, one answer, one row."""
    asked = []
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("p", False))

    def _retrieve(conn, index, pos, doc, types, vec, k, exclude=None):
        asked.append(doc)
        return []
    monkeypatch.setattr(answer.faiss_store, "retrieve", _retrieve)

    out = compare.compare_documents("Sanierungsrate?", corpus, DOCS,
                                    [config.SCOPE_TEXT])
    assert asked == [1, 2, 3]
    assert [r["label"] for r in out["rows"]] == ["Kassel", "Leipzig", "Rottweil"]
    assert [r["document_id"] for r in out["rows"]] == [1, 2, 3]


def test_a_document_that_answered_nothing_keeps_its_row(monkeypatch, corpus):
    """An empty cell is a statement about that plan. Dropping the row would
    let the reader assume the plan was never asked."""
    _turns(monkeypatch, {1: "1 Prozent pro Jahr.", 2: "2 Prozent pro Jahr."})
    monkeypatch.setattr(compare.llm_client, "compare_answers",
                        lambda task, plans: "Kassel 1, Leipzig 2.")

    out = compare.compare_documents("Sanierungsrate?", corpus, DOCS,
                                    [config.SCOPE_TEXT])
    assert len(out["rows"]) == 3
    empty = out["rows"][2]
    assert empty["label"] == "Rottweil"
    assert empty["answer"] is None and empty["citations"] == []
    assert out["answered"] == 2
    assert out["comparison"] == "Kassel 1, Leipzig 2."


def test_the_comparison_call_never_sees_a_source_passage(monkeypatch, corpus):
    """The passages are per document; the comparison is not. Handed them, the
    model can ground a claim about one plan in another plan's sentence, and
    the citations under the table -- which are per plan -- would be silent
    about it."""
    _turns(monkeypatch, {1: "1 Prozent pro Jahr.", 2: "2 Prozent pro Jahr."})
    got = {}

    def _compare(task, plans):
        got["plans"] = plans
        return "V"
    monkeypatch.setattr(compare.llm_client, "compare_answers", _compare)

    out = compare.compare_documents("Sanierungsrate?", corpus, DOCS,
                                    [config.SCOPE_TEXT])
    payload = json.dumps(got["plans"], ensure_ascii=False)
    assert SECRET not in payload
    assert "quote" not in payload and "page_number" not in payload
    assert got["plans"] == [{"label": "Kassel", "answer": "1 Prozent pro Jahr."},
                            {"label": "Leipzig", "answer": "2 Prozent pro Jahr."},
                            {"label": "Rottweil", "answer": None}]
    # And the passage is still cited, per document, where it belongs.
    assert out["rows"][0]["citations"][0]["quote"] == SECRET


def test_one_answer_is_not_a_comparison(monkeypatch, corpus):
    """With a single grounded answer the call could only paraphrase it, and
    the table already shows it next to the plans that said nothing."""
    _turns(monkeypatch, {1: "1 Prozent pro Jahr."})

    def _never(task, plans):
        raise AssertionError("the comparison call must not run")
    monkeypatch.setattr(compare.llm_client, "compare_answers", _never)

    out = compare.compare_documents("Sanierungsrate?", corpus, DOCS,
                                    [config.SCOPE_TEXT])
    assert out["answered"] == 1 and out["comparison"] is None
    assert len(out["rows"]) == 3


def test_more_documents_than_the_budget_are_named_not_dropped_quietly(
        monkeypatch, corpus):
    """Every document costs a full retrieval and answer loop, so the cap is a
    latency budget. A silent cut would read as "that plan says nothing"."""
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.faiss_store, "retrieve",
                        lambda *a, **k: [])
    monkeypatch.setattr(compare.config, "COMPARE_MAX_DOCUMENTS", 2)

    out = compare.compare_documents("Frage?", corpus, DOCS, [config.SCOPE_TEXT])
    assert [r["label"] for r in out["rows"]] == ["Kassel", "Leipzig"]
    assert out["dropped"] == ["Rottweil"]


def test_a_follow_up_searches_past_what_that_document_showed(monkeypatch, corpus):
    """Per document, not per turn: a re-check skips the sources THIS plan
    already showed, and one shared list would exclude owner ids that belong to
    a different document entirely."""
    seen = {}
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("p", True))

    def _retrieve(conn, index, pos, doc, types, vec, k, exclude=None):
        seen[doc] = exclude
        return []
    monkeypatch.setattr(answer.faiss_store, "retrieve", _retrieve)

    histories = {1: [{"examined": [["table", 87457]], "recheck": False}],
                 2: [{"examined": [["section", 9]], "recheck": False}]}
    compare.compare_documents("Schau noch mal", corpus, DOCS,
                              [config.SCOPE_TEXT], histories=histories)
    assert seen[1] == {("table", 87457)}
    assert seen[2] == {("section", 9)}
    assert seen[3] == set()


def test_the_progress_stage_names_the_document_it_runs_for(monkeypatch, corpus):
    """Five plans in sequence: without the label the reader watches four
    identical "Retrieval" spinners and cannot tell how far it has got."""
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.faiss_store, "retrieve", lambda *a, **k: [])
    labels = []

    @contextmanager
    def _spy(label):
        labels.append(label)
        yield

    compare.compare_documents("Frage?", corpus, DOCS[:2], [config.SCOPE_TEXT],
                              progress=_spy)
    assert any(lab.startswith("Kassel · ") for lab in labels)
    assert any(lab.startswith("Leipzig · ") for lab in labels)
    assert not any(lab.startswith("Rottweil") for lab in labels)


def test_a_json_answer_is_compared_as_prose(monkeypatch, corpus):
    """`answer` is the same content shaped for a machine; the comparison
    reasons in prose, and a JSON blob per plan would be compared as text."""
    _turns(monkeypatch, {1: "1 Prozent.", 2: "2 Prozent."})
    monkeypatch.setattr(answer.llm_client, "format_as_json",
                        lambda task, text: '{"rate": "' + text + '"}')
    got = {}

    def _compare(task, plans):
        got["plans"] = plans
        return "V"
    monkeypatch.setattr(compare.llm_client, "compare_answers", _compare)

    out = compare.compare_documents("Sanierungsrate?", corpus, DOCS[:2],
                                    [config.SCOPE_TEXT], as_json=True)
    assert out["rows"][0]["answer"].startswith("{")
    assert got["plans"][0]["answer"] == "1 Prozent."
    assert out["as_json"] is True


def test_the_overview_cell_is_cut_where_the_reader_can_see_it():
    """The overview is read across five rows at a glance and the full answer
    stands underneath it. A silent cut would read as the end of a sentence,
    and an empty cell as a plan that was never asked."""
    long = "Die Sanierungsrate betraegt ein Prozent pro Jahr. " * 20
    cut = compare.summary({"answer_text": long})
    assert cut.endswith(" …") and len(cut) < len(long)
    assert cut.startswith("Die Sanierungsrate")
    assert compare.summary({"answer_text": "1 Prozent."}) == "1 Prozent."
    assert compare.summary({"answer": None, "answer_text": None}) == "—"
    # Newlines in the answer would break the row apart.
    assert compare.summary({"answer_text": "a" + chr(10) + "b"}) == "a b"
    # The prose answer, not the JSON shaping of it.
    assert compare.summary({"answer": '{"r": 1}', "answer_text": "1 Prozent."}) \
        == "1 Prozent."
