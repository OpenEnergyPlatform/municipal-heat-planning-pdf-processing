"""
test_editor_prompts_server.py: what the prompts tab of `docpipe edit`
promises about files, saves, requests and the model.

Each test states one promise and holds a case that breaks it by
construction: a text the loader refuses, a file that moved, a sentence with a
name nobody fills, a click that names too many requests.

Author: Felix Vossel
"""
from __future__ import annotations

import dataclasses
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe import prompts as prompt_files
from docpipe.editor import server, trying
from docpipe.extraction import runner, thread
from docpipe.profile import load_profile

REPO = Path(__file__).resolve().parent.parent
REAL = (REPO / "profiles" / "scenarios" / "prompts",
        REPO / "docpipe" / "builtin" / "default" / "prompts")
COORD = "extraction/coord"
HEADINGS = '"headings" are the publication\'s headings up to the value\'s'


def digests() -> dict:
    return {path: server.sha256(path.read_bytes())
            for folder in REAL for path in sorted(folder.rglob("*"))
            if path.is_file()}


@pytest.fixture(autouse=True)
def real_files_stay(monkeypatch, tmp_path):
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    before = digests()
    yield
    assert digests() == before


@pytest.fixture
def profile(tmp_path):
    # scenarios with its own folder in a temp copy, still extending default
    home = tmp_path / "scenarios"
    shutil.copytree(REAL[0], home / "prompts")
    return dataclasses.replace(load_profile("scenarios"), home=home)


def make_app(tmp_path, profile, harvest=None) -> server.App:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    return server.App(profile, harvest, root)


def get(app, path: str, **query):
    return app.call("GET", path, query, None)


def post(app, path: str, body):
    return app.call("POST", path, {}, body)


def reworded(raw: str) -> str:
    """The text with one word changed."""
    out = raw.replace("Answer the question", "Reply to the question", 1)
    assert out != raw
    return out


def save(app, loaded: dict, raw: str, prompt_id: str = COORD) -> tuple:
    return post(app, "/api/prompt/save",
                {"id": prompt_id, "raw": raw, "base": loaded["sha256"]})


def own_file(profile, prompt_id: str) -> Path:
    return profile.prompts_dir / f"{prompt_id}.md"


def everything(folder: Path) -> dict:
    return {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_a_prompt_the_loader_refuses_is_not_written(tmp_path, profile):
    app = make_app(tmp_path, profile)
    path = own_file(profile, COORD)
    before = path.read_bytes()
    _, loaded = get(app, "/api/prompt", id=COORD)
    status, report = save(app, loaded, loaded["raw"] + "\n{{foo}}\n")
    assert status == 200 and report["reason"] == "check"
    assert "foo" in report["error"]
    assert path.read_bytes() == before
    # by construction the other way: one changed word is written
    assert save(app, loaded, reworded(loaded["raw"]))[1]["saved"] is True
    assert path.read_bytes() != before


def test_a_save_writes_the_text_sent_in_the_files_line_ends(tmp_path,
                                                            profile):
    app = make_app(tmp_path, profile)
    path = own_file(profile, COORD)
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n")
                     .replace(b"\n", b"\r\n"))         # a file with CRLF
    _, loaded = get(app, "/api/prompt", id=COORD)
    assert "\r" not in loaded["raw"]
    raw = reworded(loaded["raw"])
    status, report = save(app, loaded, raw)
    assert report["saved"] is True and "text" not in report
    written = path.read_bytes()
    assert written == raw.replace("\n", "\r\n").encode("utf-8")
    assert written.count(b"\n") == written.count(b"\r\n")
    assert report["sha256"] == server.sha256(written)
    assert report["path"] == app.shown(path)


def test_a_prompt_that_moved_on_disk_is_not_overwritten(tmp_path, profile):
    app = make_app(tmp_path, profile)
    path = own_file(profile, COORD)
    _, loaded = get(app, "/api/prompt", id=COORD)
    path.write_bytes(path.read_bytes() + b"\n")       # someone else saved
    moved = path.read_bytes()
    raw = reworded(loaded["raw"])
    status, report = save(app, loaded, raw)
    assert status == 409
    assert report["saved"] is False and report["reason"] == "moved"
    assert path.read_bytes() == moved


