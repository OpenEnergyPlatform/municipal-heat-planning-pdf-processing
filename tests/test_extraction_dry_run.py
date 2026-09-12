"""The whole harvest, with the model stubbed and nothing else.

This is the check that was missing. A pilot on five GPUs was the first place
four separate defects showed up — a batch size sized in one file against a
token budget sized in another, a chain that made itself the unit of
scheduling, a `computed` flag that could be shared across a whole reply, and
holes counted from a label the contract had just moved. Every one of them is
visible in a run that touches no GPU at all.

So: the real spec, the real prompt frontmatter, the real group_items,
harvest_batches, route_claims, verify_tuple and fold_batch. What is stubbed
is the model, and it answers the only thing we know to be a correct answer —
the profile's own example, which is what the prompt shows it. Retrieval is
stubbed too, because the sources are the example's own text.

Seconds, no GPU, no database. It belongs in front of every sbatch.
"""
import json
import threading
from pathlib import Path

import pytest

from docpipe.extraction import runner
from docpipe.extraction.pipeline import (Source, WorkItem, fold_batch,
                                         group_items, DocumentReport)
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _profiles():
    return sorted(p.parent.name for p in PROFILES.glob("*/extraction_spec.json"))


@pytest.fixture(params=_profiles())
def profile(request, monkeypatch):
    """One profile's real spec and real harvest prompt."""
    monkeypatch.setenv("DOCPIPE_PROFILE", request.param)
    spec_file = PROFILES / request.param / "extraction_spec.json"
    spec = load_spec(json.loads(spec_file.read_text(encoding="utf-8")))
    return request.param, spec, runner.prompts.load("extraction/harvest")


def _batches(spec, sources_per_parameter=8):
    """Work for every parameter, each source being its example's own text."""
    items = []
    for index, parameter in enumerate(spec.parameters):
        text = (parameter.example or {}).get("source") or ""
        for n in range(sources_per_parameter):
            owner = index * 100 + n
            items.append(WorkItem(7, parameter, Source(
                "table", owner, text, {"document_id": 7, "page": n})))
    return group_items(items, max_sources=runner.BATCH_SOURCES)


def _document_batches(spec, sources=8):
    """Work the way a document-level plan produces it: no parameter fixed.

    `_batches` above fixes one, which is what the plan did until the parameter
    became a coordinate. Keeping only that shape is how this gate passed while
    the corpus path crashed on its first batch: the scheduler keyed its sweeps
    through `batch.parameter.uri`, and there is no parameter to key through.
    """
    text = (spec.parameters[0].example or {}).get("source") or ""
    items = [WorkItem(7, None, Source("table", n, text,
                                      {"document_id": 7, "page": n}))
             for n in range(sources)]
    return group_items(items, max_sources=runner.BATCH_SOURCES)


def _answer(parameter, label):
    """The example, in the shape the prompt asks the model to write it."""
    example = parameter.example or {}
    defaults = dict(example.get("defaults") or {})
    defaults["source"] = label
    return {"defaults": defaults, "tuples": [dict(t) for t in example["tuples"]],
            "status": "complete", "need_more": []}


def test_every_example_survives_its_own_round_trip(profile):
    """The example goes out as the prompt describes it and comes back through
    the real parser, router and verifier. Anything the contract broke — a key
    that may not be shared, a label the router cannot resolve — shows here."""
    name, spec, _prompt = profile
    report = DocumentReport(document_id=7)
    for batch in _batches(spec, sources_per_parameter=2):
        reply = runner._parse_reply(json.dumps(
            _answer(batch.parameter, batch.label(0)), ensure_ascii=False))
        fold_batch(batch, reply, report)
    assert report.tuples, f"{name}: the profile's own example verified to nothing"
    assert not report.refusals, (
        f"{name}: the example is refused by the verifier: "
        f"{[r['reason'] for r in report.refusals][:3]}")


def test_moving_a_key_into_defaults_changes_no_verdict(profile):
    """The whole point of the defaults block is that it is a shorter way to
    say the same thing. If any key changes a verdict by moving, it is not a
    coordinate and does not belong there."""
    _name, spec, _prompt = profile
    for parameter in spec.parameters:
        example = parameter.example or {}
        tuples = [dict(t) for t in example["tuples"]]
        shared = dict(example.get("defaults") or {})
        flat = runner.expand_defaults(shared, [dict(t) for t in tuples])
        for key in sorted({k for t in flat for k in t}):
            values = {json.dumps(t.get(key), sort_keys=True) for t in flat}
            if len(values) != 1 or key in runner.NOT_DEFAULTABLE:
                continue
            moved = runner.expand_defaults(
                {**shared, key: flat[0][key]},
                [{k: v for k, v in t.items() if k != key} for t in tuples])
            assert moved == flat, (
                f"{parameter.uri}: moving {key!r} into defaults changed the tuples")


def test_a_truncated_reply_yields_nothing_at_all(profile):
    """The rescue read the tuples written before the cut and called the rest
    holes. Nothing of a cut-off reply is read any more: it is asked again
    over fewer passages, and only what a whole reply says is harvested."""
    _name, spec, _prompt = profile
    batch = _batches(spec)[0]
    whole = json.dumps(_answer(batch.parameter, batch.label(0)),
                       ensure_ascii=False)
    cut = whole[:whole.rindex("}", 0, whole.rindex("}"))]      # mid-last-tuple
    assert runner._parse_reply(cut) is None


def test_the_run_uses_the_server_it_was_given(profile):
    """The defect that killed a pilot: a chain became the unit of scheduling,
    so a single-document run put three requests to a server sized for two
    hundred. A batch is the unit, and every batch is in flight at once."""
    _name, spec, _prompt = profile
    batches = _batches(spec, sources_per_parameter=8)
    want = min(8, len(batches))
    gate = threading.Barrier(want, timeout=10)
    through = []

    def harvest(batch, prior=None):
        try:
            gate.wait()
            through.append(batch)
        except threading.BrokenBarrierError:
            pass
        return _answer(batch.parameter, batch.label(0))

    runner.harvest_batches(batches, harvest, workers=16)
    assert len(through) >= want, (
        f"only {len(through)} of {len(batches)} batches shared the server")


def test_the_answer_budget_and_the_batch_size_agree(profile):
    """Two numbers in two files that nobody compared until a pilot burned
    five GPUs on the disagreement."""
    name, spec, prompt = profile
    budget = runner.context_budget(prompt, spec)
    assert budget <= 32768, (
        f"{name}: a request needs {budget} tokens, more than the model holds")
    assert runner.fit_batch_sources(prompt, spec) >= 1, (
        f"{name}: max_tokens cannot answer for even one source")


def test_the_corpus_path_runs_the_shape_the_plan_really_produces(profile):
    """The gate has to see what the run sees. A batch that fixes no parameter
    is what every plan builds now, and the parallel scheduler is where it goes
    — the two places a stub can quietly agree with itself instead of with the
    corpus."""
    _name, spec, _prompt = profile
    batches = _document_batches(spec)
    assert batches and all(b.parameter is None for b in batches)

    def harvest(batch, prior=None):
        return {"tuples": [], "status": "complete", "need_more": []}

    answered = runner.harvest_batches(batches, harvest, workers=8)
    assert len(answered) == len(batches)
    assert all(reply.get("status") == "complete" for _b, reply in answered), (
        "a batch that raised comes back as a failure sentinel, which is how "
        "this crash looked like a harvest that found nothing")
