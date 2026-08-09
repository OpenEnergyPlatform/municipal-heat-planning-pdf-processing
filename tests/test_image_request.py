"""The model asking for a picture the text only points at.

A section reads "wie Abbildung 2-3 verdeutlicht" and then carries a bare
[p17_img1] — a token that tells the reader nothing and the model less. Two
things follow: the placeholder is named with its caption, and the model may ask
for the crop itself when it believes the answer sits in it.
"""
import sqlite3

import pytest

from docpipe.inference import db


# ---------------------------------------------------------------------------
# The placeholder carries its caption
# ---------------------------------------------------------------------------

CAPTIONS = {"p17_img1": "Abbildung 2-3: Altersstruktur 1987 und 2023",
            "p22_tbl0": "Tabelle 4: Wärmebedarf nach Sektoren"}


def test_a_placeholder_is_named_but_keeps_its_id():
    """The id stays: it is the handle the model quotes to request the crop."""
    out = db.annotate_placeholders("Wie [p17_img1] zeigt, altert die Stadt.", CAPTIONS)

    assert out == ("Wie [p17_img1: Abbildung 2-3: Altersstruktur 1987 und 2023] "
                   "zeigt, altert die Stadt.")


def test_several_placeholders_in_one_paragraph():
    out = db.annotate_placeholders("[p17_img1] und [p22_tbl0]", CAPTIONS)

    assert "Altersstruktur" in out and "Wärmebedarf nach Sektoren" in out


def test_an_unknown_id_is_left_alone():
    """A figure whose caption the pipeline never produced must not be dressed up
    as if it had one."""
    assert db.annotate_placeholders("siehe [p99_img0]", CAPTIONS) == "siehe [p99_img0]"


def test_empty_content_is_not_an_error():
    assert db.annotate_placeholders("", CAPTIONS) == ""
    assert db.annotate_placeholders(None, CAPTIONS) == ""


# ---------------------------------------------------------------------------
# Resolving a requested id against the corpus
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT, folder TEXT);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER, title TEXT,
                               content TEXT, page_number INTEGER, section_number TEXT,
                               parent INTEGER);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,
                             path TEXT, page_number INTEGER, caption TEXT,
                             description TEXT, bbox TEXT);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,
                             path TEXT, page_number INTEGER, caption TEXT,
                             markdown TEXT, bbox TEXT);
        INSERT INTO Documents VALUES (1, 'wolfratshausen.pdf', 'wolfratshausen');
        INSERT INTO Documents VALUES (2, 'jena.pdf', 'jena');
        INSERT INTO Sections VALUES (10, 1, 'Bevölkerung', 'Wie [p17_img1] zeigt.', 17, '2.1', NULL);
        INSERT INTO Sections VALUES (20, 2, 'Bevölkerung', 'Auch hier [p17_img1].', 17, '2.1', NULL);
        INSERT INTO Images VALUES (100, 10, 'p17_img1', 'images/p17_img1.png', 17,
                                   'Abbildung 2-3: Altersstruktur', 'Ein Balkendiagramm.', NULL);
        INSERT INTO Images VALUES (200, 20, 'p17_img1', 'images/p17_img1.png', 17,
                                   'Abbildung 5: Etwas anderes', 'Eine Karte.', NULL);
        INSERT INTO Tables VALUES (300, 10, 'p22_tbl0', 'images/p22_tbl0.png', 22,
                                   'Tabelle 4', '| a | b |', NULL);
    """)
    return c


def test_the_same_id_in_another_document_is_not_returned(conn):
    """p17_img1 exists in nearly every plan — an unscoped lookup would answer
    from a different municipality's figure."""
    item = db.request_item(conn, 1, "p17_img1")

    assert item["owner_id"] == 100
    assert item["title"] == "Abbildung 2-3: Altersstruktur"
    assert db.request_item(conn, 2, "p17_img1")["owner_id"] == 200


def test_a_table_is_found_too(conn):
    item = db.request_item(conn, 1, "p22_tbl0")

    assert (item["owner_kind"], item["text"]) == ("table", "| a | b |")


def test_brackets_around_the_id_are_tolerated(conn):
    """The model quotes what it saw, and what it saw was [p17_img1]."""
    assert db.request_item(conn, 1, "[p17_img1]")["owner_id"] == 100


def test_an_unknown_id_is_none_not_an_exception(conn):
    assert db.request_item(conn, 1, "p99_img9") is None
    assert db.request_item(conn, 1, "") is None


def test_the_section_text_arrives_with_captions_filled_in(conn):
    got = db.fetch_owner_content(conn, "section", 10)

    assert got["text"] == "Wie [p17_img1: Abbildung 2-3: Altersstruktur] zeigt."


