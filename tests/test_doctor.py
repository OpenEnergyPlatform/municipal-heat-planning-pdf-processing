"""What the doctor sees of a setup that the stages find out hours in.

The promise, in one sentence: the doctor says, one line each and without ever
raising, whether the context a server offers holds what each stage needs,
whether the server takes the request fields the stages send, whether the
embedding model and dimension the database records are those queries use, and
whether the profile holds each stage's prompts and wording; and with
--offline it asks no server and says what it skipped.

Every AND is its own test below, and each has a case built to violate it: a
window one token short, a server that refuses the fields, a database built by
another model, a prompt that is not there, a table with an entry the stage
requires and the profile never wrote.
"""
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import doctor, llm_preflight, prompts
from docpipe.doctor import FAIL, OK, SKIP, WARN, Asked, Check
from docpipe.profile import Profile, load_profile
from docpipe.providers import base
from docpipe.refinement import config as refine_config
from docpipe.store import schema as store_schema
from docpipe.visuals import config as visuals_config


@pytest.fixture
def kwp():
    return load_profile("kwp")


def _server(role="llm", window=32768, served=True, model="m"):
    """What the endpoint line found of one role's server."""
    line = Check("endpoint", role, OK if served else FAIL, "stand-in")
    return Asked(role, "http://x/v1", "k", model, line, window, served)


def _by_name(checks):
    return {check.name: check for check in checks}


# ---------------------------------------------------------------------------
# What the endpoint line keeps for the lines after it
# ---------------------------------------------------------------------------

def test_the_endpoint_line_keeps_the_window_and_whether_the_model_is_served(
        monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda *a, **k: (["m"], 4096))
    asked = doctor._asked("llm", "http://x/v1", "k", "m")
    assert (asked.check.status, asked.window, asked.served) == (OK, 4096, True)
    other = doctor._asked("llm", "http://x/v1", "k", "not-served")
    assert (other.check.status, other.window, other.served) == (
        FAIL, 4096, False)


def test_a_client_that_cannot_be_built_is_a_failed_line_and_not_a_crash(
        monkeypatch):
    def broken(base_url, api_key, timeout=30.0, role="llm"):
        raise ValueError("no key for this API")

    monkeypatch.setattr(llm_preflight, "serving_limits", broken)
    asked = doctor._asked("llm", "http://x/v1", "k", "m")
    assert asked.check.status == FAIL and not asked.served
    assert "ValueError: no key for this API" in asked.check.detail
    assert "llm.provider" in asked.check.hint


# ---------------------------------------------------------------------------
# The context a stage needs against the context the server offers
# ---------------------------------------------------------------------------

def test_a_window_that_holds_the_budget_passes_and_one_token_less_fails(kwp):
    need = refine_config.max_request_tokens()
    fits = _by_name(doctor.check_context("refine", kwp, [_server(window=need)]))
    assert fits["refine"].status == OK
    assert str(need) in fits["refine"].detail
    short = _by_name(doctor.check_context(
        "refine", kwp, [_server(window=need - 1)]))["refine"]
    assert short.status == FAIL
    assert f"needs {need} tokens per request" in short.detail
    assert f"the server offers {need - 1}" in short.detail
    assert "--max-model-len" in short.hint and str(need) in short.hint


def test_the_budget_is_the_one_the_stage_computes(kwp, monkeypatch):
    """Not a number the doctor works out again: change what the stage says
    and the line follows. A copy of the sum would not."""
    monkeypatch.setattr(refine_config, "max_request_tokens", lambda: 1234)
    monkeypatch.setattr(visuals_config, "max_request_tokens", lambda: 2345)
    from docpipe.extraction import runner
    monkeypatch.setattr(runner, "context_budget", lambda prompt, spec=None: 3456)
    lines = _by_name(doctor.check_context(
        None, kwp, [_server("llm", 10 ** 6), _server("vlm", 10 ** 6)]))
    assert "needs 1234 tokens" in lines["refine"].detail
    assert "needs 2345 tokens" in lines["visuals"].detail
    assert "needs 3456 tokens" in lines["extract"].detail
    assert "needs 3456 tokens" in lines["extract --review"].detail


