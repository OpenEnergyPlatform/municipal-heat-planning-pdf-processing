"""
The run reads in the order of its flow file (owner, 2026-11-10: "Alle
Regeln etc. sollen auch immer über die GUI Editierbar sein").

The promises, each with a case that breaks it by construction:

1. The steps of a coordinate run in the order of the file: the search before
   the pieces beside shows its budget first, a search sentence after the
   pieces beside is written after them, and the default file asks what the
   code asked before (sentence, beside, search).
2. A step that is off sends no request of its kind, and a coordinate whose
   search is off ends exhausted, not unstated.
3. An arrangement the code cannot run is refused with its reason: the
   coordinates before the finds, a step that keeps its place moved, a step
   that is no switch off, the plan's years between the steps of a search.
4. The two checks stay: with every step that can be off off, an answer whose
   address names no shown line is still refused.
5. A profile's flow file may set the steps; one that cannot run is refused.
"""
import copy
import json

import pytest

from docpipe.extraction import addressed, flow
from docpipe.extraction.addressed import Reader
from docpipe.extraction.pipeline import Source

from test_addressed import (ENERGY, SPEC, TABLE, TEXT, Model,
                            in_order, plan_of)


# A plan of more pieces than the pieces beside a value: its search has
# pieces of its own to show.
MANY = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
               {"document_id": 7, "page": 4 + i}) for i in range(12)]


def default_steps() -> list:
    return copy.deepcopy(flow.load(None).steps)


def coordinate_frame(steps: list) -> dict:
    return next(step for step in steps if step["id"] == "coordinates")


def reordered(*ids: str, off: tuple = ()) -> flow.Arrangement:
    """The default steps with the coordinate's steps in the order *ids*
    (the others after them as they stand), those of *off* switched off."""
    steps = default_steps()
    frame = coordinate_frame(steps)
    by = {step["id"]: step for step in frame["steps"]}
    frame["steps"] = [by[name] for name in ids] + [
        step for step in frame["steps"] if step["id"] not in ids]
    for _, step in flow._walk(steps):
        if step["id"] in off:
            step["off"] = True
    assert flow.arrangement_problems(steps) == []
    return flow.arranged(steps)


def asked(arrangement) -> list:
    """[(kind, shows)] of the requests of one coordinate nothing shown
    says, in the order they were sent."""
    model = Model(find=lambda p, n: {"found": [{"at": "3.2",
                                                "words": "1.200"}]}
                  if p["passage"]["kind"] == "table" else {"found": []})
    reader = Reader(SPEC, model.asks(), in_order, arrangement=arrangement)
    reader(plan_of(TEXT, TABLE, *MANY), [ENERGY])
    return [(kind, noted.get("shows")) for kind, payload, noted in model.calls
            if noted.get("coordinate") == "carrier"
            and kind in ("coord", "phrase", "search")]


def test_the_default_file_asks_what_the_code_asked_before():
    sequence = asked(flow.arrangement(None))
    assert sequence[:3] == [("coord", None), ("phrase", None),
                            ("search", "near")]
    assert ("search", "found") in sequence


def test_the_search_before_the_pieces_beside_shows_its_budget_first():
    sequence = asked(reordered("own_place", "search_sentence", "search",
                               "beside"))
    searches = [shows for kind, shows in sequence if kind == "search"]
    assert searches[0] == "found"
    # the failure by construction: the default order shows the pieces
    # beside first
    default = [shows for kind, shows in asked(flow.arrangement(None))
               if kind == "search"]
    assert default[0] == "near"


def test_a_sentence_after_the_pieces_beside_is_written_after_them():
    sequence = asked(reordered("own_place", "beside", "search_sentence",
                               "search"))
    kinds = [kind for kind, _ in sequence]
    assert kinds.index("phrase") > kinds.index("search")
    assert sequence[1] == ("search", "near")


def test_a_step_that_is_off_sends_no_request_of_its_kind():
    sequence = asked(reordered("own_place", "search_sentence", "beside",
                               "search", off=("beside",)))
    assert ("search", "near") not in sequence
    assert ("search", "found") in sequence
    sequence = asked(reordered("own_place", "search_sentence", "beside",
                               "search", off=("search_sentence",)))
    assert all(kind != "phrase" for kind, _ in sequence)


