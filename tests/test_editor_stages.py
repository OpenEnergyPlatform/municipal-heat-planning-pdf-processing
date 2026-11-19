"""The Stages tab (owner request 2026-11-19, point A1 of the review of that
day: "ein sechster Reiter oder ein Eintrag im Ablauf-Reiter zeigt die
Stufen 1 bis 6 als Bild"; and A3: the measured sentences hold for the
request logs of stages 4 and 5 too).

Each promise is held against a case that breaks it by construction:

1. Every stage names the group of its rules on the tab "stages", AND every
   rule of that tab belongs to exactly one stage.
2. Every prompt of the stages' folders is shown at a stage, AND every prompt
   a stage names is one the profile has or one no profile has yet.
3. What a stage's request logs say is counted with each reply read as the
   stage reads it: a reply without its key is lost, not read; the sentences
   are said at the number of attempts the stage's rule allows.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from docpipe import rules
from docpipe.editor import measured, prompts, requests as recorded, \
    stagespage
from docpipe.profile import load_profile

PROFILES = [load_profile(name) for name in ("default", "kwp", "scenarios")]


# -- 1. the rules of each stage --------------------------------------------------------

def test_every_rule_of_the_tab_belongs_to_exactly_one_stage():
    groups = [stagespage.group_of(stage) for stage in stagespage.STAGES]
    assert len(set(groups)) == len(groups)
    for profile in PROFILES:
        for one in rules.of_tab("stages", profile):
            assert one.group in groups, (one.name, one.group)
    # a rule of another group on the tab would belong to no stage
    stray = SimpleNamespace(group="Stage 9: nowhere")
    assert stray.group not in groups


def test_the_view_counts_each_stages_rules_and_prompts():
    profile = load_profile("kwp")
    shown = stagespage.view(profile, lambda stage: [])
    by_key = {stage["key"]: stage for stage in shown["stages"]}
    for stage in stagespage.STAGES:
        group = stagespage.group_of(stage)
        assert by_key[stage["key"]]["rules"] == sum(
            one.group == group for one in rules.of_tab("stages", profile))
    assert [stage["n"] for stage in shown["stages"]] == [1, 2, 3, 4, 5, 6]
    assert "visuals/table_user" in by_key["visuals"]["prompts"]
    assert "refinement/split" in by_key["refine"]["prompts"]
    assert by_key["visuals"]["log"] == "visuals"
    assert by_key["layout"]["log"] is None


# -- 2. the prompts of each stage ------------------------------------------------------------

def test_every_prompt_of_the_stages_folders_is_shown_at_a_stage():
    for profile in PROFILES:
        listed = {one["id"] for one in prompts.listing(profile)}
        shown = {one for stage in stagespage.STAGES
                 for one in stagespage.prompts_of(stage, listed)}
        for one in listed:
            if one.split("/")[0] in ("preprocessing", "refinement",
                                     "visuals"):
                assert one in shown, (profile.name, one)


def test_a_prompt_the_profile_lacks_is_not_shown():
    stage = {"prompts": ("preprocessing/page_transcribe",
                         "preprocessing/nowhere")}
    assert stagespage.prompts_of(stage, {"preprocessing/page_transcribe"}) \
        == ["preprocessing/page_transcribe"]


# -- 3. what the logs say ------------------------------------------------------------------

def request(kind, answer, attempt=1):
    shape = {"type": "json_schema", "json_schema": {"name": "t", "schema": {
        "type": "object", "properties": {"rows": {"type": "array"}},
        "required": ["rows"]}}}
    return {"t": f"{kind}_ask", "doc": "d1", "attempt": attempt,
            "made": {"system": [{"prompt": "visuals/table_system"}],
                     "user": [{"data": True}]},
            "input": {"messages": [{"role": "system", "content": "s"},
                                   {"role": "user", "content": "u"}],
                      "response_format": shape},
            "output": {"content": answer, "finish": "stop"}}


def test_a_reply_without_its_key_is_lost_and_the_sentences_follow_the_rule():
    profile = load_profile("kwp")
    events = [request("table", json.dumps({"rows": ["| a |"]})),
              request("table", json.dumps({"caption": "x"})),
              request("table", json.dumps({"rows": []}), attempt=2)]
    trace = recorded.Trace("d1/visuals.trace.jsonl.gz", events, profile)
    assert [r["check"] for r in trace.requests] == [
        "taken", "unreadable: missing_key", "taken"]
    found = measured.facts(trace.requests)
    assert found["read"] == {1: 1, 2: 1}
    assert found["unreadable"] == {"missing_key": 1}
    said = stagespage.says(profile, "visuals", [found])
    assert said["requests"] == 3 and said["attempts"] == "vision_max_attempts"
    allowed = rules.load(profile).get("vision_max_attempts")
    assert isinstance(allowed, int) and allowed >= 1
    assert any("could not be read" in one for one in said["says"])
    assert said["allowed"] == allowed
