"""The harvested values, handed on.

What is promised, sentence by sentence:

  * the store serves every accepted value AND no refusal AND each with its
    quote, page, level and reasons, as the harvest holds them;
  * a value's id is its `identity` name AND the same after the passage ids
    moved;
  * a value keeps what was read, its wording and how the reading ended for
    every coordinate AND carries the spec's labels where a spec is given;
  * two rows of one document that claim the same thing with another number
    are both served AND both say so (level C, reason conflict);
  * a value of a transcribed document is level B at best;
  * every argument of a search narrows it AND none returns everything AND
    `level` is the worst level still wanted AND a coordinate is asked by
    content or by label;
  * the table has one line per value, the quote and the page in it, a
    column triple per coordinate AND a cell cannot be taken for a formula;
  * the HTTP API answers the four questions AND writes nothing AND asks
    for the token when one is set AND does not listen beyond this machine
    without one;
  * the MCP server answers initialize, ping, tools/list and tools/call AND
    answers no notification AND reports what a tool cannot answer as a
    tool result AND a protocol error as a JSON-RPC error.
"""
import csv
import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from docpipe import cli
from docpipe.extraction import fields, identity
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import TIER_TEXT, TIER_VISUAL
from docpipe.serve import cli as serve_cli
from docpipe.serve import export, http, mcp, tools
from docpipe.serve.values import Values

P = "energy_consumption"
SPEC = {
    "parameters": [{
        "uri": P, "label": "Final energy consumption",
        "description": "Energy delivered to and consumed by end users.",
        "value_type": "float", "unit_target": "MWh/a",
        "units_accepted": {"MWh/a": 1, "GWh/a": 1000},
        "axes": {
            "carrier": {"vocabulary": {"oeo:gas": ["natural gas", "Erdgas"],
                                       "oeo:coal": ["coal", "Kohle"]}},
            "year": {"type": "int"}},
        "example": {"source": "| Erdgas | 241 GWh/a |", "tuples": [{
            "value": 241.0, "unit_raw": "GWh/a", "carrier": "oeo:gas",
            "carrier_raw": "Erdgas", "year": 2040,
            "quote": "| Erdgas | 241 GWh/a |"}]},
    }],
}


def row(value=241.0, quote="| Erdgas | 241 |", carrier="oeo:gas", year=2040,
        tier=TIER_TEXT, owner=7, page=86, **more):
    made = {"kind": "tuple", "parameter": P, "value": value,
            "value_raw": str(int(value)), "unit": "GWh/a",
            "unit_raw": "GWh/a", "value_target": value * 1000, "tier": tier,
            "quote": quote,
            "provenance": {"document_id": 1, "owner_kind": "table",
                           "owner_id": owner, "page": page,
                           "title": "Tabelle 17: Endenergie"},
            "carrier": carrier, "carrier_raw": "Erdgas",
            "carrier_state": fields.READ,
            "year": year, "year_state": fields.READ}
    made.update(more)
    return made


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture
def store(spec):
    return Values({
        "kassel": [row(), row(value=5.0, quote="| Kohle | 5 |",
                              carrier="oeo:coal", carrier_raw="Kohle",
                              tier=TIER_VISUAL),
                   row(value=9.0, quote="| Erdgas | 9 |", year=2030,
                       year_state=fields.EXHAUSTED)],
        "scan": [row(value=3.0, quote="| Erdgas | 3 |")],
    }, spec=spec, transcribed={"scan"})


# ------------------------------------------------------------------ the store

def test_every_accepted_value_is_served_with_what_backs_it(store):
    assert len(store) == 4
    value = store.find(document="kassel", text="241")["values"][0]
    assert value["id"] == identity.tuple_id("kassel", row())
    assert value["document"] == "kassel"
    assert (value["parameter"], value["label"]) == (
        P, "Final energy consumption")
    assert (value["value"], value["unit"]) == (241.0, "GWh/a")
    assert (value["value_target"], value["unit_target"]) == (
        241000.0, "MWh/a")
    assert (value["value_raw"], value["unit_raw"]) == ("241", "GWh/a")
    assert value["quote"] == "| Erdgas | 241 |"
    assert value["page"] == 86
    assert value["source"] == {"owner_kind": "table", "owner_id": 7,
                               "title": "Tabelle 17: Endenergie"}
    assert (value["level"], value["reasons"], value["from_image"]) == (
        "A", [], False)


