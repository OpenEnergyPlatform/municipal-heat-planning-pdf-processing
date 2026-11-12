"""The rules of the record of a run, its archive, the check before a run and
the passes after it decide, each read at the time of use (owner decision
2026-11-11).

The promises, each with a case that breaks it by construction:

1. A trace is written, and in the form, the rules say: off, nothing is
   written; plain, not compressed; times to the places the rule says; a text
   is referred to only above the length the rule says; and a step that asks
   may set that its own requests are not recorded.
2. Every file a run replaces or deletes goes through `archive.keep` first,
   AND the check that says so finds a place that does not (a synthetic
   source that writes without it), AND the review's working list and the
   stamps a recheck deletes are kept (owner decision 2026-10-22).
3. The check before a run derives its prompts from the flow's steps that are
   on, checks no anchor, and does what the rules say of each check: fail,
   warn or off, and of a check that cannot run.
4. Each pass does what its rules say: which states stay, in what order,
   what a refused row becomes, which class a wording maps to, what a
   recheck drops, which rows and fields a second reading asks.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import (archive, fields, preflight, recheck, remap,
                                review, stats, survey, topup, topup_parameter,
                                topup_rest, trace)
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import Refusal

ROOT = Path(__file__).resolve().parent.parent
SPEC = load_spec(json.loads(
    (ROOT / "profiles" / "kwp" / "extraction_spec.json")
    .read_text(encoding="utf-8")))
PARAMETER = SPEC.by_uri["energy_consumption"]
SLOTS = {s.name: s for s in fields.axis_slots(PARAMETER)}
STEP = {"id": "ask", "box": "coord"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("EXTRACT_TRACE", raising=False)
    monkeypatch.delenv("EXTRACT_SHOW_UNPARSABLE", raising=False)
    rules.reset()
    yield
    rules.reset()


def at(**values):
    return rules.in_step(rules.stepped(STEP, values))


# -- 1. the trace --

@pytest.fixture
def traced(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "_root", None)
    monkeypatch.setattr(trace, "_name_of", None)
    folder = tmp_path / "trace"
    yield folder
    trace.close()


def written(folder):
    trace.close()
    return sorted(p.name for p in folder.iterdir() if p.is_file())


def events(folder, kinds=None):
    trace.close()
    return [e for p in trace.files(folder) for e in trace.lines(p, kinds)]


def test_the_standard_writes_a_compressed_trace(traced):
    trace.open_trace(traced, lambda i: f"d{i}")
    trace.event("plan", 1, n=1)
    assert written(traced) == ["d1" + trace.SUFFIX]
    assert [e["n"] for e in events(traced, ["plan"])] == [1]


def test_a_trace_that_is_off_writes_nothing(traced):
    with rules.overlaid(trace_on=False):
        trace.open_trace(traced, lambda i: f"d{i}")
        trace.event("plan", 1, n=1)
    assert not traced.exists() or written(traced) == []


def test_the_setting_of_the_start_turns_the_trace_off(traced, monkeypatch):
    monkeypatch.setenv("EXTRACT_TRACE", "0")
    rules.reset()
    assert rules.get("trace_on") is False
    trace.open_trace(traced, lambda i: f"d{i}")
    trace.event("plan", 1, n=1)
    assert not traced.exists()


def test_a_plain_trace_is_read_like_a_compressed_one(traced):
    with rules.overlaid(trace_compress=False):
        trace.open_trace(traced, lambda i: f"d{i}")
        trace.event("plan", 1, n=7)
        assert written(traced) == ["d1" + trace.PLAIN]
    assert [e["n"] for e in events(traced, ["plan"])] == [7]


def request():
    return {"model": "m", "messages": [{"role": "user", "content": "q" * 50}]}


def reported(folder, **rule_values):
    """The event a request is reported by, under *rule_values*."""
    with rules.overlaid(**rule_values):
        trace.open_trace(folder, lambda i: f"d{i}")
        trace.exchanged(request(), error=ValueError("boom"),
                        times=(10.123456, 10.234567, 10.345678))
        trace.event("error", 1, kind="exception")
        return events(folder, ["error"])[0]


def test_times_are_rounded_to_the_places_the_rule_says(traced):
    assert reported(traced)["asked_at"] == 10.123
    trace.close()
    other = traced.parent / "other"
    assert reported(other, trace_time_places=5)["asked_at"] == 10.12346


def test_a_text_is_referred_to_only_above_the_length_the_rule_says(traced):
    sent = trace.sent(reported(traced), trace.pieces_of(
        e for p in trace.files(traced) for e in trace.lines(p)))
    assert sent["messages"][0]["content"] == "q" * 50
    trace.close()
    event = reported(traced.parent / "other", trace_piece_min_chars=1000)
    assert event["input"]["messages"][0]["content"] == "q" * 50


def test_the_standard_refers_to_a_long_text_once(traced):
    event = reported(traced)
    assert "piece" in event["input"]["messages"][0]["content"]


def test_a_step_that_does_not_record_its_requests_records_none(traced):
    trace.open_trace(traced, lambda i: f"d{i}")
    with at(trace_requests=False):
        trace.exchanged(request(), error=ValueError("boom"))
    trace.event("error", 1, kind="exception")
    assert "input" not in events(traced, ["error"])[0]
    trace.close()
    other = traced.parent / "other"
    trace.open_trace(other, lambda i: f"d{i}")
    with at(trace_requests=True):
        trace.exchanged(request(), error=ValueError("boom"))
    trace.event("error", 1, kind="exception")
    assert "input" in events(other, ["error"])[0]


# -- 2. the archive --

def test_a_file_is_kept_before_it_is_replaced(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text("first", encoding="utf-8")
    kept = archive.keep(path)
    assert kept is not None and kept.read_text(encoding="utf-8") == "first"


def test_a_run_that_does_not_archive_keeps_nothing(tmp_path):
    path = tmp_path / "b.jsonl"
    path.write_text("first", encoding="utf-8")
    with rules.overlaid(archive_before_replace=False):
        assert archive.keep(path) is None
    assert not (tmp_path / archive.ARCHIVE).exists()


DESTROYS = {"replace", "rename", "unlink", "write_text", "write_bytes"}
OF_THE_HARVEST = ("trace", "stats", "preflight", "topup", "topup_rest",
                  "topup_parameter", "remap", "recheck", "review", "survey",
                  "found")


def unkept(source: str) -> list:
    """What *source* replaces, deletes or writes over without a call of
    `keep` on the same file in the same function: ["function: target"]. A
    temporary file written under the name `tmp` is new and replaces
    nothing; what it is moved onto does."""
    out = []
    for func in ast.walk(ast.parse(source)):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kept, destroyed = set(), []
        for call in (n for n in ast.walk(func) if isinstance(n, ast.Call)):
            if not isinstance(call.func, ast.Attribute) and not (
                    isinstance(call.func, ast.Name)
                    and call.func.id == "open"):
                continue
            named = isinstance(call.func, ast.Attribute)
            name = call.func.attr if named else "open"
            receiver = ast.unparse(call.func.value) if named else ""
            first = ast.unparse(call.args[0]) if call.args else ""
            if name == "keep":
                kept.add(first)
            elif name in ("write_text", "write_bytes"):
                if receiver != "tmp":
                    destroyed.append(receiver)
            elif name == "unlink":
                destroyed.append(receiver)
            elif name in ("replace", "rename") and len(call.args) == 1:
                destroyed.append(first)           # str.replace has two
            elif name == "open":
                modes = [a.value for a in call.args[:2]
                         if isinstance(a, ast.Constant)
                         and isinstance(a.value, str)] + [
                    k.value.value for k in call.keywords if k.arg == "mode"]
                path_open = named and call.args and isinstance(
                    call.args[0], ast.Constant)       # path.open("w")
                if any(m[:1] in "wax" for m in modes[:1] if m):
                    destroyed.append(receiver if path_open else first)
        for target in destroyed:
            if target not in kept:
                out.append(f"{func.name}: {target}")
    return out



def test_the_check_finds_a_write_that_is_not_kept():
    bad = ("def f(path):\n    path.write_text('x')\n"
           "def g(path):\n    with path.open('w') as h:\n"
           "        h.write('x')\n"
           "def h(stamp):\n    stamp.unlink()\n"
           "def i(path):\n    open(path, 'wt').write('x')\n")
    assert [line.split(":")[0] for line in unkept(bad)] == ["f", "g", "h", "i"]
    good = ("def f(path):\n    archive.keep(path)\n    path.write_text('x')\n"
            "def g(path):\n    tmp.write_text('x')\n    archive.keep(path)\n"
            "    tmp.replace(path)\n"
            "def h(path):\n    return path.read_text()\n")
    assert unkept(good) == []


def test_every_file_a_pass_replaces_or_deletes_goes_through_keep():
    found = {}
    for name in OF_THE_HARVEST:
        source = (ROOT / "docpipe" / "extraction" / f"{name}.py")
        if source.is_file():
            bad = unkept(source.read_text(encoding="utf-8"))
            if bad:
                found[name] = bad
    assert found == {}


def test_a_recheck_keeps_the_stamps_it_deletes(tmp_path):
    (tmp_path / "a.jsonl").write_text(
        json.dumps({"kind": "summary", "document_id": 1}) + "\n",
        encoding="utf-8")
    stamp = tmp_path / "a.stamp.json"
    stamp.write_text('{"spec": "x"}', encoding="utf-8")
    archive.begin("recheck")
    got = recheck.run(tmp_path, SPEC)
    assert got["stamps cleared"] == 1 and not stamp.exists()
    copies = list((tmp_path / archive.ARCHIVE).glob("*/a.stamp.json"))
    assert [c.read_text(encoding="utf-8") for c in copies] == ['{"spec": "x"}']


def test_a_recheck_that_keeps_its_stamps_deletes_none(tmp_path):
    (tmp_path / "a.jsonl").write_text(
        json.dumps({"kind": "summary", "document_id": 1}) + "\n",
        encoding="utf-8")
    stamp = tmp_path / "a.stamp.json"
    stamp.write_text("{}", encoding="utf-8")
    with rules.overlaid(recheck_clear_stamps=False):
        assert recheck.run(tmp_path, SPEC)["stamps cleared"] == 0
    assert stamp.exists()
    # the call's own value wins over the rule
    assert recheck.run(tmp_path, SPEC, drop_stamps=False)["stamps cleared"] \
        == 0


# -- the statistics --

def harvest_with(tmp_path, *states):
    row = {"kind": "tuple", "parameter": "p",
           **{f"a{n}_state": s for n, s in enumerate(states)}}
    (tmp_path / "d.jsonl").write_text(json.dumps(row) + "\n",
                                      encoding="utf-8")
    return tmp_path


def test_the_statistics_leave_out_the_states_the_rule_names(tmp_path):
    harvest_with(tmp_path, "read", "derived", "out_of_slice", "exhausted")
    got = stats.from_harvest(tmp_path)["documents_by_open_share"]
    assert got == [{"document": "d", "open_coordinates": 1,
                    "asked_coordinates": 2}]
    with rules.overlaid(stats_not_asked_states=["derived"]):
        got = stats.from_harvest(tmp_path)["documents_by_open_share"]
    assert got[0]["asked_coordinates"] == 3


def test_a_run_writes_its_statistics_unless_the_rule_says_not(tmp_path):
    harvest_with(tmp_path, "read")
    assert stats.write(tmp_path).is_file()
    with rules.overlaid(write_stats=False):
        assert stats.write(tmp_path) is None
        assert stats.write(tmp_path, always=True).is_file()


# -- 3. the check before a run --

def test_the_prompts_are_those_of_the_steps_that_are_on(monkeypatch):
    tree = [{"id": "a", "box": "coord"}, {"id": "b", "box": "find",
                                          "off": True},
            {"id": "c", "box": "docfield"}]
    monkeypatch.setattr("docpipe.extraction.flow.tree_of",
                        lambda profile=None: tree)
    got = preflight.prompts_in_effect(None)
    assert [one for one, _optional in got] == [
        "extraction/coord", "extraction/docfield"]
    assert all(one != "extraction/anchors" for one, _o in got)
    with rules.overlaid(preflight_prompts=["extraction/example"]):
        assert preflight.prompts_in_effect(None)[-1] == (
            "extraction/example", False)


def test_the_check_names_no_anchor():
    assert "anchor" not in "".join(
        line for line in
        (ROOT / "docpipe" / "extraction" / "preflight.py")
        .read_text(encoding="utf-8").split("\n") if "check(" in line)


def test_a_word_that_means_i_do_not_know_is_the_rules(monkeypatch):
    assert preflight.shrugs() == {"unknown", "unbekannt", "n/a",
                                  "keine angabe", "out:unstated"}
    with rules.overlaid(shrug_words=["Weiss Nicht"]):
        assert preflight.shrugs() == {"weiss nicht"}


def test_a_shape_check_that_cannot_run_counts_as_the_rule_says(monkeypatch):
    monkeypatch.setattr(preflight, "left_out_of", lambda profile: None)
    profile = SimpleNamespace(component=lambda *names: None)
    assert preflight.shapes_verdict(profile, {})[0] is True
    with rules.overlaid(preflight_skip_counts_ok=False):
        assert preflight.shapes_verdict(profile, {})[0] is False


@pytest.fixture
def kwp(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    rules.reset()


def verdict_of(what, **values):
    values = {"shrug_words": ["oeo_00000292"], **values}
    with rules.overlaid(**values):
        rows = preflight.audit("kwp")
    return [row[2] for row in rows if row[1] == what]


def test_a_check_fails_warns_or_does_not_run_as_the_rule_says(kwp):
    what = "no shrug in the vocabulary"
    severity = dict(rules.get("preflight_severity"))
    assert verdict_of(what) == ["FAIL"]
    assert verdict_of(what, preflight_severity={**severity,
                                                what: "warn"}) == ["warn"]
    assert verdict_of(what, preflight_severity={**severity,
                                                what: "off"}) == []
    # and where it passes, whatever the rule says
    assert verdict_of(what, shrug_words=["never in a list"]) == ["ok"]


# -- 4. the passes --

def test_the_states_that_stay_are_the_rules():
    assert topup.keep_read() == ("read", "derived")
    assert topup.keep_asked() == ("read", "derived", "unstated")
    slot = SLOTS["carrier"]
    claim = {"carrier_state": "unstated"}
    taken = topup.reopen({"carrier_state": "exhausted"}, slot)
    assert not topup.restore(claim, slot, taken, keep=topup.keep_asked())
    with rules.overlaid(reread_improves_states=["read"]):
        claim = {"carrier_state": "unstated"}
        assert topup.restore(claim, slot, taken, keep=topup.keep_asked())


def test_a_moved_frame_coordinate_blocks_unless_the_rule_says_not():
    key = "axis/energy_consumption/year"
    assert topup.actionable({key}, SPEC, ("year",)) == ([], [key])
    with rules.overlaid(reread_blocks_frame=False):
        assert topup.actionable({key}, SPEC, ("year",)) == ([key], [])


def test_a_coordinate_with_a_list_made_per_document_blocks_without_it(
        monkeypatch):
    axis = SimpleNamespace(dynamic=True)
    target = (SimpleNamespace(axes={"x": axis}), SimpleNamespace(name="x"))
    monkeypatch.setattr(topup, "targets_of", lambda spec, key: [target])
    assert topup.actionable({"k"}, SPEC, dynamic_ok=False) == ([], ["k"])
    with rules.overlaid(reread_blocks_dynamic_list=False):
        assert topup.actionable({"k"}, SPEC, dynamic_ok=False) == (["k"], [])
    assert topup.actionable({"k"}, SPEC, dynamic_ok=True) == (["k"], [])


def test_closed_rows_are_reopened_unless_the_rule_says_not():
    rows = [{"kind": "tuple", "parameter": "energy_consumption",
             "scenario": "target", "carrier_state": "out_of_slice"}]
    gate = {"scenario": None}
    got = topup.reopened_by_gate(rows, SPEC, gate)
    assert [slot.name for _p, slot, _r in got] == ["carrier"]
    with rules.overlaid(reread_reopen_closed_rows=False):
        assert topup.reopened_by_gate(rows, SPEC, gate) == []


def test_moved_coordinates_are_read_in_the_order_the_rule_says(monkeypatch):
    keys = ["axis/energy_consumption/year", "axis/energy_consumption/carrier",
            "axis/energy_consumption/sector"]
    by_key = [key for key, _p, _s in topup.in_order(keys, SPEC)]
    assert by_key == keys
    spec = SimpleNamespace(parameters=[SimpleNamespace(uri="b"),
                                       SimpleNamespace(uri="a")])
    pair = {"1": ("a", "x"), "2": ("b", "y")}

    def targets(spec, key):
        uri, name = pair[key]
        return [(SimpleNamespace(uri=uri), SimpleNamespace(name=name))]

    monkeypatch.setattr(topup, "targets_of", targets)
    assert [k for k, _p, _s in topup.in_order(["1", "2"], spec)] \
        == ["1", "2"]
    with rules.overlaid(reread_order="spec_order"):
        assert [k for k, _p, _s in topup.in_order(["1", "2"], spec)] \
            == ["2", "1"]


def sweeping(monkeypatch, refusal=True):
    """_sweep_one over one stored row whose re-reading is refused."""
    source = SimpleNamespace(owner_kind="section", owner_id=1,
                             text="Erdgas 5 GWh", provenance={})
    row = {"kind": "tuple", "parameter": "energy_consumption",
           "quote": "Erdgas 5 GWh", "carrier": "OEO_00000292",
           "carrier_state": "read",
           "provenance": {"owner_kind": "section", "owner_id": 1,
                          "document_id": 1}}

    def sweep(batch, entries, slots, anchor_id):
        for entry in entries:
            entry.claim["carrier_state"] = "read"
            entry.claim["carrier"] = "OEO_00000292"

    deps = {"owner_sources": lambda owners: {("section", 1): source},
            "sweep": sweep}
    monkeypatch.setattr(topup, "_reverify", lambda *a, **k: Refusal(
        {"x": 1}, "a unit no list holds"))
    return row, deps


def test_a_refused_row_becomes_a_refusal_or_keeps_its_old_reading(
        monkeypatch):
    from collections import Counter
    row, deps = sweeping(monkeypatch)
    stored = dict(row)
    settled, refused = topup._sweep_one([row], PARAMETER, SLOTS["carrier"],
                                        SPEC, deps, Counter())
    assert refused == [row] and row["kind"] == "refusal"
    row, deps = sweeping(monkeypatch)
    with rules.overlaid(reread_refused_becomes_refusal="keep_old"):
        stats_ = Counter()
        settled, refused = topup._sweep_one(
            [row], PARAMETER, SLOTS["carrier"], SPEC, deps, stats_)
    assert refused == [] and row == stored and settled is False
    assert stats_["kept after refused re-reading"] == 1


def test_a_row_equal_to_a_stored_one_is_appended_unless_the_rule_says_so():
    stored = [{"kind": "tuple", "value": 1, "provenance": {"page": 1}}]
    new = [{"value": 1, "provenance": {"page": 2}}, {"value": 2}]
    assert topup_parameter.drop_stored_repeats(new, stored) == (new[1:], 1)
    with rules.overlaid(append_drop_repeats=False):
        assert topup_parameter.drop_stored_repeats(new, stored) == (new, 0)


def test_the_pass_for_a_new_parameter_is_all_or_nothing_by_the_rule():
    assert topup_parameter.refuses_incomplete() is True
    with rules.overlaid(parameter_pass_all_or_nothing=False):
        assert topup_parameter.refuses_incomplete() is False


def test_a_document_read_to_its_end_is_not_read_again_by_the_rule(tmp_path):
    stamp = tmp_path / "a.stamp.json"
    stamp.write_text(json.dumps({"producers": [{"pass": "rest"}]}),
                     encoding="utf-8")
    assert topup_rest.read_to_end(stamp) and topup_rest.done_to_end(stamp)
    with rules.overlaid(rest_once_per_document=False):
        assert topup_rest.read_to_end(stamp)         # the fact stays
        assert not topup_rest.done_to_end(stamp)
    assert topup_rest.skips_unknown_reading()
    with rules.overlaid(rest_without_trace="read_all"):
        assert not topup_rest.skips_unknown_reading()


def test_the_passages_of_a_field_without_a_ranking_follow_the_rule():
    found = survey.Found(True, answers={
        ("section", 1): survey.Answer(("section", 1), ["p"]),
        ("section", 2): survey.Answer(("section", 2), ["p"])})
    assert found.passages_of("p") == [("section", 1), ("section", 2)]
    with rules.overlaid(survey_fallback_order="reverse_document_order"):
        assert found.passages_of("p") == [("section", 2), ("section", 1)]
    found.order = {"p": [("section", 2)]}
    with rules.overlaid(survey_fallback_order="reverse_document_order"):
        assert found.passages_of("p") == [("section", 2), ("section", 1)]


def mapped(wording, current, **values):
    row = {"carrier_raw": wording, "carrier": current}
    with rules.overlaid(**values):
        counts, open_spaces = remap.remap_row(row, PARAMETER)
    return row, counts, open_spaces


def test_a_class_is_replaced_by_the_new_list_unless_the_rule_says_not():
    row, counts, _open = mapped("Erdgas", "OEO_00000211")
    assert row["carrier"] == "OEO_00000292" and counts["remapped"] == 1
    row, counts, open_ = mapped("Erdgas", "OEO_00000211",
                                remap_overwrite_class=False)
    assert row["carrier"] == "OEO_00000211" and counts["not overwritten"] == 1
    assert f"axis/{PARAMETER.uri}/carrier" in open_
    # nothing there: mapped as ever
    row, counts, _open = mapped("Erdgas", None, remap_overwrite_class=False)
    assert row["carrier"] == "OEO_00000292"


def test_a_wording_in_no_list_keeps_the_models_class_or_loses_it():
    row, counts, open_ = mapped("Xyzzy", "OEO_00000211")
    assert row["carrier"] == "OEO_00000211" and counts["not listed"] == 1
    row, counts, open_ = mapped("Xyzzy", "OEO_00000211",
                                remap_unlisted="empty")
    assert "carrier" not in row and counts["not listed"] == 1
    assert open_                                  # either way not settled


def test_a_refusal_holds_the_stamp_of_its_axis_unless_the_rule_says_not():
    refusals = [{"parameter": "energy_consumption",
                 "reason": "axis 'carrier': 'Klaergas' not in vocabulary"}]
    spaces = {"axis/energy_consumption/carrier"}
    assert remap.refused_spaces(refusals, spaces) == spaces
    with rules.overlaid(remap_refusals_block_stamp=False):
        assert remap.refused_spaces(refusals, spaces) == set()


def quoted(**states):
    row = {"carrier": "OEO_00000292", "carrier_raw": "Erdgas",
           "carrier_quote": "Strom 5 MWh", "carrier_state": "read"}
    row.update(states)
    return row


def test_a_coordinate_whose_quote_does_not_carry_it_falls_to_the_rule_state():
    row = quoted()
    got = recheck.recheck_row(row, [SLOTS["carrier"]])
    assert got["quote does not carry the answer"] == 1
    assert row["carrier_state"] == "unanswered" and "carrier" not in row
    row = quoted()
    with rules.overlaid(recheck_dropped_state="unbacked"):
        recheck.recheck_row(row, [SLOTS["carrier"]])
    assert row["carrier_state"] == "unbacked"


def test_a_coordinate_without_a_quote_is_dropped_unless_the_rule_says_not():
    row = quoted(carrier_quote="")
    recheck.recheck_row(row, [SLOTS["carrier"]])
    assert row["carrier_state"] == "unanswered"
    row = quoted(carrier_quote="")
    with rules.overlaid(recheck_drop_without_quote=False):
        got = recheck.recheck_row(row, [SLOTS["carrier"]])
    assert row["carrier"] == "OEO_00000292" and got["no evidence kept"] == 1


def test_a_derived_coordinate_is_left_alone_unless_the_rule_says_not():
    row = quoted(carrier_quote="", carrier_state="derived")
    got = recheck.recheck_row(row, [SLOTS["carrier"]])
    assert got["derived"] == 1 and row["carrier_state"] == "derived"
    row = quoted(carrier_quote="", carrier_state="derived")
    with rules.overlaid(recheck_keeps_derived=False):
        recheck.recheck_row(row, [SLOTS["carrier"]])
    assert row["carrier_state"] == "unanswered"


def energy(number=1, *, flags=(), provenance=None, **states):
    found = {"kind": "tuple", "parameter": "energy_consumption",
             "value": number,
             "unit": "GWh", "quote": f"Zitat {number}", "tier": "text_located",
             "flags": list(flags), "provenance": provenance or {},
             "parameter_state": "derived", "unit_state": "read",
             "carrier": "OEO_1", "carrier_state": "read", "year": 2030,
             "year_state": "read"}
    for key, state in states.items():
        found[f"{key}_state"] = state
        found[key] = None
    return found


def test_the_levels_and_the_once_of_a_second_reading_are_the_rules():
    rows = [energy(), energy(carrier="exhausted"),
            energy(carrier="unbacked")]
    assert review.rows_to_review(rows) == rows[1:]
    with rules.overlaid(review_levels=["D"]):
        assert review.rows_to_review(rows) == rows[2:]
    with rules.overlaid(review_levels=["A", "C"]):
        assert review.rows_to_review(rows) == [rows[0], rows[1]]
    seen = [energy(carrier="exhausted", flags=["review:agree"])]
    assert review.rows_to_review(seen) == []
    with rules.overlaid(review_once_per_row=False):
        assert review.rows_to_review(seen) == seen


def test_the_reasons_that_name_a_coordinate_are_the_rules():
    verdict = {"reasons": ["exhausted:carrier", "review:disagree",
                           "unbacked:year", "computed"]}
    assert review.disputed(verdict) == ["carrier", "year"]
    with rules.overlaid(review_axis_reasons=["exhausted"]):
        assert review.disputed(verdict) == ["carrier"]


def test_a_row_that_names_no_coordinate_is_asked_its_value_or_all_fields():
    only = review.review_fields(PARAMETER, [])
    assert [s.kind for s in only] == [fields.VALUE]
    with rules.overlaid(review_fields_when_no_axis="all_fields"):
        every = review.review_fields(PARAMETER, [])
    assert len(every) == 1 + len(fields.axis_slots(PARAMETER))
    # a row that names one is asked that one, whatever the rule says
    with rules.overlaid(review_fields_when_no_axis="all_fields"):
        assert len(review.review_fields(PARAMETER, ["carrier"])) == 2


def test_a_cell_of_the_working_list_holds_as_many_characters_as_the_rule():
    text = "wort " * 100
    assert len(review._cell(text)) <= 302
    with rules.overlaid(review_cell_chars=10):
        assert review._cell(text) == "wort wort" + " …"
    with rules.overlaid(review_cell_chars=1000):
        assert review._cell(text) == text.strip()


def test_a_second_number_is_rounded_to_the_places_the_rule_says(monkeypatch):
    monkeypatch.setattr(review, "backed", lambda *a, **k: True)
    parameter = SimpleNamespace(is_numeric=True, unit_factor=lambda unit: 1)
    row = {"value_target": 1.234568}
    reply = {"value": 1.23456789}
    assert review._value_agrees(row, parameter, reply, []) is True
    with rules.overlaid(review_compare_places=2):
        assert review._value_agrees(row, parameter, reply, []) is False


def reviewing(folder, **values):
    (folder / "d.jsonl").write_text(
        json.dumps(energy(carrier="exhausted", provenance={
            "owner_kind": "section", "owner_id": 1})) + "\n",
        encoding="utf-8")
    source = SimpleNamespace(owner_kind="section", owner_id=1, text="t")
    with rules.overlaid(**values):
        return review.run(folder, SPEC, ask=lambda *a: {},
                          sources_for=lambda row: [source])


def test_the_working_list_that_is_replaced_is_kept(tmp_path):
    archive.begin("review")
    assert reviewing(tmp_path)["reviewed"] == 1
    first = (tmp_path / "review.csv").read_text(encoding="utf-8")
    assert reviewing(tmp_path, review_once_per_row=False)["reviewed"] == 1
    copies = list((tmp_path / archive.ARCHIVE).glob("review-*/review.csv"))
    assert [c.read_text(encoding="utf-8") for c in copies] == [first]


def test_a_second_reading_stops_at_the_limit_the_rule_says(tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.jsonl").write_text(
            json.dumps(energy(carrier="exhausted", provenance={
                "owner_kind": "section", "owner_id": 1})) + "\n",
            encoding="utf-8")
    source = SimpleNamespace(owner_kind="section", owner_id=1, text="t")

    def read(**values):
        with rules.overlaid(**values):
            return review.run(tmp_path, SPEC, ask=lambda *a: {},
                              sources_for=lambda row: [source])["reviewed"]

    assert read(review_limit=2) == 2
    assert read(review_limit=0, review_once_per_row=False) == 3
