"""The requests of stages 4 and 5 in the editor (owner request 2026-11-19,
point A3 of the review of that day: "Die Stufen 4 und 5 schreiben dieselbe
Mitschrift wie die Ernte. Dann gelten Vorschau, Ausprobieren und die
Messsätze auch für sie").

The logs are written by the stages themselves: a table and a figure of the
visuals and a window of the refinement are asked of a stand-in model. Each
promise is held against a case that breaks it by construction:

1. A stage writes each document's log in the document's folder, AND its head
   holds the text of every prompt as the run read it, AND a request asked in
   a thread of its own names its document too.
2. The editor lists a stage log as "<document>/<stage>" beside the harvest's
   traces, AND the flow's measurement and a name that leaves the folder do
   not reach it.
3. A request of a log is listed under each prompt its messages are made of,
   AND under no other; every prompt of a stage is made into some request.
4. The preview makes the request again from the prompt files character for
   character, AND an edit of the message's prompt or of a prompt set into it
   changes it; a request whose prompt file changed after the run is made
   again from the texts its head holds, AND one whose message its prompts do
   not make says why.
5. What became of a request is read as the stage reads its reply, AND a reply
   without its key is unreadable.
6. A try sends the edited messages with the picture read again, the strip
   cut again where one was sent, to the model the stage asks, AND reads the
   reply as the stage does; a strip that cannot be cut again is not sent.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from docpipe import prompts as prompt_files
from docpipe.editor import prompts, requests as recorded, staged, trying
from docpipe.extraction import trace
from docpipe.profile import load_profile
from docpipe.refinement import config as refine_config
from docpipe.refinement import refine, split as refine_split
from docpipe.refinement import replies as refine_replies
from docpipe.visuals import config as visuals_config
from docpipe.visuals import process, replies as visuals_replies, strips
from docpipe.visuals.models import ProcessingStats

KWP = load_profile("kwp")
TABLE_REPLY = json.dumps({"rows": ["| a | b |", "| --- | --- |", "| 1 | 2 |"],
                          "caption": "Tabelle"})
FIGURE_REPLY = json.dumps({"description": "Eine Karte", "caption": None})


def picture(lines=6) -> bytes:
    """A small table image with blank rows between its rows of writing."""
    image = Image.new("L", (200, 20 * lines + 10), 255)
    draw = ImageDraw.Draw(image)
    for at in range(lines):
        draw.text((8, 8 + at * 20), f"Zeile {at} 1.200", fill=0)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def model(calls: list, answer):
    """A stand-in for the model: notes each request, answers *answer(request)*
    (a text, or a callable of the request)."""
    def create(**request):
        calls.append(request)
        text = answer(request) if callable(answer) else answer
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            choices=[SimpleNamespace(finish_reason="stop",
                                     message=SimpleNamespace(content=text))])
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))


def read(path) -> bytes:
    return Path(path).read_bytes()


@pytest.fixture
def processed(tmp_path, monkeypatch):
    """The processed folder of one document after stage 5 asked a table and
    a figure, and stage 4 one window, each of a stand-in model."""
    monkeypatch.setattr(trace, "enabled", lambda: True)
    folder = tmp_path / "doc1"
    (folder / "images").mkdir(parents=True)
    (folder / "images" / "t.png").write_bytes(picture())
    (folder / "images" / "f.png").write_bytes(picture(2))
    section = {"title": "Wärmebedarf", "page_number": 4,
               "content": "Der Bedarf sank. {Klammern} bleiben."}
    trace.open_stage(tmp_path, True, "visuals",
                     prompt_ids=visuals_config.PROMPT_IDS, model="vision-m")
    try:
        process.process_table({"id": "t1", "path": "images/t.png",
                               "page_number": 5}, section, folder,
                              model([], TABLE_REPLY), ProcessingStats())
        process.process_figure({"id": "f1", "path": "images/f.png",
                                "caption": "Karte 1"}, section, folder,
                               model([], FIGURE_REPLY), ProcessingStats())
    finally:
        trace.close_stage()
    window = [{"title": "Einleitung", "page_number": 2,
               "content": "Text der Einleitung."}]
    answer = json.dumps({"sections": [{"title": "Einleitung",
                                       "content": "Text der Einleitung."}]})
    trace.open_stage(tmp_path, True, "refinement",
                     prompt_ids=refine_config.prompt_ids(), model="text-m")
    try:
        with trace.working_on(folder):
            refine._call_llm(window, model([], answer))
    finally:
        trace.close_stage()
    return tmp_path


def traces(root) -> recorded.Traces:
    return recorded.Traces(None, stages=root, profile=KWP)


# -- 1. the log a stage writes --------------------------------------------------

def test_a_stage_writes_each_documents_log_in_its_folder(processed):
    assert trace.path_of(processed / "doc1", "visuals") is not None
    assert trace.path_of(processed / "doc1", "refinement") is not None
    # beside the document, never in the processed folder itself
    assert not list(processed.glob("*.trace.jsonl*"))


def test_the_head_holds_every_prompt_as_the_run_read_it(processed):
    log = traces(processed).load("doc1/visuals")
    assert log.head["stage"] == "visuals" and log.head["model"] == "vision-m"
    assert set(log.head["prompts"]) == set(visuals_config.PROMPT_IDS)
    assert log.head["prompts"]["visuals/table_user"] == prompt_files.load(
        "visuals/table_user").text
    assert traces(processed).load("doc1/refinement").head["stage"] \
        == "refinement"


def test_what_traces_after_a_stage_starts_without_the_stages_head(
        processed, tmp_path):
    """A stage ends its log with `close_stage`: the head it set is gone, so
    a trace opened next in the process (another stage, a harvest) starts
    with a head of its own or with none."""
    assert trace._head_maker is None
    # broken by construction: closing the files alone keeps the stage's head
    trace.open_stage(tmp_path, True, "visuals")
    trace.close()
    assert trace._head_maker is not None
    trace.close_stage()
    assert trace._head_maker is None


def test_a_split_asked_in_a_thread_of_its_own_names_its_document(tmp_path):
    """Stage 4 asks for the cuts of its long sections at once, each in a
    thread of its own; a request names its document through the context it
    runs in (`trace.working`), so each thread must run in the caller's."""
    def section(n):
        segments = [{"kind": "text", "page": 1,
                     "text": " ".join(f"w{n}x{i}" for i in range(50))}
                    for _ in range(4)]
        return {"title": f"Long {n}", "segments": segments,
                "content": " ".join(one["text"] for one in segments)}

    seen = []

    def ask(system, user, again):
        seen.append(trace.working())
        return {"cuts": []}

    folder = tmp_path / "doc7"
    with trace.working_on(folder):
        cuts = refine_split._ask_all_cuts([section(1), section(2)], ask, 100)
    assert sorted(cuts) == [0, 1]
    assert seen == [("doc7", str(folder))] * 2
    # broken by construction: a thread that is not handed the context does
    # not know the document, and its request would go into no log
    from concurrent.futures import ThreadPoolExecutor
    with trace.working_on(folder):
        with ThreadPoolExecutor(max_workers=2) as pool:
            lost = list(pool.map(lambda _: trace.working(), range(2)))
    assert lost == [None, None]


