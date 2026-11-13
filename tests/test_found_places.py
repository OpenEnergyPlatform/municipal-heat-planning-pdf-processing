"""A run starts at the passages earlier harvests found something in, takes no
answer from them, and leaves every open coordinate to the search. Each promise
has a case that breaks it by construction beside the one that keeps it."""
import json
from pathlib import Path

from docpipe.extraction import fields, found, runner
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))

TABLE, HEADING, OTHER = ("table", 5), ("section", 1), ("section", 2)


def passage(key, text="Text", at=None):
    return Source(key[0], key[1], text, {"document_id": 7,
                                         "section_number": at})


def stored_tuple(own=TABLE, **coordinates):
    return {"kind": "tuple", "provenance": {"owner_kind": own[0],
                                            "owner_id": own[1]},
            **coordinates}


READ_IN_HEADING = {"carrier_state": fields.READ,
                   "carrier_source": list(HEADING)}


def kept_of(*rows):
    kept = found.Kept()
    found.places_of(rows, kept)
    return kept


# -- what a found place is ---------------------------------------------------

def test_a_row_s_passage_and_where_its_coordinate_was_read_are_places():
    assert kept_of(stored_tuple(**READ_IN_HEADING)).passages == {TABLE, HEADING}


def test_a_coordinate_not_read_there_is_no_place():
    row = stored_tuple(carrier_state=fields.EXHAUSTED,
                       carrier_source=list(HEADING))
    assert kept_of(row).passages == {TABLE}


def test_a_refused_row_marks_its_passage():
    refused = {"kind": "refusal", "owner": list(TABLE), "claim": {}}
    assert kept_of(refused).passages == {TABLE}


def test_a_coordinate_is_filed_under_the_passage_of_its_row():
    assert kept_of(stored_tuple(**READ_IN_HEADING)).read_at == {
        "carrier": {TABLE: {HEADING}}}


# -- which harvests count ----------------------------------------------------

def harvest(directory, *rows, stamped=True, stamp=None):
    directory.mkdir(exist_ok=True)
    (directory / "plan.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    if stamped:
        (directory / "plan.stamp.json").write_text(json.dumps(stamp or {}),
                                                   encoding="utf-8")


def asked(*uris):
    """A stamp with the per-parameter keys of these parameters."""
    return {"slot/parameter": "x", **{f"parameter/{uri}": "x" for uri in uris}}


EVERY_BUT_BUILDINGS = [p.uri for p in SPEC.parameters
                       if p.uri != "building_count"]


def test_a_parameter_no_harvest_asked_is_gained(tmp_path):
    harvest(tmp_path / "a", stored_tuple(), stamp=asked(*EVERY_BUT_BUILDINGS))
    assert found_in(tmp_path / "a").gained(7, SPEC) == ["building_count"]


def test_a_parameter_one_harvest_asked_is_not_gained(tmp_path):
    harvest(tmp_path / "a", stored_tuple(), stamp=asked(*EVERY_BUT_BUILDINGS))
    harvest(tmp_path / "b", stored_tuple(own=OTHER),
            stamp=asked("building_count"))
    assert found_in(tmp_path / "a", tmp_path / "b").gained(7, SPEC) == []


def test_a_stamp_without_parameter_keys_gains_nothing(tmp_path):
    harvest(tmp_path / "a", stored_tuple())
    assert found_in(tmp_path / "a").gained(7, SPEC) == []


def found_in(*directories, holds=(TABLE, HEADING, OTHER)):
    every = [passage(key) for key in holds]
    return found.Found(directories, lambda _d: "plan", lambda _d, _x: every)


def keys(sources):
    return [(s.owner_kind, s.owner_id) for s in sources]


def test_the_places_of_two_harvests_add_up(tmp_path):
    harvest(tmp_path / "a", stored_tuple(own=TABLE))
    harvest(tmp_path / "b", stored_tuple(own=OTHER))
    assert keys(found_in(tmp_path / "a", tmp_path / "b").passages(7)) == \
        [TABLE, OTHER]


def test_an_unstamped_harvest_counts_for_nothing(tmp_path):
    harvest(tmp_path / "a", stored_tuple(), stamped=False)
    assert found_in(tmp_path / "a").passages(7) == []


def test_a_document_that_lost_a_place_has_no_places(tmp_path):
    harvest(tmp_path / "a", stored_tuple(**READ_IN_HEADING))
    known = found_in(tmp_path / "a", holds=(TABLE,))
    assert known.passages(7) == []
    assert known.read_at(7, ["carrier"]) == {}


# -- the plan ----------------------------------------------------------------


# -- the search --------------------------------------------------------------


# -- the stamp ---------------------------------------------------------------

def stamped(tmp_path, *passes):
    harvest(tmp_path, stored_tuple())
    (tmp_path / "plan.stamp.json").write_text(json.dumps(
        {"producers": [{"pass": p} for p in passes]}), encoding="utf-8")
    return tmp_path


def done(out, **kwargs):
    return runner.already_done("plan", out, "sha", **kwargs)


def not_stale(monkeypatch):
    monkeypatch.setattr(runner, "stale", lambda *_a: [])


def test_a_document_read_in_part_is_owed_to_a_whole_run(tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert not done(stamped(tmp_path, found.PASS))


def test_a_document_read_in_part_is_done_for_a_run_that_starts_there(
        tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert done(stamped(tmp_path, found.PASS), start_at=True)


def test_reading_the_rest_makes_it_whole(tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert done(stamped(tmp_path, found.PASS, "rest"))


def test_an_ordinary_harvest_is_done(tmp_path, monkeypatch):
    not_stale(monkeypatch)
    assert done(stamped(tmp_path, "harvest"))
