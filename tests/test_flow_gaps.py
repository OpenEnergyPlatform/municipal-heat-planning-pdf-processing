"""
test_flow_gaps.py: the gaps of the flow closed on 2026-11-13, each a
promise with a case that breaks it by construction.

1. The box beside shows the value's own piece whole between its
   neighbours only where it is told to, AND with no neighbours (0) only
   the own piece.
2. A field of the whole document that found nothing while pieces were
   never shown to it ends in `parameter_uncombed`, AND one that was shown
   every piece ends in "not stated".
3. A request about a dimension that got no answer in form ends in the
   state of `no_answer`.
4. Compute and catalogue stand before writing the harvest: the check of
   the flow says so where they stand after it, AND the flows of the
   profiles pass.
5. Where the step that asks the works of the pieces did not run (a pass),
   the first value that asks its work asks them once, without the details
   of new works, AND does so while values that wait for them hold every
   thread of the run; not where the drawing's step is off.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import threading
import types

from docpipe import rules
from docpipe.extraction import fields, flow, trust

from test_addressed import SPEC, TABLE, TEXT, plan_of


def test_beside_shows_its_own_piece_only_where_told():
    plan = plan_of(TEXT, TABLE)
    pieces = plan.pieces(False)
    assert len(pieces) >= 2
    own = pieces[0]
    assert own not in plan.beside(own)
    assert plan.beside(own, own=True)[0] is own
    with rules.overlaid(beside_pieces=0):
        assert plan.beside(own) == []
        assert plan.beside(own, own=True) == [own]


def test_a_field_not_shown_every_piece_is_not_said_unstated():
    uri = SPEC.parameters[0].uri
    states = {s["parameter"]: s["state"]
              for s in trust.parameter_states(SPEC, [], [], harvested=1,
                                              answered=1,
                                              uncombed={uri})}
    assert states[uri] == fields.EXHAUSTED
    assert all(state == fields.SAID_UNSTATED
               for other, state in states.items() if other != uri)


def test_no_answer_ends_unanswered():
    assert fields.state_for("no_answer") == fields.UNANSWERED
    assert fields.state_for("parameter_uncombed") == fields.EXHAUSTED


def test_compute_and_catalogue_stand_before_write():
    from docpipe.profile import load_profile
    for name in ("kwp", "scenarios"):
        profile = load_profile(name)
        tree = flow.load(profile).tree
        said = [p["message"] for p in flow.problems(tree, profile=profile)]
        assert not any("write" in m for m in said), said
        top = [n.get("id") for n in tree if isinstance(n, dict)]
        assert top[-1] == "write"
        broken = copy.deepcopy(tree)
        at = top.index("write")
        broken.insert(at - 1 if at else 0, broken.pop(at))
        said = [p["message"] for p in flow.problems(broken,
                                                     profile=profile)]
        assert any("before write" in m or "at the end" in m for m in said)


def works_world(monkeypatch, tree):
    """(the profile's blocks, a question of a value, the run's two threads,
    the calls of the works step, the event it began): a reader whose
    drawing is *tree*, and in place of the works step one that notes
    whether it asked details and asks three pieces the way it is given,
    each answering with the name of its thread."""
    from concurrent.futures import ThreadPoolExecutor
    from docpipe.extraction import runner
    from profiles.scenarios import blocks as scenario
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ahead")
    monkeypatch.setattr(runner, "AHEAD", pool)
    monkeypatch.setattr(runner, "LIMIT", types.SimpleNamespace(maximum=2))
    reader = types.SimpleNamespace(each=runner.run_each)
    reader.engine = types.SimpleNamespace(tree=tree, reader=reader)
    calls, began = [], threading.Event()

    def works(ask, counts, details=True, each=None):
        began.set()
        calls.append((details, (each or reader.each)(
            range(3), lambda _i: threading.current_thread().name)))
    monkeypatch.setattr(scenario, "works", works)
    ask = types.SimpleNamespace(reader=reader, plan=plan_of(TEXT, TABLE))
    return scenario, ask, pool, calls, began


def test_a_pass_asks_the_works_once_while_values_hold_every_thread(
        monkeypatch):
    scenario, ask, pool, calls, began = works_world(
        monkeypatch, [{"id": "works", "box": "ask", "preset": "works"}])
    lock = ask.plan.key_lock(("works",))

    def waiting_value():
        # Another value that asks its work holds the run's other thread
        # while the works are asked; it gives up after five seconds.
        began.wait(5)
        got = lock.acquire(timeout=5)
        if got:
            lock.release()
        return got
    try:
        first = pool.submit(scenario.works_for_pass, ask, None)
        waiting = pool.submit(waiting_value)
        first.result(timeout=30)
        assert waiting.result(timeout=30) is True
    finally:
        pool.shutdown(wait=True)
    assert [details for details, _names in calls] == [False]
    assert not any(name.startswith("ahead") for name in calls[0][1])
    scenario.works_for_pass(ask, None)
    assert len(calls) == 1 and ask.plan.works_built


def test_a_pass_asks_no_works_where_their_step_is_off(monkeypatch):
    scenario, ask, pool, calls, _began = works_world(
        monkeypatch,
        [{"id": "works", "box": "ask", "preset": "works", "off": True}])
    try:
        scenario.works_for_pass(ask, None)
    finally:
        pool.shutdown(wait=True)
    assert calls == [] and ask.plan.works_built