# -- 2. which logs the editor lists -----------------------------------------------

def test_the_editor_lists_a_stage_log_by_document_and_stage(processed,
                                                            tmp_path_factory):
    harvest = tmp_path_factory.mktemp("harvest")
    (harvest / f"7{trace.SUFFIX}").write_bytes(b"")
    # a log in a document's folder that no stage writes
    (processed / "doc1" / f"7{trace.SUFFIX}").write_bytes(b"")
    found = recorded.Traces(harvest, stages=processed, profile=KWP)
    names = {one["name"]: one["stage"] for one in found.names()}
    assert names == {"7": None, "doc1/refinement": "refinement",
                     "doc1/visuals": "visuals"}
    assert [one["name"] for one in found.names("harvest")] == ["7"]
    assert [one["name"] for one in found.names("visuals")] == ["doc1/visuals"]
    assert found.path_of("doc1/visuals") == trace.path_of(
        processed / "doc1", "visuals")
    assert found.path_of("doc1/7") is None


def test_a_name_that_leaves_the_folder_is_no_log(processed):
    found = traces(processed)
    for name in ("../doc1/visuals", "doc1/../doc1/visuals", "./visuals",
                 "doc1/nothing"):
        assert found.path_of(name) is None, name


# -- 3. which prompts a request is listed under -----------------------------------------

