"""Tests for the vLLM vision layer: JSON parsing, base64 images, the chat call."""
import base64


from docpipe.visuals import vision as V


def test_parse_json_response_variants():
    assert V._parse_json_response('{"a": 1}')[0] == {"a": 1}
    assert V._parse_json_response("<think>reason</think>{\"a\": 2}")[0] == {"a": 2}
    assert V._parse_json_response("```json\n{\"a\": 3}\n```")[0] == {"a": 3}
    assert V._parse_json_response("blah {\"a\": 4} blah")[0] == {"a": 4}
    parsed, err = V._parse_json_response("not json")
    assert parsed is None and err


def test_image_data_url_roundtrips(tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"\x89PNG\r\n")
    url = V._image_data_url(p)
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNG\r\n"


def test_check_model_available_requires_exact_match(make_client):
    client = make_client(lambda kw: None, model_id="my-model")
    assert V.check_model_available(client, "my-model")
    assert not V.check_model_available(client, "other-model")


def test_call_vision_happy_path(make_client, seq_responder, tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"x")
    client = make_client(seq_responder(['{"markdown": "M", "caption": "C"}']))
    assert V.call_vision(client, "sys", "user", p) == {"markdown": "M", "caption": "C"}


def test_call_vision_sends_base64_image_and_json_format(make_client, seq_responder, tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"x")
    rec = []
    client = make_client(seq_responder(['{"a": 1}']), recorder=rec)
    V.call_vision(client, "sys", "user", p)
    content = rec[0]["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert rec[0]["response_format"] == {"type": "json_object"}


def test_call_vision_timeout_escalates_repetition_penalty(
        make_client, seq_responder, openai_error, tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"x")
    rec = []
    client = make_client(
        seq_responder([openai_error("t", timeout=True), '{"a": 1}']),
        recorder=rec)
    assert V.call_vision(client, "sys", "user", p) == {"a": 1}
    assert rec[1]["extra_body"]["repetition_penalty"] == 1.1


def test_call_vision_exhausts_to_none(make_client, seq_responder,
                                      openai_error, tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"x")
    client = make_client(seq_responder([openai_error("boom")]))
    assert V.call_vision(client, "sys", "user", p) is None