def test_a_refusal_is_not_a_value(tmp_path, spec):
    lines = [json.dumps(row()), json.dumps({"kind": "refusal",
                                            "parameter": P}),
             json.dumps({"kind": "stamp"})]
    (tmp_path / "kassel.jsonl").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")
    loaded = Values.load(tmp_path, spec=spec)
    assert len(loaded) == 1
    with pytest.raises(FileNotFoundError):
        Values.load(tmp_path / "nowhere")


def test_the_id_does_not_move_with_the_passage_ids(spec):
    before = Values({"a": [row(owner=7)]}, spec=spec)
    after = Values({"a": [row(owner=991)]}, spec=spec)
    name = before.find()["values"][0]["id"]
    assert after.get(name)["value"] == 241.0
    assert before.get("nothing") is None


def test_a_coordinate_keeps_what_was_read_and_how(store):
    value = store.find(text="| Erdgas | 9 |")["values"][0]
    assert value["coordinates"]["carrier"] == {
        "value": "oeo:gas", "state": fields.READ, "wording": "Erdgas",
        "label": "natural gas"}
    assert value["coordinates"]["year"] == {
        "value": 2030, "state": fields.EXHAUSTED}
    assert (value["level"], value["reasons"]) == ("C", ["exhausted:year"])


def test_without_a_spec_a_value_has_no_label():
    bare = Values({"a": [row()]}).find()["values"][0]
    assert bare["label"] is None
    assert "label" not in bare["coordinates"]["carrier"]
    assert "unit_target" not in bare


def test_where_and_how_a_value_was_read_decides_its_level(store):
    by_quote = {value["quote"]: value for value in store.find()["values"]}
    assert by_quote["| Kohle | 5 |"]["level"] == "B"
    assert by_quote["| Kohle | 5 |"]["from_image"] is True
    scanned = by_quote["| Erdgas | 3 |"]
    assert (scanned["level"], scanned["reasons"]) == (
        "B", ["page_transcribed"])


def test_two_rows_that_claim_the_same_with_another_number_both_say_so(spec):
    one, other = row(), row(value=250.0, quote="Erdgas: 250 GWh")
    apart = row(value=250.0, quote="2030: 250 GWh", year=2030)
    served = Values({"a": [one, other, apart]}, spec=spec).find()["values"]
    by_quote = {value["quote"]: value for value in served}
    assert len(served) == 3
    for quote in ("| Erdgas | 241 |", "Erdgas: 250 GWh"):
        assert by_quote[quote]["level"] == "C"
        assert by_quote[quote]["reasons"] == ["conflict"]
    assert by_quote["2030: 250 GWh"]["level"] == "A"


def test_the_same_number_read_twice_is_no_conflict(spec):
    served = Values({"a": [row(), row(quote="Erdgas 241 GWh/a")]},
                    spec=spec).find()["values"]
    assert [value["level"] for value in served] == ["A", "A"]


def test_documents_and_parameters(store):
    assert store.documents() == [
        {"document": "kassel", "values": 3, "parameters": 1},
        {"document": "scan", "values": 1, "parameters": 1}]
    (parameter,) = store.parameters()
    assert parameter["parameter"] == P
    assert parameter["label"] == "Final energy consumption"
    assert (parameter["values"], parameter["documents"]) == (4, 2)
    assert parameter["units"] == {"GWh/a": 4}
    assert parameter["coordinates"]["carrier"] == [
        {"value": "oeo:gas", "count": 3, "label": "natural gas"},
        {"value": "oeo:coal", "count": 1, "label": "coal"}]
    assert parameter["coordinates"]["year"] == [
        {"value": 2040, "count": 3}, {"value": 2030, "count": 1}]


# --------------------------------------------------------------------- search

def test_no_argument_returns_everything(store):
    found = store.find()
    assert found["total"] == 4 and len(found["values"]) == 4


