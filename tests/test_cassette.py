"""A recorded run and its replay.

What is promised, sentence by sentence:

  * a run that names no cassette gets the client it always got;
  * a recorded answer comes back to the same question AND with its finish
    reason, its reasoning and its token counts;
  * a request is filed under its messages and the reply it names AND not
    under the model, the temperature or the room for the answer;
  * an image is filed under its bytes: another image is another request;
  * a question asked twice gets its two answers in the order they came AND
    the last one again after that;
  * a request the cassette does not hold raises AND is counted AND a harvest
    that met one does not end as a success;
  * a replay plans its requests for the window the recorded run had AND asks
    no server for it;
  * a replay waits for nothing, watches no server and steers no limit;
  * a cassette is only recorded for a profile whose documents may be passed
    on AND kwp is one AND scenarios and the built-in profile are not;
  * the vector of a text is filed under the text, not under its batch AND a
    replay embeds nothing it does not hold.
"""
import json
from types import SimpleNamespace as NS

import pytest

from docpipe import embedding, llm_preflight, providers
from docpipe.extraction import runner
from docpipe.profile import ENV_VAR, load_profile
from docpipe.providers import base, cassette


class FakeServer:
    """A client that answers from a list and notes what it was asked."""

    def __init__(self, answers=(), vectors=None):
        self.answers = list(answers)
        self.asked = []
        self.vectors = vectors or {}
        self.chat = NS(completions=NS(create=self._create))
        self.embeddings = NS(create=self._embed)
        self.models = NS(list=lambda: NS(data=[NS(id="m", max_model_len=8)]))
        self.marker = "the server's own"

    def _create(self, **kwargs):
        self.asked.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, str):
            return base.reply(answer, base.STOP, prompt_tokens=11,
                              completion_tokens=3, model="m")
        return answer

    def _embed(self, **kwargs):
        texts = kwargs["input"]
        return NS(data=[NS(index=i, embedding=self.vectors[text])
                        for i, text in enumerate(texts)])


def ask(client, text="How much?", **more):
    kwargs = {"model": "m", "temperature": 0, "max_tokens": 100,
              "messages": [{"role": "system", "content": "Read."},
                           {"role": "user", "content": text}]}
    kwargs.update(more)
    return client.chat.completions.create(**kwargs)


