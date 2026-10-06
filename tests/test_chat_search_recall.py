"""Measuring the chat's search against a harvest.

What is promised, sentence by sentence:

  * for each accepted value the passage AND the page the harvest read it
    from are counted as among the first hits the chat reads, and as among
    all the hits it retrieves, each on its own;
  * the question is the spec's, put to the chat's own search path, with one
    search per question and not per value, and the search is the one
    `answer_question` runs;
  * the counts are split by how the trace says the harvest found the
    passage: by search, by structure, or not in the plan, and a document
    the trace says nothing of is counted apart;
  * a value whose passage is not in the database under its document is left
    out and counted, and is never a hit;
  * the script stops after the search: no passage is read and no answer is
    written.
"""
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe.inference import answer, hybrid, llm_client      # noqa: E402
from docpipe.profile import load_profile                       # noqa: E402
from scripts import chat_search_recall as csr                  # noqa: E402

FIRST = 10


@pytest.fixture(autouse=True)
def _leave_the_chats_configuration_unread():
    """The command reads the chat's configuration, which binds the profile in
    force when it is first imported. A test that imports it with the suite's
    profile must not hand that to a page test that expects none."""
    import docpipe.app
    was = "docpipe.app.config" in sys.modules
    yield
    if not was:
        sys.modules.pop("docpipe.app.config", None)
        if hasattr(docpipe.app, "config"):
            del docpipe.app.config


def _value(owner=1, kind="section", document_id=1, page=5,
           parameter="energy_consumption", document="doc_a"):
    return csr.Value(document, document_id, parameter, kind, owner, page)


def _hits(*owners, page=1, document_id=1):
    """Hits as the search hands them on: (kind, owner, document, page)."""
    return [("section", owner, document_id, page) for owner in owners]


def _count(values, search, *, plans=None, in_database=lambda v: True,
           whole_corpus=False):
    plans = plans or csr.Plans({}, {1, 2})
    return csr.measure(values, search, plans, in_database, FIRST,
                       whole_corpus=whole_corpus)


def _all(result) -> dict:
    total: dict = {}
    for count in result["counts"].values():
        for key, number in count.items():
            total[key] = total.get(key, 0) + number
    return total


# The count
def test_a_passage_is_counted_among_the_first_hits_and_among_all():
    search = lambda document, parameter: _hits(*range(100, 150))  # noqa: E731
    owners = {"first": 100, "tenth": 109, "eleventh": 110, "last": 149,
              "past the end": 150, "never": 7}
    result = _count([_value(owner=o) for o in owners.values()], search)
    first = {name: _all(_count([_value(owner=o)], search)).get(
        "passage first", 0) for name, o in owners.items()}
    hit = {name: _all(_count([_value(owner=o)], search)).get(
        "passage hits", 0) for name, o in owners.items()}
    # the tenth hit is read, the eleventh is only retrieved
    assert first == {"first": 1, "tenth": 1, "eleventh": 0, "last": 0,
                     "past the end": 0, "never": 0}
    assert hit == {"first": 1, "tenth": 1, "eleventh": 1, "last": 1,
                   "past the end": 0, "never": 0}
    assert _all(result)["values"] == 6


def test_a_passage_of_another_kind_with_the_same_id_is_not_the_passage():
    search = lambda document, parameter: _hits(1)         # noqa: E731
    assert _all(_count([_value(owner=1, kind="table")], search)).get(
        "passage hits", 0) == 0
    assert _all(_count([_value(owner=1, kind="section")], search)).get(
        "passage hits", 0) == 1


def test_the_page_is_counted_on_its_own_not_with_the_passage():
    # the right page on another passage
    other = lambda d, p: [("section", 99, 1, 5)]              # noqa: E731
    got = _all(_count([_value(owner=1, page=5)], other))
    assert got["page first"] == 1 and got["page hits"] == 1
    assert got.get("passage first", 0) == 0 and got.get("passage hits", 0) == 0
    # the right passage on another page
    moved = lambda d, p: [("section", 1, 1, 6)]               # noqa: E731
    got = _all(_count([_value(owner=1, page=5)], moved))
    assert got["passage first"] == 1 and got["passage hits"] == 1
    assert got.get("page first", 0) == 0 and got.get("page hits", 0) == 0
    # the right page in another document is not the page
    abroad = lambda d, p: [("section", 99, 2, 5)]             # noqa: E731
    got = _all(_count([_value(owner=1, page=5, document_id=1)], abroad))
    assert got.get("page hits", 0) == 0


