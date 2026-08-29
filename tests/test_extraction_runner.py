"""The runner's pure parts: reply parsing, staleness, resume."""
import json
import time

import pytest

from docpipe.extraction import runner
from docpipe.extraction.pipeline import Source
from docpipe.extraction.runner import _parameter_payload, _parse_tuples, stale
from docpipe.extraction.spec import load

SPEC = load({"parameters": [{
    "uri": "OEO_00050016",
    "label": "Endenergieverbrauch",
    "description": "Endenergieverbrauch je Energieträger, Sektor und Jahr, "
                   "wie im Plan bilanziert.",
    "unit_target": "OEO_00050008",
    "units_accepted": {"MWh/a": 1.0},
    "axes": {"carrier": {"vocabulary": {"OEO_00000292": ["Erdgas", "Gas"]}},
             "year": {"type": "int"}},
    "example": {"source": "| Erdgas | 42.005 | MWh/a | im Jahr 2020 |",
                "tuples": [{"value": 42005, "unit_raw": "MWh/a"}]},
}]})


def test_parse_strips_think_blocks_and_fences():
    raw = ("<think>rechne...</think>```json\n"
           '{"tuples": [{"value": 1}]}\n```')
    assert _parse_tuples(raw) == [{"value": 1}]


def test_parse_finds_the_object_inside_chatter():
    raw = 'Gerne! Hier: {"tuples": []} — sonst noch etwas?'
    assert _parse_tuples(raw) == []


def test_parse_refuses_a_reply_without_a_tuples_list():
    assert _parse_tuples('{"values": [1, 2]}') is None
    assert _parse_tuples("kein JSON") is None


def test_parameter_payload_offers_classes_not_a_flat_label_list():
    """The model has to map a wording onto ONE class, so it is shown the
    classes with the spellings already known for each. URIs stay on the
    verifier's side: they mean nothing to a reader of German plans."""
    payload = _parameter_payload(SPEC.parameters[0])
    assert payload["axes"]["carrier"] == {"classes": {"Erdgas": ["Gas"]}}
    assert "example" in payload and payload["units_accepted"] == ["MWh/a"]


def test_everything_is_stale_without_a_stamp(tmp_path):
    assert stale(tmp_path / "none.json", {"a": "1"}) == ["a"]


def test_only_the_changed_version_is_stale(tmp_path):
    stamp = tmp_path / "s.json"
    stamp.write_text(json.dumps({"a": "1", "b": "2"}), encoding="utf-8")
    assert stale(stamp, {"a": "1", "b": "2"}) == []
    assert stale(stamp, {"a": "1", "b": "NEW"}) == ["b"]


def _per_probe(fn):
    """Adapt a one-probe stub to the batched contract retrieval now has.

    plan_document hands every probe of a round over in one call, because the
    real implementation builds the document's sub-index once and searches the
    probes as a matrix. Exclusion still grows from probe to probe — that is
    what this reproduces, and what the sequential version did by rebuilding
    the snapshot each time.
    """
    def retrieve(probes, document_id, exclude):
        taken = set(exclude)
        out = []
        for probe in probes:
            found = list(fn(probe, document_id, set(taken)))
            taken.update((s.owner_kind, s.owner_id) for s in found)
            out.append(found)
        return out
    return retrieve


def test_run_document_writes_then_skips_then_redoes_on_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    calls = []

    def retrieve(query, document_id, exclude):
        return [] if ("table", 1) in exclude else \
            [Source("table", 1, "| Erdgas | 42.005 | MWh/a |", {"page": 3})]

    def harvest(batch, prior=None):
        calls.extend(i.source.owner_id for i in batch.items)
        return {"tuples": [{"source": "Q1", "value": 42005, "unit_raw": "MWh/a",
                            "carrier": "Erdgas", "quote": "Erdgas | 42.005"}],
                "status": "complete", "need_more": []}

    deps = {"retrieve": _per_probe(retrieve), "harvest": harvest}
    args = (7, "plan_x", tmp_path, SPEC, "sha-1", ["{label}"], deps)

    runner.run_document(*args)
    assert (tmp_path / "plan_x.jsonl").is_file()
    assert (tmp_path / "plan_x.stamp.json").is_file()
    assert calls == [1]

    runner.run_document(*args)
    assert calls == [1], "current output is not redone"

    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v2" for i in ids})
    runner.run_document(*args)
    assert calls == [1], "stale without --force-stale only warns"
    runner.run_document(*args, force_stale=True)
    assert calls == [1, 1], "--force-stale redoes exactly the stale document"

    # No stamp is not an older stamp. A file nothing vouches for gets redone
    # without anyone having to ask, which is what deleting the stamps means
    # and what it silently failed to do.
    (tmp_path / "plan_x.stamp.json").unlink()
    runner.run_document(*args)
    assert calls == [1, 1, 1], "a file with no stamp is harvested again"


