"""
The rules the runner applies (docpipe/extraction/runner.py): each switched,
for the run or at the step that reads it, changes what the runner does AND
the standard gives today's result (owner, 2026-11-11: "alles soll anpassbar
sein"). A rule with `decided` has the owner's decision as its standard.

Three rules are applied inside `main` only (`documents_in_flight`,
`dead_server_ends_run`, `preflight_on`): no function of the runner takes
them, so they have no test here (see the report of this branch).
"""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import runner, throttle
from docpipe.profile import load_profile

from test_compute_step import (ANSWER, CODE, amount, computing, printed,
                               run_step, share)
from conftest import step_node

DEFAULT = rules.default()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for env in rules.ENVS:
        monkeypatch.delenv(env, raising=False)
    rules.reset()
    monkeypatch.setattr(runner, "retry_wait", lambda *a, **k: 0.0)
    monkeypatch.setattr(runner, "UNSERVED", runner.Unserved())
    yield
    rules.reset()


def at_step(box, **values):
    return rules.in_step(rules.stepped(step_node(box), values))


# -- the temperature and the waits of an asked-again request ------------------

def test_the_temperature_rises_by_the_step_up_to_the_most():
    assert runner.retry_temperature(0.0, 3) == pytest.approx(0.3)   # standard
    assert runner.retry_temperature(0.0, 30) == 1.0
    with rules.overlaid(retry_temperature_step=0.25):
        assert runner.retry_temperature(0.0, 2) == pytest.approx(0.5)
    with at_step("find", retry_temperature_step=0.0):
        assert runner.retry_temperature(0.2, 5) == pytest.approx(0.2)
    with at_step("find", retry_temperature_most=0.4):
        assert runner.retry_temperature(0.0, 30) == pytest.approx(0.4)
    assert runner.retry_temperature(0.0, 30) == 1.0


@pytest.fixture
def real_waits(monkeypatch):
    monkeypatch.undo()           # the fixture above made every wait 0
    rules.reset()


def test_the_waits_of_an_answer_that_could_not_be_read_follow_the_rules(
        monkeypatch, real_waits):
    monkeypatch.setattr(runner.providers, "replaying", lambda: False)
    with rules.overlaid(retry_wait_growth="linear"):
        assert runner.retry_wait(1) == 2                            # standard
        assert runner.retry_wait(2) == 4
        assert runner.retry_wait(9) == 6                            # the most
    with rules.overlaid(retry_wait_growth="linear", retry_wait_s=5):
        assert runner.retry_wait(2) == 6                 # 10, held at 6
    with rules.overlaid(retry_wait_growth="linear", retry_wait_most_s=100,
                        retry_wait_s=5):
        assert runner.retry_wait(2) == 10
    with at_step("find", retry_wait_growth="linear", retry_wait_s=0):
        assert runner.retry_wait(3) == 0


def test_the_waits_for_a_server_that_cannot_be_reached_follow_the_rules(
        monkeypatch, real_waits):
    monkeypatch.setattr(runner.providers, "replaying", lambda: False)
    assert runner.retry_wait(1, transport=True) == 15               # standard
    assert runner.retry_wait(2, transport=True) == 30
    assert runner.retry_wait(9, transport=True) == 120              # the most
    with rules.overlaid(transport_wait_s=1):
        assert runner.retry_wait(3, transport=True) == 4
    with at_step("find", transport_wait_most_s=20):
        assert runner.retry_wait(9, transport=True) == 20
    # the two curves are apart: a rule of one is no rule of the other
    with rules.overlaid(transport_wait_s=1, transport_wait_most_s=1):
        assert runner.retry_wait(9) == 6


# -- the calculation ----------------------------------------------------------

def test_code_rounds_are_the_runs_of_code_a_calculation_may_use(monkeypatch):
    assert DEFAULT["code_rounds"] == 2                # decided 2026-11-03
    assert runner.code_rounds() == 2
    with rules.overlaid(code_rounds=5):
        assert runner.code_rounds() == 5
    with at_step("compute", code_rounds=1):
        assert runner.code_rounds() == 1

    def code_runs(**values):
        step, asked, runs, _events = computing(monkeypatch, *[CODE] * 12)
        with rules.overlaid(**values):
            try:
                run_step(step, share(21), amount(185200))
            except StopIteration:
                pass
        return len(runs)
    assert code_runs() == 2
    assert code_runs(code_rounds=1) == 1
    assert code_runs(code_rounds=3) == 3