def test_saving_an_inherited_prompt_writes_a_file_of_the_profiles_own(
        tmp_path, profile):
    inherited = "visuals/table_continued"
    default = REAL[1] / "visuals" / "table_continued.md"
    assert not own_file(profile, inherited).exists()
    app = make_app(tmp_path, profile)
    _, loaded = get(app, "/api/prompt", id=inherited)
    assert loaded["own"] is False and loaded["owner"] == "default"
    assert loaded["target"] == app.shown(own_file(profile, inherited))
    raw = loaded["raw"].replace("The table right before", "The table "
                                "just before", 1)
    assert raw != loaded["raw"]
    kept = default.read_bytes()
    _, report = save(app, loaded, raw, inherited)
    assert report["saved"] is True, report
    assert report["creates"] == loaded["target"]
    assert own_file(profile, inherited).read_text(
        encoding="utf-8").replace("\r\n", "\n") == raw
    assert default.read_bytes() == kept
    assert get(app, "/api/prompt", id=inherited)[1]["own"] is True


def test_a_save_writes_only_inside_the_profiles_folder(tmp_path, profile):
    app = make_app(tmp_path, profile)
    before = everything(tmp_path)
    for bad in ("../x/y", "extraction/../../x", "..", "x/y/z", 5, None):
        status, report = post(app, "/api/prompt/save",
                              {"id": bad, "raw": "x", "base": None})
        assert status in (400, 404), bad
        assert report.get("saved") is not True
    assert everything(tmp_path) == before
    with pytest.raises(PermissionError):
        app.files.write(tmp_path / "outside.md", b"x")
    assert everything(tmp_path) == before


def test_a_sentence_taken_away_needs_a_confirmation(tmp_path, profile):
    app = make_app(tmp_path, profile)
    path = profile.prompts_dir / "extraction" / "phrases.json"
    before = path.read_bytes()
    _, loaded = get(app, "/api/phrases", module="extraction")
    table = dict(loaded["table"])
    del table["option_means"]                  # the default words it too
    body = {"module": "extraction", "table": table,
            "base": loaded["sha256"]}
    status, report = post(app, "/api/phrases/save", body)
    assert report["reason"] == "confirm" and not report["saved"]
    assert [one["key"] for one in report["removed"]] == ["option_means"]
    assert path.read_bytes() == before
    _, report = post(app, "/api/phrases/save", {**body, "confirm": True})
    assert report["saved"] is True, report
    assert "option_means" not in json.loads(path.read_text("utf-8"))
    assert report["sha256"] == server.sha256(path.read_bytes())


def test_a_sentence_with_a_name_nobody_fills_is_not_written(tmp_path,
                                                            profile):
    app = make_app(tmp_path, profile)
    path = profile.prompts_dir / "extraction" / "phrases.json"
    before = path.read_bytes()
    _, loaded = get(app, "/api/phrases", module="extraction")
    table = dict(loaded["table"])
    table["not_an_option"] += " Not {nobody}."
    body = {"module": "extraction", "table": table,
            "base": loaded["sha256"]}
    status, report = post(app, "/api/phrases/save", body)
    assert report["reason"] == "check" and report["where"] == "not_an_option"
    assert path.read_bytes() == before
    table["not_an_option"] = loaded["table"]["not_an_option"] + " Then."
    _, report = post(app, "/api/phrases/save", {**body, "table": table})
    assert report["saved"] is True, report


def test_a_new_sentence_file_is_created_with_its_folder(tmp_path, profile):
    shutil.rmtree(profile.prompts_dir / "reading")
    app = make_app(tmp_path, profile)
    _, loaded = get(app, "/api/phrases", module="reading")
    assert loaded["own_file"] is False and loaded["sha256"] is None
    changed = next(s for s in loaded["sentences"] if s["key"] == "empty")
    body = {"module": "reading", "base": None,
            "table": {"empty": changed["text"] + " Again."}}
    assert post(app, "/api/phrases/save", body)[1]["saved"] is True
    target = profile.prompts_dir / "reading" / "phrases.json"
    assert json.loads(target.read_text("utf-8")) == body["table"]
    # by construction: a file that appeared since the page loaded is "moved"
    status, report = post(app, "/api/phrases/save", body)
    assert status == 409 and report["reason"] == "moved"