def test_a_source_the_model_never_answered_is_a_visible_hole(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})

    def retrieve(query, document_id, exclude):
        return [] if ("table", 1) in exclude else \
            [Source("table", 1, "| Erdgas | 42.005 |", {"page": 3})]

    deps = {"retrieve": _per_probe(retrieve),
            "harvest": lambda b, prior=None: {
                "tuples": [{"_harvest_failed": True, "source": "Q1"}],
                "status": "failed", "need_more": []}}
    runner.run_document(7, "plan_y", tmp_path, SPEC, "sha", ["{label}"], deps)
    rows = [json.loads(l) for l in
            (tmp_path / "plan_y.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and rows[0]["kind"] == "refusal"
    assert rows[0]["claim"]["_harvest_failed"] is True


def test_candidate_tokens_cover_units_label_and_vocabulary():
    from docpipe.extraction.runner import _candidate_tokens
    tokens = _candidate_tokens(SPEC.parameters[0])
    assert {"MWh/a", "Endenergieverbrauch", "Erdgas", "Gas"} <= set(tokens)


def test_serialize_walks_only_accepted_tuples(tmp_path):
    from docpipe.extraction.serialize import run
    (tmp_path / "plan_a.jsonl").write_text(
        '{"kind": "tuple", "value": 1}\n{"kind": "refusal", "reason": "x"}\n',
        encoding="utf-8")
    (tmp_path / "plan_b.jsonl").write_text("", encoding="utf-8")
    seen = {}

    def serializer(name, rows):
        seen[name] = rows
        return f"# {name}: {len(rows)}" if rows else None

    counts = run(tmp_path, tmp_path / "out.ttl", serializer)
    assert counts == {"plan_a": 1}, "refusals and empty plans stay outside"
    assert seen["plan_a"][0]["value"] == 1
    assert (tmp_path / "out.ttl").read_text(encoding="utf-8") == "# plan_a: 1"


# ---------------------------------------------------------------------------
# picking the documents a run covers
# ---------------------------------------------------------------------------

def test_no_restriction_means_the_whole_corpus():
    from docpipe.extraction.runner import select_documents

    docs = [(1, "a.pdf"), (2, "b.pdf")]
    assert select_documents(docs, None) == (docs, [])
    assert select_documents(docs, []) == (docs, [])


def test_a_pilot_names_its_set_and_keeps_the_corpus_order():
    from docpipe.extraction.runner import select_documents

    docs = [(1, "a.pdf"), (2, "b.pdf"), (3, "c.pdf")]
    chosen, missing = select_documents(docs, [3, 1])
    assert chosen == [(1, "a.pdf"), (3, "c.pdf")]
    assert missing == []


def test_a_named_document_that_is_not_current_is_reported_not_dropped():
    """`_documents` lists current versions only, so a superseded id simply is
    not on offer. A pilot of sixteen that silently runs fourteen is worse than
    one that refuses: the missing two are exactly the interesting ones."""
    from docpipe.extraction.runner import select_documents

    chosen, missing = select_documents([(1, "a.pdf")], [1, 1081, 26])
    assert chosen == [(1, "a.pdf")]
    assert missing == [26, 1081], "sorted, so the message is stable"


def test_the_same_id_twice_is_one_document():
    from docpipe.extraction.runner import select_documents

    chosen, missing = select_documents([(7, "x.pdf")], [7, 7])
    assert chosen == [(7, "x.pdf")] and missing == []


# ---------------------------------------------------------------------------
# one model, however many threads ask for it
# ---------------------------------------------------------------------------

def test_the_embedder_is_built_once_however_many_threads_ask(monkeypatch):
    """get_embedder() CONSTRUCTS a backend rather than returning a shared one,
    and the call sat inside the per-probe embed(). Every probe loaded another
    copy of the 8B model onto one card; five fit, the sixth was CUDA OOM and
    the pilot lost all sixteen documents."""
    import threading

    from docpipe.extraction import runner

    built = []
    start = threading.Barrier(8)

    def slow_factory():
        built.append(1)
        time.sleep(0.05)               # the window the race needs
        return object()

    monkeypatch.setattr(runner, "_EMBEDDER", None)
    monkeypatch.setattr("docpipe.embedding.get_embedder", slow_factory)

    seen = []

    def ask():
        start.wait()
        seen.append(runner.embedder())

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(built) == 1, f"{len(built)} models loaded instead of one"
    assert len(set(map(id, seen))) == 1, "every thread must get the same one"


def test_the_local_backend_guards_its_lazy_load():
    """The runner holds one LocalEmbedder and eight threads call .embed() on it
    at once. A second replica of an 8B model is 16 GB of card nothing gives
    back, so the lazy init has to be guarded.

    Asserted on the guard itself: a timing test for this passed with and
    without the lock, and a test that cannot fail is worse than none.
    """
    import contextlib
    import threading

    from docpipe.embedding.local import LocalEmbedder

    embedder = LocalEmbedder(model="m")
    assert isinstance(embedder._lock, type(threading.Lock())),         "the lazy load in .embed() must sit behind a real lock"
    assert not isinstance(embedder._lock, contextlib.nullcontext)


# ---------------------------------------------------------------------------
# The batch path: plan everything, then send everything
# ---------------------------------------------------------------------------

def _source(text, owner_id=1, kind="section"):
    return Source(owner_kind=kind, owner_id=owner_id, text=text,
                  provenance={"document_id": 7})


def _item(source):
    from docpipe.extraction.pipeline import WorkItem
    return WorkItem(7, SPEC.parameters[0], source)


def test_a_source_that_fits_is_not_split():
    items = [_item(_source("kurz"))]
    assert runner.split_long_sources(items, max_chars=100) is not items
    assert [i.source.text for i in runner.split_long_sources(items, 100)] == ["kurz"]


def test_a_long_source_becomes_overlapping_windows_of_the_same_owner():
    """A section over the window used to be sent whole, rejected with a 400 and
    written off — its values were never read. Windows overlap so a number
    cannot be cut in half at the seam, and both carry the owner they came from,
    which is what provenance and dedup hang on."""
    text = "".join(f"{i:04d} " for i in range(1000))       # 5000 chars
    windows = runner.split_long_sources([_item(_source(text))], max_chars=2000)

    assert len(windows) > 1
    assert all(len(w.source.text) <= 2000 for w in windows)
    assert {w.source.owner_id for w in windows} == {1}
    assert "".join(w.source.text for w in windows) != text, "windows overlap"
    # Nothing is lost: every window is a slice of the original, and together
    # they cover it end to end.
    assert windows[0].source.text == text[:2000]
    assert text.endswith(windows[-1].source.text)
    covered = set()
    for w in windows:
        start = text.index(w.source.text)
        covered.update(range(start, start + len(w.source.text)))
    assert len(covered) == len(text)


def _chain(item):
    from docpipe.extraction.pipeline import group_items
    return group_items([item])


def test_every_batch_is_in_flight_at_once_not_one_per_document():
    """The unit of scheduling is the unit of parallelism. When a chain was
    the unit, a single-document run — the pilot's own canary stage — put
    three requests to a server sized for two hundred."""
    import threading
    batches = runner.group_items(
        [_item(_source(f"s{i}", owner_id=i)) for i in range(20)],
        max_sources=1)
    # A barrier, not a sleep: it PROVES four requests were open at the same
    # moment instead of inferring it from timing — and conftest patches
    # time.sleep away for every test, so a sleeping version measures nothing.
    gate = threading.Barrier(4, timeout=5)
    through = []

    def harvest(batch, prior=None):
        try:
            gate.wait()
            through.append(batch)
        except threading.BrokenBarrierError:
            pass                       # fewer than four ever ran together
        return {"tuples": [], "status": "complete", "need_more": []}

    # One document, one parameter: as chains this was 1, whatever the pool.
    runner.harvest_batches(batches, harvest, workers=8)
    assert len(through) >= 4, (
        f"only {len(through)} of 20 batches ever shared the server")


def test_a_request_that_raises_becomes_a_visible_hole():
    batches = runner.group_items(
        [_item(_source("a", owner_id=1)), _item(_source("b", owner_id=2))],
        max_sources=1)

    def harvest(batch, prior=None):
        if batch.items[0].source.owner_id == 2:
            raise RuntimeError("server gone")
        return {"tuples": [{"value": 1}], "status": "complete", "need_more": []}

    got = dict((b.items[0].source.owner_id, r)
               for b, r in runner.harvest_batches(batches, harvest, workers=2))
    assert got[1]["tuples"] == [{"value": 1}]
    assert got[2]["tuples"] == [{"_harvest_failed": True, "_why": "unreachable",
                                 "source": "Q1"}], (
        "a hole must stay countable, and say what made it")


def test_planning_never_calls_the_model():
    """The sweep's rounds are fed by retrieval alone. That is what lets the
    whole corpus be planned before the first request goes out."""
    from docpipe.extraction.pipeline import plan_document

    calls = []

    def retrieve(probes, document_id, exclude):
        calls.append(list(probes))
        if len(calls) > 1:
            return [[] for _ in probes]
        return [[_source("Erdgas 42.005 MWh/a im Jahr 2020")] for _ in probes]

    items, report = plan_document(7, SPEC, ["{label}"], retrieve=retrieve)
    assert calls[0] == ["Endenergieverbrauch"], (
        "every probe of a round goes over in one call, not one call per probe")
    assert len(items) == 1 and items[0].source.owner_id == 1
    assert report.owners_harvested == 1
    assert report.tuples == [] and report.refusals == []


def test_the_image_root_follows_the_pdf_root():
    """The crops sit next to the PDFs they were cut from. A run that names its
    PDF root has already said where they are; the profile default pointed at
    data/<profile>/pdf/processed, which this deployment does not have."""
    from pathlib import Path

    assert runner.resolve_image_root(Path("data/pdf"), Path("data/kwp/pdf/processed")) \
        == Path("data/pdf/processed")
    assert runner.resolve_image_root(None, Path("data/kwp/pdf/processed")) \
        == Path("data/kwp/pdf/processed")


def test_the_context_budget_holds_a_full_window_and_a_crop():
    """The number goes to --max-model-len as a floor. It has to cover the
    largest request the run can actually build, or the server rejects it."""
    class Prompt:
        text = "wort " * 500
        meta = {"max_tokens": 4096}

    budget = runner.context_budget(Prompt())
    assert budget > runner.MAX_SOURCE_CHARS // 3 + 4096
    assert budget > 1200, "the crop counts too"


def test_a_refused_request_is_not_retried(monkeypatch):
    """A 400 is a 400 three times over. The last run spent three tries and
    eight seconds of sleep on every over-long section."""
    import openai

    attempts = []

    class Error(Exception):
        status_code = 400

    class Client:
        def __init__(self, **kw):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            attempts.append(kw)
            raise Error("context length")

    monkeypatch.setattr(openai, "OpenAI", Client)
    monkeypatch.setattr(runner.prompts, "load",
                        lambda _id: type("P", (), {"text": "sys", "meta": {}})())
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    harvest = runner.make_harvester(None)
    reply = harvest(_chain(_item(_source("x")))[0], [])
    assert reply["tuples"] == [{"_harvest_failed": True, "_why": "no_answer",
                                "source": "Q1"}], (
        "a 400 is the server answering, not the server being gone — a resume "
        "must not redo the document over it")
    assert len(attempts) == 1, f"{len(attempts)} attempts for a 400"


def test_the_document_index_is_built_once_and_searched_once_per_probe_set(monkeypatch):
    """A sweep asks the same probes again in every round and only the exclusion
    grows, so the sub-index and the score matrix are invariant across rounds.
    Rebuilding both for four parameters times four rounds was sixteen times the
    work of doing it once per document and once per parameter."""
    from docpipe.inference import faiss_store, query_cache

    prepared_for = []
    searched = []

    def prepare(conn, index, id_to_pos, document_id, types):
        prepared_for.append(document_id)
        return {"document": document_id}

    def search(prepared, vecs):
        searched.append(len(list(vecs)))
        return [], []

    monkeypatch.setattr(faiss_store, "prepare_document", prepare)
    monkeypatch.setattr(faiss_store, "search_prepared", search)
    monkeypatch.setattr(faiss_store, "rank_prepared",
                        lambda conn, prepared, s, p, k, **kw: [])
    monkeypatch.setattr(query_cache, "get", lambda conn, key: [0.1, 0.2])

    retrieve = runner.make_retrieve(None, None, {}, None)
    retrieve(["a", "b"], 7, set())                 # parameter one, round one
    retrieve(["a", "b"], 7, {("section", 1)})      # round two: same probes
    retrieve(["c"], 7, set())                      # parameter two
    retrieve(["a", "b"], 9, set())                 # next document

    assert prepared_for == [7, 9], "one sub-index per document, not per round"
    assert searched == [2, 1, 2], "round two reuses round one's search"


# --- the search anchor, written from the definition -------------------------

class _StubReply:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {
            "content": content, "reasoning_content": None})()})()]


