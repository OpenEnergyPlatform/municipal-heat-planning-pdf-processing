"""answer_question against a stubbed corpus — the turn without any UI."""
import pytest

from docpipe.inference import answer, config


class _Hit(dict):
    pass


def _hit(idx, kind="section", owner=1, text="Der Wärmebedarf betrug 100 GWh."):
    return {"owner_kind": kind, "owner_id": owner, "content": text, "title": "T",
            "document_id": 1, "page_number": 1, "image_path": None}


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

    from contextlib import contextmanager

    @contextmanager
    def _spy(label):
        labels.append(label)
        yield

    answer.answer_question("Frage?", corpus, 1, [config.SCOPE_TEXT])          # no progress
    answer.answer_question("Frage?", corpus, 1, [config.SCOPE_TEXT], progress=_spy)
    assert labels                                                        # got reported
