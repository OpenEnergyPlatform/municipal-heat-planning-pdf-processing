"""The runner's pure parts: reply parsing, staleness, resume."""
import json

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


def test_parameter_payload_flattens_vocab_to_labels_only():
    """The model chooses among corpus labels; URIs are the verifier's side."""
    payload = _parameter_payload(SPEC.parameters[0])
    assert payload["axes"]["carrier"] == {"labels": ["Erdgas", "Gas"]}
    assert "example" in payload and payload["units_accepted"] == ["MWh/a"]


def test_everything_is_stale_without_a_stamp(tmp_path):
    assert stale(tmp_path / "none.json", {"a": "1"}) == ["a"]


def test_only_the_changed_version_is_stale(tmp_path):
    stamp = tmp_path / "s.json"
    stamp.write_text(json.dumps({"a": "1", "b": "2"}), encoding="utf-8")
    assert stale(stamp, {"a": "1", "b": "2"}) == []
    assert stale(stamp, {"a": "1", "b": "NEW"}) == ["b"]


def test_run_document_writes_then_skips_then_redoes_on_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    calls = []

    def retrieve(query, document_id, exclude):
        return [] if ("table", 1) in exclude else \
            [Source("table", 1, "| Erdgas | 42.005 | MWh/a |", {"page": 3})]

    def harvest(source, parameter):
        calls.append(source.owner_id)
        return [{"value": 42005, "unit_raw": "MWh/a", "carrier": "Erdgas",
                 "quote": "Erdgas | 42.005"}]

    deps = {"retrieve": retrieve, "harvest": harvest}
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


def test_a_source_the_model_never_answered_is_a_visible_hole(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})

    def retrieve(query, document_id, exclude):
        return [] if ("table", 1) in exclude else \
            [Source("table", 1, "| Erdgas | 42.005 |", {"page": 3})]

    deps = {"retrieve": retrieve,
            "harvest": lambda s, p: [{"_harvest_failed": True}]}
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