class _StubClient:
    """Records what it was asked and answers with a fixed reply."""
    def __init__(self, content):
        self.content, self.seen = content, []
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kw):
        self.seen.append(kw)
        return _StubReply(self.content)


def test_the_anchors_are_written_once_per_parameter_not_per_document():
    """The QA app writes a HyDE anchor per question. Here the question is the
    parameter's definition, which does not change between documents — so one
    call each, and a probe string that is stable for the whole corpus is what
    makes the query-embedding cache pay."""
    from docpipe.extraction import runner
    from docpipe.extraction.spec import load

    spec = load({"parameters": [{
        "uri": "OEO_00050016", "label": "Endenergieverbrauch",
        "description": "the energy delivered to and consumed by end users",
        "unit_target": "OEO_00050008", "units_accepted": {"MWh/a": 1.0},
        "axes": {}, "example": {"source": "| x | 5 | MWh/a |",
                                "tuples": [{"value": 5, "unit_raw": "MWh/a"}]}}]})
    client = _StubClient('{"anchors": ["Der Endenergieverbrauch fuer Waerme im '
                         'Stadtgebiet betrug 2022 rund 512 GWh/a.", "zu kurz"]}')
    anchors = runner.make_anchors(spec, client=client)
    assert len(client.seen) == 1, "one call per parameter"
    assert len(anchors["OEO_00050016"]) == 1, "a two-word anchor is no anchor"
    assert "512 GWh/a" in anchors["OEO_00050016"][0]


