"""The chat answers in statements, each with its own quote.

What is promised, sentence by sentence (each AND is a test of its own):

  * the chat shows a statement only if its quote stands in the passage it
    cites, whole, and is at least 12 characters (the real check, never
    stood in for here);
  * AND it says how many of the statements the model made it dropped;
  * AND it keeps what was read off an image marked as read off, and the
    sentence of the focused re-read is the statement;
  * AND it shows a statement about a calculated value only with a code run
    of this turn that ran OK and a quote of its inputs;
  * AND earlier batches' checked statements are carried forward exactly as
    checked: the model is told them, never asked to write them again;
  * AND what reaches a follow-up, a comparison and the JSON step is the text
    of the statements that stood the check, and nothing that was dropped.

Reading a reply (no repair, the cause named) is in test_chat_reply.py.
"""
import random

import pytest

from docpipe.inference import answer, compare, config, llm_client, statements

PASSAGE = ("Der Wärmebedarf betrug im Jahr 2020 insgesamt 100 GWh. "
           "Der Anteil der Fernwärme lag bei 30 Prozent. "
           "Die Stadtwerke Musterstadt GmbH betreiben drei Heizwerke.")
Q1 = "Der Wärmebedarf betrug im Jahr 2020 insgesamt 100 GWh."
Q2_FABRICATED = "Der Anteil der Wärmepumpen lag bei 55 Prozent."
Q3 = "Die Stadtwerke Musterstadt GmbH betreiben drei Heizwerke."


def _hit(owner=1, text=PASSAGE, kind="section", document_id=1, **more):
    return {"owner_kind": kind, "owner_id": owner, "content": text,
            "text": text, "title": "T", "document_id": document_id,
            "page_number": 1, "image_path": None, **more}


def _items(hits):
    return {i: {"index": i, "source": f"s{i}", "text": "T\n" + h["text"]}
            for i, h in enumerate(hits)}


def _text(statement, quote, index=0):
    return {"statement": statement, "basis": "text", "index": index,
            "quote": quote}


def _back(wrote, hits=None, **more):
    hits = hits or [_hit()]
    defaults = dict(items=_items(hits), hits=hits, attached=set(),
                    delivered={}, runs=[], run_offset=0)
    defaults.update(more)
    return statements.back(wrote, **defaults)


def _said(*wrote, complete=True, **more):
    """What `answer_from_sources` returns for one batch."""
    return {"statements": list(wrote), "complete": complete, "compute": [],
            "attached_images": [], "requested": [], "fault": None, **more}


@pytest.fixture
def corpus():
    return answer.Corpus(conn=None, index=None, id_to_pos={},
                         embed=lambda item: ([0.0] * 4, False),
                         resolve_image=lambda path: None)


@pytest.fixture
def turn(monkeypatch, corpus):
    """A turn over the given hits whose answer calls reply as told: a list
    with one reply per batch. The real checks run; the replies are the only
    thing stood in for. Returns what each call was asked."""
    asked = []

    def run(hits, replies, as_json=False, batches=None, **more):
        monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                            lambda *a, **k: ("p", False))
        monkeypatch.setattr(answer.hybrid.faiss_store, "retrieve",
                            lambda *a, **k: hits)
        monkeypatch.setattr(answer.chunker, "get_tokenizer", lambda *a: None)
        if batches:
            monkeypatch.setattr(answer.config, "ANSWER_CONTEXT_TOKENS", 1)
        queue = list(replies)

        def from_sources(task, items, **kw):
            asked.append({"items": items, **kw})
            return queue.pop(0)

        monkeypatch.setattr(answer.llm_client, "answer_from_sources",
                            from_sources)
        return answer.answer_question("Frage?", corpus, 1,
                                      [config.SCOPE_TEXT], as_json=as_json,
                                      **more)

    run.asked = asked
    return run


# ---------------------------------------------------------------------------
# AND 1: shown only if the quote stands in the passage it cites
# ---------------------------------------------------------------------------

def test_one_fabricated_quote_removes_exactly_its_statement(turn):
    """Three statements, the second quotes a sentence the passage does not
    hold. The whole answer used to stay (the prose was kept and only the
    support was skipped); now exactly the statement goes."""
    assert Q2_FABRICATED not in PASSAGE
    out = turn([_hit()], [_said(
        _text("Der Bedarf war 100 GWh.", Q1),
        _text("Wärmepumpen decken 55 Prozent.", Q2_FABRICATED),
        _text("Es gibt drei Heizwerke.", Q3))])
    assert out["answer"] == ("- Der Bedarf war 100 GWh. [1]\n"
                             "- Es gibt drei Heizwerke. [2]")
    assert "55" not in out["answer"] and "Wärmepumpen" not in out["answer"]
    assert out["answer_text"] == ("Der Bedarf war 100 GWh.\n"
                                  "Es gibt drei Heizwerke.")
    assert (out["statements_made"], out["statements_shown"],
            out["statements_dropped"]) == (3, 2, 1)
    assert [c["quote"] for c in out["citations"]] == [Q1, Q3]
    assert [s["text"] for s in out["statements"]] == [
        "Der Bedarf war 100 GWh.", "Es gibt drei Heizwerke."]
    assert all("hit" not in s for s in out["statements"])


def test_the_check_is_the_real_one_and_a_stand_in_would_pass_what_it_stops():
    """The instrument: a check that passes everything shows the fabricated
    statement. Only the real `grounded_quote` stops it."""
    wrote = [_text("Wärmepumpen decken 55 Prozent.", Q2_FABRICATED)]
    shown, dropped = _back(wrote)
    assert shown == [] and [d["why"] for d in dropped] == ["quote"]
    shown, dropped = _back(wrote, grounded=lambda quote, item: quote)
    assert len(shown) == 1 and dropped == []


