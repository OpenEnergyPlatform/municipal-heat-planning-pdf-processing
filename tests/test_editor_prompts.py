"""What the prompts tab of `docpipe edit` promises about a prompt's text, the
requests of a record and a try (owner decisions 2026-11-10).

The records are made by the run itself: a request sent through
`runner.make_asks` to a stand-in model is what a trace holds. Each test
states one promise and holds a case that breaks it by construction.

Measured once, on 2026-11-10: with the files of that day the preview gives
every request of a smoke probe of both profiles character for character
(338 requests of kwp, 108 of scenarios)."""
import copy
import json
from types import SimpleNamespace

import pytest

from docpipe.editor import prompts, requests as recorded, trying
from docpipe.extraction import addressed, runner
from docpipe.profile import load_profile

KWP = load_profile("kwp")
SCENARIOS = load_profile("scenarios")
LINES = ["1 Der Verbrauch sank.", "2 | Rathaus | 1.200 | 2021 |",
         "3 Danach kam die Sanierung."]
PAYLOAD = {"value": {"words": "1.200", "at": "2.2"},
           "passage": {"kind": "table", "page": "4", "lines": LINES},
           "question": "Für welches Jahr gilt diese Zahl?"}
HEADED = {**PAYLOAD, "headings": ["H1 Bestand", "H2 Verbrauch"]}
ANSWER = '{"at": "2.3", "words": "2021"}'
FOUND = '{"found": [{"at": "2.2", "words": "1.200"}]}'


def read(path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def model(calls: list, answer: str = ANSWER):
    """A stand-in for the model: it notes every request and answers
    *answer*, a request for finds with one find. So the run takes each
    reply as it comes and asks nothing a second time."""
    def create(**request):
        calls.append(request)
        finds = "found" in json.dumps(request.get("response_format") or {})
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=FOUND if finds else answer))])
    return SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))


@pytest.fixture
def record(monkeypatch):
    """(the requests a run sent, each as a trace holds it) for a
    coordinate asked without headings, with them, and once more."""
    sent: list = []
    monkeypatch.setattr(runner, "_client", lambda: model(sent))
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)
    asks = runner.make_asks(KWP)
    form = addressed.coord_format(False)
    example = {"at": "2", "words": "..."}
    asks.coord(PAYLOAD, 7, shape=form, example=example)
    asks.coord(HEADED, 7, shape=form, example=example)
    asks.follow("coord", {**PAYLOAD, "answer": {"at": "9"},
                          "what": ["nichts"]}, 7, shape=form,
                example=example)
    asks.find({"field": {"name": "Energieverbrauch"},
               "passage": PAYLOAD["passage"]}, 7,
              shape=addressed.found_format(),
              example=({"found": [{"at": "2.2", "words": "1.200"}]},
                       {"found": []}))
    kinds = ["coord", "coord", "follow", "find"]
    assert len(sent) == len(kinds)                  # each was asked once
    events = [{"t": f"{kind}_ask", "doc": 7, "attempt": 1,
               **({"asked": "coord"} if kind == "follow" else {}),
               "input": request,
               "output": {"content": ANSWER, "finish": "stop"}}
              for kind, request in zip(kinds, sent)]
    return recorded.Trace("doc7.trace.jsonl.gz", events)


def view(trace, index: int, edits=None, profile=KWP) -> dict:
    return prompts.preview(profile, trace.requests[index],
                           trace.sent(index), edits or {}, read)


def edited(prompt_id: str, change, profile=KWP) -> str:
    raw = prompts.on_disk(profile, prompt_id, read)["raw"]
    out = change(raw)
    assert out != raw
    return out


# -- the preview is the text the run sends ------------------------------------------

def test_the_files_on_disk_give_a_recorded_request_character_for_character(
        record):
    for index in range(len(record.requests)):
        got = view(record, index)
        assert got["why"] is None, got["why"]
        assert got["same_as_recorded"] is True
        assert got["example"] == "record" and got["changed"] is False
        assert got["edit"]["system"] == record.requests[index]["system"]
    # the failure by construction: a record sent with another word is not
    # what the files give, and the preview says so
    other = copy.deepcopy(record.sent(0))
    system = other["messages"][0]
    system["content"] = system["content"].replace("Zeile", "Reihe", 1)
    assert system["content"] != record.requests[0]["system"]
    got = prompts.preview(KWP, record.requests[0], other, {}, read)
    assert got["same_as_recorded"] is False


def test_a_changed_part_changes_only_the_requests_that_carry_its_field(
        record):
    def reword(raw: str) -> str:
        cut = prompts.segments(raw)
        part = next(p for p in cut["parts"] if p["keys"] == ["headings"])
        part["text"] = part["text"].rstrip("\n") + " Neu gesagt.\n"
        return prompts.joined(cut)
    edits = {"extraction/coord": edited("extraction/coord", reword)}
    plain, headed = view(record, 0, edits), view(record, 1, edits)
    assert plain["changed"] is False
    assert plain["edit"]["system"] == plain["file"]["system"]
    assert headed["changed"] is True
    marked = [sentence for line in headed["lines"]
              for sentence, changed in line if changed]
    assert marked and all("Neu gesagt." in sentence for sentence in marked)
    # a request asked once more goes under the prompt of the one it
    # follows, and its message ends with the words of the follow-up prompt
    follow = {"extraction/follow": edited(
        "extraction/follow", lambda raw: raw.rstrip("\n") + " Bitte.\n")}
    again = view(record, 2, follow)
    assert again["changed"] is True
    assert again["edit"]["user"].endswith("Bitte.")
    assert again["edit"]["system"] == again["file"]["system"]
    assert view(record, 0, follow)["changed"] is False