def test_anchors_that_never_arrive_leave_the_templates_alone():
    """No anchors is not fatal: templates are what this stage searched with
    until now."""
    from docpipe.extraction import runner
    from docpipe.extraction.spec import load

    spec = load({"parameters": [{
        "uri": "OEO_00050016", "label": "Endenergieverbrauch",
        "description": "the energy delivered to and consumed by end users",
        "unit_target": "OEO_00050008", "units_accepted": {"MWh/a": 1.0},
        "axes": {}, "example": {"source": "| x | 5 | MWh/a |",
                                "tuples": [{"value": 5, "unit_raw": "MWh/a"}]}}]})
    assert runner.make_anchors(spec, client=_StubClient("not json")) == {
        "OEO_00050016": []}


def test_an_action_object_is_read_as_code_and_an_answer_is_not():
    from docpipe.extraction import runner

    assert runner._parse_action(
        '{"action": "python", "code": "print(604000 * 0.4)"}'
    ) == "print(604000 * 0.4)"
    assert runner._parse_action('{"tuples": [{"value": 5}]}') is None
    assert runner._parse_action('{"action": "python"}') is None
    assert runner._parse_action(None) is None


# ---------------------------------------------------------------------------
# What one batched request actually sends and reads back
# ---------------------------------------------------------------------------