def test_compute_extra_attempts_are_the_requests_beyond_the_code_and_replies(
        monkeypatch):
    assert DEFAULT["compute_extra_attempts"] == 1     # decided 2026-11-03

    def asked_when(**values):
        step, asked, _runs, _events = computing(monkeypatch, *[CODE] * 40)
        with rules.overlaid(**values):
            run_step(step, share(21), amount(185200))
        return len(asked)
    tries = runner.reply_limit() + runner.code_rounds()
    assert asked_when() == tries + 1
    assert asked_when(compute_extra_attempts=0) == tries
    assert asked_when(compute_extra_attempts=4) == tries + 4


def test_code_output_chars_are_what_the_model_is_shown_of_the_output(
        monkeypatch):
    assert DEFAULT["code_output_chars"] == 2000
    # The output prints the answer first, so the answer is taken whatever
    # is cut from the rest.
    output = "38892.0\n" + "x" * 5000

    def shown(**values):
        out = {"ok": True, "stdout": output, "error": None}
        step, asked, _runs, _events = computing(monkeypatch, CODE, ANSWER,
                                                ran=out)
        with rules.overlaid(**values):
            run_step(step, share(21), amount(185200))
        return asked[1]["messages"][-1]["content"]
    assert output[:2000] in shown() and output[:2001] not in shown()
    assert output[:10] in shown(code_output_chars=10)
    assert output[:11] not in shown(code_output_chars=10)
    assert output[:4000] in shown(code_output_chars=4000)


# -- a passage and what the request is sized by -------------------------------

def test_heading_in_front_chars_say_how_early_a_heading_may_stand():
    hit = {"owner_kind": "section", "owner_id": 4, "document_id": 1,
           "title": "Bilanz", "text": "Einleitung. Bilanz der Stadt."}
    assert DEFAULT["heading_in_front_chars"] == 200
    assert runner._source_of(hit).text == hit["text"]          # standard
    with rules.overlaid(heading_in_front_chars=0):
        assert runner._source_of(hit).text == "Bilanz\n" + hit["text"]
    with at_step("find", heading_in_front_chars=5):
        assert runner._source_of(hit).text == "Bilanz\n" + hit["text"]
    with at_step("find", heading_in_front_chars=25):
        assert runner._source_of(hit).text == hit["text"]
    assert runner._source_of(hit).text == hit["text"]


def test_message_overhead_tokens_are_counted_beyond_the_text(monkeypatch):
    monkeypatch.setattr(runner, "PROMPT_COUNTER", None)
    conversation = [{"role": "user", "content": "x" * 30}]
    standard = runner.prompt_tokens("system", conversation)
    with rules.overlaid(message_overhead_tokens=36):
        assert runner.prompt_tokens("system", conversation) \
            == standard + 20 * 2                      # two messages, 20 more
    with at_step("find", message_overhead_tokens=0):
        assert runner.prompt_tokens("system", conversation) \
            == standard - 16 * 2
    assert runner.prompt_tokens("system", conversation) == standard


def test_least_answer_tokens_are_the_room_below_which_nothing_is_sent(
        monkeypatch):
    monkeypatch.setattr(runner, "PROMPT_COUNTER", None)
    monkeypatch.setattr(runner, "model_window", lambda: 1000)
    conversation = [{"role": "user", "content": "x" * 300}]
    assert DEFAULT["least_answer_tokens"] == 512
    room = runner.answer_room("", conversation, 1 << 30)
    assert 0 < room
    below = room + 1                      # one token under the room needed
    with rules.overlaid(least_answer_tokens=room):
        assert runner.request_room("", conversation, 1 << 30) == room
    with rules.overlaid(least_answer_tokens=below):
        assert runner.request_room("", conversation, 1 << 30) is None
    with at_step("find", least_answer_tokens=below):
        assert runner.request_room("", conversation, 1 << 30) is None
    assert runner.request_room("", conversation, 1 << 30) == (
        room if room >= 512 else None)