def test_a_quote_that_stands_in_another_shown_passage_does_not_back_this_statement():
    """The quote has to stand in ITS source: a real sentence of excerpt 1
    cited as the support of excerpt 0 backs nothing."""
    other = "Die Sanierungsrate liegt in diesem Quartier bei einem Prozent."
    hits = [_hit(owner=1), _hit(owner=2, text=other)]
    shown, dropped = _back([_text("Rate ein Prozent.", other, index=0)], hits)
    assert shown == [] and dropped[0]["why"] == "quote"
    shown, dropped = _back([_text("Rate ein Prozent.", other, index=1)], hits)
    assert len(shown) == 1 and shown[0]["owner_id"] == 2
    # an index of no excerpt of this batch, one that is no integer (a word,
    # a float, a digit written as text), one that is a truth value, and one
    # that is missing: all without a source
    batch = {1: _items(hits)[1]}
    for index in (0, 7, -1, "x", 1.0, "1", True, None):
        shown, dropped = _back([_text("Rate.", other, index=index)], hits,
                               items=batch)
        assert shown == [] and dropped[0]["why"] == "no_source", index
    wrote = {"statement": "Rate.", "basis": "text", "quote": other}
    assert _back([wrote], hits)[1][0]["why"] == "no_source"


def test_a_short_real_substring_is_no_quote():
    """A quote has to be a place: 11 characters of the passage are not,
    12 are; case and whitespace do not matter."""
    short, just = "tadtwerke M", "Stadtwerke M"
    assert len(short) == 11 and len(just) == 12
    for quote, shown_ones in (("GmbH", 0), (short, 0), (just, 1),
                              ("STADTWERKE   MUSTERSTADT", 1),
                              ("„Stadtwerke Musterstadt GmbH“", 1)):
        shown, dropped = _back([_text("Die Stadtwerke.", quote)])
        assert len(shown) == shown_ones, quote
        assert len(dropped) == 1 - shown_ones, quote
        if not shown_ones:
            assert dropped[0]["why"] == "quote"


def test_every_drop_reason_is_reached_and_every_statement_is_one_or_the_other():
    """One constructed statement per reason; a reason that can no longer be
    produced fails this. Then random mixes: nothing is lost between what is
    shown and what is dropped."""
    attached = {1}
    hits = [_hit(owner=1), _hit(owner=2)]
    runs = [{"code": "print(1)", "output": {"ok": True, "stdout": "1"}}]
    pool = {
        "shown_text": _text("Bedarf.", Q1, index=0),
        "blank": {"statement": "  ", "basis": "text", "index": 0, "quote": Q1},
        "unknown_basis": {"statement": "x", "basis": "memory", "index": 0},
        "not_a_statement": "Bedarf 100 GWh",
        "no_source": _text("Bedarf.", Q1, index=9),
        "quote": _text("Bedarf.", Q2_FABRICATED, index=0),
        "image": {"statement": "Etwa 650 GWh.", "basis": "image",
                  "index": 0, "reading": "Erdgas 2035: ca. 650 GWh/a"},
        "shown_image": {"statement": "Etwa 650 GWh (abgelesen).",
                        "basis": "image", "index": 1,
                        "reading": "Erdgas 2035: ca. 650 GWh/a"},
        "run": {"statement": "Summe 5.", "basis": "computed", "index": 0,
                "quote": Q1, "run": 4},
        "shown_computed": {"statement": "Summe 1.", "basis": "computed",
                           "index": 0, "quote": Q1, "run": 1},
    }
    reached = set()
    for name, one in pool.items():
        shown, dropped = _back([one], hits, attached=attached, runs=runs)
        assert len(shown) + len(dropped) == 1, name
        assert bool(shown) == name.startswith("shown"), name
        reached.update(d["why"] for d in dropped)
    assert reached == set(statements.WHY)
    rng = random.Random(7)
    for _ in range(200):
        mix = [rng.choice(list(pool.values()))
               for _ in range(rng.randint(0, 9))]
        shown, dropped = _back(mix, hits, attached=attached, runs=runs)
        assert len(shown) + len(dropped) == len(mix)


def test_a_dropped_statement_keeps_what_the_model_wrote_and_says_why():
    wrote = _text("Wärmepumpen decken 55 Prozent.", Q2_FABRICATED)
    _shown, dropped = _back([wrote])
    assert dropped == [{**wrote, "why": "quote"}]
    assert wrote.get("why") is None                 # the input was not touched


def test_a_statement_is_one_line():
    shown, _ = _back([_text("Der Bedarf\nwar   100 GWh.\n", Q1)])
    assert shown[0]["text"] == "Der Bedarf war 100 GWh."


# ---------------------------------------------------------------------------
# AND 2: how many were dropped is carried, counted in statements
# ---------------------------------------------------------------------------

def test_what_is_counted_is_statements_and_every_batch_adds_to_it(turn):
    out = turn([_hit(1), _hit(2)], [
        _said(_text("Bedarf.", Q1), _text("Falsch.", Q2_FABRICATED),
              complete=False),
        _said(_text("Heizwerke.", Q3, index=1), _text("Auch falsch.",
                                                      "nirgends zu finden"),
              complete=True)], batches=2)
    assert out["n_batches"] == 2
    assert (out["statements_made"], out["statements_shown"],
            out["statements_dropped"]) == (4, 2, 2)
    assert out["n_findings"] == 2           # citations: another unit


def test_a_batch_whose_reply_could_not_be_read_was_not_examined(turn):
    """A re-check searches past the sources a turn examined. Sources whose
    reply stayed unreadable were not looked at: skipping them would leave
    them unread for good, after the page said they could not be read. A batch
    that was read, whatever became of its statements, was examined."""
    unread = _said(complete=False, fault="syntax")
    out = turn([_hit(1), _hit(2)], [
        unread, _said(_text("Heizwerke.", Q3, index=1))], batches=2)
    assert out["n_batches"] == 2
    assert out["examined"] == [("section", 2)]
    # the instrument: the same batches, both read (one with nothing backed)
    out = turn([_hit(1), _hit(2)], [
        _said(_text("Falsch.", Q2_FABRICATED), complete=False),
        _said(_text("Heizwerke.", Q3, index=1))], batches=2)
    assert out["examined"] == [("section", 1), ("section", 2)]
    # a turn whose only batch could not be read examined nothing
    out = turn([_hit(1)], [unread])
    assert out["examined"] == []