def test_the_request_labels_every_source_and_carries_what_we_have():
    from docpipe.extraction.pipeline import Batch
    batch = Batch(7, SPEC.parameters[0],
                  [_item(_source("erste", owner_id=1)),
                   _item(_source("zweite", owner_id=2))])
    payload = runner._batch_payload(batch, [
        {"value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a",
         "carrier": "Erdgas", "quote": "| Erdgas | 42.005 |",
         "tier": "text", "provenance": {"page": 3}, "flags": []}])

    assert [s["id"] for s in payload["sources"]] == ["Q1", "Q2"]
    assert [s["text"] for s in payload["sources"]] == ["erste", "zweite"]
    prior = payload["prior"][0]
    assert prior["value"] == 42005 and prior["carrier"] == "Erdgas"
    assert "provenance" not in prior and "tier" not in prior, (
        "prior is there so the model recognises a repeat, nothing else")
    assert "unit_raw" not in prior


def test_a_reply_without_a_status_is_read_as_partial():
    """The conservative reading of silence: there may be more here. A missing
    status must not be taken as 'exhausted', or a truncated reply would close
    a chain that still had values in it."""
    assert runner._parse_reply('{"tuples": []}')["status"] == "partial"
    assert runner._parse_reply(
        '{"tuples": [], "status": "complete"}')["status"] == "complete"
    assert runner._parse_reply("nicht json") is None


def test_need_more_keeps_only_what_can_be_searched_for():
    reply = runner._parse_reply(
        '{"tuples": [], "status": "partial", "need_more": ["Bezugsjahr 2020", "", 7]}')
    assert reply["need_more"] == ["Bezugsjahr 2020"]


# ---------------------------------------------------------------------------
# The answer contract: shared coordinates, and what survives a cut-off reply
# ---------------------------------------------------------------------------

def test_shared_coordinates_are_folded_into_every_tuple():
    """Ten of sixteen keys are identical across a table's tuples, and writing
    them once is half the answer. The model writes them once."""
    reply = runner._parse_reply(json.dumps({
        "defaults": {"source": "Q2", "unit": "kWh/a", "quantity": "final energy "
                     "consumption value", "year": 2020},
        "tuples": [{"value": 1, "carrier": "Erdgas", "quote": "a"},
                   {"value": 2, "carrier": "Heizöl", "quote": "b"}],
        "status": "complete", "need_more": []}, ensure_ascii=False))
    assert [t["unit"] for t in reply["tuples"]] == ["kWh/a", "kWh/a"]
    assert [t["year"] for t in reply["tuples"]] == [2020, 2020]
    assert [t["carrier"] for t in reply["tuples"]] == ["Erdgas", "Heizöl"]


def test_a_tuple_overrides_the_shared_value():
    """The point of defaults is to state the rule once and the exception where
    it happens — the one row in MWh/a among thirty-eight in kWh/a."""
    reply = runner._parse_reply(json.dumps({
        "defaults": {"unit": "kWh/a"},
        "tuples": [{"value": 1, "quote": "a"},
                   {"value": 2, "unit": "MWh/a", "quote": "b"}]}))
    assert [t["unit"] for t in reply["tuples"]] == ["kWh/a", "MWh/a"]


def test_the_evidence_pair_can_never_be_shared():
    """A shared quote would hand every tuple in the reply the same evidence,
    which is the one thing this stage exists to prevent."""
    reply = runner._parse_reply(json.dumps({
        "defaults": {"quote": "geteiltes Zitat", "value": 999,
                     "compute": [{"code": "x"}], "_harvest_failed": True,
                     "unit": "kWh/a"},
        "tuples": [{"value": 1, "quote": "eigenes Zitat"}, {"unit": "MWh/a"}]}))
    assert reply["tuples"][0]["quote"] == "eigenes Zitat"
    assert "quote" not in reply["tuples"][1], "no tuple inherits a quote"
    assert "value" not in reply["tuples"][1]
    assert "compute" not in reply["tuples"][1]
    assert "_harvest_failed" not in reply["tuples"][1]
    assert reply["tuples"][1]["unit"] == "MWh/a"


def _cut_off(n=3, tail='{"value": 44, "unit": "kWh/a", "quan'):
    """A reply shaped like the ones vLLM returns at the token ceiling: whole
    tuples, then a stop in the middle of a key."""
    whole = ", ".join(
        json.dumps({"source": "Q1", "value": i, "quote": f"Zeile {i}"})
        for i in range(n))
    return '{"defaults": {"unit": "kWh/a"}, "tuples": [' + whole + ", " + tail


def test_the_tuples_written_before_the_cut_are_kept():
    reply = runner.rescue_reply(_cut_off())
    assert [t["value"] for t in reply["tuples"]] == [0, 1, 2]
    assert all(t["unit"] == "kWh/a" for t in reply["tuples"]), (
        "the defaults block is rescued too")
    assert reply["status"] == "truncated"


def test_the_rescue_survives_a_quote_whose_braces_do_not_balance():
    """Quotes are lifted verbatim from the plans, and 15 of 1936 sections in
    the pilot set are BibTeX dumps. A brace counter reads those as structure;
    only a real JSON scanner knows which brace is evidence."""
    bib = "@misc{bmj2025, title = {Gesetze / Verordnungen}}"
    text = ('{"tuples": [' + json.dumps({"value": 1, "quote": bib})
            + ', ' + json.dumps({"value": 2, "quote": "} allein {"})
            + ', {"value": 3, "quo')
    reply = runner.rescue_reply(text)
    assert [t["value"] for t in reply["tuples"]] == [1, 2]
    assert reply["tuples"][0]["quote"] == bib