@pytest.mark.parametrize("arguments, total", [
    ({"document": "scan"}, 1),
    ({"document": "nowhere"}, 0),
    ({"parameter": P}, 4),
    ({"parameter": "final energy  consumption"}, 4),    # by label
    ({"parameter": "emissions"}, 0),
    ({"level": "A"}, 1),
    ({"level": "B"}, 3),
    ({"level": "C"}, 4),
    ({"coordinates": {"year": 2030}}, 1),
    ({"coordinates": {"year": "2030"}}, 1),
    ({"coordinates": {"carrier": "oeo:coal"}}, 1),
    ({"coordinates": {"carrier": "Natural Gas"}}, 3),   # by label
    ({"coordinates": {"carrier": "oeo:gas", "year": 2040}}, 2),
    ({"coordinates": {"sector": "industry"}}, 0),       # not a coordinate
    ({"text": "kohle"}, 1),
    ({"text": "erdgas"}, 3),
    ({"text": "natural gas"}, 3),           # the label of a coordinate
    ({"text": "tabelle"}, 0),               # the source title is not text
    ({"document": "kassel", "level": "B", "text": "erdgas"}, 1),
])
def test_every_argument_narrows(store, arguments, total):
    assert store.find(**arguments)["total"] == total


def test_a_page_of_the_result(store):
    first = store.find(limit=3)
    rest = store.find(limit=3, offset=3)
    assert (first["total"], len(first["values"]), len(rest["values"])) \
        == (4, 3, 1)
    assert rest["offset"] == 3
    assert [v["id"] for v in first["values"] + rest["values"]] \
        == [v["id"] for v in store.find()["values"]]
    assert store.find(limit=0)["values"] == []


@pytest.mark.parametrize("arguments", [{"level": "D"}, {"limit": -1},
                                       {"offset": -1}])
def test_a_search_that_cannot_be_asked(store, arguments):
    with pytest.raises(ValueError):
        store.find(**arguments)


# ---------------------------------------------------------------------- table

def test_the_table_has_one_line_per_value_with_quote_and_page(store):
    text = export.to_csv(store.find()["values"])
    lines = list(csv.DictReader(io.StringIO(text)))
    assert len(lines) == 4
    first = lines[0]
    assert first["quote"] == "| Erdgas | 241 |" and first["page"] == "86"
    assert (first["value"], first["unit"], first["level"]) == (
        "241.0", "GWh/a", "A")
    assert (first["carrier"], first["carrier_label"],
            first["carrier_state"]) == ("oeo:gas", "natural gas",
                                        fields.READ)
    assert first["source_kind"] == "table"
    header = text.splitlines()[0].split(",")
    assert header[:len(export.FIXED)] == list(export.FIXED)
    assert header[len(export.FIXED):] == [
        "carrier", "carrier_label", "carrier_state",
        "year", "year_label", "year_state"]
    assert lines[2]["reasons"] == "exhausted:year"


@pytest.mark.parametrize("quote", ["=1+1", "+49 30", "-12 %", "@sum"])
def test_a_cell_cannot_be_taken_for_a_formula(store, quote):
    value = dict(store.find()["values"][0], quote=quote)
    (line,) = csv.DictReader(io.StringIO(export.to_csv([value])))
    assert line["quote"] == "'" + quote


def test_json_lines_carry_the_value_whole(store):
    values = store.find()["values"]
    lines = export.to_jsonl(values).splitlines()
    assert [json.loads(line) for line in lines] == values


def test_an_empty_table_still_has_its_header():
    assert export.to_csv([]).strip() == ",".join(export.FIXED)


# ------------------------------------------------------------------- commands

def _harvest(tmp_path):
    folder = tmp_path / "harvest"
    folder.mkdir()
    (folder / "kassel.jsonl").write_text(
        json.dumps(row()) + "\n" + json.dumps(
            row(value=5.0, quote="| Kohle | 5 |", carrier="oeo:coal",
                tier=TIER_VISUAL)) + "\n",
        encoding="utf-8")
    return folder