def test_a_turn_where_every_statement_was_dropped_has_no_answer_and_says_so(
        turn):
    out = turn([_hit()], [_said(_text("Falsch.", Q2_FABRICATED),
                                _text("Auch falsch.", "nirgends zu finden"))])
    assert out["answer"] is None and out["answer_text"] is None
    assert out["citations"] == [] and out["faults"] == []
    assert (out["statements_made"], out["statements_dropped"]) == (2, 2)


# ---------------------------------------------------------------------------
# AND 3: what was read off an image stays marked as read off
# ---------------------------------------------------------------------------

def test_a_read_off_is_backed_only_by_a_crop_that_was_attached():
    bar = _hit(owner=5, kind="figure", image_path="b.png")
    hits = [_hit(owner=1), bar]
    reading = "Erdgas-Balken 2035: ca. 650 GWh/a"
    shown, dropped = _back(
        [{"statement": "Etwa 650 GWh (abgelesen).", "basis": "image",
          "index": 1, "reading": reading}], hits, attached={1})
    (one,) = shown
    assert one["visual"] is True and one["quote"] == reading
    assert (one["owner_kind"], one["owner_id"]) == ("figure", 5)
    for bad, why in (
            ({"index": 0}, "image"),                 # a crop never attached
            ({"reading": "650"}, "image"),           # says nothing of it
            ({"index": 9}, "no_source"),
            ({"block": "p3_img1"}, "image")):        # asked for, not here
        wrote = {"statement": "Etwa 650 GWh.", "basis": "image", "index": 1,
                 "reading": reading, **bad}
        shown, dropped = _back([wrote], hits, attached={1})
        assert shown == [] and dropped[0]["why"] == why, bad


def test_a_crop_the_model_asked_for_backs_a_statement_by_its_block():
    asked = _hit(owner=8, kind="figure", image_path="c.png")
    reading = "Segment 2035: ca. 7 GWh/a"
    wrote = {"statement": "Etwa 7 GWh.", "basis": "image",
             "block": "[p17_img1]", "reading": reading}
    delivered = {"p17_img1": {"block_id": "p17_img1", "hit": asked}}
    shown, _ = _back([wrote], delivered=delivered)
    assert shown[0]["owner_id"] == 8 and shown[0]["visual"]
    assert shown[0]["block"] == "p17_img1" and shown[0]["index"] is None
    # asked for but not delivered (not in the map): no statement stands on it
    shown, dropped = _back([wrote], delivered={})
    assert shown == [] and dropped[0]["why"] == "image"


def test_a_crop_the_model_asked_for_is_cited_only_by_a_statement_that_stands_on_it(
        monkeypatch, turn):
    """The request is no citation by itself any more: a crop nobody cites is
    not shown as evidence (it stays among the sources that were examined). A
    statement names it by its block, with or without the brackets the model
    saw it in, and the passage is fetched for it."""
    fetched = []

    def fetch(conn, kind, owner):
        fetched.append((kind, owner))
        return {"owner_kind": kind, "owner_id": owner, "title": "Abb. 2-3",
                "text": "Ein Balkendiagramm.", "document_id": 1,
                "page_number": 17, "image_path": "c.png"}

    monkeypatch.setattr(answer.db, "fetch_owner_content", fetch)
    asked = {"block_id": "[p17_img1]", "title": "Abb. 2-3", "delivered": True,
             "owner_kind": "figure", "owner_id": 8}
    unused = {"block_id": "p22_tbl0", "title": "Tabelle 4", "delivered": True,
              "owner_kind": "table", "owner_id": 9}
    missing = {"block_id": "p99_img9", "title": None, "delivered": False,
               "owner_kind": None, "owner_id": None}
    reading = "Segment 2035: ca. 7 GWh/a"
    wrote = [{"statement": "Etwa 7 GWh (abgelesen).", "basis": "image",
              "block": "p17_img1", "reading": reading},
             {"statement": "Etwa 8 GWh (abgelesen).", "basis": "image",
              "block": "p99_img9", "reading": "Segment 2036: ca. 8 GWh/a"}]
    out = turn([_hit()], [_said(*wrote, requested=[asked, unused, missing])])
    assert fetched == [("figure", 8)]       # only what a statement names
    assert out["answer"] == "Etwa 7 GWh (abgelesen). [1]"
    assert [c["owner_id"] for c in out["citations"]] == [8]
    assert out["citations"][0]["visual"] is True
    assert out["citations"][0]["quote"] == reading
    assert (out["statements_made"], out["statements_dropped"]) == (2, 1)
    assert ("table", 9) in out["examined"] and ("figure", 8) in out["examined"]
    assert out["requested"] == ["[p17_img1]", "p22_tbl0"]
    # a passage that cannot be read back backs nothing
    monkeypatch.setattr(answer.db, "fetch_owner_content",
                        lambda conn, kind, owner: None)
    out = turn([_hit()], [_said(wrote[0], requested=[asked])])
    assert out["answer"] is None and out["statements_dropped"] == 1


