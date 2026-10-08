"""A stamp from before the harvest lost its prompt of its own.

Promised: a stored stamp that still carries the key of the removed prompt is
current under today's run, AND no pass that writes into a stamp rewrites or
drops that key, AND the published stamp schema takes it without requiring it,
AND the stamp today's run writes has no such key and still validates.

The key is the one deliberate mention of the removed prompt outside the schema
pattern, so every test that needs it is here. Each promise has a case built to
violate it: a stamp whose question moved, a pass that writes the stamp from
today's keys, a closed schema that is given a key it does not know, a stamp
built the way the old code built it.
"""
import json

import pytest

from docpipe.extraction import remap, review, runner
from docpipe.extraction.schema import stamp_schema
from docpipe.extraction.spec import fingerprints
from tests.test_extraction_review import (SPEC as REVIEW_SPEC, _agreeing,
                                          _asker, _harvest as _review_harvest,
                                          _row as _review_row,
                                          _sources as _review_sources,
                                          _summary as _review_summary)
from tests.test_extraction_topup import (PARAMETER, SPEC, _deps, _harvest,
                                         _row, _rows, _stamp, _summary,
                                         _sweeper)
from tests.test_extraction_topup_parameter import World, _old, _stored_stamp

LEGACY_KEY = "extraction/harvest"
LEGACY_SHA = "0123456789abcdef" * 4
SPEC_SHA, ANCHORS_SHA = "a" * 64, "b" * 16
SECTOR = f"axis/{PARAMETER}/sector"


@pytest.fixture(autouse=True)
def _no_unserved_request_from_another_test():
    runner.UNSERVED.clear()
    yield
    runner.UNSERVED.clear()


@pytest.fixture
def today(monkeypatch):
    """The stamp a run of kwp writes now, key for key."""
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    return runner._stamp_current(SPEC_SHA, ANCHORS_SHA, SPEC)


def legacy_of(stamp: dict, **more) -> dict:
    """What the same run wrote while the harvest had a prompt of its own."""
    return {**stamp, LEGACY_KEY: LEGACY_SHA, **more}


def keeps_the_key(path) -> bool:
    return json.loads(path.read_text(encoding="utf-8")).get(
        LEGACY_KEY) == LEGACY_SHA