def test_the_rescue_survives_escapes_brackets_and_newlines_in_a_quote():
    quote = ('| Wärmeverbrauch [kWh/a] | 4.605 |\n| --- |\n'
             r'Er nennt sie "Wärmenetze" und schreibt \| als Trenner')
    text = ('{"tuples": [' + json.dumps({"value": 1, "quote": quote},
                                        ensure_ascii=False) + ', {"val')
    reply = runner.rescue_reply(text)
    assert reply["tuples"][0]["quote"] == quote


def test_a_cut_before_the_first_tuple_is_not_a_rescue():
    assert runner.rescue_reply('{"defaults": {"unit": "kWh/a"}, "tuples": [{"val') is None
    assert runner.rescue_reply("kein json") is None


def test_the_sources_after_the_cut_stay_countable_holes():
    """A rescue must not trade a loud hole for a silent one: the model writes
    in source order, so the loss is always the tail of the batch, and those
    sources would otherwise read as 'looked at, found nothing'."""
    from docpipe.extraction.pipeline import Batch
    batch = Batch(7, SPEC.parameters[0],
                  [_item(_source("a", owner_id=i)) for i in range(1, 5)])
    holes = runner._holes(batch, [{"source": "Q1", "value": 1},
                                  {"source": "Q2", "value": 2}])
    assert [h["source"] for h in holes] == ["Q3", "Q4"]
    assert all(h["_harvest_failed"] and h["_cut_off"] for h in holes)


def test_a_truncated_reply_is_not_retried(monkeypatch):
    """Measured 31 times over one pilot: five attempts, five identical
    truncations, zero recoveries. The loop must stop after the first."""
    import openai
    attempts = []

    class Message:
        content = _cut_off()
        reasoning_content = None

    class Choice:
        finish_reason = "length"
        message = Message()

    class Client:
        def __init__(self, **kw):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            attempts.append(kw)
            return type("R", (), {"choices": [Choice()], "usage": None})()

    monkeypatch.setattr(openai, "OpenAI", Client)
    monkeypatch.setattr(runner.prompts, "load",
                        lambda _id: type("P", (), {"text": "sys", "meta": {}})())
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)

    harvest = runner.make_harvester(None)
    reply = harvest(_chain(_item(_source("x")))[0], [])
    assert len(attempts) == 1, f"{len(attempts)} Versuche fuer einen Abbruch"
    assert [t["value"] for t in reply["tuples"] if "value" in t] == [0, 1, 2]


# What the served model can hold. vLLM reported max_seq_len=32768 for the
# 122B this stage runs against, and --max-model-len above it is refused at
# startup — so a budget over this is not a tuning question, it is a run that
# never begins.
SERVED_WINDOW = 32768

# For the sizing assertion below. A source that yields at all yields 12 tuples
# at the 90th percentile, measured over the finished pilots. Characters per
# token came out of the truncated replies directly: they stopped at exactly
# max_tokens, so content length over max_tokens is the measurement, and it
# came out between 2.62 and 2.82 — the low end is the conservative one.
P90_TUPLES_PER_SOURCE = 12
CHARS_PER_TOKEN = 2.62


def _profile_specs():
    """Every profile that has an extraction spec, as (name, Spec, prompt)."""
    import json
    import os
    from pathlib import Path
    from docpipe.extraction.spec import load as load_spec
    root = Path(__file__).resolve().parent.parent / "profiles"
    for spec_file in sorted(root.glob("*/extraction_spec.json")):
        name = spec_file.parent.name
        os.environ["DOCPIPE_PROFILE"] = name
        yield (name,
               load_spec(json.loads(spec_file.read_text(encoding="utf-8"))),
               runner.prompts.load("extraction/harvest"))


def test_every_profile_fits_the_window_it_will_be_served(monkeypatch):
    """The test that was missing. max_tokens lives in a prompt's frontmatter
    and BATCH_SOURCES lives in this module, and until a pilot burned five GPUs
    nothing had ever compared them. The job script serves
    max(context_budget, 32768) as --max-model-len, so a budget over the
    model's own ceiling is a server that refuses to start."""
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    checked = 0
    for name, spec, prompt in _profile_specs():
        budget = runner.context_budget(prompt, spec)
        assert budget <= SERVED_WINDOW, (
            f"{name}: budget {budget} over the {SERVED_WINDOW} the model holds")
        assert budget > int(prompt.meta["max_tokens"]), (
            f"{name}: the answer cannot be the whole request")
        checked += 1
    assert checked >= 2, "the profiles stopped being found"


