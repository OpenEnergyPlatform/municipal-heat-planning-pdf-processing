"""The chat's places: who is sent when, and what a parallel turn answers."""
import sqlite3
import threading
import time

import pytest

from docpipe.extraction import scheduler
from docpipe.inference import answer, chunker, compare, config, db, llm_client, pool
from docpipe.inference import replies, statements


class Reply:
    def __init__(self, model):
        self.model = model


class Limited(Exception):
    status_code = 429


class FakeClient:
    """Takes *hold* seconds per request, counts how many each model has open."""

    def __init__(self, hold=0.02, refuse=()):
        self.hold, self.refuse = hold, set(refuse)
        self.open, self.most, self.asked = {}, {}, []
        self.lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        model = kwargs["model"]
        with self.lock:
            self.asked.append(model)
            self.open[model] = self.open.get(model, 0) + 1
            self.most[model] = max(self.most.get(model, 0), self.open[model])
        time.sleep(self.hold)
        with self.lock:
            self.open[model] -= 1
        if model in self.refuse:
            raise Limited()
        return Reply(model)


@pytest.fixture
def wide(monkeypatch):
    """Two models with two places each, and a pool of this test's own."""
    def build(client):
        monkeypatch.setattr(config, "LLM_MODELS", ("a", "b"))
        monkeypatch.setattr(config, "LLM_SLOTS_PER_MODEL", 2)
        made = pool.Pool(client, ("a", "b"), 2)
        monkeypatch.setattr(pool, "_pool", made)
        return made
    return build


# -- places --------------------------------------------------------------------

def test_no_model_ever_holds_more_than_its_places_and_all_are_used(wide):
    client = FakeClient()
    made = wide(client)
    pool.together([lambda: made.create(model="x") for _ in range(12)])
    assert len(client.asked) == 12
    assert client.most == {"a": 2, "b": 2}


def test_a_429_closes_the_one_model_that_sent_it(wide):
    client = FakeClient(hold=0, refuse={"a"})
    made = wide(client)
    with pytest.raises(Limited):
        made.create(model="x")          # the first request goes to a
    assert made.seats.clients["a"].gate.closed()
    assert not made.seats.clients["b"].gate.closed()
    assert made.seats.limit == 2
    assert made.create(model="x").model == "b"


def test_asked_again_a_request_lands_on_the_other_model(wide):
    client = FakeClient(hold=0)
    made = wide(client)
    assert [made.create(model="x").model for _ in range(4)] == ["a", "b", "a", "b"]


