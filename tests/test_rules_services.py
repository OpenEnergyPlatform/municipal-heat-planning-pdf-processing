"""
The rules of the services around the reading (throttle, the check before
the run, the profile check, the calculation's hit lists): each switched
changes what the code does AND the standard gives today's result (owner,
2026-11-11: "alles soll anpassbar sein"). Each test sets a value no
standard has, so a code that kept its own number fails it.
"""
import dataclasses
import json
import threading
import time
from types import SimpleNamespace

import pytest

from docpipe import llm_preflight, rules
from docpipe.extraction import preflight, reading, throttle
from docpipe.profile import load_profile

DEFAULT = rules.default()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for env in rules.ENVS:
        monkeypatch.delenv(env, raising=False)
    rules.reset()
    yield
    rules.reset()


def at_step(box, **values):
    return rules.in_step(rules.stepped({"id": "x", "box": box}, values))


# -- the limit of open requests -----------------------------------------------

class Clock(SimpleNamespace):
    """time for the steering thread: records each wait and then holds the
    thread for good, so it steers once and is seen doing it."""

    def __init__(self):
        super().__init__(time=time.time, monotonic=time.monotonic,
                         perf_counter=time.perf_counter)
        self.slept = []
        self.looked = threading.Event()

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.looked.set()
        threading.Event().wait()


def steered_after(monkeypatch, **values) -> list:
    clock = Clock()
    monkeypatch.setattr(throttle, "time", clock)
    gate = SimpleNamespace(listen=lambda hear: None, closed=lambda: False)
    with rules.overlaid(**values):
        throttle.start_hosted(gate)
        assert clock.looked.wait(5)
    return clock.slept


def test_the_limit_is_steered_as_often_as_its_rule_says(monkeypatch):
    assert steered_after(monkeypatch) == [DEFAULT["limit_poll_s"]]
    assert steered_after(monkeypatch, limit_poll_s=0.25) == [0.25]


def test_the_server_s_metrics_are_read_with_the_timeout_of_the_rule():
    assert throttle.Reader("http://h:8000/v1").timeout \
        == DEFAULT["metrics_timeout_s"] == 3
    with rules.overlaid(metrics_timeout_s=1.5):
        assert throttle.Reader("http://h:8000/v1").timeout == 1.5


# -- the check before the run -------------------------------------------------

def test_the_server_is_asked_for_its_models_with_the_timeout_of_the_rule(
        monkeypatch):
    timeouts = []

    def client(role, **kw):
        timeouts.append(kw["timeout"])
        card = SimpleNamespace(id="m", max_model_len=4096)
        return SimpleNamespace(models=SimpleNamespace(
            list=lambda: SimpleNamespace(data=[card])))

    monkeypatch.setattr(llm_preflight.providers, "client", client)
    assert llm_preflight.serving_limits("http://h/v1", "k") == (["m"], 4096)
    with rules.overlaid(preflight_timeout_s=3):
        llm_preflight.serving_limits("http://h/v1", "k")
    assert timeouts == [DEFAULT["preflight_timeout_s"], 3]
    assert DEFAULT["preflight_timeout_s"] == 30


# -- the profile check --------------------------------------------------------

def test_a_property_left_out_on_purpose_is_one_the_rule_lists(tmp_path):
    scenarios = load_profile("scenarios")
    listed = preflight.left_out_of(scenarios)
    assert ("study", "OEO_00000508") in listed
    home = tmp_path / "scenarios"
    home.mkdir()
    kept = [row for row in DEFAULT_ROWS(scenarios)
            if row["property"] != "OEO_00000508"]
    (home / "rules.json").write_text(
        json.dumps({"rules": {"not_extracted": kept}}), encoding="utf-8")
    other = dataclasses.replace(scenarios, home=home)
    left = preflight.left_out_of(other)
    assert ("study", "OEO_00000508") not in left
    assert len(left) == len(listed) - 1


def DEFAULT_ROWS(profile) -> list:
    return json.loads((profile.package_dir / "rules.json").read_text(
        encoding="utf-8"))["rules"]["not_extracted"]


# -- the hit lists of the calculation -----------------------------------------

def test_a_calculation_is_shown_the_best_of_each_kind_the_rule_names():
    ranked = [SimpleNamespace(owner_kind=kind, n=n)
              for n, kind in enumerate(["section", "table", "section",
                                        "figure", "table", "section"])]
    assert DEFAULT["compute_shown"] == {"section": 15, "table": 20,
                                       "figure": 20}
    assert [hit.n for hit in reading.shown_hits(ranked)] == [0, 1, 2, 3, 4, 5]
    with at_step("compute", compute_shown={"section": 1, "table": 1,
                                           "figure": 0}):
        assert [hit.n for hit in reading.shown_hits(ranked)] == [0, 1]