def test_the_extraction_budget_is_its_harvests_own(kwp):
    from docpipe.extraction import runner
    spec = runner.load_spec(Path(kwp.component("extraction", "SPEC_PATH")))
    need = runner.context_budget(
        prompts.load(runner.HARVEST_PROMPT_ID, kwp), spec)
    line = _by_name(doctor.check_context(
        "extract", kwp, [_server(window=need - 1)]))["extract"]
    assert line.status == FAIL and f"needs {need} tokens" in line.detail


def test_each_stage_is_held_to_the_window_of_its_own_role(kwp):
    """The vision stage runs on the vision server: a text server with room to
    spare says nothing about it."""
    lines = _by_name(doctor.check_context(
        None, kwp, [_server("llm", 10 ** 6), _server("vlm", 100)]))
    assert lines["visuals"].status == FAIL
    assert "the server offers 100" in lines["visuals"].detail
    assert {lines[name].status for name in
            ("refine", "extract", "extract --review")} == {OK}


def test_a_role_nobody_asked_about_has_no_line(kwp):
    lines = _by_name(doctor.check_context(None, kwp, [_server("llm")]))
    assert "visuals" not in lines and "refine" in lines


def test_a_server_that_reports_no_window_is_a_warning_with_the_number_needed(
        kwp):
    need = refine_config.max_request_tokens()
    line = _by_name(doctor.check_context(
        "refine", kwp, [_server(window=None)]))["refine"]
    assert line.status == WARN and "does not report" in line.detail
    assert str(need) in line.detail and str(need) in line.hint
    assert "start it" in line.hint