def test_docpipe_export_writes_the_table(tmp_path, capsys):
    folder = _harvest(tmp_path)
    out = tmp_path / "out" / "values.csv"
    assert serve_cli.export_main([str(folder), "--out", str(out)]) == 0
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")     # for Excel
    assert len(out.read_text(encoding="utf-8-sig").splitlines()) == 3
    assert "2 value(s)" in capsys.readouterr().err

    lines = tmp_path / "values.jsonl"
    assert serve_cli.export_main([str(folder), "--out", str(lines),
                                  "--level", "A"]) == 0
    (only,) = lines.read_text(encoding="utf-8").splitlines()
    assert json.loads(only)["quote"] == "| Erdgas | 241 |"

    assert serve_cli.export_main([str(folder), "--format", "jsonl"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_the_commands_refuse_what_is_not_there(tmp_path):
    with pytest.raises(SystemExit) as caught:
        serve_cli.export_main([str(tmp_path / "nowhere")])
    assert "not a directory" in str(caught.value)
    with pytest.raises(SystemExit) as caught:
        serve_cli.export_main([str(_harvest(tmp_path)), "--db",
                               str(tmp_path / "no.db")])
    assert "no.db" in str(caught.value)
    with pytest.raises(SystemExit):
        serve_cli.serve_main([str(tmp_path)])          # neither --http/--mcp


def test_the_commands_are_commands():
    assert cli.STAGES["export"][0] == "docpipe.serve.export"
    assert cli.STAGES["serve"][0] == "docpipe.serve"


# ------------------------------------------------------------------- HTTP API

def test_the_api_answers_the_four_questions(store):
    status, body = http.answer(store, "/")
    assert status == 200 and body["values"] == 4
    assert set(body["endpoints"]) == {"/documents", "/parameters", "/values",
                                      "/values/<id>"}
    assert http.answer(store, "/documents") == (
        200, {"documents": store.documents()})
    assert http.answer(store, "/parameters")[1]["parameters"] \
        == store.parameters()
    status, body = http.answer(
        store, "/values", "document=kassel&coordinate.year=2040&level=B")
    assert status == 200 and body["total"] == 2
    name = body["values"][0]["id"]
    assert http.answer(store, f"/values/{name}") == (200, store.get(name))


@pytest.mark.parametrize("path, query, status, says", [
    ("/values", "level=D", 400, "level must be one of"),
    ("/values", "limit=many", 400, "limit must be a whole number"),
    ("/values", "limit=-1", 400, "must not be negative"),
    ("/values", "colour=red", 400, "unknown argument(s): colour"),
    ("/values", "document=a&document=b", 400, "document is given twice"),
    ("/values/nothing", "", 404, "no value 'nothing'"),
    ("/tables", "", 404, "no such path"),
    ("/values/a/b", "", 404, "no such path"),
])
def test_what_the_api_cannot_answer(store, path, query, status, says):
    got, body = http.answer(store, path, query)
    assert got == status and says in body["error"]


@pytest.fixture
def running(store, monkeypatch):
    def start(secret=None):
        if secret is None:
            monkeypatch.delenv(http.TOKEN_ENV, raising=False)
        else:
            monkeypatch.setenv(http.TOKEN_ENV, secret)
        server = http.make_server(store, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}"

    started = []
    yield start
    for server, thread in started:
        server.shutdown()
        server.server_close()
        thread.join(5)


def _get(url, method="GET", **headers):
    request = urllib.request.Request(url, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as reply:
            return reply.status, reply.headers, reply.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def test_the_server_answers_in_json_and_writes_nothing(running):
    base = running()
    status, headers, body = _get(base + "/values?text=kohle")
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body)["total"] == 1
    status, _headers, body = _get(base + "/values", method="HEAD")
    assert status == 200 and body == b""
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        status, headers, _body = _get(base + "/values", method=method)
        assert status == 405 and headers["Allow"] == "GET, HEAD"


def test_with_a_token_set_every_request_has_to_carry_it(running):
    base = running("s3cret-for-this-test")
    status, headers, body = _get(base + "/documents")
    assert status == 401 and headers["WWW-Authenticate"] == "Bearer"
    assert "documents" not in json.loads(body)
    assert _get(base + "/documents", Authorization="Bearer wrong")[0] == 401
    assert _get(base + "/documents",
                Authorization="s3cret-for-this-test")[0] == 401
    status, _headers, body = _get(
        base + "/documents", Authorization="Bearer s3cret-for-this-test")
    assert status == 200 and len(json.loads(body)["documents"]) == 2


def test_it_does_not_listen_beyond_this_machine_without_a_token(
        store, monkeypatch):
    monkeypatch.delenv(http.TOKEN_ENV, raising=False)
    with pytest.raises(SystemExit) as caught:
        http.make_server(store, "0.0.0.0", 0)
    assert http.TOKEN_ENV in str(caught.value)
    monkeypatch.setenv(http.TOKEN_ENV, "  ")            # blank is not a token
    with pytest.raises(SystemExit):
        http.make_server(store, "0.0.0.0", 0)


# ------------------------------------------------------------------------ MCP

def call(store, method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return mcp.respond(store, message)


def test_initialize_names_the_server_and_its_tools_capability(store):
    got = call(store, "initialize", {"protocolVersion": "2025-03-26",
                                     "capabilities": {}})
    assert got["id"] == 1 and got["jsonrpc"] == "2.0"
    result = got["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "docpipe"
    assert "list_parameters" in result["instructions"]
    newest = call(store, "initialize", {"protocolVersion": "1999-01-01"})
    assert newest["result"]["protocolVersion"] == mcp.VERSIONS[0]


def test_ping_and_the_list_of_tools(store):
    assert call(store, "ping")["result"] == {}
    listed = call(store, "tools/list")["result"]["tools"]
    assert [tool["name"] for tool in listed] == [
        "list_documents", "list_parameters", "find_values", "get_value"]
    for tool in listed:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_a_tool_call_answers_what_the_api_answers(store):
    got = call(store, "tools/call", {"name": "find_values", "arguments": {
        "document": "kassel", "coordinates": {"year": 2040}}})["result"]
    assert got["isError"] is False
    assert got["structuredContent"] == store.find(
        document="kassel", coordinates={"year": 2040})
    (part,) = got["content"]
    assert part["type"] == "text"
    assert json.loads(part["text"]) == got["structuredContent"]
    name = got["structuredContent"]["values"][0]["id"]
    one = call(store, "tools/call", {"name": "get_value",
                                     "arguments": {"id": name}})["result"]
    assert one["structuredContent"] == store.get(name)
    assert call(store, "tools/call", {"name": "list_documents"})[
        "result"]["structuredContent"] == {"documents": store.documents()}


@pytest.mark.parametrize("arguments, says", [
    ({"level": "D"}, "level must be one of"),
    ({"colour": "red"}, "unknown argument(s): colour"),
    ({"coordinates": [2030]}, "coordinates must be an object"),
])
def test_what_a_tool_cannot_answer_is_a_tool_result(store, arguments, says):
    got = call(store, "tools/call", {"name": "find_values",
                                     "arguments": arguments})
    assert "error" not in got
    assert got["result"]["isError"] is True
    assert says in got["result"]["content"][0]["text"]


def test_a_value_that_is_not_there_is_a_tool_result(store):
    got = call(store, "tools/call", {"name": "get_value",
                                     "arguments": {"id": "nothing"}})
    assert got["result"]["isError"] is True
    assert "nothing" in got["result"]["content"][0]["text"]
    got = call(store, "tools/call", {"name": "get_value", "arguments": {}})
    assert got["result"]["isError"] is True


@pytest.mark.parametrize("message, code", [
    ({"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
     mcp.METHOD_NOT_FOUND),
    ({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
      "params": {"name": "drop_everything"}}, mcp.INVALID_PARAMS),
    ({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": [1]},
     mcp.INVALID_PARAMS),
    ({"jsonrpc": "1.0", "id": 3, "method": "ping"}, mcp.INVALID_REQUEST),
    ({"id": 3}, mcp.INVALID_REQUEST),
    ([1, 2], mcp.INVALID_REQUEST),
])
def test_a_protocol_error_is_a_json_rpc_error(store, message, code):
    got = mcp.respond(store, message)
    assert got["error"]["code"] == code and "result" not in got


def test_a_notification_is_not_answered(store):
    assert mcp.respond(store, {"jsonrpc": "2.0",
                               "method": "notifications/initialized"}) is None
    assert mcp.respond(store, {"jsonrpc": "2.0", "method": "ping"}) is None


def test_the_server_answers_line_by_line_until_the_input_ends(store):
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}),
        json.dumps({"jsonrpc": "2.0",
                    "method": "notifications/initialized"}),
        "",
        "{this is not json",
        json.dumps({"jsonrpc": "2.0", "id": "b", "method": "tools/call",
                    "params": {"name": "list_parameters"}}),
    ]
    sink = io.StringIO()
    assert mcp.serve(store, io.StringIO("\n".join(lines) + "\n"), sink) == 0
    answers = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert [answer.get("id") for answer in answers] == [1, None, "b"]
    assert answers[1]["error"]["code"] == mcp.PARSE_ERROR
    assert answers[2]["result"]["structuredContent"]["parameters"][0][
        "parameter"] == P


def test_one_failing_call_does_not_end_the_server(store, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tools, "call", broken)
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "list_documents"}}),
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})]
    sink = io.StringIO()
    mcp.serve(store, io.StringIO("\n".join(lines) + "\n"), sink)
    first, second = [json.loads(line) for line in
                     sink.getvalue().splitlines()]
    assert first["error"]["code"] == -32603 and first["id"] == 1
    assert "boom" not in json.dumps(first)
    assert second == {"jsonrpc": "2.0", "id": 2, "result": {}}


