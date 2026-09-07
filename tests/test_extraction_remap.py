"""A moved vocabulary applied to a harvest that is already on disk.

The whole claim is that an ontology change costs the coordinates it touched
instead of a corpus run: 1.082 documents, about 93 GPU hours, for one new
spelling. That claim rests on two things being true at once — the values are
actually re-mapped, and the stamp only says so where the pass could really
account for it. A stamp written forward too eagerly is worse than no remap at
all: the next run would skip a document whose coordinates are still old.

So these hold both halves, and every way the pass has to admit it cannot help.

No model, no GPU, no database.
"""
import json

from docpipe.extraction import remap
from docpipe.extraction.spec import fingerprints, load as load_spec


def _spec(carrier_labels):
    return load_spec({"parameters": [{
        "uri": "energy",
        "label": "Endenergieverbrauch",
        "description": "Endenergieverbrauch je Energietraeger, Sektor und "
                       "Jahr, wie im Plan bilanziert.",
        "value_type": "float",
        "unit_target": "kWh",
        "units_accepted": {"MWh/a": 1.0},
        "axes": {"carrier": {"vocabulary": carrier_labels},
                 "year": {"type": "int"}},
        "example": {"source": "| Erdgas | 42.005 | MWh/a | im Jahr 2020 |",
                    "tuples": [{"value": 42005, "unit_raw": "MWh/a",
                                "carrier": "Erdgas", "year": 2020}]},
    }]})


OLD_LIST = {"oeo:gas": ["Erdgas", "Gas"]}
NEW_LIST = {"oeo:gas": ["Erdgas", "Gas"],
            "oeo:sewage": ["Klaergas", "Klaerschlammgas"]}


def _tuple(**overrides):
    row = {"kind": "tuple", "parameter": "energy", "value": 42005,
           "unit": "MWh/a", "carrier": "oeo:gas", "carrier_raw": "Erdgas",
           "carrier_state": "read", "year": 2020}
    row.update(overrides)
    return row


def _harvest(tmp_path, rows, stamp=None):
    path = tmp_path / "plan.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")
    if stamp is not None:
        remap.stamp_path_of(path).write_text(json.dumps(stamp),
                                             encoding="utf-8")
    return path


def _rows(path):
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").strip().splitlines()]


def _stamp(spec, **extra):
    return {"spec": "spec-sha", "model": "m", "anchors": "a",
            "extraction/field": "f", **fingerprints(spec), **extra}


# ---------------------------------------------------------------------------
# The values
# ---------------------------------------------------------------------------
def test_a_wording_the_new_list_knows_reaches_its_class(tmp_path):
    """The measured case: "Klaergas" sat under biogas because the list had no
    entry for it, and 29 Kassel tuples with it. The wording was kept next to
    the class for exactly this, so a term request costs a pass over the files
    and not a re-read of the corpus."""
    new = _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(carrier="oeo:gas", carrier_raw="Klaergas",
               flags=["mapped:carrier:Klaergas->oeo:gas"]),
        _tuple(),
    ], stamp=_stamp(_spec(OLD_LIST)))

    stats = remap.remap_file(path, new, _stamp(new))
    rows = _rows(path)
    assert rows[0]["carrier"] == "oeo:sewage"
    assert "flags" not in rows[0], "the flag was about the list that changed"
    assert rows[1]["carrier"] == "oeo:gas", "an unaffected value is untouched"
    assert stats["remapped"] == 1 and stats["unchanged"] == 1


def test_a_coordinate_the_old_list_could_not_place_is_filled(tmp_path):
    """An unmapped coordinate is the single most useful line for a vocabulary
    review, and the point of the review is that the next list places it."""
    new = _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(carrier=None, carrier_raw="Klaerschlammgas",
               flags=["unmapped:carrier:Klaerschlammgas"])],
        stamp=_stamp(_spec(OLD_LIST)))

    stats = remap.remap_file(path, new, _stamp(new))
    row = _rows(path)[0]
    assert row["carrier"] == "oeo:sewage" and "flags" not in row
    assert stats["newly mapped"] == 1


def test_a_wording_in_no_list_keeps_the_reading_it_has(tmp_path):
    """The model's own mapping is a judgement call the spec did not foresee.
    Replacing it with an empty cell would lose a finding rather than correct
    one, and the flag that says so has to survive too."""
    new = _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(carrier="oeo:gas", carrier_raw="Grubengas",
               flags=["mapped:carrier:Grubengas->oeo:gas"])],
        stamp=_stamp(_spec(OLD_LIST)))

    stats = remap.remap_file(path, new, _stamp(new))
    row = _rows(path)[0]
    assert row["carrier"] == "oeo:gas"
    assert row["flags"] == ["mapped:carrier:Grubengas->oeo:gas"]
    assert stats["not listed"] == 1