def test_a_prompt_cut_for_editing_is_put_back_character_for_character():
    for profile in (KWP, SCENARIOS):
        for row in prompts.listing(profile):
            raw = prompts.on_disk(profile, row["id"], read)["raw"]
            cut = prompts.segments(raw)
            assert prompts.joined(cut) == raw
    cut = prompts.segments(prompts.on_disk(KWP, "extraction/coord",
                                           read)["raw"])
    assert cut["front"].startswith("---\n") and len(cut["parts"]) == 5
    assert all(part["mark"].startswith("<!-- with: ")
               and part["mark"].endswith("-->\n") for part in cut["parts"])


# -- a text a run would fail on is not written ------------------------------------

def _twice(raw: str) -> str:
    cut = prompts.segments(raw)
    cut["parts"].append(dict(cut["parts"][0]))
    return prompts.joined(cut)


@pytest.mark.parametrize("change, said", [
    (lambda raw: raw + "\n{{foo}}\n", "{{foo}} is not in the file"),
    (lambda raw: raw.replace("{{example}}", "ein Beispiel"),
     "{{example}} is gone"),
    (_twice, "two with parts"),
    (lambda raw: raw.replace("max_tokens: ", "max_tokens: viele "),
     "max_tokens"),
    (lambda raw: raw.replace("temperature: 0", "temperature: [", 1),
     "settings on top"),
])
def test_a_text_a_run_would_fail_on_is_not_written(change, said):
    disk = prompts.on_disk(KWP, "extraction/coord", read)
    raw = change(disk["raw"])
    assert raw != disk["raw"]
    report, data, _ = prompts.save(KWP, "extraction/coord", raw, disk)
    assert report["ok"] is False and said in report["error"]
    assert data is None and report["reason"] == "check"


def _glued(raw: str) -> str:
    """The first marker of a part run into the line before it."""
    from docpipe.extraction import thread
    mark = thread.MARK.search(raw)
    return raw[:mark.start() - 1] + " One more sentence." + raw[mark.start():]


@pytest.mark.parametrize("change", [
    _glued,
    lambda raw: raw + "\n<!--with: note-->\nWords for it.\n",
    lambda raw: raw + "\n<!-- with: note --> Words for it.\n",
    lambda raw: raw + "\n<!-- with: note, more -->\nWords for it.\n",
    lambda raw: raw + "\n<!-- follow-up : note -->\nWords for it.\n",
])
def test_a_marker_the_run_would_take_for_text_is_not_written(change):
    disk = prompts.on_disk(KWP, "extraction/coord", read)
    report, data, _ = prompts.save(KWP, "extraction/coord",
                                   change(disk["raw"]), disk)
    assert report["ok"] is False and "opens no part" in report["error"]
    assert data is None and report["reason"] == "check"


def test_a_marker_on_a_line_of_its_own_opens_a_part_and_is_written():
    disk = prompts.on_disk(KWP, "extraction/coord", read)
    raw = disk["raw"] + "\n<!-- with: note -->\nWords for it.\n"
    report, data, _ = prompts.save(KWP, "extraction/coord", raw, disk)
    assert report["ok"] and report["saved"] and data is not None
    assert [part["keys"] for part in prompts.segments(raw)["parts"]][-1] == [
        "note"]
    # what the file on disk already writes is not held against a change
    # elsewhere: only what the text adds
    old = {**disk, "raw": disk["raw"] + "\nSee <!-- with: note --> above.\n"}
    report, _, _ = prompts.save(KWP, "extraction/coord",
                                old["raw"] + "One sentence more.\n", old)
    assert report["ok"] and report["saved"]


def test_a_marked_instruction_is_the_instruction_character_for_character():
    before = ("Read the row.  No backticks! In this form:\n"
              "\n"
              "  1. One line. Another line.\n")
    after = before.replace("No backticks!", "No quotes at all!")
    cut = prompts.marked(before, after)
    assert "\n".join("".join(piece for piece, _ in line)
                     for line in cut["lines"]) == after
    changed = [piece for line in cut["lines"] for piece, flag in line if flag]
    assert changed == ["No quotes at all! "]
    assert cut["gone"] == ["No backticks!"]
    # the failure by construction: a text that is the same marks nothing
    same = prompts.marked(after, after)
    assert not any(flag for line in same["lines"] for _, flag in line)
    assert same["gone"] == []


