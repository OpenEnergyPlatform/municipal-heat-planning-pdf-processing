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

Seconds, no GPU, no database. It belongs in front of every GPU run.
"""
import json
import threading
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import (Source, WorkItem, fold_batch,
                                         group_items, DocumentReport)
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _profiles():
    return sorted(p.parent.name for p in PROFILES.glob("*/extraction_spec.json"))


@pytest.fixture(params=_profiles())
def profile(request, monkeypatch):
    """One profile's real spec, and whether it names frame axes, which decides
    if its harvest sends a frame request."""
    monkeypatch.setenv("DOCPIPE_PROFILE", request.param)
    spec_file = PROFILES / request.param / "extraction_spec.json"
    spec = load_spec(json.loads(spec_file.read_text(encoding="utf-8")))
    framed = bool(fields.frame_slots(
        spec, load_profile(request.param).component("extraction", "FRAME")
        or ()))
    return request.param, spec, framed


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
    name, spec, _framed = profile
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
    _name, spec, _framed = profile
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
    _name, spec, _framed = profile
    batch = _batches(spec)[0]
    whole = json.dumps(_answer(batch.parameter, batch.label(0)),
                       ensure_ascii=False)
    cut = whole[:whole.rindex("}", 0, whole.rindex("}"))]      # mid-last-tuple
    assert runner._parse_reply(cut) is None


def test_the_run_uses_the_server_it_was_given(profile):
    """The defect that killed a pilot: a chain became the unit of scheduling,
    so a single-document run put three requests to a server sized for two
    hundred. A batch is the unit, and every batch is in flight at once."""
    _name, spec, _framed = profile
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
    name, spec, framed = profile
    budget = runner.request_budget(spec, framed)
    # The job serves the larger of the budget and 32768. kwp stays inside
    # that; a profile above it widens the window, up to the ceiling
    # test_extraction_runner.py states.
    limit = 32768 if name == "kwp" else 40960
    assert budget <= limit, (
        f"{name}: a request needs {budget} tokens, more than the {limit} "
        f"this profile may ask the job to serve")
    assert runner.batch_sources_for(spec) >= 1, (
        f"{name}: max_tokens cannot answer for even one source")


def test_the_corpus_path_runs_the_shape_the_plan_really_produces(profile):
    """The gate has to see what the run sees. A batch that fixes no parameter
    is what every plan builds now, and the parallel scheduler is where it goes
    — the two places a stub can quietly agree with itself instead of with the
    corpus."""
    _name, spec, _framed = profile
    batches = _document_batches(spec)
    assert batches and all(b.parameter is None for b in batches)

    def harvest(batch, prior=None):
        return {"tuples": [], "status": "complete", "need_more": []}

    answered = runner.harvest_batches(batches, harvest, workers=8)
    assert len(answered) == len(batches)
    assert all(reply.get("status") == "complete" for _b, reply in answered), (
        "a batch that raised comes back as a failure sentinel, which is how "
        "this crash looked like a harvest that found nothing")


def test_the_lists_a_document_closes_reach_its_requests_and_their_check(
        profile, monkeypatch):
    """A list that exists only per document (`dynamic`) is filled by the
    plan. The requests that read the passages and the check of their answers
    have to see the same list: built from the run's spec they offered
    nothing, and the model wrote a wording on exactly the fields whose point
    is the choice. No error anywhere, which is why it has to be looked for
    here."""
    from docpipe.extraction import fields
    _name, spec, _framed = profile
    lists = {}
    for parameter in spec.parameters:
        if parameter.vocabulary_dynamic:
            lists[parameter.uri] = {"x:entry": ["an entry of this document"]}
        for axis_name, axis in parameter.axes.items():
            if axis.dynamic:
                lists[axis_name] = {"x:entry": ["an entry of this document"]}
    if not lists:
        pytest.skip("this profile closes no list per document")
    filled = runner.fill_dynamic_axes(spec, lists)
    assert filled.parameter_question == spec.parameter_question
    assert filled.unit_question == spec.unit_question
    carrier = next(p for p in spec.parameters
                   if any(a.dynamic for a in p.axes.values()))
    axis_name = next(n for n, a in carrier.axes.items() if a.dynamic)
    example = carrier.example
    first = dict(example["tuples"][0])
    quote = first["quote"]
    batch = group_items([WorkItem(7, None, Source(
        "section", 1, example["source"], {"document_id": 7, "page": 1}))],
        max_sources=runner.BATCH_SOURCES)[0]
    batch.spec = filled
    assert "an entry of this document" in json.dumps(
        runner._batch_payload(batch, [], runner.spec_of(batch, spec)),
        ensure_ascii=False), "the value request offers the document's list"

    rows_reply = {"tuples": [{"source": "Q1", "value": first["value"],
                              "value_raw": first.get("value_raw",
                                                     first["value"]),
                              "quote": quote}],
                  "status": "complete", "need_more": []}
    offered = {}
    monkeypatch.setattr(runner, "make_harvester",
                        lambda *a, **kw: (lambda batch, prior=None: rows_reply))

    def make_asker(image_root=None, **kw):
        def ask(shown, rows, slots, corrections=None, document_id=None,
                usage_out=None, owner_of=None, bases=None):
            slots = slots if isinstance(slots, (list, tuple)) else [slots]
            out = {}
            for slot in slots:
                offered[slot.name] = (slot.question,
                                      [o.label for o in slot.options])
                value = (carrier.label if slot.name == "parameter"
                         else "a name the list does not hold")
                # The wording is the row's own, which its quote prints.
                out[slot.name] = {"answers": {row.label: {
                    "value": value, "value_raw": rows_reply["tuples"][0][
                        "value_raw"], "quote": quote} for row in rows}}
            return {"fields": out}
        return ask

    monkeypatch.setattr(runner, "make_field_asker", make_asker)
    reply = runner.make_fieldwise_harvester(spec=spec)(batch)
    assert offered["parameter"][0] == spec.parameter_question
    assert offered[axis_name][1] == ["an entry of this document"]
    report = DocumentReport(7)
    fold_batch(batch, reply, report, spec=runner.spec_of(batch, spec))
    row, = report.tuples
    assert row["parameter"] == carrier.uri
    assert row.get(axis_name) is None, "no entry of the list, so no choice"
    assert row[f"{axis_name}_state"] == fields.UNBACKED