def test_a_coordinate_whose_search_is_off_ends_exhausted():
    model = Model(find=lambda p, n: {"found": [{"at": "3.2",
                                                "words": "1.200"}]}
                  if p["passage"]["kind"] == "table" else {"found": []})
    arrangement = reordered("own_place", "search_sentence", "beside",
                            "search", off=("search",))
    reads = Reader(SPEC, model.asks(), in_order,
                   arrangement=arrangement)(plan_of(TEXT, TABLE, *MANY),
                                            [ENERGY])
    (claim,) = [claim for read in reads for claim in read.claims]
    assert claim["carrier_state"] == addressed.EXHAUSTED
    assert all(noted.get("shows") != "found"
               for _, noted in model.of("search"))


@pytest.mark.parametrize("change, said", [
    (lambda steps: steps.insert(2, steps.pop(
        [s["id"] for s in steps].index("figures"))), "keeps its place"),
    (lambda steps: steps.insert(0, steps.pop(
        [s["id"] for s in steps].index("finds"))), "finds stands before"),
    (lambda steps: steps.insert(
        [s["id"] for s in steps].index("finds"), steps.pop(
            [s["id"] for s in steps].index("coordinates"))),
     "coordinates stands before finds"),
    (lambda steps: steps[[s["id"] for s in steps].index("finds")].update(
        off=True), "finds cannot be off"),
    (lambda steps: coordinate_frame(steps).update(steps=[
        {**s} for s in sorted(coordinate_frame(steps)["steps"],
                              key=lambda s: {"own_place": 0,
                                             "search_sentence": 1,
                                             "plan_years": 2}.get(
                                  s["id"], 3))]),
     "plan_years stands between the steps of the search"),
    (lambda steps: coordinate_frame(steps)["steps"].append(
        coordinate_frame(steps)["steps"].pop(0)), "own_place keeps its place"),
    (lambda steps: steps.pop(), "stands 0 times"),
])
def test_an_arrangement_the_code_cannot_run_is_refused_with_its_reason(
        change, said):
    steps = default_steps()
    assert flow.arrangement_problems(steps) == []
    change(steps)
    problems = flow.arrangement_problems(steps)
    assert any(said in problem for problem in problems), problems


def test_the_two_checks_stay_with_every_step_that_can_be_off_off():
    steps = default_steps()
    for _, step in flow._walk(steps):
        if flow.BLOCKS[step["id"]].switch:
            step["off"] = True
    assert flow.arrangement_problems(steps) == []
    finds = iter([{"found": [{"at": "9.2", "words": "1.200"}]},
                  {"found": []}])
    model = Model(find=lambda p, n: next(finds, {"found": []}))
    reads = Reader(SPEC, model.asks(), in_order,
                   arrangement=flow.arranged(steps))(plan_of(TABLE), [ENERGY])
    assert not [claim for read in reads for claim in read.claims]
    assert reads[0].failed == {addressed.NOT_AN_ADDRESS: 1}


def test_a_profile_s_own_steps_are_read_and_one_that_cannot_run_refused(
        tmp_path):
    steps = default_steps()
    frame = coordinate_frame(steps)
    frame["steps"] = [frame["steps"][0], frame["steps"][2],
                      frame["steps"][1], *frame["steps"][3:]]
    good = tmp_path / "flow.json"
    good.write_text(json.dumps({"steps": steps}), encoding="utf-8")
    read = flow.parse(good.read_text(encoding="utf-8"), good, False)
    assert flow.arranged(read["steps"]).coordinate[:2] == ("beside",
                                                           "search_sentence")
    steps.insert(0, steps.pop([s["id"] for s in steps].index("compute")))
    good.write_text(json.dumps({"steps": steps}), encoding="utf-8")
    with pytest.raises(flow.FlowError, match="compute"):
        flow.parse(good.read_text(encoding="utf-8"), good, False)


def test_a_document_step_that_is_off_sends_no_request_of_its_kind():
    once = SPEC.by_uri["energy"]
    steps = default_steps()
    for step in steps:
        if step["id"] == "document_fields":
            step["off"] = True
    model = Model(docfield=lambda p, n: {"found": []})
    field = type(once)(**{**once.__dict__, "once_per_document": True}) \
        if hasattr(once, "__dict__") else once
    Reader(SPEC, model.asks(), in_order,
           arrangement=flow.arranged(steps))(plan_of(TEXT, TABLE), [field])
    assert model.of("docfield") == []
    model = Model(docfield=lambda p, n: {"found": []})
    Reader(SPEC, model.asks(), in_order)(plan_of(TEXT, TABLE), [field])
    assert model.of("docfield")
