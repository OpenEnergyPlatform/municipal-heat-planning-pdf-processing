"""Every field a request carries is named in its instruction (owner request
2026-11-19, point C1 of the review of that day; C3 and C4 resolved by it).

The promises, each with a case that breaks it by construction:

1. A field is named by a part of the prompt for it or by its name in quotes
   in what the request is told, AND a field with neither is unnamed.
2. The profile check builds every request of a dry run and passes for both
   profiles, AND it fails, naming the request and the field, where a prompt
   no longer names a field its requests carry.
3. The check of a flow names a step whose answer may carry a field its prompt
   has no word for (the model may ask to see more), AND a step whose prompt
   has the words for it, or that offers nothing, is no problem.
4. The page refuses a prompt that drops the part of a field, AND takes it
   where what every request is told names the field instead.
5. The request of a search sentence shows the field's brief, AND the whole
   description where the rule field_text says so.
6. A search request is told how to fetch only where its answer may fetch,
   AND is told it there.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import re
from types import SimpleNamespace

import pytest

from docpipe import prompts, rules
from docpipe.editor import flowtry
from docpipe.editor import prompts as editor_prompts
from docpipe.extraction import flow as flow_files
from docpipe.extraction import preflight, runner, shows, thread
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import load_profile


@dataclasses.dataclass(frozen=True)
class Prompt:
    id: str
    text: str


def parts_of(text: str) -> thread.Parts:
    return thread.cut(Prompt("test/prompt", text))


# -- 1. named ----------------------------------------------------------------------

def test_a_field_is_named_by_its_part_or_by_its_name_in_quotes():
    parts = parts_of('Read "value".\n\n<!-- with: headings -->\n'
                     'The headings up to the value.\n')
    assert thread.unnamed(parts, ["value", "headings"]) == []
    # the failure by construction: a field with neither
    assert thread.unnamed(parts, ["value", "headings", "before"]) \
        == ["before"]
    # a quote in a part the request is told names a field too
    parts = parts_of('Read.\n\n<!-- with: question -->\n'
                     '"question" asks about "value".\n')
    assert thread.unnamed(parts, ["question", "value"]) == []
    assert thread.unnamed(parts, ["value"]) == ["value"]


def test_what_a_reply_form_offers_is_carried():
    shape = {"json_schema": {"schema": {"properties": {"more": {
        "items": {"properties": {"get": {"enum": ["next"]}}}}}}}}
    assert runner.carried_fields({"value": 1, "conversation": []}, shape) \
        == ["value", "more"]


# -- 2. the profile check ------------------------------------------------------

def spec_of(profile):
    path = profile.component("extraction", "SPEC_PATH")
    return load_spec(json.loads(open(path, encoding="utf-8").read()))


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_every_request_of_a_dry_run_names_what_it_carries(name, monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    profile = load_profile(name)
    with rules.overlaid():
        rules.use(profile)
        ok, detail = preflight.requests_name_their_fields(
            profile, spec_of(profile))
    assert ok, detail


def test_the_check_fails_where_a_prompt_no_longer_names_a_field(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    profile = load_profile("kwp")
    real = flowtry.prompt_files.load

    def without_label(prompt_id, *args, **kwargs):
        got = real(prompt_id, *args, **kwargs)
        if prompt_id == "extraction/phrase":
            got = dataclasses.replace(got, text=got.text.replace(
                '"label"', "label"))
        return got
    monkeypatch.setattr(flowtry.prompt_files, "load", without_label)
    with rules.overlaid():
        rules.use(profile)
        ok, detail = preflight.requests_name_their_fields(
            profile, spec_of(profile))
    assert not ok
    assert re.search(r"phrase: label \(\d+ request", detail)
    assert "description" not in detail


# -- 3. the check of a flow -------------------------------------------------------

def test_a_step_whose_answer_may_fetch_needs_words_for_it(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    profile = load_profile("kwp")
    with rules.overlaid():
        rules.use(profile)
        tree = copy.deepcopy(flow_files.load(profile).tree)
        assert flow_files.prompt_problems(tree, profile) == []
        node = next(n for n, _ in flow_files.walk(tree)
                    if n.get("preset") == "find")
        node.setdefault("set", {})["fetch"] = True
        said = flow_files.prompt_problems(tree, profile)
        assert [p["id"] for p in said] == [node["id"]]
        assert "more" in said[0]["message"]
        # nothing is fetched where the rule fetch_rounds is 0
        node["rules"] = {"fetch_rounds": 0}
        assert flow_files.prompt_problems(tree, profile) == []


def test_a_prompt_with_the_words_for_fetching_is_no_problem():
    default = load_profile("default")
    with rules.overlaid():
        rules.use(default)
        tree = copy.deepcopy(flow_files.load(default).tree)
        node = next(n for n, _ in flow_files.walk(tree)
                    if n.get("preset") == "find")
        node.setdefault("set", {})["fetch"] = True
        assert flow_files.untold_offers(
            node, prompts.load("extraction/find", default)) == []


# -- 4. the page --------------------------------------------------------------------

def test_the_page_refuses_a_prompt_that_drops_the_part_of_a_field(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    profile = load_profile("kwp")
    pid = "extraction/find"
    disk = editor_prompts.on_disk(profile, pid, lambda p: open(p, "rb").read())
    text = disk["raw"]
    part = re.search(r"<!-- with: headings -->\n.*?(?=<!-- with: )", text,
                     re.S)
    dropped = text[:part.start()] + text[part.end():]
    said = editor_prompts.problem(profile, pid, dropped, disk)
    assert said and "headings" in said
    named = dropped.replace(
        "{{example}}", '{{example}}\n\n"headings" are the headings.', 1)
    assert editor_prompts.problem(profile, pid, named, disk) is None


# -- 5. the brief -------------------------------------------------------------------

def test_the_search_sentence_shows_the_brief_of_its_field():
    field = SimpleNamespace(label="Heat demand", description="LONG " * 50,
                            brief="The heat a town needs in a year.")
    with rules.overlaid(field_text="short"):
        assert shows._description(None, field, None) \
            == "The heat a town needs in a year."
    with rules.overlaid(field_text="whole"):
        assert shows._description(None, field, None) == "LONG " * 50
    # a field without a brief shows its description
    plain = SimpleNamespace(label="x", description="what x is", brief=None)
    with rules.overlaid(field_text="short"):
        assert shows._description(None, plain, None) == "what x is"


# -- 6. fetching told where it is offered -------------------------------------

@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_search_request_is_told_to_fetch_only_where_it_may(name):
    profile = load_profile(name)
    with rules.overlaid():
        rules.use(profile)
        parts = thread.cut(prompts.load("extraction/search", profile))
        plain = parts.system({"question", "value", "passages"}).text
        fetching = parts.system({"question", "value", "passages",
                                 "more"}).text
    assert '"more"' not in plain
    assert '"more"' in fetching