def test_a_crop_that_was_asked_for_and_never_arrived_backs_no_statement(
        monkeypatch, turn):
    """The crop's file could not be read, so the model never saw it: the
    request has its owner (the passage is known) and `delivered` is False. A
    reading of a picture that was not in front of the model backs nothing,
    and the request is not among the crops the turn reports as received."""
    fetched = []

    def fetch(conn, kind, owner):
        fetched.append((kind, owner))
        return {"owner_kind": kind, "owner_id": owner, "title": "Abb. 2-3",
                "text": "Ein Balkendiagramm.", "document_id": 1,
                "page_number": 17, "image_path": "c.png"}

    monkeypatch.setattr(answer.db, "fetch_owner_content", fetch)
    lost = {"block_id": "p17_img1", "title": "Abb. 2-3", "delivered": False,
            "owner_kind": "figure", "owner_id": 8}
    wrote = {"statement": "Etwa 7 GWh (abgelesen).", "basis": "image",
             "block": "p17_img1", "reading": "Segment 2035: ca. 7 GWh/a"}
    out = turn([_hit()], [_said(wrote, requested=[lost])])
    assert out["answer"] is None and out["citations"] == []
    assert (out["statements_made"], out["statements_dropped"]) == (1, 1)
    assert fetched == [] and out["requested"] == []
    assert ("figure", 8) not in out["examined"]
    # the instrument: the same crop delivered backs the same statement
    out = turn([_hit()], [_said(wrote, requested=[{**lost, "delivered": True}])])
    assert out["answer"] == "Etwa 7 GWh (abgelesen). [1]"
    assert fetched == [("figure", 8)]


def test_a_statement_whose_basis_is_none_of_the_three_is_dropped_with_a_real_quote():
    """Text, image and computed are the bases there are. A statement of any
    other basis is not backed by a quote that stands, however well it stands:
    which of the checks it would be held to is not known."""
    for basis in ("memory", "Text", "", None, 1, ["text"], {}):
        wrote = {"statement": "Der Bedarf war 100 GWh.", "basis": basis,
                 "index": 0, "quote": Q1}
        shown, dropped = _back([wrote])
        assert shown == [], basis
        assert [d["why"] for d in dropped] == ["blank"], basis
    wrote = {"statement": "Der Bedarf war 100 GWh.", "index": 0, "quote": Q1}
    assert _back([wrote])[0] == []                   # no basis at all
    # the instrument: the same statement with its basis is shown
    assert len(_back([{**wrote, "basis": "text"}])[0]) == 1


def test_a_crop_is_named_by_its_block_id_with_or_without_the_brackets_it_was_seen_in():
    assert llm_client.crop_id("p17_img1") == "p17_img1"
    assert llm_client.crop_id("[p17_img1]") == "p17_img1"
    assert llm_client.crop_id("  [ p17_img1 ] ") == "p17_img1"
    for nothing in (None, "", "  ", "[]"):
        assert llm_client.crop_id(nothing) == ""
    assert llm_client.crop_id(7) == "7"
    # the crops the statements of a reply name: the passages to look up
    wrote = [{"basis": "image", "block": "[p17_img1]"},
             {"basis": "image", "block": "p22_tbl0"},
             {"basis": "image", "block": ""}, {"basis": "text"},
             "not a statement", None]
    assert statements.blocks_named(wrote) == {"p17_img1", "p22_tbl0"}
    assert statements.blocks_named([]) == set()
    assert statements.blocks_named(None) == set()


def test_citations_are_numbered_in_order_and_one_per_source_quote_and_run():
    def shown(owner, quote, run=None, visual=False):
        return {"owner_kind": "section", "owner_id": owner, "quote": quote,
                "run": run, "visual": visual, "computed": run is not None,
                "hit": {"owner_kind": "section", "owner_id": owner,
                        "page_number": owner}}

    rows = [shown(1, "Der Wärmebedarf betrug 100 GWh."),
            shown(2, "Die Stadtwerke Musterstadt GmbH betreiben Netze."),
            shown(1, "DER  Wärmebedarf betrug 100 GWh."),     # the same place
            shown(1, "Der Anteil der Fernwärme lag bei 30 Prozent."),
            shown(1, "Der Wärmebedarf betrug 100 GWh.", run=1),
            shown(1, "Der Wärmebedarf betrug 100 GWh.", run=2)]
    cited = statements.citations_of(rows)
    assert [c["n"] for c in cited] == [1, 2, 3, 4, 5]
    assert [r["citation"] for r in rows] == [1, 2, 1, 3, 4, 5]
    assert [c["run"] for c in cited] == [None, None, None, 1, 2]
    assert [c["computed"] for c in cited] == [False] * 3 + [True] * 2
    assert cited[0]["quote"] == "Der Wärmebedarf betrug 100 GWh."
    assert cited[0]["page_number"] == 1         # the passage's own fields
    assert statements.citations_of([]) == []


def test_the_readoff_note_is_added_once_when_a_visual_statement_lacks_the_marker():
    def visual(text):
        return {"text": text, "visual": True, "citation": 1}

    plain = {"text": "Der Bedarf war 100 GWh.", "visual": False,
             "citation": 2}
    marker, note = "abgelesen", "(Hinweis: Schätzwerte.)"
    # two statements without the marker: one note, under both forms
    answer_, text = statements.assemble(
        [visual("Etwa 600 GWh."), visual("Etwa 40 GWh."), plain],
        marker, note)
    assert answer_.count(note) == 1 and text.count(note) == 1
    assert answer_.endswith("\n\n" + note) and text.endswith("\n\n" + note)
    # the marker in each: none
    answer_, text = statements.assemble(
        [visual("Etwa 600 GWh (aus der Abbildung abgelesen)."),
         visual("40 GWh, abgelesen."), plain], marker, note)
    assert note not in answer_ and note not in text
    # the marker in the first only: the second still lacks it
    answer_, _ = statements.assemble(
        [visual("Etwa 600 GWh, abgelesen."), visual("Etwa 40 GWh.")],
        marker, note)
    assert answer_.count(note) == 1
    # a text-only answer never gets it
    answer_, text = statements.assemble([plain], marker, note)
    assert note not in answer_ and note not in text
    # case does not matter
    assert note not in statements.assemble(
        [visual("Etwa 600 GWh, ABGELESEN.")], marker, note)[0]