def spec_of(profile):
    from docpipe.extraction.spec import load as load_spec
    path = Path(__file__).resolve().parent.parent / "profiles" / profile \
        / "extraction_spec.json"
    return load_spec(json.loads(path.read_text(encoding="utf-8")))


def prompt_of(words):
    return SimpleNamespace(meta={}, text=" ".join(["w"] * words),
                           placeholders=frozenset(), id="p")


def test_the_window_the_server_is_started_with_follows_its_rules(
        monkeypatch):
    prompt = prompt_of(100)
    standard = runner.context_budget(prompt)
    assert (DEFAULT["window_words_per_token"],
            DEFAULT["window_tokens_per_image"]) == (3, 1200)
    # a prompt of 100 words is counted at 3 characters a word-token
    with rules.overlaid(window_words_per_token=6):
        assert runner.context_budget(prompt) == standard + 100 * 3
    monkeypatch.setattr(runner, "attach_images", lambda: True)
    with_images = runner.context_budget(prompt)
    with rules.overlaid(window_tokens_per_image=100):
        assert runner.context_budget(prompt) < with_images
    monkeypatch.setattr(runner, "attach_images", lambda: False)
    with rules.overlaid(window_tokens_per_image=100):
        assert runner.context_budget(prompt) == runner.context_budget(prompt)
        assert runner.context_budget(prompt) < with_images


def test_the_extra_tokens_of_a_payload_are_the_rule_s():
    prompt, spec = prompt_of(100), spec_of("kwp")
    standard = runner.context_budget(prompt, spec)
    assert DEFAULT["window_extra_tokens"] == 600
    with rules.overlaid(window_extra_tokens=0):
        assert runner.context_budget(prompt, spec) == standard - 600
    with rules.overlaid(window_extra_tokens=1600):
        assert runner.context_budget(prompt, spec) == standard + 1000


def test_a_list_built_for_one_document_has_the_room_the_rule_gives(
        monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "scenarios")
    rules.reset()
    prompt, spec = prompt_of(100), spec_of("scenarios")
    assert any(p.vocabulary_dynamic or any(a.dynamic
                                           for a in p.axes.values())
               for p in spec.parameters)
    standard = runner.context_budget(prompt, spec)
    assert DEFAULT["dynamic_list_tokens"] == 4000
    with rules.overlaid(dynamic_list_tokens=6000):
        assert runner.context_budget(prompt, spec) == standard + 2000
    with rules.overlaid(dynamic_list_tokens=0):
        assert runner.context_budget(prompt, spec) == standard - 4000


def test_the_window_floor_is_the_tokens_every_request_takes_at_least():
    """`window_floor_tokens` says "the tokens every request is assumed to
    take at least": without a spec the payload is the floor, so a floor
    3000 tokens higher asks for a window 3000 tokens larger."""
    prompt = prompt_of(100)
    standard = runner.context_budget(prompt)
    assert DEFAULT["window_floor_tokens"] == 2000
    with rules.overlaid(window_floor_tokens=5000):
        assert runner.context_budget(prompt) == standard + 3000


# -- the documents, the stamp, the review -------------------------------------