# --------------------------------------------------- the edges of the above

def test_an_export_writes_every_value_and_counts_what_it_wrote(tmp_path,
                                                               capsys):
    """More values than one answer of a server carries. A file gets all of
    them, and the count that is printed is the count of its lines."""
    from docpipe.serve.values import MAX_LIMIT
    many = MAX_LIMIT + 5
    folder = tmp_path / "harvest"
    folder.mkdir()
    (folder / "kassel.jsonl").write_text("".join(
        json.dumps(row(value=float(index), quote=f"| Zeile | {index} |",
                       year=1000 + index)) + "\n"
        for index in range(many)), encoding="utf-8")
    out = tmp_path / "values.csv"
    assert serve_cli.export_main([str(folder), "--out", str(out)]) == 0
    with open(out, encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == many
    assert f"{many} value(s)" in capsys.readouterr().err
    # a server's answer stays held to the limit
    assert len(Values.load(folder).find(limit=many)["values"]) == MAX_LIMIT


@pytest.mark.parametrize("other, conflict", [
    # the same reading in another unit
    (dict(value=241000.0, unit="MWh/a", value_target=241000.0), False),
    # another number in the kept unit
    (dict(value=250000.0, unit="MWh/a", value_target=250000.0), True),
    # not converted: held by its number and its unit, as written
    (dict(value=241000.0, unit="MWh/a", value_target=None), True),
    (dict(value=241.0, unit="GWh/a", value_target=None), False),
])
def test_one_reading_in_two_units_is_no_conflict(other, conflict):
    rows = [row(), row(quote="| Erdgas | 241.000 MWh |", **other)]
    served = Values({"kassel": rows}).find()["values"]
    assert [("conflict" in value["reasons"]) for value in served] \
        == [conflict, conflict]


@pytest.mark.parametrize("quote", ["a\rb", "a\nb", "a\r\nb", 'a "b", c'])
def test_a_cell_with_a_line_break_comes_back_as_one_cell(quote):
    store = Values({"kassel": [row(quote=quote), row(value=5.0,
                                                    quote="| Kohle | 5 |")]})
    text = export.to_csv(store.find()["values"])
    lines = list(csv.DictReader(io.StringIO(text, newline="")))
    assert [line["quote"] for line in lines] == [quote, "| Kohle | 5 |"]


@pytest.mark.parametrize("start", ["=", "+", "-", "@", "\t", "\r"])
def test_text_that_begins_like_a_formula_is_written_as_text(start):
    assert export._cell(start + "cmd") == "'" + start + "cmd"
    assert export._cell("cmd" + start) == "cmd" + start
    assert export._cell(-5.0) == -5.0


def _piped(data=b"", encoding="cp1252"):
    """A standard stream as a terminal with a code page gives it."""
    return io.TextIOWrapper(io.BytesIO(data), encoding=encoding)


def test_the_mcp_server_speaks_utf8_whatever_the_terminal_does(monkeypatch):
    """A quote with a character the code page does not have. The protocol's
    text is UTF-8 in both directions."""
    store = Values({"kassel": [row(quote="| CO\u2082 aus Erdgas | 241 |")]})
    asked = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "find_values", "arguments": {
                            "text": "CO\u2082"}}}, ensure_ascii=False)
    source, sink = _piped((asked + "\n").encode("utf-8")), _piped()
    monkeypatch.setattr("sys.stdin", source)
    monkeypatch.setattr("sys.stdout", sink)
    assert mcp.serve(store) == 0
    sink.flush()
    (answer,) = [json.loads(line) for line in
                 sink.buffer.getvalue().decode("utf-8").split("\n") if line]
    found = answer["result"]["structuredContent"]
    assert found["total"] == 1                  # the question was read right
    assert found["values"][0]["quote"] == "| CO\u2082 aus Erdgas | 241 |"