def test_the_focused_reread_is_the_statement_and_the_citation(
        monkeypatch, turn, corpus):
    """The model's first wording is not shown: the sentence of the focused
    call replaces it, in the answer, in the citation and in the history
    text. Where that call gives nothing, the first reading stays and the
    turn's record has the fault."""
    bar = _hit(owner=5, kind="figure", text="Balkendiagramm Erdgas.",
               image_path="b.png")
    first = "Erdgas-Balken 2035: ca. 650 GWh/a"
    wrote = {"statement": "Etwa 650 GWh im Jahr 2035.", "basis": "image",
             "index": 0, "reading": first}
    reply = _said(wrote, attached_images=[0])
    corpus.resolve_image = lambda path: "b.png"
    read = {}

    def read_off(task, image, hint):
        read["hint"] = hint
        return {"reading": "Erdgas 2035: ca. 600 GWh/a (abgelesen)"}

    monkeypatch.setattr(answer.llm_client, "read_off_image", read_off)
    out = turn([bar], [reply])
    assert read["hint"] == first
    assert out["answer"] == "Erdgas 2035: ca. 600 GWh/a (abgelesen) [1]"
    assert out["answer_text"] == "Erdgas 2035: ca. 600 GWh/a (abgelesen)"
    assert out["citations"][0]["quote"] == "Erdgas 2035: ca. 600 GWh/a (abgelesen)"
    assert out["citations"][0]["visual"] is True
    assert "650" not in out["answer"]

    # the focused call gives nothing: the first reading and the first words
    monkeypatch.setattr(answer.llm_client, "read_off_image",
                        lambda task, image, hint: None)
    out = turn([bar], [_said(wrote, attached_images=[0])])
    assert out["citations"][0]["quote"] == first
    assert out["answer"].startswith("Etwa 650 GWh im Jahr 2035. [1]")
    # and it is marked as read off even though the model forgot to
    note = answer.wording.readoff()[1]
    assert out["answer"].endswith("\n\n" + note)


def test_a_focused_reread_that_comes_back_blank_leaves_a_fault(
        monkeypatch, turn, corpus):
    bar = _hit(owner=5, kind="figure", text="Balkendiagramm Erdgas.",
               image_path="b.png")
    wrote = {"statement": "Etwa 650 GWh (abgelesen).", "basis": "image",
             "index": 0, "reading": "Erdgas-Balken 2035: ca. 650 GWh/a"}
    corpus.resolve_image = lambda path: "b.png"
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm_client, "_image_part",
                        lambda path, max_side=None, png=False: {
                            "type": "image_url", "image_url": {"url": "d"}})
    monkeypatch.setattr(llm_client, "_chat_json",
                        lambda messages, temperature: {"reading": ""})
    monkeypatch.setattr(answer.llm_client, "read_off_image",
                        llm_client.read_off_image)
    out = turn([bar], [_said(wrote, attached_images=[0])])
    assert out["answer"] is not None
    assert out["faults"] == [{"request": "readoff_reply",
                              "cause": "wrong_shape"}]


# ---------------------------------------------------------------------------
# AND 4: a statement about a calculated value
# ---------------------------------------------------------------------------

def test_a_computed_statement_needs_a_run_that_ran_and_a_quote_of_its_inputs():
    runs = [{"code": "print(42)", "output": {"ok": True, "stdout": "42"}},
            {"code": "boom", "output": {"ok": False, "error": "NameError"}}]

    def computed(**more):
        return {"statement": "Es sind 42.", "basis": "computed", "index": 0,
                "quote": Q1, "run": 1, **more}

    shown, _ = _back([computed()], runs=runs, run_offset=3)
    (one,) = shown
    assert one["computed"] is True and one["quote"] == Q1
    assert one["run"] == 4                  # 3 runs before this call, plus 1
    for bad, why in (({"run": 5}, "run"),           # no such run
                     ({"run": 0}, "run"),           # runs count from 1
                     ({"run": -1}, "run"),
                     ({"run": 2}, "run"),           # it ran into an error
                     ({"run": None}, "run"),
                     ({"run": "1.5"}, "run"),
                     ({"quote": Q2_FABRICATED}, "quote"),   # inputs not quoted
                     ({"quote": "42"}, "quote"),            # no place
                     ({"index": 3}, "no_source")):
        shown, dropped = _back([computed(**bad)], runs=runs)
        assert shown == [] and dropped[0]["why"] == why, bad
    # no code ran at all in this call
    shown, dropped = _back([computed()], runs=[])
    assert shown == [] and dropped[0]["why"] == "run"
    # a run without an output is no run that ran
    shown, dropped = _back([computed()], runs=[{"code": "x"}])
    assert shown == [] and dropped[0]["why"] == "run"


def test_a_computed_statement_is_shown_under_the_run_of_the_turn(turn):
    """The second batch runs code once more: its statement names run 1 of its
    own call, and is shown under run 3 of the turn."""
    ok = {"ok": True, "stdout": "1"}
    first = _said(_text("Bedarf.", Q1), complete=False, compute=[
        {"code": "a", "output": ok}, {"code": "b", "output": ok}])
    second = _said(
        {"statement": "Summe 42.", "basis": "computed", "index": 1,
         "quote": Q3, "run": 1},
        compute=[{"code": "c", "output": ok}])
    out = turn([_hit(1), _hit(2)], [first, second], batches=2)
    assert len(out["compute"]) == 3
    (citation,) = [c for c in out["citations"] if c["computed"]]
    assert citation["run"] == 3 and citation["quote"] == Q3
    assert out["statements"][1]["run"] == 3
    # two statements on one quote but two runs are two pieces of evidence
    rows = [{"statement": f"Summe {n}.", "basis": "computed", "index": 0,
             "quote": Q1, "run": n} for n in (1, 2)]
    out = turn([_hit()], [_said(*rows, compute=[
        {"code": "a", "output": ok}, {"code": "b", "output": ok}])])
    assert [c["run"] for c in out["citations"]] == [1, 2]