def database(tmp_path):
    path = tmp_path / "corpus.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                is_current INTEGER);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               section_number INTEGER);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             page_number INTEGER);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             page_number INTEGER);
    """)
    return path, conn


def test_largest_first_reads_the_documents_by_their_sections(tmp_path):
    _path, conn = database(tmp_path)
    conn.executemany("INSERT INTO Documents VALUES (?, ?, 1)",
                     [(1, "a.pdf"), (2, "b.pdf")])
    conn.executemany("INSERT INTO Sections VALUES (?, ?, ?)",
                     [(1, 1, 1), (2, 2, 1), (3, 2, 2), (4, 2, 3)])
    assert DEFAULT["largest_first"] is True
    assert [name for _id, name in runner._documents(conn)] \
        == ["b.pdf", "a.pdf"]                                    # standard
    with rules.overlaid(largest_first=False):
        assert [name for _id, name in runner._documents(conn)] \
            == ["a.pdf", "b.pdf"]
    assert [name for _id, name in runner._documents(conn)] \
        == ["b.pdf", "a.pdf"]


def test_the_rest_of_a_document_starts_at_the_open_rows_where_the_rule_says(
        tmp_path):
    path, conn = database(tmp_path)
    conn.executemany("INSERT INTO Sections VALUES (?, 7, ?)",
                     [(1, 1), (2, 2), (3, 3), (4, 4)])
    conn.commit()
    fetch = lambda _conn, kind, owner: {"text": f"{kind} {owner}",  # noqa
                                        "title": "", "document_id": 7}
    rest = runner.make_rest_of_document(path, content=fetch)

    def order(**values):
        with rules.overlaid(**values):
            return [s.owner_id for s in rest(7, set(), 3)]
    assert DEFAULT["rest_starts_at_open_rows"] is True
    assert order() == [3, 4, 1, 2]                               # standard
    assert order(rest_starts_at_open_rows=False) == [1, 2, 3, 4]
    with at_step("order", rest_starts_at_open_rows=False):
        assert [s.owner_id for s in rest(7, set(), 3)] == [1, 2, 3, 4]
    assert [s.owner_id for s in rest(7, set(), 3)] == [3, 4, 1, 2]


def parents_of(tmp_path):
    path, _conn = database(tmp_path)
    sections = {("section", 5): {"owner_kind": "section", "owner_id": 5,
                                 "document_id": 1, "title": "",
                                 "text": "a" * 3000 + " [T1] " + "b" * 3000},
                ("table", 9): {"owner_kind": "table", "owner_id": 9,
                               "document_id": 1, "title": "", "text": "| 1 |",
                               "section_id": 5, "block_id": "T1"}}
    return path, lambda _conn, kind, owner: sections.get((kind, owner))


def test_review_parent_chars_are_how_much_of_the_section_above_is_shown(
        tmp_path):
    path, fetch = parents_of(tmp_path)
    own = runner.Source("table", 9, "| 1 |",
                        {"parent_section": 5, "block_id": "T1"})
    parents = runner.make_parents(path, content=fetch)
    assert DEFAULT["review_parent_chars"] == 4000
    standard = parents([own])[0].text               # 6,006 characters long
    assert len(standard) <= 4000 and "[T1]" in standard
    with rules.overlaid(review_parent_chars=500):
        cut = parents([own])[0].text
        assert len(cut) <= 500 and "[T1]" in cut        # cut around the table
    with rules.overlaid(review_parent_chars=9000):
        assert len(parents([own])[0].text) > 6000
    with at_step("review", review_parent_chars=300):
        assert len(parents([own])[0].text) <= 300


def test_review_shown_passages_say_whether_the_section_is_shown_with_the_row(
        tmp_path):
    path, fetch = parents_of(tmp_path)
    sources = runner.make_review_sources(path, content=fetch)
    row = {"provenance": {"owner_kind": "table", "owner_id": 9}}
    assert DEFAULT["review_shown_passages"] == "own_and_section"
    assert [(s.owner_kind, s.owner_id) for s in sources(row)] \
        == [("table", 9), ("section", 5)]                        # standard
    with rules.overlaid(review_shown_passages="own_only"):
        assert [(s.owner_kind, s.owner_id) for s in sources(row)] \
            == [("table", 9)]
    assert len(sources(row)) == 2
    assert rules.problem("review_shown_passages", "everything") is not None


def test_a_stamp_is_compared_by_the_question_keys_the_rule_names(tmp_path):
    assert DEFAULT["question_keys"] == ["parameter/", "value/", "axis/",
                                        "slot/"]                # 2026-09-10
    stamp = tmp_path / "d.stamp.json"
    stamp.write_text(json.dumps({"parameter/p": 1, "axis/p.a": 1}))
    current = {"parameter/p": 1, "axis/p.a": 2}
    assert runner.stale(stamp, current) == ["axis/p.a"]          # standard
    with rules.overlaid(question_keys=["parameter/"]):
        assert runner.stale(stamp, current) == []
    with rules.overlaid(question_keys=["axis/"]):
        assert runner.stale(stamp, current) == ["axis/p.a"]
    assert runner.stale(stamp, current) == ["axis/p.a"]


def test_span_marks_are_what_the_rows_of_a_span_of_years_are_marked_with():
    from test_addressed import SPEC, Model, in_order
    from docpipe.extraction.addressed import Reader
    assert rules.load(load_profile("kwp"), environ={})["span_marks"] \
        == {"qualifier": "out:approximate"}                      # 2026-11-07
    assert DEFAULT["span_marks"] == {}
    reader = Reader(SPEC, Model().asks(), in_order)
    assert reader.span_marks == {"qualifier": "out:approximate"}
    with rules.overlaid(span_marks={}):
        assert reader.span_marks == {}
    with at_step("find", span_marks={"year": "out:total"}):
        assert reader.span_marks == {"year": "out:total"}
    assert reader.span_marks == {"qualifier": "out:approximate"}


def failed_report(unreachable, others, harvested):
    refusals = ([{"claim": {"_harvest_failed": True,
                            "_why": "unreachable"}}] * unreachable
                + [{"claim": {"_harvest_failed": True,
                              "_why": "cut_off"}}] * others)
    return SimpleNamespace(refusals=refusals, owners_harvested=harvested)


def test_unreachable_share_is_the_lost_share_that_voids_a_document():
    report = failed_report(3, 0, 4)
    assert DEFAULT["unreachable_share"] == 0.5
    assert runner.not_happened(report) == ("unreachable", 3, 4)  # standard
    assert runner.not_happened(failed_report(2, 0, 4)) is None
    with rules.overlaid(unreachable_share=1):
        assert runner.not_happened(report) is None
    with rules.overlaid(unreachable_share=0.2):
        assert runner.not_happened(failed_report(2, 0, 4)) == (
            "unreachable", 2, 4)
    assert runner.not_happened(report) == ("unreachable", 3, 4)


def test_show_unparsable_is_how_many_unreadable_replies_the_log_shows(
        monkeypatch):
    reply = SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
        content="not json", reasoning_content=""))
    assert DEFAULT["show_unparsable"] == 20
    monkeypatch.setattr(runner, "_UNPARSABLE_SHOWN", 0)
    assert "not json" in runner._unparsable(reply)               # standard
    with rules.overlaid(show_unparsable=0):
        assert runner._unparsable(reply) == ""
    monkeypatch.setattr(runner, "_UNPARSABLE_SHOWN", 0)
    with rules.overlaid(show_unparsable=2):
        shown = [runner._unparsable(reply) for _ in range(3)]
        assert [bool(one) for one in shown] == [True, True, False]


# -- finding a quote in the PDF -----------------------------------------------

def locating(tmp_path, monkeypatch):
    """A locate over a document of one section on pages 1 to 4 whose quote
    is on none: the pages its words were laid out of, in order."""
    import tempfile
    from docpipe.inference import pdf_locate
    tmp_path = Path(tempfile.mkdtemp(dir=tmp_path))      # one per locate
    path = tmp_path / "corpus.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);
        CREATE TABLE Pages (id INTEGER PRIMARY KEY, page_number INTEGER);
        CREATE TABLE SectionPages (section INTEGER, page INTEGER);
        INSERT INTO Documents VALUES (1, 'a.pdf');
        INSERT INTO Pages VALUES (1, 1), (2, 2), (3, 3), (4, 4);
        INSERT INTO SectionPages VALUES (5, 1), (5, 2), (5, 3), (5, 4);
    """)
    conn.commit()
    conn.close()
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    laid = []
    monkeypatch.setattr(pdf_locate, "page_words",
                        lambda pdf, page: laid.append(page) or [page])
    monkeypatch.setattr(pdf_locate, "rects_from_words",
                        lambda words, quote: None)
    locate = runner.make_locate(path, tmp_path)
    source = runner.Source("section", 5, "text",
                           {"document_id": 1, "page": 1})
    return locate, source, laid