def test_a_request_is_listed_under_each_prompt_it_is_made_of(processed):
    log = traces(processed).load("doc1/visuals")
    table = next(r for r in log.requests if r["kind"] == "table")
    figure = next(r for r in log.requests if r["kind"] == "figure")
    assert prompts.concerns("visuals/table_user", table)
    assert prompts.concerns("visuals/caption_generate_table", table)
    assert prompts.concerns("visuals/caption_keep", figure)
    # a prompt the request is not made of
    assert not prompts.concerns("visuals/figure_user", table)
    assert not prompts.concerns("visuals/caption_keep", table)
    assert not prompts.concerns("extraction/coord", table)
    assert prompts.kinds_of("visuals/caption_keep") == ["figure", "table"]
    assert prompts.kinds_of("refinement/split") == ["split"]
    assert prompts.kinds_of("visuals/context_sentence") == []


def test_every_prompt_of_a_stage_is_made_into_some_request():
    for stage, ids in (("visuals", visuals_config.PROMPT_IDS),
                       ("refinement", refine_config.prompt_ids()
                        + refine_split.PROMPT_IDS
                        + ("refinement/refine",
                           "refinement/refine_corrections"))):
        made = {one for kind_ids in prompts.stage_requests(stage).values()
                for one in kind_ids}
        assert set(ids) <= made, stage
    assert visuals_replies.REQUESTS and refine_replies.REQUESTS


# -- 4. the preview ---------------------------------------------------------------

def one(root, name: str, kind: str):
    log = traces(root).load(name)
    index = next(i for i, r in enumerate(log.requests) if r["kind"] == kind)
    return log, index


def test_the_preview_makes_the_request_again_character_for_character(
        processed):
    for name, kind in (("doc1/visuals", "table"), ("doc1/visuals", "figure"),
                       ("doc1/refinement", "refine")):
        log, index = one(processed, name, kind)
        got = staged.preview(KWP, log.requests[index], log.sent(index), {},
                             read, log.head)
        assert got["why"] is None, (kind, got["why"])
        assert got["same_as_recorded"] is True and got["changed"] is False


def test_an_edit_of_the_message_or_of_a_prompt_set_into_it_changes_it(
        processed):
    log, index = one(processed, "doc1/visuals", "table")
    request, sent = log.requests[index], log.sent(index)
    for edited in ("visuals/table_user", "visuals/caption_generate_table"):
        raw = prompts.on_disk(KWP, edited, read)["raw"]
        got = staged.preview(KWP, request, sent,
                             {edited: raw + "\nNEUER SATZ."}, read, log.head)
        assert got["why"] is None and got["changed"] is True, edited
        assert "NEUER SATZ." in got["edit"]["user"]
        assert "NEUER SATZ." not in got["file"]["user"]
        assert any(piece[1] for line in got["user_lines"] for piece in line)
        assert got["edit"]["system"] == got["file"]["system"]
    # the prompt of the instruction changes the instruction only
    raw = prompts.on_disk(KWP, "visuals/table_system", read)["raw"]
    got = staged.preview(KWP, request, sent,
                         {"visuals/table_system": raw + "\nNOCH EINER."},
                         read, log.head)
    assert got["edit"]["system"].endswith("NOCH EINER.")
    assert got["edit"]["user"] == got["file"]["user"]
    # a prompt the request is not made of changes nothing
    raw = prompts.on_disk(KWP, "visuals/figure_user", read)["raw"]
    got = staged.preview(KWP, request, sent,
                         {"visuals/figure_user": raw + "\nX."}, read,
                         log.head)
    assert got["changed"] is False


def test_a_prompt_changed_after_the_run_is_read_back_with_the_heads_text(
        processed):
    log, index = one(processed, "doc1/visuals", "table")
    request, sent = log.requests[index], log.sent(index)
    path = Path(prompts.on_disk(KWP, "visuals/table_user", read)["path"])

    def changed(where) -> bytes:
        """The files as they are after the run: the table's message
        prompt has a word more before the section."""
        data = read(where)
        if Path(where) == path:
            data = data.replace(b"{section_content}",
                                b"Neu: {section_content}")
        return data

    got = staged.preview(KWP, request, sent, {}, changed, log.head)
    assert got["why"] is None
    assert "Neu: " in got["file"]["user"]
    assert got["same_as_recorded"] is False
    # without the head the record cannot be read back with the new file
    lost = staged.preview(KWP, request, sent, {}, changed, {})
    assert lost["why"] and "cannot be read back" in lost["why"]


def test_a_message_its_prompts_do_not_make_says_why(processed):
    log, index = one(processed, "doc1/visuals", "figure")
    sent = log.sent(index)
    for message in sent["messages"]:
        if message["role"] == "system":
            message["content"] = "Eine andere Anweisung."
    got = staged.preview(KWP, log.requests[index], sent, {}, read, log.head)
    assert got["why"] and got["file"] is None