def test_a_coordinate_with_no_wording_cannot_be_mapped_at_all(tmp_path):
    """The URI is all that survived, and which wording the model resolved to
    it is gone. That is the difference between minutes and 93 GPU hours, so
    it is counted rather than shrugged at."""
    new = _spec(NEW_LIST)
    path = _harvest(tmp_path, [_tuple(carrier="oeo:gas", carrier_raw=None)],
                    stamp=_stamp(_spec(OLD_LIST)))
    stats = remap.remap_file(path, new, _stamp(new))
    assert _rows(path)[0]["carrier"] == "oeo:gas"
    assert stats["no wording"] == 1
    # And the space stays stale: this coordinate cannot be vouched for, so a
    # later run has to be able to see that it is still the old one.
    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    assert stored["axis/energy/carrier"] == \
        fingerprints(_spec(OLD_LIST))["axis/energy/carrier"]


def test_the_summary_is_recomputed_from_the_coordinates_that_moved(tmp_path):
    """This pass changes what the tuples say. A carried-over summary would
    report a harvest that no longer exists."""
    new = _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(carrier=None, carrier_raw="Klaergas"),
        {"kind": "summary", "document_id": 857, "tuples": 1, "refusals": 0,
         "levels": {"A": 0, "B": 0, "C": 1}, "reasons": {"conflict": 1},
         "image_origin": 0}], stamp=_stamp(_spec(OLD_LIST)))

    remap.remap_file(path, new, _stamp(new))
    rows = _rows(path)
    assert [r["kind"] for r in rows] == ["tuple", "summary"], "one, not two"
    assert rows[-1]["document_id"] == 857
    assert rows[-1]["reasons"] == {}, "recomputed, not carried"


# ---------------------------------------------------------------------------
# The stamp
# ---------------------------------------------------------------------------
def test_a_fully_remapped_answer_space_is_written_forward(tmp_path):
    """Without this the pass fixes the values and the next run still redoes
    the document, which is the cost it exists to avoid."""
    old, new = _spec(OLD_LIST), _spec(NEW_LIST)
    path = _harvest(tmp_path, [_tuple(carrier_raw="Klaergas", carrier=None)],
                    stamp=_stamp(old))
    stats = remap.remap_file(path, new, _stamp(new))

    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    assert stored["axis/energy/carrier"] == fingerprints(new)["axis/energy/carrier"]
    assert stored["spec"] == "spec-sha", "the file sha did not move here"
    assert stats["stamps carried forward"] == 1
    # And nothing else was touched: the year axis never moved.
    assert stored["axis/energy/year"] == fingerprints(new)["axis/energy/year"]


def test_a_space_the_pass_could_not_settle_stays_stale(tmp_path):
    """One wording nobody listed is enough. Writing the key forward would let
    the next run skip a document whose coordinate is still the old one, and
    the whole point of the fine-grained stamp is that it can be believed."""
    old, new = _spec(OLD_LIST), _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(carrier_raw="Klaergas", carrier=None),
        _tuple(carrier_raw="Grubengas", carrier="oeo:gas")], stamp=_stamp(old))
    remap.remap_file(path, new, _stamp(new))

    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    assert stored["axis/energy/carrier"] == fingerprints(old)["axis/energy/carrier"]
    # The value it COULD map was still written: the file is better than it was.
    assert _rows(path)[0]["carrier"] == "oeo:sewage"


def test_a_refusal_the_grown_list_might_place_keeps_its_space_stale(tmp_path):
    """A claim refused because its wording was in no vocabulary becomes a
    tuple once the list grows, and only a re-harvest can do that. Marking the
    space current would hide exactly the value the option was added for."""
    old, new = _spec(OLD_LIST), _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(),
        {"kind": "refusal", "parameter": "energy",
         "reason": "axis 'carrier': 'Klaergas' not in vocabulary and axis is "
                   "required", "claim": {}, "owner": ["table", 1]}],
        stamp=_stamp(old))
    stats = remap.remap_file(path, new, _stamp(new))

    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    assert stored["axis/energy/carrier"] == fingerprints(old)["axis/energy/carrier"]
    assert stats["refusals may now map"] == 1