def test_the_answer_budget_covers_a_full_batch(monkeypatch):
    """The other half of the same pairing: a request that reads
    BATCH_SOURCES sources has to be allowed to answer for all of them. At one
    source per request 4096 was already marginal; at six it was the defect
    that killed a pilot."""
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    for name, spec, prompt in _profile_specs():
        fitted = runner.fit_batch_sources(prompt, spec)
        assert fitted >= 1, f"{name}: not even one source fits the answer budget"
        # Sizing is the profile's own: the spec's example IS the contract the
        # prompt shows the model, so a batch that fits it is a batch the model
        # can finish answering for.
        assert fitted <= runner.BATCH_SOURCES
        if fitted < runner.BATCH_SOURCES:
            # It fits because it was made to. Check the next size up really
            # does not, or the clamp is just pessimism.
            bigger = runner.fit_batch_sources(prompt, spec, wanted=fitted + 1)
            assert bigger == fitted, f"{name}: the clamp is too tight"


def test_the_computed_switch_can_never_be_shared():
    """`computed` is not a coordinate but a switch: it decides WHICH evidence
    check applies, letting the value be absent from its own quote as long as
    the sandbox printed it. Shared across a reply it would open that door for
    every tuple in it — and a table whose rows are all computed is exactly
    the case the defaults block was written for."""
    reply = runner._parse_reply(json.dumps({
        "defaults": {"computed": True, "unit": "kWh/a"},
        "tuples": [{"value": 1, "quote": "a"}]}))
    assert "computed" not in reply["tuples"][0]
    assert reply["tuples"][0]["unit"] == "kWh/a"


def test_the_holes_are_the_tail_of_the_batch_not_the_unlabelled_sources():
    """Under the defaults contract `source` is one of the keys stated once
    for the whole reply, so every rescued tuple carries the same label.
    Reading it would report five of six sources as never answered, and could
    never report the one the block names — even when the cut hit it first."""
    from docpipe.extraction.pipeline import Batch
    batch = Batch(7, SPEC.parameters[0],
                  [_item(_source("a", owner_id=i)) for i in range(1, 7)])
    rescued = runner._parse_reply(json.dumps({
        "defaults": {"source": "Q3"},
        "tuples": [{"value": 1, "quote": "a"}, {"value": 2, "quote": "b"}]}))
    holes = runner._holes(batch, rescued["tuples"])
    assert [h["source"] for h in holes] == ["Q4", "Q5", "Q6"], (
        "Q1 to Q3 were reached; the loss is what comes after")


# ---------------------------------------------------------------------------
# The heading the model could read but not cite
# ---------------------------------------------------------------------------

def test_the_caption_joins_the_text_the_quote_is_checked_against():
    """A unit, a year or a scenario printed only in a caption was visible to
    the model and quotable by nobody: _batch_payload sends it as its own
    field, the verifier only ever saw the transcription. Measured on this
    corpus, a table's caption is absent from its markdown 98.6% of the time
    and 15992 captions carry a year."""
    source = runner._source_of({
        "owner_kind": "table", "owner_id": 5,
        "title": "Tabelle 12: Endenergieverbrauch 2035 im Zielszenario [MWh/a]",
        "text": "| Erdgas | 42.005 |", "page_number": 7})
    assert source.text.startswith("Tabelle 12:")
    assert "| Erdgas | 42.005 |" in source.text
    assert source.body == "| Erdgas | 42.005 |", (
        "the repair still works from the transcription alone")


def test_a_heading_already_in_the_text_is_not_repeated():
    source = runner._source_of({
        "owner_kind": "section", "owner_id": 5, "title": "5.2 Zielszenario",
        "text": "5.2 Zielszenario\n\nDer Bedarf sinkt.", "page_number": 7})
    assert source.text.count("5.2 Zielszenario") == 1
    assert source.body is None, "nothing was prefixed, so there is nothing to strip"


def test_the_repair_stays_unambiguous_when_the_caption_repeats_a_number():
    """The one regression the joining could cause: the repair rests on the
    value occurring exactly once, and 1.9% of table numbers also appear in
    their own caption. It reads the transcription, so it still does."""
    from docpipe.extraction.pipeline import Source, WorkItem, DocumentReport, fold_claims

    source = Source("table", 5, "Waermebedarf 42.005 MWh/a\n| Erdgas | 42.005 |",
                    {"page": 7}, body="| Erdgas | 42.005 |")
    report = DocumentReport(document_id=7)
    fold_claims(WorkItem(7, SPEC.parameters[0], source),
                [{"value": 42005, "unit": "MWh/a", "unit_raw": "MWh/a",
                  "carrier": "Erdgas", "quote": "Erdgas 42.005 MWh"}], report)
    assert report.tuples, [r["reason"] for r in report.refusals]
    assert "quote_repaired" in report.tuples[0]["flags"]


def test_a_document_the_server_never_answered_for_is_not_stamped(tmp_path, monkeypatch):
    """The failure that could cost a whole overnight run: a dead server makes
    every request fail the same way, every document comes back all sentinels,
    and stamping those writes up to a thousand empty documents down as
    finished. The resume then skips every one of them without a word."""
    monkeypatch.setattr(runner.prompts, "versions", lambda ids: {i: "v1" for i in ids})
    from docpipe.extraction.pipeline import DocumentReport

    def report_with(why):
        report = DocumentReport(document_id=7)
        report.owners_harvested = 4
        report.refusals = [
            {"parameter": "p", "reason": "value is not a number",
             "claim": {"_harvest_failed": True, "_why": why}, "owner": ["section", i]}
            for i in range(4)]
        return report

    runner.finish_document(report_with("unreachable"), "tot", tmp_path, "sha")
    assert (tmp_path / "tot.jsonl").is_file(), "the holes are still written down"
    assert not (tmp_path / "tot.stamp.json").exists(), (
        "an unreachable server must not mark the document harvested")

    runner.finish_document(report_with("no_answer"), "stumm", tmp_path, "sha")
    assert (tmp_path / "stumm.stamp.json").is_file(), (
        "a model that answered nothing IS a harvest, and redoing it forever "
        "is the other way to lose a run")