# -- 5. what became of a request ------------------------------------------------------

def test_what_became_of_a_request_is_read_as_the_stage_reads_it(processed):
    log, index = one(processed, "doc1/visuals", "table")
    assert log.requests[index]["check"] == "taken"
    request = {**log.requests[index], "_reply": recorded.reply_key(
        log.sent(index)["response_format"])}
    broken = {**request, "answer": json.dumps({"caption": "x"})}
    assert recorded.stage_check(broken, KWP) == "unreadable: missing_key"
    assert recorded.stage_check({**request, "answer": "kein JSON"}, KWP) \
        .startswith("unreadable: ")


# -- 6. a try ---------------------------------------------------------------------------

VISION = {"configured": True, "why": None, "limit": 3, "role": "vlm",
          "base_url": "http://vision", "api_key": "x", "model": "vision-m",
          "host": "vision"}


def test_a_try_sends_the_edited_messages_with_the_picture_read_again(
        processed):
    log, index = one(processed, "doc1/visuals", "table")
    raw = prompts.on_disk(KWP, "visuals/table_user", read)["raw"]
    calls: list = []
    got = trying.run(KWP, log, [index],
                     {"visuals/table_user": raw + "\nNEUER SATZ."}, read,
                     config=VISION, make_client=lambda config: model(
                         calls, TABLE_REPLY), read_bytes=read)
    assert got["staged"] is True and got["counts"]["sent"] == 1
    sent = calls[0]
    assert sent["model"] == "vision-m"
    user = next(m for m in sent["messages"] if m["role"] == "user")
    text = next(p["text"] for p in user["content"] if p["type"] == "text")
    url = next(p["image_url"]["url"] for p in user["content"]
               if p["type"] == "image_url")
    assert text.endswith("NEUER SATZ.")
    assert url.endswith(__import__("base64").b64encode(
        (processed / "doc1" / "images" / "t.png").read_bytes()).decode())
    assert sent["response_format"] == log.sent(index)["response_format"]
    row = got["results"][0]
    assert row["new"]["in_form"] is True and row["same"] is True
    # a reply without the key the stage reads
    got = trying.run(KWP, log, [index], {}, read, config=VISION,
                     make_client=lambda config: model([], '{"caption": 1}'),
                     read_bytes=read)
    new = got["results"][0]["new"]
    assert new["in_form"] is False and new["fault"] == "missing_key"


def test_a_strip_is_cut_again_and_one_that_cannot_be_is_not_sent(processed):
    log, index = one(processed, "doc1/visuals", "table")
    sent = log.sent(index)
    whole = (processed / "doc1" / "images" / "t.png").read_bytes()
    halves = strips.halves(whole)
    assert halves, "the test image has to have halves"
    upper = halves[0]
    import hashlib
    for message in sent["messages"]:
        if isinstance(message["content"], list):
            for part in message["content"]:
                if part["type"] == "image_url":
                    part["image_url"]["strip"] = hashlib.sha256(
                        upper).hexdigest()
    view = staged.preview(KWP, log.requests[index], sent, {}, read, log.head)
    messages = staged.messages_of(sent, view, processed / "doc1", read)
    url = next(p["image_url"]["url"] for m in messages
               if isinstance(m["content"], list) for p in m["content"]
               if p["type"] == "image_url")
    assert url.endswith(__import__("base64").b64encode(upper).decode())
    # a strip no cut of the file gives
    for message in sent["messages"]:
        if isinstance(message["content"], list):
            for part in message["content"]:
                if part["type"] == "image_url":
                    part["image_url"]["strip"] = "0" * 64
    with pytest.raises(LookupError):
        staged.messages_of(sent, view, processed / "doc1", read)


def test_a_try_goes_to_the_model_the_stage_asks(processed, monkeypatch):
    log, _ = one(processed, "doc1/visuals", "table")
    assert trying.role_of(log) == "vlm"
    assert trying.role_of(traces(processed).load("doc1/refinement")) == "llm"
    monkeypatch.delenv("VLM_BASE_URL", raising=False)
    with pytest.raises(trying.Refused):
        trying.run(KWP, log, [0], {}, read, read_bytes=read)
    monkeypatch.setenv("VLM_BASE_URL", "http://vision:8001/v1")
    assert trying.settings("vlm")["configured"] is True
    assert trying.settings("vlm")["role"] == "vlm"