def test_prompts_never_carry_the_address_or_key_of_the_model(
        tmp_path, profile, monkeypatch):
    monkeypatch.setenv("EDIT_TRY_BASE_URL", "http://models.example:8000/v1")
    monkeypatch.setenv("EDIT_TRY_API_KEY", "sk-very-secret-key")
    monkeypatch.setenv("EDIT_TRY_MODEL", "a-model")
    status, answer = get(make_app(tmp_path, profile), "/api/prompts")
    assert status == 200
    assert answer["try"]["configured"] is True
    assert answer["try"]["host"] == "models.example"
    assert "base_url" not in answer["try"] and "api_key" not in answer["try"]
    text = json.dumps(answer)
    assert "sk-very-secret-key" not in text and "8000/v1" not in text
    assert COORD in [one["id"] for one in answer["prompts"]]
    assert answer["traces"] == [] and "--harvest" in answer["traces_note"]


def traced(tmp_path, profile) -> server.App:
    """An app over a harvest of one trace: a request that carries "headings"
    and one that does not, each with the instruction the run itself makes."""
    folder = tmp_path / "harvest"
    folder.mkdir()
    prompt = prompt_files.load(COORD, profile)
    lines = []
    for parameter, extra in (("p_a", {"headings": ["H1 Introduction"]}),
                             ("p_b", {})):
        payload = {"question": "What?", "passage": {
            "kind": "section", "page": "1",
            "lines": ["1 A first line.", "2 A second line."]}, **extra}
        system = runner.system_text(
            runner.request_prompt(thread.cut(prompt), payload),
            {"at": "1", "words": "A first line."})
        lines.append({
            "t": "coord_ask", "doc": 1, "attempt": 1, "ms": 1,
            "prompt_tokens": 1, "completion_tokens": 1,
            "parameter": parameter,
            "input": {"model": "m", "temperature": 0, "max_tokens": 1024,
                      "response_format": None, "extra_body": None,
                      "messages": [
                          {"role": "system", "content": system},
                          {"role": "user", "content": json.dumps(
                              payload, ensure_ascii=False, indent=1)}]},
            "output": {"content": '{"at": "1", "words": "A first line."}',
                       "finish": "stop"}})
    with gzip.open(folder / "doc1.trace.jsonl.gz", "wt",
                   encoding="utf-8") as handle:
        handle.write("\n".join(json.dumps(one) for one in lines) + "\n")
    return make_app(tmp_path, profile, folder)


def counting_model():
    """A model that records the calls it gets."""
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content='{"at": "1"}')
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3))
    chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    return SimpleNamespace(chat=chat, calls=calls)


def test_try_sends_exactly_the_named_requests_and_nothing_else_sends(
        tmp_path, profile, monkeypatch):
    model = counting_model()
    monkeypatch.setattr(trying, "client_of", lambda config: model)
    monkeypatch.setattr(trying, "settings", lambda: {
        "configured": True, "why": None, "limit": 3, "base_url": "http://x/",
        "api_key": "k", "model": "m", "host": "x"})
    app = traced(tmp_path, profile)
    raw = get(app, "/api/prompt", id=COORD)[1]["raw"]
    edits = {COORD: raw + "\nMore.\n"}
    assert get(app, "/api/prompts")[1]["traces"][0]["name"] == "doc1"
    assert get(app, "/api/requests", trace="doc1", prompt=COORD)[0] == 200
    assert post(app, "/api/request/preview",
                {"trace": "doc1", "index": 0, "edits": edits})[0] == 200
    assert post(app, "/api/prompt/check",
                {"id": COORD, "raw": raw})[0] == 200
    assert model.calls == []
    status, done = post(app, "/api/request/try",
                        {"trace": "doc1", "indexes": [0, 1], "edits": {}})
    assert status == 200 and len(model.calls) == done["counts"]["sent"] == 2
    # by construction: more than the limit is refused and sends nothing
    status, refused = post(app, "/api/request/try", {
        "trace": "doc1", "indexes": [0, 1, 0, 1], "edits": {}})
    assert status == 400 and refused["error"] and len(model.calls) == 2