def test_the_anchors_are_frozen_so_a_restart_searches_the_same_way(tmp_path, monkeypatch):
    """Two calls in one job shared 0 of 18 anchor strings. The anchors decide
    which passages the corpus is harvested from, so a restart searching
    differently is a corpus nobody can say the provenance of."""
    monkeypatch.setattr(runner.prompts, "versions", lambda ids: {i: "v1" for i in ids})
    monkeypatch.setattr(runner.prompts, "load",
                        lambda _id: type("P", (), {"text": "sys", "meta": {}})())
    calls = []

    class Client:
        def __init__(self, **kw):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            calls.append(kw)
            body = json.dumps({"anchors": [f"Ein Satz wie er im Plan stuende {len(calls)}"]})
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {"content": body})()})()]})()

    import openai
    monkeypatch.setattr(openai, "OpenAI", Client)
    store, key = tmp_path / "anchors.json", runner.anchors_key("sha")

    first = runner.make_anchors(SPEC, store=store, key=key)
    assert len(calls) == 1 and first[SPEC.parameters[0].uri]
    second = runner.make_anchors(SPEC, store=store, key=key)
    assert second == first, "a restart must search with the same anchors"
    assert len(calls) == 1, "and must not pay for them twice"

    assert runner.make_anchors(SPEC, store=store, key="anderer-schluessel") != first, (
        "a new spec, prompt or model is a new anchor set")


def test_the_page_rectangles_can_be_switched_off(monkeypatch, tmp_path):
    """They say where on the page a quote sits, never whether a value is
    accepted. A corpus run died of "stack smashing detected" inside MuPDF
    after 204 documents; being able to finish without the boxes is the
    difference between a night's work and none."""
    monkeypatch.setenv("EXTRACT_LOCATE", "0")
    assert runner.make_locate(tmp_path / "x.db", tmp_path) is None
    monkeypatch.setenv("EXTRACT_LOCATE", "1")
    assert runner.make_locate(tmp_path / "x.db", tmp_path) is not None


@pytest.mark.parametrize("raw,expect", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    # The shapes the greedy {.*} span could not read. Both looked well formed
    # in the log and were dropped: a second object after the answer, and a
    # sentence after it that happens to end in a brace.
    ('{"a": 1}{"b": 2}', {"a": 1}),
    ('{"a": 1}\nDas war die Antwort (siehe oben) {Ende}', {"a": 1}),
    ('Hier ist das Ergebnis: {"a": 1} — fertig.', {"a": 1}),
    ('{"a": 1', None),
    ('gar kein json', None),
])
def test_one_object_is_read_and_trailing_anything_is_not(raw, expect):
    assert runner._loads_object(raw) == expect


def test_an_unreadable_reply_is_sent_back_with_the_reason(monkeypatch):
    """A model error goes to the model, like a verification failure does.

    Retrying a malformed reply without saying what was malformed is one
    attempt three times.
    """
    from docpipe.extraction import fields
    seen = []

    class _Msg:
        def __init__(self, content):
            self.content = content
            self.reasoning_content = ""

    class _Choice:
        def __init__(self, content):
            self.message = _Msg(content)
            self.finish_reason = "stop"

    class _Resp:
        def __init__(self, content):
            self.choices = [_Choice(content)]
            self.usage = None

    replies = iter(["kein json", '{"answers": {}}'])

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    seen.append(kw["messages"])
                    return _Resp(next(replies))

    monkeypatch.setattr(runner, "_client", lambda: _Client())
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    ask = runner.make_field_asker()
    slot = fields.Slot(name="year", kind=fields.NUMBER, question="Welches Jahr?")
    out = ask([], [], slot)
    assert out == {"answers": {}}
    assert len(seen) == 2, "it has to try again"
    followup = seen[1][-1]
    assert followup["role"] == "user"
    assert "JSON" in followup["content"], "the retry must say what was wrong"


def test_the_unreadable_diagnostic_shows_the_end_and_marks_the_cut():
    """The tail is the half that matters, and an unmarked cut misleads.

    This line used to print the first 160 characters and stop, so a JSON
    string that was merely long ended mid-word with no sign of why — and a
    reply that was cut off read as a reply whose quote had run into the next
    log field. The defect it is meant to expose lives at the end.
    """
    class _M:
        content = '{"answers": {"R1": {"quote": "' + "x" * 900 + '"}}'
        reasoning_content = ""

    class _R:
        message = _M()
        finish_reason = "stop"

    runner._UNPARSABLE_SHOWN = 0
    line = runner._unparsable(_R())
    assert f"content {len(_M.content)}ch" in line
    assert "weitere" in line, "the cut has to be marked"
    assert _M.content[-40:] in line, "the end of the reply has to be visible"