def test_a_page_is_counted_among_the_first_hits_by_the_rank_of_its_hits():
    hits = _hits(*range(20), page=9)[:12]
    hits[0] = ("section", 0, 1, 3)
    hits[11] = ("section", 11, 1, 5)       # the only hit on page 5: the 12th
    search = lambda d, p: hits                                 # noqa: E731
    got = _all(_count([_value(owner=500, page=5)], search))
    assert got["page hits"] == 1 and got.get("page first", 0) == 0


def test_a_value_without_a_page_is_in_no_page_count():
    search = lambda d, p: _hits(1)                              # noqa: E731
    got = _all(_count([_value(owner=1, page=None)], search))
    assert got["values"] == 1 and got["passage hits"] == 1
    assert got.get("pages", 0) == 0 and got.get("page hits", 0) == 0


def test_a_search_that_finds_nothing_counts_the_value_as_missed():
    got = _all(_count([_value()], lambda d, p: []))
    assert got["values"] == 1
    assert got.get("passage hits", 0) == 0 and got.get("page hits", 0) == 0


# The split by how the harvest found the passage
def test_the_counts_are_split_by_what_the_trace_says():
    plans = csr.Plans(
        origins={(1, "section", 1): {"retrieval"},
                 (1, "section", 2): {"structure"},
                 (1, "section", 3): {"structure", "retrieval"}},
        traced={1})
    values = [_value(owner=1), _value(owner=2), _value(owner=3),
              _value(owner=4),                        # traced, never planned
              _value(owner=1, document_id=2)]         # no plan for document 2
    result = _count(values, lambda d, p: _hits(1, 2, 3, 4), plans=plans)
    counts = result["counts"]
    # planned by a search at least once: found by search
    assert counts[csr.SEARCH]["values"] == 2
    # planned by structure only: the trace says so
    assert counts[csr.STRUCTURE]["values"] == 1
    # in a document that has plans, and in none of them: the trace does not
    # say, and it is not structure for being absent
    assert counts[csr.UNPLANNED]["values"] == 1
    # a document the trace says nothing of
    assert counts[csr.UNKNOWN]["values"] == 1


def test_a_plan_of_one_document_does_not_speak_for_another():
    """The same kind and id stand in two documents' plans, since ids are
    counters per table and documents have their own harvests."""
    plans = csr.Plans(origins={(1, "section", 7): {"retrieval"}}, traced={1, 2})
    got = _count([_value(owner=7, document_id=2)], lambda d, p: _hits(7),
                 plans=plans)["counts"]
    assert got[csr.SEARCH]["values"] == 0
    assert got[csr.STRUCTURE]["values"] == 0
    assert got[csr.UNPLANNED]["values"] == 1


def test_the_plans_are_read_from_the_trace_beside_the_harvest(tmp_path):
    trace = tmp_path / "trace"
    trace.mkdir()
    events = [
        {"t": "plan", "doc": 1, "rank": 0, "origin": "retrieval",
         "kind": "section", "owner": 11},
        {"t": "plan", "doc": 1, "rank": None, "origin": "structure",
         "kind": "table", "owner": 12},
        {"t": "rows", "doc": 1, "text": 'a "plan" in a word'},
        {"t": "coord", "doc": 1, "kind": "section", "owner": 99}]
    (trace / "doc_a.trace.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events)
        + "\nnot json {\"plan\"\n[\"plan\"]\n\"plan\"\n",
        encoding="utf-8")
    plans = csr.read_plans(tmp_path, ["doc_a", "doc_b"])
    assert plans.traced == {1}                  # doc_b has no trace file
    assert plans.of(_value(owner=11)) == csr.SEARCH
    assert plans.of(_value(owner=12, kind="table")) == csr.STRUCTURE
    assert plans.of(_value(owner=99)) == csr.UNPLANNED   # a coord is no plan
    assert plans.of(_value(owner=11, document_id=5)) == csr.UNKNOWN