@pytest.fixture(autouse=True)
def _no_cassette(monkeypatch):
    for name in (cassette.RECORD_ENV, cassette.REPLAY_ENV, "LLM_PROVIDER",
                 "VLM_PROVIDER", "EMBEDDING_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cassette, "_players", {})


@pytest.fixture
def shareable(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "kwp")


def record(tmp_path, monkeypatch, server):
    path = tmp_path / "run" / "cassette.jsonl"
    monkeypatch.setenv(cassette.RECORD_ENV, str(path))
    monkeypatch.setattr(providers, "_client", lambda role, kwargs: server)
    return path, providers.client("llm", base_url="http://x", api_key="k")


def replay(path, monkeypatch):
    monkeypatch.delenv(cassette.RECORD_ENV, raising=False)
    monkeypatch.setenv(cassette.REPLAY_ENV, str(path))
    monkeypatch.setattr(providers, "_client", lambda role, kwargs: pytest.fail(
        "a replay made a client"))
    return providers.client("llm", base_url="http://x", api_key="k")


# ---------------------------------------------------------------- no cassette

def test_a_run_that_names_no_cassette_gets_the_client_it_always_got(
        monkeypatch):
    server = FakeServer()
    seen = {}

    def made(role, kwargs):
        seen.update(role=role, kwargs=kwargs)
        return server

    monkeypatch.setattr(providers, "_client", made)
    got = providers.client("llm", base_url="http://x", api_key="k")
    assert got is server
    assert seen == {"role": "llm",
                    "kwargs": {"base_url": "http://x", "api_key": "k"}}
    assert providers.replaying() is False


def test_an_empty_variable_names_no_cassette(monkeypatch):
    monkeypatch.setenv(cassette.RECORD_ENV, "  ")
    monkeypatch.setenv(cassette.REPLAY_ENV, "")
    assert cassette.recording() is None
    assert cassette.replaying() is None
    assert providers.replaying() is False


# ------------------------------------------------------------ record + replay

def test_a_recorded_answer_comes_back_to_the_same_question(
        tmp_path, monkeypatch, shareable):
    said = base.reply('{"value": 12}', "length", prompt_tokens=40,
                      completion_tokens=9, model="m", reasoning="thought")
    path, client = record(tmp_path, monkeypatch, FakeServer([said]))
    first = ask(client)
    assert first is said                    # the recorded run saw the answer
    again = ask(replay(path, monkeypatch))
    message = again.choices[0].message
    assert message.content == '{"value": 12}'
    assert message.reasoning_content == "thought"
    assert again.choices[0].finish_reason == "length"
    assert (again.usage.prompt_tokens, again.usage.completion_tokens) \
        == (40, 9)


def test_the_recorder_hands_on_what_it_does_not_record(
        tmp_path, monkeypatch, shareable):
    server = FakeServer()
    _path, client = record(tmp_path, monkeypatch, server)
    assert client.marker == "the server's own"
    assert client.models.list().data[0].id == "m"


@pytest.mark.parametrize("change", [
    {"model": "another"}, {"temperature": 0.7}, {"max_tokens": 9},
    {"extra_body": {"reasoning_effort": "low"}},
])
def test_what_the_installation_sets_does_not_file_a_request_elsewhere(
        tmp_path, monkeypatch, shareable, change):
    path, client = record(tmp_path, monkeypatch, FakeServer(["yes"]))
    ask(client)
    got = ask(replay(path, monkeypatch), **change)
    assert got.choices[0].message.content == "yes"


@pytest.mark.parametrize("change", [
    {"text": "How many?"},
    {"response_format": {"type": "json_schema",
                         "json_schema": {"name": "other", "schema": {}}}},
    {"response_format": {"type": "json_object"}},
])
def test_another_question_or_another_reply_is_another_request(
        tmp_path, monkeypatch, shareable, change):
    path, client = record(tmp_path, monkeypatch, FakeServer(["yes"]))
    ask(client, response_format={"type": "json_schema", "json_schema": {
        "name": "field", "schema": {}}})
    kwargs = {"response_format": {"type": "json_schema", "json_schema": {
        "name": "field", "schema": {}}}}
    kwargs.update(change)
    held = replay(path, monkeypatch)
    with pytest.raises(cassette.CassetteMiss):
        ask(held, **kwargs)
    assert held.missed == 1


def test_the_schema_of_a_reply_may_change_under_its_name(
        tmp_path, monkeypatch, shareable):
    """The name is what a stage asks for; the schema text is the provider
    layer's rewriting of it and differs from API to API."""
    path, client = record(tmp_path, monkeypatch, FakeServer(["yes"]))
    ask(client, response_format={"type": "json_schema", "json_schema": {
        "name": "field", "schema": {"type": "object"}}})
    got = ask(replay(path, monkeypatch), response_format={
        "type": "json_schema", "json_schema": {
            "name": "field", "schema": {"type": "object", "x": 1}}})
    assert got.choices[0].message.content == "yes"


def _with_image(data):
    return [{"role": "user", "content": [
        {"type": "text", "text": "What does the figure show?"},
        {"type": "image_url", "image_url": {"url": data}}]}]


def test_an_image_is_filed_under_its_bytes(tmp_path, monkeypatch, shareable):
    path, client = record(tmp_path, monkeypatch, FakeServer(["a bar chart"]))
    ask(client, messages=_with_image("data:image/png;base64,AAAA"))
    line = path.read_text(encoding="utf-8")
    assert "AAAA" not in line               # the key is a hash
    held = replay(path, monkeypatch)
    got = ask(held, messages=_with_image("data:image/png;base64,AAAA"))
    assert got.choices[0].message.content == "a bar chart"
    with pytest.raises(cassette.CassetteMiss):
        ask(held, messages=_with_image("data:image/png;base64,BBBB"))


def _png(colour, level):
    image_module = pytest.importorskip("PIL.Image")
    if not hasattr(image_module, "new"):
        pytest.skip("Pillow is a stub here")
    import base64
    import io
    picture = image_module.new("RGB", (64, 48), colour)
    for x in range(0, 64, 3):
        picture.putpixel((x, x % 48), (x * 3 % 256, 10, 200))
    held = io.BytesIO()
    picture.save(held, format="PNG", compress_level=level)
    return "data:image/png;base64," + base64.b64encode(
        held.getvalue()).decode("ascii")


def test_a_picture_is_filed_under_its_pixels_not_under_its_encoding(
        tmp_path, monkeypatch, shareable):
    """The same picture written by another build of the encoder is other
    bytes. A recording made on one machine is answered on another."""
    one, other = _png("white", 1), _png("white", 9)
    assert one != other                         # other bytes, same picture
    path, client = record(tmp_path, monkeypatch, FakeServer(["a bar chart"]))
    ask(client, messages=_with_image(one))
    held = replay(path, monkeypatch)
    got = ask(held, messages=_with_image(other))
    assert got.choices[0].message.content == "a bar chart"
    with pytest.raises(cassette.CassetteMiss):  # another picture is another
        ask(held, messages=_with_image(_png("black", 1)))


def test_a_question_asked_twice_gets_its_answers_in_order(
        tmp_path, monkeypatch, shareable):
    path, client = record(tmp_path, monkeypatch,
                          FakeServer(["first", "second"]))
    ask(client)
    ask(client)
    held = replay(path, monkeypatch)
    said = [ask(held).choices[0].message.content for _ in range(3)]
    assert said == ["first", "second", "second"]
    assert held.replayed == 3 and held.missed == 0


def test_a_request_the_cassette_does_not_hold_raises_and_is_counted(
        tmp_path, monkeypatch, shareable):
    path, client = record(tmp_path, monkeypatch, FakeServer(["yes"]))
    ask(client)
    held = replay(path, monkeypatch)
    with pytest.raises(cassette.CassetteMiss) as caught:
        ask(held, text="Something new")
    assert "cassette.jsonl" in str(caught.value)
    assert (held.replayed, held.missed) == (0, 1)
    ask(held)
    assert (held.replayed, held.missed) == (1, 1)


def test_every_stage_of_a_replay_reads_one_player(tmp_path, monkeypatch,
                                                 shareable):
    path, client = record(tmp_path, monkeypatch, FakeServer(["yes"]))
    ask(client)
    one = replay(path, monkeypatch)
    other = providers.client("vlm", base_url="http://y", api_key="k")
    assert one is other is cassette.player()


def test_a_cassette_that_cannot_be_read_says_which(tmp_path, monkeypatch):
    monkeypatch.setenv(cassette.REPLAY_ENV, str(tmp_path / "missing.jsonl"))
    with pytest.raises(cassette.CassetteMiss) as caught:
        providers.client("llm")
    assert "missing.jsonl" in str(caught.value)
    assert cassette.REPLAY_ENV in str(caught.value)


# ------------------------------------------------------------------- the run

def test_a_replay_is_planned_for_the_window_of_the_recorded_run(
        tmp_path, monkeypatch, shareable):
    path = tmp_path / "cassette.jsonl"
    monkeypatch.setenv(cassette.RECORD_ENV, str(path))
    cassette.note_limits("text-model", 32768)
    cassette.note_limits("vision-model", 16384)
    monkeypatch.delenv(cassette.RECORD_ENV)
    monkeypatch.setenv(cassette.REPLAY_ENV, str(path))
    monkeypatch.setattr(llm_preflight, "serving_limits", lambda *a, **k:
                        pytest.fail("a replay asked a server"))
    assert llm_preflight.assert_serving(
        "http://x", "k", "text-model", 10 ** 9) == 32768
    assert llm_preflight.assert_serving(
        "http://x", "k", "vision-model", 1, role="vlm") == 16384
    # a model the recorded run did not name: the last window written
    assert llm_preflight.assert_serving("http://x", "k", "else", 1) == 16384


def test_the_preflight_of_a_recorded_run_writes_its_window(
        tmp_path, monkeypatch, shareable):
    path = tmp_path / "cassette.jsonl"
    monkeypatch.setenv(cassette.RECORD_ENV, str(path))
    monkeypatch.setattr(llm_preflight, "serving_limits",
                        lambda *a, **k: (["m"], 4096))
    monkeypatch.setattr(llm_preflight, "assert_request_extras",
                        lambda *a, **k: None)
    assert llm_preflight.assert_serving("http://x", "k", "m", 100) == 4096
    header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert header["kind"] == cassette.HEADER
    assert (header["model"], header["max_model_len"]) == ("m", 4096)


def test_no_cassette_no_header(tmp_path, monkeypatch):
    cassette.note_limits("m", 4096)
    assert list(tmp_path.iterdir()) == []


def test_a_replay_waits_for_nothing(tmp_path, monkeypatch):
    assert runner.retry_wait(3) > 0
    assert runner.retry_wait(3, transport=True) > 0
    path = tmp_path / "cassette.jsonl"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv(cassette.REPLAY_ENV, str(path))
    assert runner.retry_wait(3) == 0
    assert runner.retry_wait(3, transport=True) == 0


def test_a_replay_steers_no_limit(tmp_path, monkeypatch):
    path = tmp_path / "cassette.jsonl"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv(cassette.REPLAY_ENV, str(path))
    monkeypatch.setenv("EXTRACT_LIMIT_ADAPTIVE", "1")
    monkeypatch.setattr(runner, "LIMIT", None)
    monkeypatch.setattr(providers, "gate", lambda role: pytest.fail(
        "a replay asked for the gate of a server"))
    runner.start_limit()
    assert runner.LIMIT is None


def test_a_harvest_that_asked_something_new_does_not_end_as_a_success(
        tmp_path, monkeypatch, shareable):
    assert runner.unheld_requests() == 0            # no cassette, no verdict
    path, client = record(tmp_path, monkeypatch, FakeServer(["yes"]))
    ask(client)
    held = replay(path, monkeypatch)
    ask(held)
    assert runner.unheld_requests() == 0
    with pytest.raises(cassette.CassetteMiss):
        ask(held, text="Something new")
    assert runner.unheld_requests() == 1


# ------------------------------------------------------- who may be recorded

def test_kwp_says_its_documents_may_be_passed_on():
    assert load_profile("kwp").documents_shareable is True


@pytest.mark.parametrize("name", ["scenarios", "default"])
def test_the_other_profiles_do_not(name):
    assert load_profile(name).documents_shareable is False


@pytest.mark.parametrize("name", ["scenarios", "default", None])
def test_nothing_is_recorded_for_a_profile_that_does_not_say_so(
        tmp_path, monkeypatch, name):
    if name is None:
        monkeypatch.delenv(ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(ENV_VAR, name)
    server = FakeServer(["yes"])
    path = tmp_path / "cassette.jsonl"
    monkeypatch.setenv(cassette.RECORD_ENV, str(path))
    monkeypatch.setattr(providers, "_client", lambda role, kwargs: server)
    with pytest.raises(ValueError) as caught:
        providers.client("llm")
    assert "documents_shareable" in str(caught.value)
    assert repr(name) in str(caught.value)
    assert not path.exists() and server.asked == []


# ------------------------------------------------------------------- vectors

def test_a_vector_is_filed_under_its_text_not_under_its_batch(
        tmp_path, monkeypatch, shareable):
    server = FakeServer(vectors={"a": [1.0, 0.0], "b": [0.0, 1.0]})
    path, client = record(tmp_path, monkeypatch, server)
    client.embeddings.create(model="e", input=["a", "b"])
    held = replay(path, monkeypatch)
    got = held.embeddings.create(model="e", input=["b"])
    assert [item.embedding for item in got.data] == [[0.0, 1.0]]
    got = held.embeddings.create(model="e", input="a")
    assert [item.embedding for item in got.data] == [[1.0, 0.0]]


def test_the_embedder_of_a_replay_is_the_cassette(tmp_path, monkeypatch,
                                                  shareable):
    server = FakeServer(vectors={"heat demand": [0.5, 0.5]})
    path, client = record(tmp_path, monkeypatch, server)
    client.embeddings.create(model="e", input=["heat demand"])
    replay(path, monkeypatch)
    monkeypatch.setattr(embedding, "_from_path", lambda *a, **k: pytest.fail(
        "a replay built an embedder"))
    embedder = embedding.get_embedder("some.module:factory")
    assert embedder.embed_one({"text": "heat demand"}) == [0.5, 0.5]
    with pytest.raises(cassette.CassetteMiss):
        embedder.embed([{"text": "something else"}])
    held = cassette.player()
    assert held.missed == 1
    with pytest.raises(cassette.CassetteMiss):
        embedder.embed([{"text": "heat demand", "image": b"png"}])
    assert held.missed == 2                     # counted like any other


def test_without_a_cassette_the_embedder_is_the_configured_one(monkeypatch):
    made = object()
    monkeypatch.setattr(embedding, "_from_path", lambda spec, **kw: made)
    assert embedding.get_embedder("some.module:factory") is made