def stamp_at(tmp_path, stamp: dict, name="plan"):
    path = tmp_path / f"{name}.stamp.json"
    path.write_text(json.dumps(stamp), encoding="utf-8")
    (tmp_path / f"{name}.jsonl").write_text("{}\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# It is current
# ---------------------------------------------------------------------------

def test_a_stamp_with_the_removed_prompt_is_current_and_its_document_skipped(
        tmp_path, today):
    path = stamp_at(tmp_path, legacy_of(today))
    assert runner.stale(path, today) == []
    # Whatever sha the old stamp recorded: it is recorded and never compared.
    changed = stamp_at(tmp_path, legacy_of(today, **{LEGACY_KEY: "f" * 64}),
                       name="other")
    assert runner.stale(changed, today) == []
    for force_stale in (False, True):
        assert runner.already_done(
            "plan", tmp_path, SPEC_SHA, force_stale=force_stale,
            anchors_sha=ANCHORS_SHA, spec=SPEC) is True
    assert runner.documents_to_harvest(
        [(1, "plan.pdf"), (2, "other.pdf")], tmp_path, SPEC_SHA,
        anchors_sha=ANCHORS_SHA, spec=SPEC) == []


def test_a_stamp_with_the_removed_prompt_and_a_moved_question_is_stale(
        tmp_path, today):
    """Built to fail: the same stamp, with one question that is not today's.
    It is stale in that key and in no other, so the comparison does look at
    a stamp that carries the removed key, and what keeps the first one current
    is the questions and not the key."""
    axis = next(key for key in today if key.startswith("axis/"))
    path = stamp_at(tmp_path, legacy_of(today, **{axis: "moved"}))
    assert runner.stale(path, today) == [axis]
    assert runner.already_done(
        "plan", tmp_path, SPEC_SHA, force_stale=True,
        anchors_sha=ANCHORS_SHA, spec=SPEC) is False
    assert runner.documents_to_harvest(
        [(1, "plan.pdf")], tmp_path, SPEC_SHA, force_stale=True,
        anchors_sha=ANCHORS_SHA, spec=SPEC) == [(1, "plan.pdf")]


# ---------------------------------------------------------------------------
# No pass writes it away
# ---------------------------------------------------------------------------

def test_a_remap_that_earns_a_key_leaves_the_removed_prompt_where_it_was(
        tmp_path, today):
    axis = next(key for key in today if key.startswith("axis/"))
    path = stamp_at(tmp_path, legacy_of(today, **{axis: "moved"}))
    assert remap.stamp_forward(path, today, {axis}) is True
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored[axis] == today[axis], "the pass really wrote"
    assert keeps_the_key(path)
    assert runner.stale(path, today) == []


def test_a_top_up_that_re_reads_a_coordinate_leaves_the_removed_prompt(
        tmp_path):
    from docpipe.extraction import topup
    path = _harvest(tmp_path, [_row(), _summary()],
                    stamp=legacy_of(_stamp(**{SECTOR: "moved"})))
    stats = topup.run(tmp_path, SPEC, _stamp(), _deps(sweep=_sweeper(
        {"sector": {"value": "Haushalte", "raw": "Haushalte"}})))
    assert stats["stamps carried forward"] == 1
    assert _rows(path)[0]["sector_raw"] == "Haushalte", "the pass really wrote"
    assert keeps_the_key(tmp_path / "plan.stamp.json")


def test_a_pass_that_appends_a_parameter_leaves_the_removed_prompt(tmp_path):
    first = legacy_of(_stored_stamp(_old("heat_load")))
    world = World(tmp_path, stamp=first)
    written, failed, _stats = world.run()
    assert (written, failed) == (True, 0), "the pass really wrote"
    assert "parameter/heat_load" in world.stamp()
    assert keeps_the_key(world.stamp_path)
    assert runner.stale(world.stamp_path, world.current) == []


def test_a_review_leaves_the_removed_prompt_where_it_was(tmp_path):
    _review_harvest(tmp_path, [_review_row(), _review_summary()])
    stamp = tmp_path / "plan.stamp.json"
    stamp.write_text(json.dumps({"spec": "sha", "model": "m",
                                 LEGACY_KEY: LEGACY_SHA}), encoding="utf-8")
    review.run(tmp_path, REVIEW_SPEC, ask=_asker(_agreeing()),
               sources_for=lambda row: _review_sources(),
               prompt_sha="abc123", model="ein-modell",
               producer=runner.producer("review", "ein-modell"))
    stored = json.loads(stamp.read_text(encoding="utf-8"))
    assert stored["review/prompt"] == "abc123", "the pass really wrote"
    assert [p["pass"] for p in stored["producers"]] == ["harvest", "review"]
    assert keeps_the_key(stamp)


def test_a_stamp_written_from_todays_keys_has_lost_the_removed_prompt(
        tmp_path, today):
    """Built to fail: what a pass would leave that rewrote the stamp from the
    keys of the run instead of updating the one it found. The check the tests
    above make is false for it."""
    path = stamp_at(tmp_path, legacy_of(today))
    assert keeps_the_key(path)
    path.write_text(json.dumps(today), encoding="utf-8")
    assert not keeps_the_key(path)
    path.write_text(json.dumps(legacy_of(today, **{LEGACY_KEY: "f" * 64})),
                    encoding="utf-8")
    assert not keeps_the_key(path), "another sha is another key to a reader"


# ---------------------------------------------------------------------------
# The published schema takes it
# ---------------------------------------------------------------------------

@pytest.fixture
def validator():
    jsonschema = pytest.importorskip("jsonschema")
    shape = stamp_schema()
    return jsonschema.Draft202012Validator(shape), shape


def _complete(shape: dict) -> dict:
    stamp = {key: "0" * 64 for key in shape["required"]}
    stamp.update(model="m", anchors="")
    return stamp


def test_the_stamp_schema_takes_the_removed_prompt_and_does_not_require_it(
        validator):
    check, shape = validator
    assert LEGACY_KEY not in shape["required"]
    assert check.is_valid(_complete(shape)), "a stamp without the key"
    assert check.is_valid(legacy_of(_complete(shape))), "a stamp with it"


def test_the_stamp_schema_is_still_closed_and_still_requires_the_prompts_left(
        validator):
    """Built to fail: a key the schema does not name, a recorded sha that is
    none, and a stamp that lacks a prompt which is required."""
    check, shape = validator
    stamp = legacy_of(_complete(shape))
    assert not check.is_valid({**stamp, "extraction/nonsense": "0" * 64})
    assert not check.is_valid({**stamp, LEGACY_KEY: "not a sha"})
    assert not check.is_valid({k: v for k, v in stamp.items()
                               if k != "extraction/rows"})


# ---------------------------------------------------------------------------
# The stamp of today
# ---------------------------------------------------------------------------

def test_the_stamp_a_run_writes_has_no_key_for_the_removed_prompt_and_validates(
        today, validator):
    check, _shape = validator
    assert LEGACY_KEY not in today
    assert LEGACY_KEY not in runner.PROMPT_IDS
    assert {k for k in today if k.startswith("extraction/")} == set(
        runner.PROMPT_IDS)
    # Without the spec's keys, as the schema test of the runner's stamp does.
    written = runner._stamp_current(SPEC_SHA, ANCHORS_SHA)
    assert LEGACY_KEY not in written
    assert check.is_valid(written), list(check.iter_errors(written))
    entry = runner.producer("harvest", "m")
    assert LEGACY_KEY not in entry["prompts"]
    assert set(entry["prompts"]) == set(runner.PROMPT_IDS)
    assert check.is_valid({**written, "producers": [entry]})


def test_a_stamp_built_the_old_way_is_one_the_checks_find(today):
    """Built to fail: the check above, run over a stamp that has the key,
    reports it."""
    assert LEGACY_KEY in legacy_of(today)
    assert {k for k in legacy_of(today) if k.startswith("extraction/")} != set(
        runner.PROMPT_IDS)


def test_the_fine_keys_of_the_legacy_fixture_are_the_ones_a_run_writes():
    """The fixture is an old stamp and not a stamp of another kind: the keys
    that decide currency are today's, so that what keeps it current is the
    removed key's absence from the comparison and nothing the fixture lacks."""
    stored = legacy_of(_stamp())
    assert {k for k in stored if k.startswith(runner.QUESTION_KEYS)} == {
        k for k in fingerprints(SPEC)}