def test_locate_max_pages_are_how_many_pages_of_a_section_a_quote_is_sought_on(
        tmp_path, monkeypatch):
    assert DEFAULT["locate_max_pages"] == 3
    for values, laid_out in (({}, [1, 2, 3]),
                             ({"locate_max_pages": 1}, [1]),
                             ({"locate_max_pages": 4}, [1, 2, 3, 4])):
        locate, source, laid = locating(tmp_path, monkeypatch)
        with rules.overlaid(**values):
            assert locate(source, "a quote") is None
        assert laid == laid_out
    locate, source, laid = locating(tmp_path, monkeypatch)
    with at_step("write", locate_max_pages=2):
        locate(source, "a quote")
    assert laid == [1, 2]


def test_locate_cache_pages_are_how_many_pages_with_their_words_stay_in_memory(
        tmp_path, monkeypatch):
    assert DEFAULT["locate_cache_pages"] == 512

    def laid_out(**values):
        locate, source, laid = locating(tmp_path, monkeypatch)
        with rules.overlaid(locate_max_pages=2, **values):
            locate(source, "a quote")
            locate(source, "another quote")
        return laid
    assert laid_out() == [1, 2]                  # the second time from memory
    assert laid_out(locate_cache_pages=1) == [1, 2, 1, 2]    # one at a time