# ---------------------------------------------------------------------------
# The action in the answer loop
# ---------------------------------------------------------------------------

def _final(**kw):
    return {"found": True, "complete": True, "answer": "19.499 Einwohner",
            "supports": [{"index": 0, "quote": "x"}], **kw}


def test_the_model_can_ask_for_a_crop_and_gets_it(monkeypatch, tmp_path):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    png = tmp_path / "p17_img1.png"
    png.write_bytes(b"\x89PNG\r\n")
    calls = {"n": 0}
    seen_parts = []

    def fake_chat_json(messages, temperature):
        calls["n"] += 1
        seen_parts.append(messages)
        if calls["n"] == 1:
            return {"action": "image", "id": "p17_img1"}
        return _final()

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)
    monkeypatch.setattr(llm, "_image_part", lambda p, **kw: {"type": "image_url", "url": p})
    asked = []

    def requester(block_id):
        asked.append(block_id)
        return {"owner_kind": "figure", "owner_id": 100, "title": "Abbildung 2-3",
                "image_path": str(png), "text": "Ein Balkendiagramm."}

    out = llm.answer_from_sources("Wie viele Einwohner?",
                                  [{"index": 0, "source": "s", "text": "[p17_img1: Abbildung 2-3]"}],
                                  image_requester=requester, max_image_requests=2)

    assert asked == ["p17_img1"]
    assert calls["n"] == 2, "one request round, then the answer"
    assert out["answer"] == "19.499 Einwohner"
    assert out["requested"] == [{"block_id": "p17_img1", "title": "Abbildung 2-3",
                                 "delivered": True, "owner_kind": "figure", "owner_id": 100}]


def test_a_translated_action_name_is_still_understood(monkeypatch):
    """The hint is English, the prompt around it is German, and models translate
    the value they are told to echo. Refusing "image" would drop the request and
    look like the model ignoring the format."""
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    calls = {"n": 0}

    def fake_chat_json(messages, temperature):
        calls["n"] += 1
        return {"action": "image", "id": "p17_img1"} if calls["n"] == 1 else _final()

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)

    out = llm.answer_from_sources("?", [{"index": 0, "source": "s", "text": "t"}],
                                  image_requester=lambda b: None, max_image_requests=2)

    assert out["requested"] and out["requested"][0]["block_id"] == "p17_img1"


def test_an_unavailable_crop_still_lets_the_model_answer(monkeypatch):
    """The picture is missing from disk; leaving the model waiting for it would
    cost the turn."""
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    calls = {"n": 0}

    def fake_chat_json(messages, temperature):
        calls["n"] += 1
        return {"action": "image", "id": "p17_img1"} if calls["n"] == 1 else _final()

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)

    out = llm.answer_from_sources("?", [{"index": 0, "source": "s", "text": "t"}],
                                  image_requester=lambda b: None, max_image_requests=2)

    assert out["requested"][0]["delivered"] is False
    assert out["found"] is True


def test_asking_twice_for_the_same_crop_stops_the_loop(monkeypatch):
    """It did not help the first time; a second copy of the same picture only
    burns the budget the model needs to answer with. The loop drops out, and the
    existing envelope correction then insists on a real answer."""
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm, "_image_part", lambda p, **kw: {"type": "image_url", "url": p})
    calls = {"n": 0}
    asked = []

    def fake_chat_json(messages, temperature):
        calls["n"] += 1
        return {"action": "image", "id": "p17_img1"} if calls["n"] < 3 else _final()

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)

    def requester(block_id):
        asked.append(block_id)
        return {"owner_kind": "figure", "owner_id": 1, "title": "A", "image_path": "x.png"}

    out = llm.answer_from_sources("?", [{"index": 0, "source": "s", "text": "t"}],
                                  image_requester=requester, max_image_requests=3)

    assert asked == ["p17_img1"], "the repeat request is never resolved a second time"
    assert calls["n"] == 3, "asked, asked again, then forced to answer"
    assert out["answer"] == "19.499 Einwohner"
    assert len(out["requested"]) == 1


def test_the_action_is_not_offered_when_it_is_switched_off(monkeypatch):
    llm = pytest.importorskip("docpipe.inference.llm_client")
    monkeypatch.setattr(llm, "LLM_STUB_MODE", False)
    seen = []

    def fake_chat_json(messages, temperature):
        seen.append(messages[0]["content"])
        return _final()

    monkeypatch.setattr(llm, "_chat_json", fake_chat_json)

    llm.answer_from_sources("?", [{"index": 0, "source": "s", "text": "t"}],
                            image_requester=None, max_image_requests=0)

    assert '"action": "image"' not in seen[0]