def test_the_runs_the_model_is_shown_are_numbered_so_a_statement_can_name_one():
    """A statement names its `run`, so each run in the tail has a number in
    the order it ran; without the numbers there is nothing to name."""
    ok = {"ok": True, "stdout": "42"}
    bad = {"ok": False, "error": "NameError"}
    heading = llm_client._w()["code_heading"]
    tail = llm_client._compute_tail(
        [{"code": "print(41)", "output": ok}, {"code": "boom", "output": bad},
         {"code": "print(43)", "output": ok}], force=False)
    first, second, third = (tail.index(f"{heading} {n}:") for n in (1, 2, 3))
    assert first < tail.index("print(41)") < second < tail.index("boom") \
        < third < tail.index("print(43)")
    assert f"{heading} 4:" not in tail
    # the numbers restart with every call: it is one call's runs that are named
    again = llm_client._compute_tail([{"code": "print(1)", "output": ok}],
                                     force=True)
    assert f"{heading} 1:\nprint(1)" in again and f"{heading} 2:" not in again
    assert llm_client._compute_tail([], force=True) == ""


def test_the_second_half_of_a_cut_batch_is_shifted_past_the_runs_of_the_first():
    first = {"statements": [{"statement": "a", "basis": "computed",
                             "run": 1}], "complete": True,
             "compute": [{"code": "x"}, {"code": "y"}],
             "attached_images": [0], "requested": [], "fault": None}
    second = {"statements": [{"statement": "b", "basis": "computed",
                              "run": 1}, "not a dict",
                             {"statement": "c", "basis": "text"}],
              "complete": False, "compute": [{"code": "z"}],
              "attached_images": [2, 0], "requested": [{"block_id": "p"}],
              "fault": "cut_off"}
    joined = llm_client._joined(first, second)
    assert [s.get("run") for s in joined["statements"]
            if isinstance(s, dict)] == [1, 3, None]
    assert joined["statements"][2] == "not a dict"
    assert joined["complete"] is False and joined["fault"] == "cut_off"
    assert len(joined["compute"]) == 3
    assert joined["attached_images"] == [0, 2]
    assert first["statements"][0]["run"] == 1 and second["statements"][0][
        "run"] == 1                              # nothing was changed in place


# ---------------------------------------------------------------------------
# AND 5: earlier batches' statements are carried forward as checked
# ---------------------------------------------------------------------------

def test_a_later_batch_gets_only_the_checked_statements_as_prior(turn):
    out = turn([_hit(1), _hit(2)], [
        _said(_text("Bedarf war 100 GWh.", Q1),
              _text("Falsch erfunden.", Q2_FABRICATED), complete=False),
        _said(_text("Und wieder erfunden.", "nirgends zu finden", index=1),
              complete=True)], batches=2)
    first, second = turn.asked
    assert first["prior"] is None
    assert second["prior"] == ["Bedarf war 100 GWh."]    # not the dropped one
    assert "Falsch erfunden." not in str(second["prior"])
    # a fabricated statement of the second batch leaves the answer as the
    # first batch's: it can neither add itself nor take anything away
    assert out["answer"] == "Bedarf war 100 GWh. [1]"
    assert out["n_batches"] == 2
    assert (out["statements_made"], out["statements_dropped"]) == (3, 2)


def test_the_answer_is_the_first_batchs_statements_then_the_second_batchs(
        turn):
    out = turn([_hit(1), _hit(2)], [
        _said(_text("Bedarf war 100 GWh.", Q1), complete=False),
        _said(_text("Es gibt drei Heizwerke.", Q3, index=1),
              _text("Der Bedarf war 100 GWh, neu gesagt.", Q1, index=1))],
        batches=2)
    assert turn.asked[1]["prior"] == ["Bedarf war 100 GWh."]
    assert [s["text"] for s in out["statements"]][:1] == [
        "Bedarf war 100 GWh."]                       # as it was checked
    assert out["answer_text"].splitlines()[0] == "Bedarf war 100 GWh."
    assert out["answer_text"].splitlines()[1] == "Es gibt drei Heizwerke."
    # append-only: the second batch cannot take the first one's back, and a
    # repeat of it is one more statement and not a rewrite of the old one
    assert len(out["statements"]) == 3


def test_complete_with_nothing_shown_yet_does_not_stop_the_scan(turn):
    """A model that says "complete" about statements that all failed has
    answered nothing: the next batch is still read."""
    out = turn([_hit(1), _hit(2)], [
        _said(_text("Erfunden.", Q2_FABRICATED), complete=True),
        _said(_text("Heizwerke.", Q3, index=1), complete=True)], batches=2)
    assert out["n_batches"] == 2 and len(turn.asked) == 2
    assert out["answer"] == "Heizwerke. [1]"
    # and with something shown, complete stops it
    turn.asked.clear()
    out = turn([_hit(1), _hit(2)], [
        _said(_text("Bedarf.", Q1), complete=True)], batches=2)
    assert out["n_batches"] == 1 and len(turn.asked) == 1


def test_a_citation_is_one_per_source_and_quote_and_each_statement_names_it(
        turn):
    out = turn([_hit()], [_said(
        _text("Bedarf.", Q1), _text("Bedarf, anders gesagt.", Q1),
        _text("Heizwerke.", Q3))])
    assert [c["n"] for c in out["citations"]] == [1, 2]
    assert [c["quote"] for c in out["citations"]] == [Q1, Q3]
    assert [s["citation"] for s in out["statements"]] == [1, 1, 2]
    assert out["answer"] == "- Bedarf. [1]\n- Bedarf, anders gesagt. [1]\n" \
                            "- Heizwerke. [2]"


# ---------------------------------------------------------------------------
# What reaches the history, the comparison and the JSON step
# ---------------------------------------------------------------------------

def test_json_answer_is_shaped_from_checked_text_only(turn, monkeypatch):
    seen = {}

    def shape(task, text):
        seen["text"] = text
        return '{"bedarf": "100 GWh"}'

    monkeypatch.setattr(answer.llm_client, "format_as_json", shape)
    out = turn([_hit()], [_said(
        _text("Der Bedarf war 100 GWh.", Q1),
        _text("Kryptonit deckt alles.", Q2_FABRICATED))], as_json=True)
    assert seen["text"] == "Der Bedarf war 100 GWh."
    assert "Kryptonit" not in seen["text"] and "Kryptonit" not in str(out)
    assert out["answer"] == '{"bedarf": "100 GWh"}' and out["as_json"] is True
    # the JSON has no marks, so the citations carry no number
    assert out["citations"] and all("n" not in c for c in out["citations"])