# One search per question
def test_one_search_is_made_per_document_and_parameter_not_per_value():
    asked = []

    def search(document, parameter):
        asked.append((document, parameter))
        return _hits(1)

    values = [_value(owner=1), _value(owner=2), _value(owner=3),
              _value(owner=1, parameter="other"),
              _value(owner=1, document_id=2)]
    search = _caching(search)
    _count(values, search)
    assert sorted(asked) == [(1, "energy_consumption"), (1, "other"),
                             (2, "energy_consumption")]


def _caching(search):
    seen = {}

    def cached(document, parameter):
        if (document, parameter) not in seen:
            seen[(document, parameter)] = search(document, parameter)
        return seen[(document, parameter)]
    return cached


def test_the_whole_corpus_is_searched_without_a_document():
    asked = []
    values = [_value(document_id=1), _value(document_id=2)]
    _count(values, lambda d, p: asked.append((d, p)) or _hits(1),
           whole_corpus=True)
    assert asked == [(None, "energy_consumption")] * 2
    asked.clear()
    _count(values, lambda d, p: asked.append((d, p)) or _hits(1))
    assert asked == [(1, "energy_consumption"), (2, "energy_consumption")]


# A database that is not the harvest's
def test_a_value_whose_passage_is_not_in_the_database_is_left_out_and_counted():
    values = [_value(owner=1), _value(owner=2), _value(owner=3)]
    present = {1}
    result = _count(values, lambda d, p: _hits(1, 2, 3),
                    in_database=lambda v: v.owner in present)
    # the two that are not there are neither hits nor misses
    assert _all(result)["values"] == 1
    assert _all(result)["passage hits"] == 1
    assert result["left"]["not in the database"] == 2


def test_in_database_asks_for_the_passage_under_its_document(tmp_path,
                                                             monkeypatch):
    """What `open_chat` hands over: a passage that moved to another document
    is not the harvest's passage."""
    from docpipe.inference import db
    stored = {"content": {"owner_kind": "section", "owner_id": 4,
                          "document_id": 2}}
    monkeypatch.setattr(db, "fetch_owner_content",
                        lambda conn, kind, owner: stored["content"])
    monkeypatch.setattr(db, "connect_readonly", lambda path: object())
    monkeypatch.setattr(db, "available_scopes", lambda conn: ["Body text"])
    from docpipe.inference import faiss_store, lexical
    monkeypatch.setattr(faiss_store, "load_global_index",
                        lambda path: (object(), {}))
    monkeypatch.setattr(lexical, "connect", lambda path: None)
    files = [tmp_path / "x.db", tmp_path / "x.index"]
    for path in files:
        path.write_bytes(b"")
    _corpus, scopes, in_database = csr.open_chat(*files)
    assert scopes == ["Body text"]
    assert in_database(_value(kind="section", owner=4, document_id=2))
    assert not in_database(_value(kind="section", owner=4, document_id=1))
    stored["content"] = None
    assert not in_database(_value(kind="section", owner=4, document_id=2))