def test_the_file_sha_moves_only_when_nothing_else_is_stale(tmp_path):
    """It is a coarse mirror of the keys under it. Moved while a prompt
    change sits unaddressed, a document reads as current and is skipped."""
    old, new = _spec(OLD_LIST), _spec(NEW_LIST)
    rows = [_tuple(carrier_raw="Klaergas", carrier=None)]

    # Only the vocabulary moved: the pass accounts for the whole difference.
    clean = _harvest(tmp_path, rows, stamp=_stamp(old))
    remap.remap_file(clean, new, {**_stamp(new), "spec": "neu"})
    assert json.loads(remap.stamp_path_of(clean).read_text(
        encoding="utf-8"))["spec"] == "neu"

    # A prompt moved as well: nothing here can speak for that.
    other = tmp_path / "second"
    other.mkdir()
    path = other / "plan.jsonl"
    path.write_text(json.dumps(rows[0], ensure_ascii=False) + "\n",
                    encoding="utf-8")
    remap.stamp_path_of(path).write_text(json.dumps(_stamp(old)),
                                         encoding="utf-8")
    remap.remap_file(path, new, {**_stamp(new), "spec": "neu",
                                 "extraction/field": "andere"})
    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    assert stored["spec"] == "spec-sha"
    assert stored["extraction/field"] == "f", "not this pass's business"
    assert stored["axis/energy/carrier"] == fingerprints(new)["axis/energy/carrier"]


def test_a_row_naming_an_unknown_parameter_stops_the_whole_stamp(tmp_path):
    """There is no list to map it against, so nothing here may touch it --
    and nothing here may vouch for the document either."""
    old, new = _spec(OLD_LIST), _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(carrier_raw="Klaergas", carrier=None),
        _tuple(parameter="erfunden")], stamp=_stamp(old))
    stats = remap.remap_file(path, new, _stamp(new))

    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    assert stored["axis/energy/carrier"] == fingerprints(old)["axis/energy/carrier"]
    assert stats["unknown parameter kept"] == 1


def test_a_harvest_without_a_stamp_is_still_remapped(tmp_path):
    """A file nothing vouches for gets re-harvested anyway, and its values
    are no reason to leave them wrong in the meantime."""
    new = _spec(NEW_LIST)
    path = _harvest(tmp_path, [_tuple(carrier_raw="Klaergas", carrier=None)])
    stats = remap.remap_file(path, new, _stamp(new))
    assert _rows(path)[0]["carrier"] == "oeo:sewage"
    assert stats["stamps carried forward"] == 0


def test_a_directory_pass_leaves_the_trace_alone(tmp_path):
    """A trace sits next to its harvest in a copied set and is not a harvest.
    Rewriting it would replace a run's own record with a remap of nothing."""
    new = _spec(NEW_LIST)
    _harvest(tmp_path, [_tuple(carrier_raw="Klaergas", carrier=None)])
    trace = tmp_path / "plan.trace.jsonl"
    trace.write_text(json.dumps({"t": "rows", "ms": 10}) + "\n",
                     encoding="utf-8")

    stats = remap.run(tmp_path, new, _stamp(new))
    assert stats["documents"] == 1
    assert json.loads(trace.read_text(encoding="utf-8"))["t"] == "rows"


def test_a_refusal_nobody_can_attribute_unsettles_the_whole_document(tmp_path):
    """Guessing which answer space a refusal belonged to would be the same
    mistake in a smaller place. A refusal that names no axis could be about
    any of them, so none of them may be written forward."""
    old, new = _spec(OLD_LIST), _spec(NEW_LIST)
    path = _harvest(tmp_path, [
        _tuple(carrier_raw="Klaergas", carrier=None),
        {"kind": "refusal", "parameter": None,
         "reason": "value 'Klaergas' not in vocabulary", "claim": {},
         "owner": ["table", 1]}], stamp=_stamp(old))
    remap.remap_file(path, new, _stamp(new))

    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    for key, value in fingerprints(old).items():
        assert stored[key] == value, key
    # The value it could map was still written: the file is better than it was.
    assert _rows(path)[0]["carrier"] == "oeo:sewage"


# ---------------------------------------------------------------------------
# A category parameter answers from a list of its own
# ---------------------------------------------------------------------------
def _category_spec(labels):
    return load_spec({"parameters": [{
        "uri": "scenario_type",
        "label": "Art des Szenarios",
        "description": "Die Art eines Szenarios, gewaehlt aus der Liste der "
                       "Klassen, die dieses Feld zulaesst.",
        "value_type": "category",
        "vocabulary": labels,
        "axes": {},
        "example": {"source": "Das Zielszenario beschreibt den angestrebten "
                              "Zustand im Jahr 2045.",
                    "tuples": [{"value": "Zielszenario"}]},
    }]})


CATEGORY_OLD = {"oeo:target": ["Zielszenario"]}
CATEGORY_NEW = {"oeo:target": ["Zielszenario"],
                "oeo:wem": ["Trendszenario", "WEM"]}