def test_where_the_json_cannot_be_made_the_prose_stays_and_says_why(
        turn, monkeypatch):
    monkeypatch.setattr(answer.llm_client, "format_as_json",
                        lambda task, text: None)
    out = turn([_hit()], [_said(_text("Der Bedarf war 100 GWh.", Q1))],
               as_json=True)
    assert out["answer"] == "Der Bedarf war 100 GWh. [1]"
    assert out["as_json"] is False
    assert out["citations"][0]["n"] == 1

    def unreadable(task, text):
        raise llm_client.ReplyError("syntax", "json_reply", 4)

    monkeypatch.setattr(answer.llm_client, "format_as_json", unreadable)
    out = turn([_hit()], [_said(_text("Der Bedarf war 100 GWh.", Q1))],
               as_json=True)
    assert out["answer"] == "Der Bedarf war 100 GWh. [1]"
    assert out["as_json"] is False


def test_a_provider_that_takes_schemas_only_is_not_asked_for_the_users_json(
        monkeypatch):
    """Where the shape cannot be asked for, there is no JSON, and that is
    recorded: it used to be a warning in a log and a JSON that was only the
    answer wrapped in a key."""
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_client, "_chat_json", lambda *a, **k: (_ for _ in (
    )).throw(AssertionError("the model must not be asked")))
    with llm_client.collecting() as faults:
        assert llm_client.format_as_json("Format?", "Der Bedarf.") is None
    assert faults == [{"request": "json_format", "cause": "not_asked"}]
    with pytest.raises(ValueError):
        llm_client.note_fault("json_format", "no such cause")


def test_compare_sees_only_checked_answers(monkeypatch, corpus):
    where = {}
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.chunker, "get_tokenizer", lambda *a: None)

    def retrieve(conn, index, pos, doc, types, vec, k, exclude=None):
        where["doc"] = doc
        return [_hit(document_id=doc)]
    monkeypatch.setattr(answer.hybrid.faiss_store, "retrieve", retrieve)
    texts = {1: [_text("Kassel: 1 Prozent.", Q1),
                 _text("Kassel: Kryptonit.", Q2_FABRICATED)],
             2: [_text("Leipzig: 2 Prozent.", Q1)]}
    monkeypatch.setattr(answer.llm_client, "answer_from_sources",
                        lambda task, items, **kw: _said(*texts[where["doc"]]))
    got = {}

    def compared(task, plans):
        got["plans"] = plans
        return "Vergleich."

    monkeypatch.setattr(compare.llm_client, "compare_answers", compared)
    out = compare.compare_documents(
        "Rate?", corpus, [(1, "Kassel"), (2, "Leipzig")], [config.SCOPE_TEXT])
    assert got["plans"] == [{"label": "Kassel", "answer": "Kassel: 1 Prozent."},
                            {"label": "Leipzig",
                             "answer": "Leipzig: 2 Prozent."}]
    assert "Kryptonit" not in str(got["plans"])
    rows = {r["label"]: r for r in out["rows"]}
    assert (rows["Kassel"]["statements_made"],
            rows["Kassel"]["statements_dropped"]) == (2, 1)
    assert rows["Leipzig"]["statements_dropped"] == 0
    assert out["faults"] == []
    # one answered document is still no comparison
    texts[2] = [_text("Leipzig: erfunden.", Q2_FABRICATED)]
    got.clear()
    out = compare.compare_documents(
        "Rate?", corpus, [(1, "Kassel"), (2, "Leipzig")], [config.SCOPE_TEXT])
    assert out["answered"] == 1 and out["comparison"] is None
    assert got == {}
    assert out["rows"][1]["statements_dropped"] == 1


def test_a_failed_comparison_leaves_a_fault_of_its_own(monkeypatch, corpus):
    monkeypatch.setattr(answer.llm_client, "make_search_phrase",
                        lambda *a, **k: ("p", False))
    monkeypatch.setattr(answer.chunker, "get_tokenizer", lambda *a: None)
    monkeypatch.setattr(answer.hybrid.faiss_store, "retrieve",
                        lambda *a, **k: [_hit()])
    monkeypatch.setattr(answer.llm_client, "answer_from_sources",
                        lambda task, items, **kw: _said(_text("Rate.", Q1)))
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    monkeypatch.setattr(llm_client, "_chat_json",
                        lambda messages, temperature: {"comparison": " "})
    out = compare.compare_documents(
        "Rate?", corpus, [(1, "Kassel"), (2, "Leipzig")], [config.SCOPE_TEXT])
    assert out["answered"] == 2 and out["comparison"] is None
    assert out["faults"] == [{"request": "comparison_reply",
                              "cause": "wrong_shape"}]
    assert all(r["faults"] == [] for r in out["rows"])


def test_stub_mode_answers_with_a_backed_statement(monkeypatch, corpus):
    """The stub's statement is checked like any other: its quote is the first
    120 characters of the first excerpt, which stand in it."""
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", True)
    monkeypatch.setattr(answer.hybrid.faiss_store, "retrieve",
                        lambda *a, **k: [_hit()])
    monkeypatch.setattr(answer.chunker, "get_tokenizer", lambda *a: None)
    out = answer.answer_question("Frage?", corpus, 1, [config.SCOPE_TEXT])
    assert out["answer"] and out["n_findings"] == 1
    assert (out["statements_made"], out["statements_dropped"]) == (1, 0)
    items = [{"index": 0, "source": "s", "text": "T\n" + PASSAGE}]
    (stub,) = llm_client.answer_from_sources("x", items)["statements"]
    assert llm_client.grounded_quote(stub["quote"], items[0]) is not None
    assert llm_client.answer_from_sources("x", [])["statements"] == []


# ---------------------------------------------------------------------------
# A reply cut off at its token limit: the batch is halved, a unit gets room
# ---------------------------------------------------------------------------