def test_one_place_is_the_plain_client_and_one_after_the_other(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODELS", ("a",))
    monkeypatch.setattr(config, "LLM_SLOTS_PER_MODEL", 1)
    client = FakeClient()
    assert pool.over(client) is client
    me = threading.get_ident()
    assert pool.together([threading.get_ident] * 2) == [me, me]


def test_a_request_of_a_withdrawn_ticket_is_not_sent(wide):
    client = FakeClient()
    made = wide(client)
    ticket = scheduler.Ticket()
    ticket.withdraw()

    def run():
        pool._TICKET.set(ticket)
        made.create(model="x")

    import contextvars
    with pytest.raises(scheduler.Withdrawn):
        contextvars.copy_context().run(run)
    assert client.asked == []


# -- the queue -----------------------------------------------------------------

class OnePlace:
    limit = maximum = 1
    in_flight = 0

    def acquire(self):
        self.in_flight += 1

    def release(self):
        self.in_flight -= 1


def test_a_needed_request_overtakes_one_sent_ahead_and_promotion_undoes_that():
    queue = scheduler.Scheduler(OnePlace())
    hold = threading.Event()
    sent = []
    blocker = queue.submit(lambda: hold.wait(2), document=1)
    while queue.limit.in_flight == 0:
        time.sleep(0.001)
    ahead = scheduler.Ticket(ahead=True)
    promoted = scheduler.Ticket(ahead=True)
    jobs = [queue.submit(lambda: sent.append("ahead"), 1, ahead),
            queue.submit(lambda: sent.append("promoted"), 2, promoted),
            queue.submit(lambda: sent.append("needed"), 3)]
    queue.promote(promoted)
    hold.set()
    for job in (blocker, *jobs):
        job.result(2)
    assert sent == ["promoted", "needed", "ahead"]


# -- in order ------------------------------------------------------------------

def test_answers_come_in_order_whichever_returned_first(wide):
    wide(FakeClient())
    second_done = threading.Event()

    def ask(i):
        if i == 0:
            assert second_done.wait(2)
        else:
            second_done.set()
        return i

    assert list(pool.in_order(2, lambda i: i, ask)) == [0, 1]


def test_a_batch_sent_ahead_did_not_see_the_one_before_it(wide):
    wide(FakeClient())
    taken = []
    second_started = threading.Event()

    def prepare(i):
        if i == 1:
            second_started.set()
        return i, list(taken)

    def ask(job):
        if job[0] == 0:
            assert second_started.wait(2)
        return job

    got = []
    for job in pool.in_order(2, prepare, ask):
        got.append(job)
        taken.append(job[0])
    assert got == [(0, []), (1, [])]


def test_without_a_free_place_the_next_batch_waits_and_sees_the_one_before(
        monkeypatch, wide):
    wide(FakeClient())
    monkeypatch.setattr(pool, "room", lambda: 0)
    taken = []
    got = []
    for job in pool.in_order(2, lambda i: (i, list(taken)), lambda job: job):
        got.append(job)
        taken.append(job[0])
    assert got == [(0, []), (1, [0])]


def test_leaving_withdraws_what_has_not_been_sent(monkeypatch, wide):
    open_again = threading.Event()

    class Busy(FakeClient):
        def create(self, **kwargs):
            open_again.wait(2)
            return super().create(**kwargs)

    client = Busy(hold=0)
    made = wide(client)
    monkeypatch.setattr(pool, "room", lambda: 1)
    # Every place taken: what comes now waits in the queue.
    busy = threading.Thread(target=lambda: pool.together(
        [lambda: made.create(model="x") for _ in range(4)]))
    busy.start()
    while made.seats.in_flight < 4:
        time.sleep(0.001)

    in_queue = threading.Event()
    outcome = []

    def ask(i):
        if i == 0:
            assert in_queue.wait(2)
            return i
        in_queue.set()
        try:
            made.create(model="x")
            outcome.append("sent")
        except scheduler.Withdrawn:
            outcome.append("withdrawn")

    answers = pool.in_order(2, lambda i: i, ask)
    assert next(answers) == 0
    answers.close()
    open_again.set()
    busy.join(2)
    while not outcome:
        time.sleep(0.001)
    assert outcome == ["withdrawn"]
    assert len(client.asked) == 4


# -- faults --------------------------------------------------------------------

def test_a_cut_taken_back_in_one_thread_leaves_the_fault_of_another(monkeypatch, wide):
    """With one list shared, `_ask` deletes from its own position on, and that
    takes the other thread's note with it."""
    wide(FakeClient())
    noted = threading.Event()
    other_noted = threading.Event()

    def chat(messages, temperature):
        if messages == "cut":
            llm_client.note_fault("x", "cut_off")
            noted.set()
            assert other_noted.wait(2)
            raise llm_client.ReplyError("cut_off", "x")
        assert noted.wait(2)
        llm_client.note_fault("y", "syntax")
        other_noted.set()
        raise llm_client.ReplyError("syntax", "y")

    monkeypatch.setattr(llm_client, "_chat_json", chat)

    def asked(messages):
        def run():
            with pytest.raises(llm_client.ReplyError):
                llm_client._ask(None, messages, 0.0, splittable=True)
        return run

    with llm_client.collecting() as faults:
        llm_client.together([asked("cut"), asked("other")])
    assert faults == [{"request": "y", "cause": "syntax"}]


def test_faults_of_parallel_work_stand_in_the_order_of_the_work(wide):
    wide(FakeClient())
    first_may_end = threading.Event()

    def first():
        assert first_may_end.wait(2)
        llm_client.note_fault("first", "syntax")

    def second():
        llm_client.note_fault("second", "syntax")
        first_may_end.set()

    with llm_client.collecting() as faults:
        llm_client.together([first, second])
    assert [f["request"] for f in faults] == ["first", "second"]


# -- one turn ------------------------------------------------------------------

PASSAGE = "Der Waermebedarf liegt im Jahr 2030 bei rund 120 GWh pro Jahr."


def hits(n):
    return [{"owner_kind": "section", "owner_id": i, "text": f"{PASSAGE} Nr {i}.",
             "title": None, "section_title": "S", "page_number": 1,
             "document_id": 1} for i in range(n)]


def stated(index, text):
    return {"statement": text, "basis": "text", "index": index,
            "quote": PASSAGE}


def reply(chunk_items, written, complete=False, fault=None):
    return {"statements": written, "complete": complete, "compute": [],
            "attached_images": [], "requested": [], "fault": fault}


@pytest.fixture
def turn(monkeypatch):
    """`_answer_hits` over three batches of one passage each."""
    monkeypatch.setattr(config, "ANSWER_CONTEXT_TOKENS", 1)
    monkeypatch.setattr(chunker, "get_tokenizer", lambda *a: None)

    def run(n=3):
        corpus = answer.Corpus(conn=None, index=None, id_to_pos={},
                               embed=lambda item: (None, False))
        with llm_client.collecting() as faults:
            result = answer._empty(False, faults)
            out = answer._answer_hits(
                "task", corpus, 1, [], hits(n), result, faults, mode="text",
                phrase="p", start_time=time.time(), history=None,
                as_json=False, progress=answer._silent)
        return out, list(faults)

    return run


def test_a_batch_that_answers_first_still_stands_second(monkeypatch, wide, turn):
    wide(FakeClient())
    second_done = threading.Event()

    def asked(task, items, **kw):
        at = items[0]["index"]
        if at == 0:
            assert second_done.wait(2)
            return reply(items, [stated(0, "erste Aussage")])
        if at == 1:
            second_done.set()
            return reply(items, [stated(1, "zweite Aussage")], complete=True)
        return reply(items, [stated(2, "dritte Aussage")])

    monkeypatch.setattr(llm_client, "answer_from_sources", asked)
    monkeypatch.setattr(llm_client, "repeats_among", lambda task, texts: [])
    out, _faults = turn()
    assert [s["text"] for s in out["statements"]] == ["erste Aussage",
                                                      "zweite Aussage"]
    assert out["n_batches"] == 2


def test_a_batch_not_needed_read_nothing_and_leaves_no_fault(monkeypatch, wide, turn):
    wide(FakeClient())
    started = threading.Event()

    def asked(task, items, **kw):
        at = items[0]["index"]
        if at == 0:
            assert started.wait(2)
            return reply(items, [stated(0, "erste Aussage")], complete=True)
        started.set()
        llm_client.note_fault(replies.ANSWER, "syntax")
        return reply(items, [], fault="syntax")

    monkeypatch.setattr(llm_client, "answer_from_sources", asked)
    out, faults = turn()
    assert out["examined"] == [("section", 0)]
    assert faults == []


def test_a_repeat_named_by_the_model_leaves_and_the_first_stays(monkeypatch, wide, turn):
    wide(FakeClient())
    started = threading.Event()

    def asked(task, items, **kw):
        at = items[0]["index"]
        if at == 0:
            assert started.wait(2)
            return reply(items, [stated(0, "Bedarf 120 GWh")])
        started.set()
        assert kw["prior"] is None      # sent ahead of the first
        return reply(items, [stated(at, "Bedarf 120 GWh, anders gesagt")])

    monkeypatch.setattr(llm_client, "answer_from_sources", asked)
    seen = []

    def named(task, texts):
        seen.append(texts)
        return [{"statement": 2, "of": 1}]

    monkeypatch.setattr(llm_client, "repeats_among", named)
    out, _faults = turn(2)
    assert seen == [["Bedarf 120 GWh", "Bedarf 120 GWh, anders gesagt"]]
    assert [s["text"] for s in out["statements"]] == ["Bedarf 120 GWh"]
    assert out["statements_repeated"] == 1
    assert out["n_findings"] == 1


def test_nothing_sent_ahead_asks_no_repeat_request(monkeypatch, turn):
    monkeypatch.setattr(config, "LLM_MODELS", ("a",))
    monkeypatch.setattr(config, "LLM_SLOTS_PER_MODEL", 1)
    told = []

    def asked(task, items, **kw):
        told.append(kw["prior"])
        return reply(items, [stated(items[0]["index"], f"Aussage {len(told)}")])

    def never(task, texts):
        raise AssertionError("no batch went ahead")

    monkeypatch.setattr(llm_client, "answer_from_sources", asked)
    monkeypatch.setattr(llm_client, "repeats_among", never)
    out, _faults = turn(2)
    assert told == [None, ["Aussage 1"]]
    assert out["statements_shown"] == 2


# -- repeats -------------------------------------------------------------------

def test_only_a_later_statement_repeats_an_earlier_one():
    pairs = [{"statement": 3, "of": 1},   # stands
             {"statement": 1, "of": 2},   # the earlier one would go
             {"statement": 2, "of": 2},   # itself
             {"statement": 9, "of": 1},   # not in the list
             {"statement": 2, "of": 0},   # not in the list
             {"statement": "2", "of": 1},  # no number
             "2"]
    assert statements.repeated(pairs, 3) == {2}


def test_nothing_named_nothing_leaves():
    assert statements.repeated(None, 3) == set()


# -- reading from threads ------------------------------------------------------

def test_every_thread_reads_over_its_own_connection():
    made = []

    def connect():
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        made.append(conn)
        return conn

    conn = db.PerThread(connect)
    assert conn.execute("SELECT 1").fetchone() == (1,)
    assert conn.execute("SELECT 2").fetchone() == (2,)
    assert len(made) == 1
    thread = threading.Thread(target=lambda: conn.execute("SELECT 3"))
    thread.start()
    thread.join()
    assert len(made) == 2


# -- several documents ---------------------------------------------------------

def test_the_documents_of_a_comparison_are_asked_at_the_same_time(monkeypatch, wide):
    wide(FakeClient())
    # Passes only if both documents are inside their turn at once.
    both = threading.Barrier(2, timeout=2)

    def asked(task, corpus, document_id, scopes, **kw):
        both.wait()
        return {"answer": f"Antwort {document_id}", "answer_text": None}

    monkeypatch.setattr(compare, "answer_question", asked)
    monkeypatch.setattr(llm_client, "compare_answers", lambda task, plans: "x")
    out = compare.compare_documents("task", None, [(1, "A"), (2, "B")], [])
    assert [row["label"] for row in out["rows"]] == ["A", "B"]
    assert out["answered"] == 2


def test_with_one_place_the_documents_are_asked_in_turn(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODELS", ("a",))
    monkeypatch.setattr(config, "LLM_SLOTS_PER_MODEL", 1)
    inside = []

    def asked(task, corpus, document_id, scopes, **kw):
        inside.append(threading.get_ident())
        return {"answer": None, "answer_text": None}

    monkeypatch.setattr(compare, "answer_question", asked)
    compare.compare_documents("task", None, [(1, "A"), (2, "B")], [])
    assert inside == [threading.get_ident()] * 2