def test_the_request_list_filters_and_keeps_its_selects_whole(tmp_path,
                                                              profile):
    app = traced(tmp_path, profile)
    _, every = get(app, "/api/requests", trace="doc1", prompt=COORD)
    assert every["total"] == every["matching"] == 2
    assert "headings" in every["carried"]
    _, some = get(app, "/api/requests", trace="doc1", prompt=COORD,
                  carries="headings")
    assert [row["index"] for row in some["requests"]] == [0]
    assert some["matching"] == 1 and some["carried"] == every["carried"]
    assert some["kinds"] == every["kinds"] == ["coord"]
    assert some["fields"] == ["p_a", "p_b"]
    _, none = get(app, "/api/requests", trace="doc1", carries="nothing")
    assert none["matching"] == 0 and none["requests"] == []
    _, other = get(app, "/api/requests", trace="doc1", prompt="extraction/find")
    assert other["matching"] == 0 and other["kinds"] == []
    _, paged = get(app, "/api/requests", trace="doc1", offset="1", limit="1")
    assert [row["index"] for row in paged["requests"]] == [1]
    assert get(app, "/api/requests", trace="no_such")[0] == 404
    assert get(app, "/api/requests", trace="doc1", limit="many")[0] == 400
    assert get(app, "/api/requests", trace="doc1", prompt="x/none")[0] == 404


def test_a_preview_of_an_edited_part_reaches_only_the_requests_told_it(
        tmp_path, profile):
    app = traced(tmp_path, profile)
    raw = get(app, "/api/prompt", id=COORD)[1]["raw"]
    assert HEADINGS in raw
    edit = raw.replace(HEADINGS, HEADINGS.replace("headings up",
                                                  "headings, all of them, up"))
    assert edit != raw

    def preview(index: int, edits: dict) -> dict:
        status, answer = post(app, "/api/request/preview", {
            "trace": "doc1", "index": index, "edits": edits})
        assert status == 200
        return answer
    for index in (0, 1):
        said = preview(index, {})
        assert said["preview"]["same_as_recorded"] is True, said["preview"]
        assert said["preview"]["changed"] is False
    carrying, other = preview(0, {COORD: edit}), preview(1, {COORD: edit})
    assert carrying["preview"]["changed"] is True
    assert "all of them" in carrying["preview"]["edit"]["system"]
    assert other["preview"]["changed"] is False
    assert carrying["recorded"]["system"] == \
        carrying["preview"]["file"]["system"]
    assert carrying["notes"]["parameter"] == "p_a"
    assert post(app, "/api/request/preview", {
        "trace": "doc1", "index": 0, "edits": {COORD: 5}})[0] == 400
    assert post(app, "/api/request/preview", {
        "trace": "doc1", "index": 9, "edits": {}})[0] == 404


def test_the_review_runs_both_commands_and_reads_the_summary(
        tmp_path, profile, monkeypatch):
    app = make_app(tmp_path, profile)
    folder = app.review_root / "20261110T000000Z"
    seen, plan = [], {"out": f"written to {folder}\n", "code": 0}

    def fake(command, **kwargs):
        seen.append((command, kwargs["cwd"]))
        if "render_prompts.py" in command[1]:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "summary.md").write_text("# the summary",
                                               encoding="utf-8")
            return SimpleNamespace(returncode=plan["code"],
                                   stdout=plan["out"], stderr="")
        return SimpleNamespace(returncode=0, stdout="29 checks", stderr="")

    monkeypatch.setattr(server.subprocess, "run", fake)
    status, report = post(app, "/api/review", {})
    assert status == 200 and report["ok"] is True
    assert [c for c, _ in seen] == [
        [sys.executable, "-m", "docpipe", "preflight", "--profile",
         "scenarios"],
        [sys.executable, "scripts/render_prompts.py", "--profile",
         "scenarios", "--before", "HEAD"]]
    assert all(cwd == app.root for _, cwd in seen)
    assert report["steps"][1]["summary"] == "# the summary"
    # by construction: no line, a folder outside the roots, or a failing
    # command leave no summary or make the answer not ok
    for out in ("", f"written to {tmp_path}\n"):
        plan["out"] = out
        assert post(app, "/api/review", {})[1]["steps"][1]["summary"] is None
    plan["code"] = 1
    assert post(app, "/api/review", {})[1]["ok"] is False