def _excerpts(count):
    return [{"index": i, "source": f"s{i}",
             "text": f"Der Auszug Nummer {i} steht hier ganz allein."}
            for i in range(count)]


def _count_excerpts(messages):
    import json
    text = messages[0]["content"]
    return len(json.loads(text[text.rindex("\n\n") + 2:])["excerpt"])


def _wrote_for(messages):
    import json
    text = messages[0]["content"]
    items = json.loads(text[text.rindex("\n\n") + 2:])["excerpt"]
    return {"statements": [
        {"statement": f"Nr. {it['index']}.", "basis": "text",
         "index": it["index"], "quote": it["text"]} for it in items],
        "complete": True}


def test_a_cut_off_batch_is_halved_and_what_the_halves_say_is_joined(
        monkeypatch):
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    sizes = []

    def chat(messages, temperature):
        sizes.append(_count_excerpts(messages))
        if sizes[-1] > 2:
            raise llm_client.ReplyError("cut_off", "answer_reply", 1)
        return _wrote_for(messages)

    monkeypatch.setattr(llm_client, "_chat_json", chat)
    out = llm_client.answer_from_sources("Frage?", _excerpts(4))
    assert sizes == [4, 2, 2]
    assert [s["index"] for s in out["statements"]] == [0, 1, 2, 3]
    assert out["fault"] is None and out["complete"] is True


def test_a_single_excerpt_gets_more_room_once_and_then_is_a_hole(monkeypatch):
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    rooms = []
    monkeypatch.setattr(llm_client, "LLM_MAX_TOKENS", 100)

    def chat(messages, temperature):
        rooms.append(llm_client._ROOM.get() or llm_client.LLM_MAX_TOKENS)
        raise llm_client.ReplyError("cut_off", "answer_reply", 1)

    monkeypatch.setattr(llm_client, "_chat_json", chat)
    out = llm_client.answer_from_sources("Frage?", _excerpts(1))
    assert rooms == [100, 200]
    assert out["statements"] == [] and out["fault"] == "cut_off"
    # more room is no more than once, and it does not outlive the request
    assert llm_client._ROOM.get() is None


def test_a_cut_batch_stops_halving_where_the_depth_ends(monkeypatch):
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
    sizes = []

    def chat(messages, temperature):
        sizes.append(_count_excerpts(messages))
        raise llm_client.ReplyError("cut_off", "answer_reply", 1)

    monkeypatch.setattr(llm_client, "_chat_json", chat)
    out = llm_client.answer_from_sources("Frage?", _excerpts(16))
    # 16 -> 8+8 -> 4 each -> 2 each, and there it stops: three halvings.
    # What is left is asked with more room once, and then it is a hole.
    assert max(sizes) == 16 and min(sizes) == 2
    assert sizes.count(2) == 16             # eight pieces, each asked twice
    assert out["statements"] == [] and out["fault"] == "cut_off"
    assert len(sizes) < 60


def test_a_half_that_stays_cut_is_a_hole_and_the_other_half_still_counts(
        monkeypatch):
    monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)

    def chat(messages, temperature):
        text = messages[0]["content"]
        if _count_excerpts(messages) > 1 and '"index": 3' in text:
            raise llm_client.ReplyError("cut_off", "answer_reply", 1)
        if '"index": 3' in text:
            raise llm_client.ReplyError("cut_off", "answer_reply", 1)
        return _wrote_for(messages)

    monkeypatch.setattr(llm_client, "_chat_json", chat)
    out = llm_client.answer_from_sources("Frage?", _excerpts(4))
    assert [s["index"] for s in out["statements"]] == [0, 1, 2]
    assert out["fault"] == "cut_off" and out["complete"] is False


# ---------------------------------------------------------------------------
# The prompts and the schema name the same keys
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_prompts_and_schema_name_the_same_keys(name):
    from docpipe import prompts
    from docpipe.inference import replies
    from docpipe.profile import load_profile
    profile = load_profile(name)

    def load(prompt_id):
        return prompts.load(prompt_id, profile).text

    text = load("inference/answer_head") + load("inference/answer_tail")
    statement = replies.answer()[1]["properties"]["statements"]["items"]
    for key in ("statements", "complete", *statement["properties"]):
        if key in ("block", "run"):
            continue                       # named where the action is offered
        assert f'"{key}"' in text, (name, key)
    for basis in replies.BASES:
        if basis == "computed":
            assert '"computed"' in load("inference/compute_hint"), name
        else:
            assert f'"{basis}"' in text, (name, basis)
    assert '"run"' in load("inference/compute_hint")
    assert '"block"' in load("inference/image_hint")
    # the old envelope is gone from every word the model reads
    for key in ('"found"', '"supports"', '"answer"'):
        assert key not in text, (name, key)
    # the format of the task is scoped to the statements, never the envelope
    assert ("Formatvorgaben" if name == "kwp" else "Format requirements") \
        in text
    if name == "kwp":
        assert "aus der Abbildung abgelesen" in text and "Schätzwert" in text
    else:
        assert "read off from the figure" in text
    # the two ends join: the head ends where a paragraph ends, the tail starts
    assert load("inference/answer_head").endswith("\n\n")
    assert not load("inference/answer_tail").startswith("\n")


@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_no_profile_keeps_a_prompt_of_the_old_envelope(name):
    """Removed means removed: the files are gone from every profile, and
    nothing loads them."""
    from docpipe import prompts
    from docpipe.profile import load_profile
    profile = load_profile(name)
    for gone in ("answer_spec_text", "answer_spec_json", "envelope_correction",
                 "readoff_correction", "revise"):
        assert not prompts.path_for(f"inference/{gone}", profile).is_file(), \
            (name, gone)
    assert set(llm_client._PROMPTS.values()) == set(llm_client.PROMPT_IDS)
    assert not {"inference/answer_spec_text", "inference/revise",
                "inference/envelope_correction",
                "inference/readoff_correction"} & set(llm_client.PROMPT_IDS)