# -- the queue of the run -----------------------------------------------------

def test_limit_adaptive_decides_whether_the_requests_follow_the_servers_load(
        monkeypatch):
    steered = []
    monkeypatch.setattr(runner, "LIMIT", None)
    monkeypatch.setattr(runner, "SCHEDULER", None)
    monkeypatch.setattr(runner, "AHEAD", None)
    monkeypatch.setattr(runner.providers, "replaying", lambda: False)
    monkeypatch.setattr(runner.providers, "gate", lambda role: None)
    monkeypatch.setattr(runner, "llm_base_url", lambda: "http://x/v1")
    monkeypatch.setattr(throttle, "start", lambda url: steered.append(url)
                        or throttle.AdaptiveLimit(start=2, minimum=2,
                                                  maximum=2))
    assert DEFAULT["limit_adaptive"] is True          # decided 2026-10-22
    with rules.overlaid(limit_adaptive=False):
        runner.start_limit()
        assert steered == [] and runner.LIMIT is None
    runner.start_limit()
    assert steered == ["http://x/v1"] and runner.LIMIT is not None
    runner.AHEAD.shutdown(wait=False)


# -- what `main` decides: the check before the run, the documents read at
# once, the end of a run whose server is dead ---------------------------

def test_the_check_before_the_run_asks_the_server_unless_the_rule_is_off(
        monkeypatch):
    asked = []
    monkeypatch.setattr(runner, "assert_serving", lambda *a, **k: (
        asked.append(("serving", a[3], k["what"])) or 4096))
    monkeypatch.setattr(runner, "assert_step_models", lambda *a, **k: (
        asked.append(("models",))))
    monkeypatch.setattr(runner, "set_model_len", lambda n: asked.append(
        ("window", n)))
    assert runner.preflight(1000, what="extraction") is True
    assert asked == [("serving", 1000, "extraction"), ("window", 4096)]
    asked.clear()
    assert runner.preflight(1000, what="extraction",
                            profile=load_profile("kwp")) is True
    assert ("models",) in asked
    # the failure by construction: the rule off asks the server nothing
    asked.clear()
    with rules.overlaid(preflight_on=False):
        assert runner.preflight(1000, what="extraction",
                                profile=load_profile("kwp")) is False
    assert asked == []


def test_the_documents_read_at_once_are_the_rule_s_and_at_least_one():
    assert runner.documents_at_once() == 256
    with rules.overlaid(documents_in_flight=3):
        assert runner.documents_at_once() == 3
    with rules.overlaid(documents_in_flight=1):
        assert runner.documents_at_once() == 1


def test_a_dead_server_ends_the_run_unless_the_rule_says_to_go_on(caplog):
    with caplog.at_level("ERROR"):
        assert runner.dead_server_ends_run(300.0) is True
    assert "the run goes on" not in caplog.text
    # the failure by construction: the rule off says it and does not end
    with rules.overlaid(dead_server_ends_run=False):
        with caplog.at_level("ERROR"):
            assert runner.dead_server_ends_run(300.0) is False
    assert "the run goes on" in caplog.text