def test_a_changed_word_is_written_as_typed_in_the_files_line_ends():
    disk = prompts.on_disk(KWP, "extraction/coord", read)
    raw = disk["raw"].replace("Zeile", "Reihe", 1)
    report, data, target = prompts.save(KWP, "extraction/coord", raw, disk)
    assert report["ok"] and report["saved"] and report["creates"] is None
    assert data == raw.replace("\n", disk["newline"]).encode("utf-8")
    assert target == disk["path"]
    assert report["lines"] == {"added": 1, "removed": 1}
    # nothing to write where nothing changed
    same, data, _ = prompts.save(KWP, "extraction/coord", disk["raw"], disk)
    assert data is None and same["reason"] == "same"


def test_an_inherited_prompt_is_saved_as_a_file_of_the_profiles_own():
    row = next(row for row in prompts.listing(KWP) if not row["own"])
    disk = prompts.on_disk(KWP, row["id"], read)
    assert disk["owner"].name == "default"
    raw = disk["raw"].rstrip("\n") + "\nOne more line.\n"
    report, data, target = prompts.save(KWP, row["id"], raw, disk)
    assert report["ok"] and data is not None
    assert target == report["creates"] != disk["path"]
    assert KWP.package_dir in target.parents
    # the failure by construction: a prompt of its own creates nothing
    own = prompts.on_disk(KWP, "extraction/coord", read)
    assert prompts.judge(KWP, "extraction/coord", own["raw"] + "x",
                         own)["creates"] is None


# -- a try -------------------------------------------------------------------------

READY = {"configured": True, "why": None, "limit": trying.LIMIT,
         "base_url": "http://model.invalid/v1", "api_key": "k",
         "model": "stand-in", "host": "model.invalid"}


def test_a_try_sends_one_call_per_named_request_and_no_more_than_three(
        record):
    calls: list = []
    client = model(calls)

    def run(indexes, config=READY):
        return trying.run(KWP, record, indexes, {}, read, config=config,
                          make_client=lambda config: client)
    for index in range(len(record.requests)):       # looking sends nothing
        view(record, index)
    assert calls == []
    got = run([0, 1])
    assert len(calls) == 2 and got["counts"]["sent"] == 2
    assert [call["model"] for call in calls] == ["stand-in"] * 2
    # each is the recorded request: its messages and its reply form
    assert calls[0]["messages"] == record.sent(0)["messages"]
    assert calls[0]["response_format"] == record.sent(0)["response_format"]
    with pytest.raises(trying.Refused, match="3 requests at most"):
        run([0, 1, 2, 3])
    with pytest.raises(trying.Refused, match="at least one request"):
        run([])
    with pytest.raises(trying.Refused, match="No model is set up"):
        run([0], {"configured": False, "why": trying.NO_MODEL})
    assert len(calls) == 2


@pytest.mark.parametrize("answer, same, in_form, holds, why", [
    (ANSWER, True, True, True, None),
    ('{"at": "3", "words": "Sanierung"}', False, True, True, None),
    ('{"at": "9", "words": "2021"}', False, True, False, "not_an_address"),
    ('{"at": "2.3", "words": "2030"}', False, True, False,
     "words_not_in_line"),
    ('{"at": 0, "words": ""}', False, True, None, None),
    ('{"words": "2021"}', False, False, None, None),
    ("2021", False, False, None, None),
])
def test_a_new_answer_is_read_and_checked_as_the_run_does(
        record, answer, same, in_form, holds, why):
    got = trying.run(KWP, record, [0], {}, read, config=READY,
                     make_client=lambda config: model([], answer))
    (row,) = got["results"]
    assert row["sent"] and row["new"]["error"] is None
    assert row["same"] is same and row["new"]["in_form"] is in_form
    assert row["holds"] is holds
    assert [one["why"] for one in row["addresses"] if one["why"]] == (
        [why] if why else [])


def test_the_entries_of_a_list_are_no_lines_an_address_can_name():
    payload = {"passage": {"lines": ["1 Erdgas ist teuer."]},
               "list": ["1 Erdgas", "2 Strom"]}
    held = trying.addresses({"at": "1", "words": "teuer"}, payload)
    assert held[0]["holds"] is True
    # the failure by construction: line 2 stands in the list only
    assert trying.addresses({"at": "2", "words": "Strom"},
                            payload)[0]["why"] == "not_an_address"


def test_a_model_is_only_what_the_environment_names(monkeypatch):
    for name in ("EDIT_TRY_BASE_URL", "EDIT_TRY_API_KEY", "EDIT_TRY_MODEL",
                 "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert trying.settings()["configured"] is False
    assert trying.settings()["why"] == trying.NO_MODEL
    monkeypatch.setenv("LLM_BASE_URL", "http://run.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "run-model")
    assert trying.settings()["host"] == "run.invalid"
    monkeypatch.setenv("EDIT_TRY_BASE_URL", "http://try.invalid/v1")
    monkeypatch.setenv("EDIT_TRY_MODEL", "try-model")
    got = trying.settings()
    assert (got["host"], got["model"]) == ("try.invalid", "try-model")
    assert json.dumps(got).count("try.invalid") == 2