def test_a_category_parameters_own_list_is_its_own_stamp_key(tmp_path):
    """It is an answer space like an axis: a moved option can be re-mapped
    from the wording the harvest kept, while a rewritten question cannot. One
    key for both would make the two indistinguishable and cost a corpus run
    for the cheap one."""
    old, new = _category_spec(CATEGORY_OLD), _category_spec(CATEGORY_NEW)
    assert "value/scenario_type" in fingerprints(old)
    assert (fingerprints(old)["value/scenario_type"]
            != fingerprints(new)["value/scenario_type"])
    # And the parameter itself did not move: only its list did.
    assert (fingerprints(old)["parameter/scenario_type"]
            == fingerprints(new)["parameter/scenario_type"])


def test_a_category_value_is_remapped_from_its_wording(tmp_path):
    old, new = _category_spec(CATEGORY_OLD), _category_spec(CATEGORY_NEW)
    stamp_old = {"spec": "spec-sha", "model": "m", "anchors": "a",
                 "extraction/field": "f", **fingerprints(old)}
    stamp_new = {**stamp_old, **fingerprints(new)}
    path = _harvest(tmp_path, [{"kind": "tuple", "parameter": "scenario_type",
                                "value": None, "value_raw": "Trendszenario",
                                "flags": ["unmapped:value:Trendszenario"]}])
    remap.stamp_path_of(path).write_text(json.dumps(stamp_old),
                                         encoding="utf-8")

    stats = remap.remap_file(path, new, stamp_new)
    row = _rows(path)[0]
    assert row["value"] == "oeo:wem" and "flags" not in row
    assert stats["newly mapped"] == 1
    stored = json.loads(remap.stamp_path_of(path).read_text(encoding="utf-8"))
    assert stored["value/scenario_type"] == fingerprints(new)["value/scenario_type"]


# ---------------------------------------------------------------------------
# The pieces, named
#
# remap_file is the interface, but each of these decides on its own whether a
# stamp key may move, so each is held to its contract here rather than only
# through the file it is called from.
# ---------------------------------------------------------------------------
def test_spaces_of_takes_the_answer_spaces_and_nothing_else():
    """A prompt and a model are not answer spaces: no wording is mapped
    against them, so this pass can never speak for them."""
    stamp = _stamp(_spec(OLD_LIST))
    got = remap.spaces_of(stamp)
    assert got == {"axis/energy/carrier", "axis/energy/year"} | {
        k for k in stamp if k.startswith("value/")}
    assert not {"spec", "model", "anchors", "extraction/field"} & got


def test_remap_row_reports_the_space_it_left_open():
    """The caller has no other way to know: the row it gets back looks the
    same whether the wording resolved or was left alone."""
    spec = _spec(NEW_LIST)
    parameter = spec.parameters[0]
    counts, open_spaces = remap.remap_row(
        _tuple(carrier="oeo:gas", carrier_raw="Grubengas"), parameter)
    assert open_spaces == {"axis/energy/carrier"} and counts["not listed"] == 1
    counts, open_spaces = remap.remap_row(
        _tuple(carrier=None, carrier_raw="Klaergas"), parameter)
    assert open_spaces == set() and counts["newly mapped"] == 1


def test_refused_spaces_names_the_axis_or_gives_up_on_everything():
    spaces = {"axis/energy/carrier", "axis/energy/year"}
    named = [{"parameter": "energy",
              "reason": "axis 'carrier': 'Klaergas' not in vocabulary and "
                        "axis is required"}]
    assert remap.refused_spaces(named, spaces) == {"axis/energy/carrier"}
    # A refusal that has nothing to do with a list is not this pass's problem.
    other = [{"parameter": "energy", "reason": "value is not a number"}]
    assert remap.refused_spaces(other, spaces) == set()
    # And one nobody can place takes everything with it.
    vague = [{"parameter": None, "reason": "value 'x' not in vocabulary"}]
    assert remap.refused_spaces(vague, spaces) == spaces


def test_stamp_forward_says_whether_it_wrote(tmp_path):
    """The caller counts it, and a pass that reports documents it did not
    actually carry forward is a pass nobody can check."""
    old, new = _spec(OLD_LIST), _spec(NEW_LIST)
    path = tmp_path / "plan.stamp.json"
    path.write_text(json.dumps(_stamp(old)), encoding="utf-8")
    spaces = remap.spaces_of(_stamp(new))
    assert remap.stamp_forward(path, _stamp(new), spaces) is True
    # Nothing changed the second time, so there is nothing to write.
    assert remap.stamp_forward(path, _stamp(new), spaces) is False
    # And a document with no stamp is not given one here.
    assert remap.stamp_forward(tmp_path / "missing.stamp.json",
                               _stamp(new), spaces) is False