def test_a_corpus_that_is_not_there_is_said(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        csr.open_chat(tmp_path / "no.db", tmp_path / "no.index")
    assert "no.db" in str(stopped.value)


# The harvest
def _tuple(owner=1, page=5, parameter="energy_consumption", **provenance):
    where = {"document_id": 1, "owner_kind": "section", "owner_id": owner,
             "page": page, **provenance}
    return {"kind": "tuple", "parameter": parameter, "quote": "q", "value": 1,
            "provenance": where}


def test_only_accepted_values_are_read_and_a_row_without_address_is_counted(
        tmp_path):
    rows = [
        _tuple(owner=1),
        {"kind": "refusal", "parameter": "x", "reason": "r", "claim": {},
         "owner": {}},
        {"kind": "summary", "document_id": 1, "tuples": 2},
        _tuple(owner=2, page=None),
        {"kind": "tuple", "parameter": "energy_consumption", "quote": "q"},
        {"kind": "tuple", "parameter": "energy_consumption",
         "provenance": {"document_id": 1, "owner_kind": "section"}},
    ]
    (tmp_path / "doc_a.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    values, left = csr.harvest_values(csr.collect(tmp_path))
    assert [(v.owner, v.page) for v in values] == [(1, 5), (2, None)]
    assert values[0].document == "doc_a" and values[0].document_id == 1
    assert dict(left) == {"no address": 2}


# The chat's search path
class _Recorded:
    """The model, the embedder and the hybrid search as stand-ins that say
    what they were asked."""

    def __init__(self, monkeypatch, *, phrase="a sentence", hits=None):
        self.phrases, self.embedded, self.retrieved = [], [], []
        self.hits = hits if hits is not None else [
            {"owner_kind": "section", "owner_id": 1, "document_id": 1,
             "page_number": 5, "text": "t"}]

        def make_search_phrase(task, visual=False, history=None):
            self.phrases.append((task, visual))
            return (phrase if phrase is not None else task), False

        def retrieve(*args, **kwargs):
            self.retrieved.append((args, kwargs))
            return [dict(hit) for hit in self.hits]

        monkeypatch.setattr(llm_client, "LLM_STUB_MODE", False)
        monkeypatch.setattr(llm_client, "make_search_phrase",
                            make_search_phrase)
        monkeypatch.setattr(hybrid, "retrieve", retrieve)
        # no tokenizer is fetched for a turn that reads nothing here
        monkeypatch.setattr(answer.chunker, "get_tokenizer",
                            lambda *a, **k: None)
        self.corpus = answer.Corpus(
            conn="conn", index="index", id_to_pos={"id": 1},
            embed=lambda item: (self.embedded.append(item) or [0.5, 0.5],
                                False),
            lexical="words")


SCOPES = ["Body text", "Tables (description only)"]


def test_the_question_goes_through_the_phrase_the_embedding_and_the_search(
        monkeypatch):
    seen = _Recorded(monkeypatch)
    search = csr.ChatSearch(seen.corpus, SCOPES,
                            {"energy_consumption": "Energieverbrauch"})

    got = search(7, "energy_consumption")

    assert seen.phrases == [("Energieverbrauch", False)]
    assert seen.embedded == [{"text": "a sentence"}]
    (args, kwargs), = seen.retrieved
    # the document, the types of the scopes, the vector, the hits asked for
    assert args[:3] == ("conn", "index", {"id": 1})
    assert args[3] == 7
    assert args[4] == ["section_text", "table_text"]
    assert args[5] == [0.5, 0.5] and args[6] == answer.config.TOP_K
    # the word index is asked with the question and the sentence
    assert kwargs["text"] == "Energieverbrauch a sentence"
    assert kwargs["lexical_index"] == "words"
    assert got == [("section", 1, 1, 5)]


def test_a_search_over_figures_and_tables_only_asks_for_the_visual_sentence(
        monkeypatch):
    seen = _Recorded(monkeypatch)
    csr.ChatSearch(seen.corpus, ["Tables (description only)"],
                   {"p": "Q"})(1, "p")
    assert seen.phrases == [("Q", True)]


def test_the_search_is_the_one_answer_question_runs(monkeypatch):
    """The drift pin: what the script hands the hybrid search is what the
    chat hands it, for the same question, sentence and vector."""
    seen = _Recorded(monkeypatch, hits=[])      # a turn that finds nothing
    csr.ChatSearch(seen.corpus, SCOPES, {"p": "Question?"})(7, "p")
    ours = seen.retrieved.pop()

    answer.answer_question("Question?", seen.corpus, 7, SCOPES)
    theirs = seen.retrieved.pop()

    assert ours == theirs


def test_the_pin_can_fail_when_the_two_searches_differ(monkeypatch):
    """Built to violate the promise: a search that words the word index
    with the question alone is another search than the chat's."""
    seen = _Recorded(monkeypatch, hits=[])
    csr.ChatSearch(seen.corpus, SCOPES, {"p": "Question?"})(7, "p")
    ours = seen.retrieved.pop()
    answer.answer_question("Another question?", seen.corpus, 7, SCOPES)
    assert ours != seen.retrieved.pop()


def test_a_query_that_is_an_image_is_not_asked_of_the_word_index(monkeypatch):
    """What `answer_question` always did and `search_hits` carries over: an
    image has no words, and a text query has the question and the sentence."""
    seen = _Recorded(monkeypatch, hits=[])
    answer.search_hits("Q", "a sentence", [0.5], seen.corpus, 7, SCOPES,
                       image_only=True)
    answer.search_hits("Q", "a sentence", [0.5], seen.corpus, 7, SCOPES)
    image, text = (kwargs["text"] for _args, kwargs in seen.retrieved)
    assert image is None and text == "Q a sentence"
    # the turn itself asks for it when its query is an image
    seen.retrieved.clear()
    answer.answer_question("Q", seen.corpus, 7, SCOPES, image_bytes=b"png",
                           image_only=True)
    assert seen.retrieved[0][1]["text"] is None


def test_over_the_whole_corpus_a_hit_says_whose_it_is(monkeypatch):
    seen = _Recorded(monkeypatch)
    seen.corpus.document_label = lambda document: f"plan {document}"
    (hit,) = answer.search_hits("Q", "s", [0.5], seen.corpus, None, SCOPES)
    assert hit["document_label"] == "plan 1"
    (hit,) = answer.search_hits("Q", "s", [0.5], seen.corpus, 1, SCOPES)
    assert "document_label" not in hit


def test_one_search_is_made_per_question_and_the_hits_are_kept_light(
        monkeypatch):
    seen = _Recorded(monkeypatch)
    search = csr.ChatSearch(seen.corpus, SCOPES, {"p": "Q", "o": "R"})
    first = search(1, "p")
    assert search(1, "p") is first
    search(2, "p")
    search(1, "o")
    assert len(search) == 3 and len(seen.retrieved) == 3
    # no passage text is held on to
    assert all(isinstance(hit, tuple) and len(hit) == 4
               for hits in search._seen.values() for hit in hits)


def test_a_sentence_that_is_the_question_itself_is_counted(monkeypatch):
    """The model's request failed and the chat searched with the question:
    a measurement of another search, said instead of passed."""
    seen = _Recorded(monkeypatch, phrase=None)
    search = csr.ChatSearch(seen.corpus, SCOPES, {"p": "Q ", "o": "R"})
    search(1, "p")
    search(1, "o")
    assert search.sentence_is_question == 2
    other = _Recorded(monkeypatch, phrase="a sentence")
    fine = csr.ChatSearch(other.corpus, SCOPES, {"p": "Q"})
    fine(1, "p")
    assert fine.sentence_is_question == 0


def test_the_script_stops_after_the_search(monkeypatch):
    """No passage is read, no answer is written: everything of the answer
    loop that comes after the search is made to fail if it is touched."""
    seen = _Recorded(monkeypatch)

    def touched(*args, **kwargs):
        raise AssertionError("the answer loop went on after the search")

    for name in ("answer_from_sources", "ask_chunk", "read_off_image",
                 "format_as_json", "grounded_quote", "visual_reading",
                 "choose", "compare_answers"):
        if hasattr(llm_client, name):
            monkeypatch.setattr(llm_client, name, touched)
    monkeypatch.setattr(answer.chunker, "pack_chunks", touched)
    monkeypatch.setattr(answer.chunker, "get_tokenizer", lambda *a, **k: None)
    search = csr.ChatSearch(seen.corpus, SCOPES, {"energy_consumption": "Q"})

    result = csr.measure([_value()], search, csr.Plans({}, {1}),
                         lambda v: True, FIRST)

    assert _all(result)["passage hits"] == 1
    # and the same stand-ins do stop `answer_question`, so the guard above
    # is one that would have fired
    with pytest.raises(AssertionError):
        answer.answer_question("Q", seen.corpus, 1, SCOPES)


# The report
def test_the_report_counts_what_it_counts_in_the_unit_it_counts():
    result = _count([_value(owner=1), _value(owner=2), _value(owner=3)],
                    lambda d, p: _hits(1, 2))
    text = csr.render(result, first=10, hits=50, searches=1,
                      sentence_is_question=0, whole_corpus=False, accepted=4,
                      unplaced={"no address": 1})
    assert "values: 4 accepted; 3 measured" in text
    assert "not measured, no address: 1 value(s)" in text
    assert "1 search(es), one per document and parameter" in text
    assert "the question itself (the model gave none): 0 of 1" in text
    assert "first 10 of the up to 50 hits" in text
    row = [line for line in text.splitlines() if line.startswith("all")][0]
    assert "2/3 (66.7%)" in row                  # passage in the first 10
    assert "found by structure" in text and "no plan in the trace" in text
    assert "not in the plan" in text


def test_a_bucket_without_values_says_nothing_instead_of_a_share():
    result = _count([], lambda d, p: [])
    text = csr.render(result, first=10, hits=50, searches=0,
                      sentence_is_question=0, whole_corpus=True, accepted=0,
                      unplaced={})
    row = [line for line in text.splitlines() if line.startswith("all")][0]
    assert "%" not in row, "a share of nothing is not a number"
    assert "one per parameter" in text


# The command
def _harvest(tmp_path, rows_by_document: dict, plans=None):
    folder = tmp_path / "harvest"
    folder.mkdir()
    for name, rows in rows_by_document.items():
        (folder / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    for name, events in (plans or {}).items():
        (folder / "trace").mkdir(exist_ok=True)
        (folder / "trace" / f"{name}.trace.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return folder


@pytest.fixture
def chat(monkeypatch):
    # the command binds the profile it is given into the environment; this
    # puts the suite's own back afterwards
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    seen = _Recorded(monkeypatch, hits=[
        {"owner_kind": "section", "owner_id": 1, "document_id": 1,
         "page_number": 5, "text": "t"}])
    monkeypatch.setattr(csr, "open_chat", lambda db, index: (
        seen.corpus, ["Body text"], lambda value: value.owner != 404))
    return seen


def test_the_command_reports_the_counts(tmp_path, chat, capsys):
    folder = _harvest(
        tmp_path,
        {"doc_a": [_tuple(owner=1), _tuple(owner=2), _tuple(owner=404),
                   _tuple(owner=1, parameter="gone_from_the_spec"),
                   {"kind": "tuple", "parameter": "energy_consumption"}]},
        plans={"doc_a": [{"t": "plan", "doc": 1, "rank": 0,
                          "origin": "retrieval", "kind": "section",
                          "owner": 1}]})

    code = csr.main([str(folder), "--profile", "kwp"])

    out = capsys.readouterr().out
    assert code == 0
    # the spec's own label is the question
    from docpipe.extraction.spec import load as load_spec
    spec = load_spec(load_profile("kwp").component("extraction", "SPEC_PATH"))
    label = next(p.label for p in spec.parameters
                 if p.uri == "energy_consumption")
    assert chat.phrases == [(label, False)]
    assert "values: 5 accepted; 2 measured" in out
    assert "not measured, no address: 1 value(s)" in out
    assert "not measured, not in the database: 1 value(s)" in out
    assert "not measured, parameter not in the spec: 1 value(s)" in out
    # owner 1 was planned by a search and is the first hit; owner 2 is not a
    # hit and no plan lists it: not a finding by structure, and said so
    by_search = next(line for line in out.splitlines()
                     if line.startswith("found by search"))
    unplanned = next(line for line in out.splitlines()
                     if line.startswith("not in the plan"))
    by_structure = next(line for line in out.splitlines()
                        if line.startswith("found by structure"))
    assert "1/1 (100.0%)" in by_search
    assert "0/1 (0.0%)" in unplanned
    assert "%" not in by_structure, "no passage was listed by structure"


def test_the_command_stops_on_a_harvest_without_an_accepted_value(
        tmp_path, chat, capsys):
    folder = _harvest(tmp_path, {"doc_a": [
        {"kind": "refusal", "parameter": "x", "reason": "r", "claim": {},
         "owner": {}}]})
    assert csr.main([str(folder), "--profile", "kwp"]) == 1
    assert "no accepted value" in capsys.readouterr().err
    assert chat.phrases == [], "nothing was asked"


def test_the_command_stops_on_a_folder_that_is_not_there(tmp_path, chat,
                                                         capsys):
    assert csr.main([str(tmp_path / "nowhere"), "--profile", "kwp"]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_the_command_takes_the_first_documents_only_when_asked(
        tmp_path, chat, capsys):
    folder = _harvest(tmp_path, {"a": [_tuple()], "b": [_tuple()],
                                 "c": [_tuple()]})
    assert csr.main([str(folder), "--profile", "kwp", "--documents", "2"]) == 0
    assert "values: 2 accepted; 2 measured" in capsys.readouterr().out


def test_the_command_needs_a_profile_for_the_spec(tmp_path, chat, monkeypatch):
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    folder = _harvest(tmp_path, {"a": [_tuple()]})
    with pytest.raises(SystemExit) as stopped:
        csr.main([str(folder)])
    assert "no profile" in str(stopped.value)


def test_the_command_says_a_profile_without_a_spec_has_no_question(
        tmp_path, chat, capsys):
    folder = _harvest(tmp_path, {"a": [_tuple()]})
    assert csr.main([str(folder), "--profile", "default"]) == 1
    assert "no extraction spec" in capsys.readouterr().err