def test_an_export_to_standard_output_is_utf8_with_its_own_line_ends(
        tmp_path, monkeypatch):
    folder = tmp_path / "harvest"
    folder.mkdir()
    (folder / "kassel.jsonl").write_text(
        json.dumps(row(quote="| CO\u2082 | 241 |\nZeile zwei"),
                   ensure_ascii=False) + "\n", encoding="utf-8")
    sink = _piped()
    monkeypatch.setattr("sys.stdout", sink)
    assert serve_cli.export_main([str(folder)]) == 0
    sink.flush()
    written = sink.buffer.getvalue()
    assert "CO\u2082".encode("utf-8") in written
    assert b"\r\r\n" not in written             # no line end written twice
    (line,) = csv.DictReader(io.StringIO(written.decode("utf-8"),
                                         newline=""))
    assert line["quote"] == "| CO\u2082 | 241 |\nZeile zwei"


def test_a_token_is_held_as_the_bytes_that_were_sent(running):
    base = running("p\u00e4ssword")
    sent = "p\u00e4ssword".encode("utf-8").decode("latin-1")   # as on the wire
    assert _get(base + "/documents", Authorization=f"Bearer {sent}")[0] == 200
    assert _get(base + "/documents", Authorization=f"bearer {sent}")[0] == 200
    assert _get(base + "/documents", Authorization=f"BEARER {sent}")[0] == 200
    assert _get(base + "/documents", Authorization="Bearer password")[0] \
        == 401
    assert _get(base + "/documents", Authorization=f"Basic {sent}")[0] == 401
    assert _get(base + "/documents", Authorization="Bearer")[0] == 401


def test_a_coordinate_given_twice_is_refused_like_any_other_argument(store):
    status, body = http.answer(store, "/values",
                               "coordinate.year=2030&coordinate.year=2040")
    assert status == 400 and "coordinate.year is given twice" in body["error"]
    status, body = http.answer(store, "/values",
                               "coordinate.year=2040&coordinate.carrier=gas")
    assert status == 200


def test_the_server_listens_on_an_address_of_either_family(store,
                                                           monkeypatch):
    import socket
    monkeypatch.delenv(http.TOKEN_ENV, raising=False)
    if not socket.has_ipv6:
        pytest.skip("no IPv6 here")
    try:
        server = http.make_server(store, "::1", 0)
    except OSError as exc:
        pytest.skip(f"no IPv6 loopback here ({exc})")
    try:
        assert server.address_family == socket.AF_INET6
    finally:
        server.server_close()
    plain = http.make_server(store, "127.0.0.1", 0)
    try:
        assert plain.address_family == socket.AF_INET
    finally:
        plain.server_close()