def test_a_hosted_api_that_reports_no_window_is_not_told_to_start_it(
        kwp, monkeypatch):
    """No hosted API says its context, so this is the line every hosted
    setup gets: a hint to start a server would be wrong for all of them."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    need = refine_config.max_request_tokens()
    line = _by_name(doctor.check_context(
        "refine", kwp, [_server(window=None)]))["refine"]
    assert line.status == WARN and "does not report" in line.detail
    assert str(need) in line.hint and "llm.model" in line.hint
    assert "start it" not in line.hint
    assert "--max-model-len" not in line.hint


def test_a_server_that_was_not_read_is_not_compared_and_says_so(kwp):
    line = _by_name(doctor.check_context(
        "refine", kwp, [_server(window=None, served=False)]))["refine"]
    assert line.status == SKIP
    assert "not compared" in line.detail
    assert str(refine_config.max_request_tokens()) in line.detail


def test_a_hosted_model_is_told_to_change_the_model_not_the_flag(
        kwp, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    line = _by_name(doctor.check_context(
        "refine", kwp, [_server(window=1000)]))["refine"]
    assert line.status == FAIL
    assert "llm.model" in line.hint and "--max-model-len" not in line.hint


def test_the_stage_named_is_the_only_stage_looked_at(kwp):
    servers = [_server("llm"), _server("vlm")]
    assert list(_by_name(doctor.check_context("visuals", kwp, servers))) == [
        "visuals"]
    assert list(_by_name(doctor.check_context("chat", kwp, servers))) == []
    assert "refine" in _by_name(doctor.check_context(None, kwp, servers))


def test_a_stage_that_cannot_say_what_it_needs_is_a_failed_line_not_a_crash(
        kwp, monkeypatch):
    def broken():
        raise RuntimeError("the prompt is half written")

    monkeypatch.setattr(refine_config, "max_request_tokens", broken)
    lines = _by_name(doctor.check_context(None, kwp, [_server()]))
    assert lines["refine"].status == FAIL
    assert "RuntimeError: the prompt is half written" in lines["refine"].detail
    assert lines["extract"].status == OK        # the rest is still looked at


def test_a_profile_with_no_extraction_skips_the_extraction_budget(tmp_path):
    bare = Profile(name="probe", home=tmp_path)
    lines = _by_name(doctor.check_context("extract", bare, [_server()]))
    assert lines["extract"].status == lines["extract --review"].status == SKIP
    assert "no extraction" in lines["extract"].detail


def test_without_a_profile_no_budget_is_asked_for():
    (line,) = doctor.check_context(None, None, [_server()])
    assert (line.name, line.status) == ("all", SKIP)


def test_offline_the_context_lines_say_they_were_skipped(kwp):
    (line,) = doctor.check_context(None, kwp, [], skipped="--offline")
    assert (line.area, line.name, line.status, line.detail) == (
        "context", "all", SKIP, "--offline")


# ---------------------------------------------------------------------------
# The request fields the server takes
# ---------------------------------------------------------------------------

def _chat(monkeypatch, create, hosted=False):
    """The server behind llm_preflight: *create* answers the chat request."""
    sent = []

    def answer(**kwargs):
        sent.append(kwargs)
        return create(**kwargs)

    client = base.facade(answer, models=lambda: NS(data=[NS(id="m")]))
    monkeypatch.setattr(llm_preflight.providers, "client",
                        lambda role, **kw: client)
    if hosted:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
    else:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
    return sent


class _Status(Exception):
    def __init__(self, status_code, message="refused"):
        super().__init__(message)
        self.status_code = status_code


def _raises(error):
    def create(**kwargs):
        raise error
    return create


def test_a_server_that_takes_the_fields_passes_with_the_fields_named(
        monkeypatch):
    sent = _chat(monkeypatch, lambda **kw: base.reply("ok", "length"))
    (line,) = doctor.check_request(None, [_server()])
    assert line.status == OK and "m accepts" in line.detail
    assert "reasoning_effort" in line.detail
    assert sent[0]["extra_body"] == llm_preflight.request_extras()


def test_a_server_that_refuses_the_fields_is_a_failure_with_the_variable_to_set(
        monkeypatch):
    _chat(monkeypatch, _raises(_Status(400, "unknown field reasoning_effort")))
    (line,) = doctor.check_request(None, [_server()])
    assert line.status == FAIL
    assert "refuses the reasoning settings" in line.detail
    assert "LLM_REASONING_EFFORT=off" in line.hint
    assert "unknown field reasoning_effort" in line.hint


def test_a_server_that_does_not_answer_is_no_verdict_and_never_accepted(
        monkeypatch):
    """The probe returned without a refusal: that is not "accepted", and a
    line that said so would be the failure the doctor is there to find."""
    _chat(monkeypatch, _raises(_Status(503, "overloaded")))
    (line,) = doctor.check_request(None, [_server()])
    assert line.status == WARN
    assert line.detail.startswith("no verdict") and "overloaded" in line.detail
    assert "accepts" not in line.detail


def test_a_rate_limited_server_is_no_verdict_either(monkeypatch):
    _chat(monkeypatch, _raises(_Status(429, "slow down")))
    (line,) = doctor.check_request(None, [_server()])
    assert line.status == WARN


def test_a_hosted_model_is_asked_inside_a_reply_schema(monkeypatch):
    sent = _chat(monkeypatch, lambda **kw: base.reply('{"ok": true}', "stop"),
                 hosted=True)
    (line,) = doctor.check_request(None, [_server()])
    assert line.status == OK and "reply schema" in line.detail
    assert sent[0]["response_format"]["type"] == "json_schema"


def test_a_hosted_model_that_does_not_answer_in_the_schema_fails(monkeypatch):
    _chat(monkeypatch, lambda **kw: base.reply("Sure, here you go", "stop"),
          hosted=True)
    (line,) = doctor.check_request(None, [_server()])
    assert line.status == FAIL and "reply schema" in line.detail


def test_a_server_whose_endpoint_failed_is_not_probed(monkeypatch):
    sent = _chat(monkeypatch, lambda **kw: base.reply("ok", "length"))
    (line,) = doctor.check_request(None, [_server(served=False)])
    assert line.status == SKIP and sent == []


def test_every_server_asked_gets_a_line_of_its_own_role(monkeypatch):
    _chat(monkeypatch, lambda **kw: base.reply("ok", "length"))
    lines = doctor.check_request(None, [_server("llm"), _server("vlm")])
    assert [line.name for line in lines] == ["llm", "vlm"]


def test_a_probe_that_breaks_is_a_line_and_not_a_crash(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the client is wrong")

    monkeypatch.setattr(llm_preflight, "assert_request_accepted", broken)
    (line,) = doctor.check_request(None, [_server()])
    assert line.status == FAIL and "the client is wrong" in line.detail


@pytest.mark.parametrize("stage, probed", [
    (None, True), ("refine", True), ("extract", True), ("visuals", True),
    ("chat", False), ("chunk", False)])
def test_only_the_commands_that_send_the_fields_probe_them(
        monkeypatch, stage, probed):
    """The chat sends no reasoning settings: a server it talks to is not
    failed for refusing what the chat never sends."""
    sent = _chat(monkeypatch, _raises(_Status(400, "unknown field")))
    lines = doctor.check_request(stage, [_server()])
    assert bool(lines) is probed
    assert bool(sent) is probed


def test_offline_the_request_line_says_it_was_skipped(monkeypatch):
    sent = _chat(monkeypatch, lambda **kw: base.reply("ok", "length"))
    (line,) = doctor.check_request(None, [], skipped="--offline")
    assert (line.area, line.name, line.status, line.detail) == (
        "request", "all", SKIP, "--offline")
    assert sent == []


# ---------------------------------------------------------------------------
# The embedding model and dimension of the index against the queries'
# ---------------------------------------------------------------------------

@pytest.fixture
def queries(monkeypatch):
    """The model and dimension queries are embedded with."""
    from docpipe.embedding import config
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "model-q")
    monkeypatch.setattr(config, "EMBEDDING_DIM", 8)


def _built(tmp_path, model=None, dim=None):
    """A profile whose database records what built its index."""
    profile = Profile(name="probe", data_root=tmp_path)
    with sqlite3.connect(profile.db_path) as conn:
        store_schema.apply(conn)
        if model is not None:
            store_schema.note_embedding(conn, model, dim, "local", 512, "0.1")
    return profile


def test_an_index_built_as_queries_are_embedded_passes(tmp_path, queries):
    lines = _by_name(doctor.check_embedding(None, _built(tmp_path,
                                                         "model-q", 8)))
    assert (lines["model"].status, lines["dimension"].status) == (OK, OK)
    assert "model-q" in lines["model"].detail
    assert "8 dimensions" in lines["dimension"].detail


def test_an_index_built_by_another_model_fails_naming_both(tmp_path, queries):
    lines = _by_name(doctor.check_embedding(None, _built(tmp_path,
                                                         "model-old", 8)))
    assert lines["model"].status == FAIL
    assert "model-old" in lines["model"].detail
    assert "model-q" in lines["model"].detail
    assert "embedding.model" in lines["model"].hint
    assert lines["dimension"].status == OK         # the two are asked apart


def test_an_index_of_another_length_fails_with_both_lengths(tmp_path, queries):
    lines = _by_name(doctor.check_embedding(None, _built(tmp_path,
                                                         "model-q", 4096)))
    assert lines["dimension"].status == FAIL
    assert "4096" in lines["dimension"].detail
    assert "8" in lines["dimension"].detail
    assert "embedding.dim" in lines["dimension"].hint
    assert lines["model"].status == OK


def test_a_database_that_records_nothing_is_a_warning_not_a_pass(
        tmp_path, queries):
    lines = _by_name(doctor.check_embedding(None, _built(tmp_path)))
    assert lines["model"].status == lines["dimension"].status == WARN
    assert "records no embedding model" in lines["model"].detail
    assert "chunk" in lines["model"].hint


def test_no_database_means_the_comparison_is_skipped(tmp_path, queries):
    profile = Profile(name="probe", data_root=tmp_path)
    lines = doctor.check_embedding(None, profile)
    assert [line.status for line in lines] == [SKIP, SKIP]
    assert "does not exist" in lines[0].detail


def test_a_database_that_cannot_be_read_fails_and_the_doctor_goes_on(
        tmp_path, queries):
    profile = Profile(name="probe", data_root=tmp_path)
    profile.db_path.write_bytes(b"this is not a database" * 100)
    lines = _by_name(doctor.check_embedding(None, profile))
    assert lines["model"].status == lines["dimension"].status == FAIL


def test_the_comparison_reads_the_file_so_it_needs_no_server(tmp_path, queries,
                                                             monkeypatch):
    monkeypatch.setattr(llm_preflight, "serving_limits", lambda *a, **k:
                        pytest.fail("a server was asked"))
    assert doctor.check_embedding(None, _built(tmp_path, "model-q", 8))


@pytest.mark.parametrize("stage, looked_at", [
    (None, True), ("chat", True), ("extract", True), ("chunk", True),
    ("refine", False), ("visuals", False), ("ingest", False)])
def test_only_the_commands_that_embed_or_search_look_at_the_index(
        tmp_path, queries, stage, looked_at):
    lines = doctor.check_embedding(stage, _built(tmp_path, "model-q", 8))
    assert bool(lines) is looked_at


# ---------------------------------------------------------------------------
# What the profile holds for each stage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_the_profiles_the_package_ships_hold_what_their_stages_ask(name):
    lines = doctor.check_stages(None, load_profile(name))
    failed = [line for line in lines if line.status == FAIL]
    assert not failed, failed
    assert {line.name for line in lines if line.area == "prompts"} == set(
        doctor.PROMPTED)


def test_a_prompt_that_is_not_there_is_named_with_how_many_are_missing(
        tmp_path):
    """Built to fail: a profile of the name kwp whose prompts folder holds one
    of the eight extraction prompts."""
    kept = tmp_path / "prompts" / "extraction"
    kept.mkdir(parents=True)
    (kept / "harvest.md").write_text("only this one", encoding="utf-8")
    profile = Profile(name="kwp", home=tmp_path)
    lines = _by_name([c for c in doctor.check_stages("extract", profile)
                      if c.area == "prompts"])
    line = lines["extract"]
    assert line.status == FAIL
    assert line.detail.startswith("7 of 8 prompt(s) missing")
    assert "extraction/field" in line.detail
    assert "extraction/harvest" not in line.detail
    assert str(tmp_path / "prompts") in line.hint


def test_a_stage_that_has_all_its_prompts_says_how_many(kwp):
    line = _by_name(doctor.check_stages("chat", kwp))["chat"]
    assert line.status == OK and line.detail == "15 prompt(s) found"


def test_a_prompt_that_is_there_but_cannot_be_read_fails_as_one_that_is_not(
        tmp_path):
    """The stage reads its prompts with the loader, and a file whose front
    matter is no mapping stops it at the first request as a missing one
    does. A file that merely exists would pass a check of the path."""
    from docpipe.refinement import config
    folder = tmp_path / "prompts" / "refinement"
    folder.mkdir(parents=True)
    broken, *fine = (prompt_id.partition("/")[2]
                     for prompt_id in config.PROMPT_IDS)
    (folder / f"{broken}.md").write_text("---\n- not a mapping\n---\nbody",
                                         encoding="utf-8")
    for name in fine:
        (folder / f"{name}.md").write_text("a prompt", encoding="utf-8")
    profile = Profile(name="probe", home=tmp_path)
    line = _by_name(doctor.check_stages("refine", profile))["refine"]
    assert line.status == FAIL
    assert f"1 of {len(config.PROMPT_IDS)} prompt(s) cannot be read" in line.detail
    assert f"refinement/{broken}" in line.detail
    assert "front matter must be a mapping" in line.detail
    assert "missing" not in line.detail
    assert "front matter" in line.hint


def test_missing_and_unreadable_prompts_are_both_said(tmp_path):
    from docpipe.refinement import config
    folder = tmp_path / "prompts" / "refinement"
    folder.mkdir(parents=True)
    first, second = (prompt_id.partition("/")[2]
                     for prompt_id in config.PROMPT_IDS)
    (folder / f"{first}.md").write_text("---\n- x\n---\nbody",
                                        encoding="utf-8")
    line = _by_name(doctor.check_stages(
        "refine", Profile(name="probe", home=tmp_path)))["refine"]
    assert line.status == FAIL
    assert f"refinement/{second}" in line.detail and "missing" in line.detail
    assert "cannot be read" in line.detail
    assert str(tmp_path / "prompts") in line.hint


def test_a_prompt_the_profile_extends_into_is_found_there(tmp_path):
    inherits = Profile(name="probe", home=tmp_path, extends="kwp")
    lines = [c for c in doctor.check_stages("refine", inherits)
             if c.area == "prompts"]
    assert [c.status for c in lines] == [OK]


def test_a_profile_with_no_extraction_skips_extraction_and_not_the_rest(
        tmp_path):
    bare = Profile(name="probe", home=tmp_path)
    lines = doctor.check_stages("extract", bare)
    assert {(c.area, c.name): c.status for c in lines} == {
        ("prompts", "extract"): SKIP, ("wording", "extraction.PHRASES"): SKIP}
    (compile_line,) = doctor.check_stages("compile", bare)
    assert compile_line.status == SKIP


def test_a_profile_that_wrote_no_table_for_the_chat_fails_it(tmp_path):
    lines = _by_name(doctor.check_stages("chat", Profile(name="probe",
                                                         home=tmp_path)))
    assert lines["inference.PHRASES"].status == FAIL
    assert "inference.PHRASES" in lines["inference.PHRASES"].detail
    assert lines["inference.UI"].status == FAIL


def test_an_entry_the_stage_requires_and_the_profile_lacks_is_named(
        kwp, monkeypatch):
    """The stage's own check decides, and it names the entry: add one to
    what the extraction stage requires and the line fails with it."""
    from docpipe.extraction import wording
    monkeypatch.setattr(wording, "_checked", {})
    monkeypatch.setattr(wording, "REQUIRED",
                        wording.REQUIRED | {"a_phrase_nobody_wrote"})
    line = _by_name(doctor.check_stages("extract", kwp))["extraction.PHRASES"]
    assert line.status == FAIL and "a_phrase_nobody_wrote" in line.detail
    assert line.hint


def test_the_chat_phrases_and_labels_are_held_to_what_the_chat_requires(
        kwp, monkeypatch):
    from docpipe.inference import wording
    monkeypatch.setattr(wording, "_checked", {})
    monkeypatch.setattr(wording, "_ui_checked", {})
    monkeypatch.setattr(wording, "REQUIRED",
                        wording.REQUIRED | {"a_guide_nobody_wrote"})
    monkeypatch.setattr(wording, "UI_REQUIRED",
                        wording.UI_REQUIRED | {"a_label_nobody_wrote"})
    lines = _by_name(doctor.check_stages("chat", kwp))
    assert "a_guide_nobody_wrote" in lines["inference.PHRASES"].detail
    assert "a_label_nobody_wrote" in lines["inference.UI"].detail
    assert lines["inference.PHRASES"].status == FAIL
    assert lines["inference.UI"].status == FAIL


def test_the_graph_route_is_checked_where_the_profile_has_one(kwp, monkeypatch):
    line = _by_name(doctor.check_stages("chat", kwp))["graph route"]
    assert line.status == OK and "5 reason(s) worded" in line.detail
    from docpipe.inference import kg_route

    def lacking(profile):
        raise LookupError("profile 'kwp' has kg.VALUE_QUERY and lacks "
                          "['label_of']")

    monkeypatch.setattr(kg_route, "hooks", lacking)
    broken = _by_name(doctor.check_stages("chat", kwp))["graph route"]
    assert broken.status == FAIL and "label_of" in broken.detail


def test_a_profile_that_answers_from_no_graph_skips_the_route():
    line = _by_name(doctor.check_stages("chat", load_profile("scenarios")))[
        "graph route"]
    assert line.status == SKIP and "no graph route" in line.detail


def test_the_stage_named_is_the_only_stage_looked_at_for_the_profile(kwp):
    names = {(c.area, c.name) for c in doctor.check_stages("refine", kwp)}
    assert names == {("prompts", "refine")}
    names = {(c.area, c.name) for c in doctor.check_stages("extract", kwp)}
    assert names == {("prompts", "extract"), ("wording", "extraction.PHRASES")}


def test_without_a_profile_nothing_is_looked_at_and_it_says_so():
    lines = doctor.check_stages(None, None)
    assert [(c.area, c.status) for c in lines] == [("prompts", SKIP),
                                                   ("wording", SKIP)]


def test_a_stage_whose_package_is_missing_is_a_warning_not_a_failure(
        kwp, monkeypatch):
    def missing(stage):
        raise ModuleNotFoundError("No module named 'cv2'", name="cv2")

    monkeypatch.setattr(doctor, "_prompt_ids", missing)
    line = _by_name(doctor.check_stages("preprocess", kwp))["preprocess"]
    assert line.status == WARN and "needs the package cv2" in line.detail


@pytest.mark.parametrize("name", ["docpipe.nowhere", "profiles.kwp.nowhere"])
def test_a_module_of_our_own_that_is_missing_is_a_failure_not_a_package(
        kwp, monkeypatch, name):
    """A broken installation or a broken profile would otherwise read as a
    package to install."""
    def missing(stage):
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr(doctor, "_prompt_ids", missing)
    line = _by_name(doctor.check_stages("preprocess", kwp))["preprocess"]
    assert line.status == FAIL and name in line.detail


# The lists the doctor reads are the stages' whole lists.

# stage: (the folder of the code that loads them, the folder of the prompts)
STAGE_PROMPTS = {"preprocess": ("preprocessing", "preprocessing"),
                 "refine": ("refinement", "refinement"),
                 "visuals": ("visuals", "visuals"),
                 "extract": ("extraction", "extraction"),
                 "chat": ("inference", "inference"),
                 "compile": ("compile", "extraction")}


def test_every_stage_that_loads_prompts_is_one_the_doctor_looks_at():
    assert sorted(STAGE_PROMPTS) == sorted(doctor.PROMPTED)


@pytest.mark.parametrize("stage", sorted(STAGE_PROMPTS))
def test_the_prompts_a_stage_declares_are_the_prompts_its_code_loads(stage):
    """The doctor reads each stage's own list. A prompt the stage loads and
    its list does not name is one the doctor would never look for."""
    from tests.test_architecture import CORE, _requested_prompt_ids
    code, folder = STAGE_PROMPTS[stage]
    loaded = {pid for pid in _requested_prompt_ids(CORE / code)
              if pid.startswith(folder + "/")}
    declared = set(doctor._prompt_ids(stage))
    unlisted = loaded - declared
    # the refinement lists the prompt in use, of the two it can load
    allowed = ({"refinement/refine", "refinement/refine_corrections"}
               if stage == "refine" else set())
    assert unlisted <= allowed, sorted(unlisted)
    assert declared <= loaded, sorted(declared - loaded)


# ---------------------------------------------------------------------------
# The whole doctor
# ---------------------------------------------------------------------------

@pytest.fixture
def served(monkeypatch, tmp_path):
    """One server, `m`, with a window; counts how it was asked."""
    asked = {"models": [], "probes": []}

    def listing(base_url, api_key, timeout=30.0, role="llm"):
        asked["models"].append(role)
        return ["m"], asked.get("window", 10 ** 6)

    def probe(base_url, api_key, model, *, what="x", role="llm"):
        asked["probes"].append(role)

    monkeypatch.setattr(llm_preflight, "serving_limits", listing)
    monkeypatch.setattr(llm_preflight, "assert_request_accepted", probe)
    monkeypatch.setattr(doctor, "importlib", NS(util=NS(
        find_spec=lambda name: object())))
    for name in ("LLM_PROVIDER", "VLM_PROVIDER", "VLM_BASE_URL",
                 "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("DOCPIPE_DATA_ROOT", str(tmp_path))
    return asked


def test_each_server_is_asked_once_however_many_lines_use_its_answer(served):
    checks = doctor.run(None, offline=False)
    assert served["models"] == ["llm"] and served["probes"] == ["llm"]
    areas = {check.area for check in checks}
    assert {"endpoint", "context", "request", "prompts", "wording"} <= areas


def test_the_chat_alone_asks_its_server_for_models_and_sends_it_no_probe(served):
    checks = doctor.run("chat", offline=False)
    assert served["models"] == ["llm"] and served["probes"] == []
    assert not [c for c in checks if c.area == "request"]


def test_offline_no_server_is_asked_and_each_group_says_it_was_skipped(served):
    checks = doctor.run(None, offline=True)
    assert served["models"] == [] and served["probes"] == []
    skipped = {(c.area, c.name): c for c in checks if c.detail == "--offline"}
    assert set(skipped) == {("endpoint", "all"), ("context", "all"),
                            ("request", "all")}
    assert all(c.status == SKIP for c in skipped.values())
    # what needs no server is still looked at
    assert {c.area for c in checks} >= {"prompts", "wording", "data"}


def test_offline_from_the_command_each_group_that_needs_a_server_says_so(
        tmp_path):
    """The command as a user runs it, with nothing stubbed."""
    from tests.test_cli import _checks, _docpipe
    run = _docpipe("--profile", "kwp", "doctor", "--offline", "--json",
                   cwd=tmp_path, stubs=False,
                   DOCPIPE_DATA_ROOT=str(tmp_path / "data"))
    checks = _checks(run)
    for area in ("endpoint", "context", "request"):
        assert (checks[(area, "all")]["status"],
                checks[(area, "all")]["detail"]) == ("skip", "--offline")
    # and what needs no server was looked at all the same
    assert ("prompts", "extract") in checks
    assert ("wording", "extraction.PHRASES") in checks
    assert ("embedding", "model") in checks
    failed = [c for c in checks.values() if c["status"] == "fail"]
    assert all(c["area"] == "packages" for c in failed), failed


def test_a_window_too_small_for_a_stage_makes_the_doctor_exit_nonzero(
        served, capsys):
    served["window"] = 1000
    assert doctor.main([]) == 1
    printed = capsys.readouterr().out
    assert "context   fail refine: needs" in printed
    assert "the server offers 1000" in printed


def test_a_server_that_refuses_the_fields_makes_the_doctor_exit_nonzero(
        served, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise llm_preflight.PreflightError(
            "http://x/v1 refuses the reasoning settings a stage sends.\n"
            "  unknown field\n  set LLM_REASONING_EFFORT=off")

    monkeypatch.setattr(llm_preflight, "assert_request_accepted", refuse)
    assert doctor.main([]) == 1
    assert "request   fail llm: " in capsys.readouterr().out


def test_a_setup_with_everything_in_place_ends_without_a_failure(served,
                                                                  capsys):
    # no database and no PDFs: warnings, as before the new lines existed
    assert doctor.main([]) == 0
    assert " fail " not in capsys.readouterr().out


def test_every_line_the_doctor_writes_has_a_known_status_and_its_words(served):
    for check in doctor.run(None, offline=False):
        assert check.status in (OK, WARN, FAIL, SKIP), check
        assert check.area and check.name and check.detail, check
        assert isinstance(check.hint, str)


# -------------------------------------------- the chat with no profile named

def test_asked_about_the_chat_with_no_profile_the_doctor_checks_the_built_in_one(
        monkeypatch):
    """The chat answers on the built-in profile when none is named, so a
    failure for the missing name would be a failure of nothing."""
    from docpipe.profile import ENV_VAR
    monkeypatch.delenv(ENV_VAR, raising=False)
    (line,), profile = doctor.check_profile("chat")
    assert line.status == OK and "default" in line.detail
    assert "--profile" in line.hint            # and how to name another
    assert profile is not None and profile.name == "default"
    # its lines are then checked against that profile, not skipped
    chat = [c for c in doctor.check_stages("chat", profile) if c.name == "chat"]
    assert chat and all(c.status != SKIP for c in chat)


@pytest.mark.parametrize("stage", [None, "refine", "visuals", "extract"])
def test_every_other_stage_still_fails_without_a_profile(stage, monkeypatch):
    from docpipe.profile import ENV_VAR
    monkeypatch.delenv(ENV_VAR, raising=False)
    (line,), profile = doctor.check_profile(stage)
    assert line.status == FAIL and line.detail == "no profile named"
    assert profile is None
