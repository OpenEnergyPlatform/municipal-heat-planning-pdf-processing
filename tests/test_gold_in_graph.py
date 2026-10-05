"""A person's decision on a value is kept beside the value, and changes nothing.

What is promised: a serialized graph keeps what a person decided about a field
of a value beside that value (kwp: a `Decision` node in the provenance file
that points at the value, with the verdict, the name, the time and the note;
scenarios: a comment line above the value) AND the value is the same with the
decision as without it (the graph's Turtle is unchanged, the provenance has
only the decision's triples more, and a "wrong" verdict leaves the value in
the graph) AND a value nobody decided carries none AND a decision for a row
the harvest does not hold is counted and named in a log line AND decisions are
looked up after the harvest is read, never in `collect`.
"""
import json
import logging

import pytest

from docpipe.extraction import gold, provenance, serialize
from tests import golden_graph_inputs as inputs

rdflib = pytest.importorskip("rdflib")
if not hasattr(rdflib, "Graph") or not hasattr(rdflib.Graph, "parse"):
    pytest.skip("rdflib is a stub here", allow_module_level=True)

RDF_TYPE = rdflib.URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
RDF_VALUE = rdflib.URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#value")
CREATOR = rdflib.URIRef("http://purl.org/dc/terms/creator")
CREATED = rdflib.URIRef("http://purl.org/dc/terms/created")
COMMENT = rdflib.URIRef("http://www.w3.org/2000/01/rdf-schema#comment")
XSD_DATE_TIME = rdflib.URIRef("http://www.w3.org/2001/XMLSchema#dateTime")
MHPX = "https://purl.org/mhpo/prov/"
ABOUT = rdflib.URIRef(MHPX + "about")
DECISION = rdflib.URIRef(MHPX + "Decision")
HAS_NUMBER = "OEO_00140178"
AT = "2026-10-05T10:00:00+00:00"
DOCUMENT = "plan_kassel"


def _dir(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    return folder


def _harvest(tmp_path, name, rows):
    folder = tmp_path / "harvest"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return folder


def _kwp_rows():
    return [inputs.kwp_row(year_state="read"),
            inputs.kwp_row(year=2035, value_target=77.0, year_state="read",
                           quote="| Erdgas | 77 |")]


def _kwp(tmp_path, held=None):
    """(graph text, provenance graph, graph) of the kwp harvest in
    *tmp_path*, serialized with the decisions *held*."""
    from profiles.kwp import kg
    folder = _harvest(tmp_path, DOCUMENT, _kwp_rows())
    out = tmp_path / "graph.ttl"
    write = kg.make_serializer(inputs.kwp_database(tmp_path))
    writer = provenance.Writer(kg.PROVENANCE["base"], kg.PROVENANCE)
    serialize.run(folder, out, write, writer, gold=held)
    return (out.read_text(encoding="utf-8"),
            rdflib.Graph().parse(provenance.path_for(out), format="turtle"),
            rdflib.Graph().parse(out, format="turtle"))


def _harvested(tmp_path):
    return serialize.collect(_harvest(tmp_path, DOCUMENT, _kwp_rows()))[
        DOCUMENT]


def _decided(tmp_path, *entries):
    """The decisions file of *tmp_path*'s harvest, with *entries* written to
    it: (row index, field, verdict, by, note)."""
    rows = _harvested(tmp_path)
    path = gold.path_beside(tmp_path / "harvest")
    for index, field, verdict, by, note in entries:
        gold.decide(path, DOCUMENT, rows[index], field, verdict, by=by,
                    note=note, at=AT)
    return gold.Gold.load(path)


def _value_node(graph, number):
    (node,) = [s for s, p, o in graph
               if str(p).endswith(HAS_NUMBER) and float(o) == number]
    return node


def _decisions(found):
    return sorted(found.subjects(RDF_TYPE, DECISION))


def _stable(graph, leave=()):
    """The triples of a graph that two parses of one file share: no blank
    node, and none of the subjects in *leave*."""
    return {(s, p, o) for s, p, o in graph
            if not isinstance(s, rdflib.BNode)
            and not isinstance(o, rdflib.BNode) and s not in leave}


# ---------------------------------------------------- kwp: the provenance file

def test_a_decided_value_carries_its_record_in_the_provenance_file(tmp_path):
    held = _decided(tmp_path, (0, "year", gold.WRONG, "Anna",
                               "the column is 2035"))
    _text, found, graph = _kwp(tmp_path, held)
    value = _value_node(graph, 241.0)
    (decision,) = _decisions(found)
    assert (decision, ABOUT, value) in found
    said = {p: o for _s, p, o in found.triples((decision, None, None))}
    assert str(said[rdflib.URIRef(MHPX + "coordinate")]) == "year"
    assert str(said[RDF_VALUE]) == gold.WRONG
    assert str(said[CREATOR]) == "Anna"
    assert str(said[COMMENT]) == "the column is 2035"
    assert str(said[CREATED]) == AT and said[CREATED].datatype == XSD_DATE_TIME
    # nothing starts from the value: the graph stays the graph's own
    assert not list(found.triples((value, None, None)))


def test_a_value_nobody_decided_carries_none(tmp_path):
    held = _decided(tmp_path, (0, "value", gold.CORRECT, "Anna", None))
    _text, found, graph = _kwp(tmp_path, held)
    (decision,) = _decisions(found)
    assert (decision, ABOUT, _value_node(graph, 241.0)) in found
    assert (decision, ABOUT, _value_node(graph, 77.0)) not in found


def test_no_decisions_no_decision_node(tmp_path):
    _text, found, _graph = _kwp(_dir(tmp_path, "none"), None)
    assert _decisions(found) == []
    _text, found, _graph = _kwp(_dir(tmp_path, "empty"), gold.Gold([]))
    assert _decisions(found) == []


def test_a_wrong_verdict_leaves_the_value_in_the_graph(tmp_path):
    held = _decided(tmp_path, (0, "value", gold.WRONG, "Anna", None),
                    (0, "year", gold.WRONG, "Anna", None))
    text, found, graph = _kwp(_dir(tmp_path, "with"), held)
    without_text, without, _graph = _kwp(_dir(tmp_path, "without"), None)
    # the graph is the same, byte for byte, and the value is still in it
    assert text == without_text
    assert _value_node(graph, 241.0)
    # and the provenance is the same but for the decisions' own triples
    decisions = set(_decisions(found))
    assert len(decisions) == 2 and _decisions(without) == []
    assert _stable(found, leave=decisions) == _stable(without)
    assert _stable(found) != _stable(without)       # the comparison can fail


def test_what_a_person_said_last_is_what_is_recorded(tmp_path):
    rows = _harvested(tmp_path)
    path = gold.path_beside(tmp_path / "harvest")
    gold.decide(path, DOCUMENT, rows[0], "value", gold.WRONG, by="Anna",
                note="first thought", at=AT)
    gold.decide(path, DOCUMENT, rows[0], "value", gold.CORRECT, by="Ben",
                note="on second thought", at="2026-10-06T08:00:00+00:00")
    _text, found, _graph = _kwp(tmp_path, gold.Gold.load(path))
    (decision,) = _decisions(found)
    assert str(found.value(decision, RDF_VALUE)) == gold.CORRECT
    assert str(found.value(decision, CREATOR)) == "Ben"


def test_a_note_with_quotes_and_line_breaks_reads_back_as_it_was_written(
        tmp_path):
    """What a person types into a note cannot break the provenance file or
    add a statement to it."""
    note = ("a " + chr(34) + "quoted" + chr(34) + " word, a " + chr(92)
            + " backslash," + chr(10) + "another line <urn:x:y> a <urn:z> . "
            "# no comment")
    held = _decided(tmp_path, (0, "value", gold.WRONG, "Anna", note))
    _text, found, _graph = _kwp(tmp_path, held)
    (decision,) = _decisions(found)
    assert str(found.value(decision, COMMENT)) == note
    assert not [s for s in found.subjects() if str(s) == "urn:x:y"]


def test_a_time_that_is_no_datetime_stays_a_string_and_no_name_is_none(
        tmp_path):
    rows = _harvested(tmp_path)
    path = gold.path_beside(tmp_path / "harvest")
    gold.decide(path, DOCUMENT, rows[0], "value", gold.CORRECT, at="Monday")
    _text, found, _graph = _kwp(tmp_path, gold.Gold.load(path))
    (decision,) = _decisions(found)
    created = found.value(decision, CREATED)
    assert str(created) == "Monday" and created.datatype is None
    assert found.value(decision, COMMENT) is None
    assert found.value(decision, CREATOR) is None


def test_a_decision_on_the_second_of_two_rows_of_one_name_is_on_its_value(
        tmp_path):
    """Two rows with one quote and one value, read for two years: the same
    name in their document, `<id>` and `<id>.2`. The decision on the second
    is recorded on the second's value and on no other."""
    from profiles.kwp import kg
    rows = [inputs.kwp_row(year_state="read"),
            inputs.kwp_row(year=2035, year_state="read")]
    folder = _harvest(tmp_path, DOCUMENT, rows)
    harvested = serialize.collect(folder)[DOCUMENT]
    first, second = gold.identity.tuple_ids(DOCUMENT, harvested)
    assert second == first + ".2"
    path = gold.path_beside(folder)
    gold.decide(path, DOCUMENT, harvested[1], "year", gold.WRONG, by="Anna",
                at=AT)
    out = tmp_path / "graph.ttl"
    write = kg.make_serializer(inputs.kwp_database(tmp_path))
    writer = provenance.Writer(kg.PROVENANCE["base"], kg.PROVENANCE)
    serialize.run(folder, out, write, writer, gold=gold.Gold.load(path))
    graph = rdflib.Graph().parse(out, format="turtle")
    found = rdflib.Graph().parse(provenance.path_for(out), format="turtle")
    (value_2035,) = set(graph.subjects(None, rdflib.URIRef(kg.year_iri(2035))))
    (value_2030,) = set(graph.subjects(None, rdflib.URIRef(kg.year_iri(2030))))
    (decision,) = _decisions(found)
    assert (decision, ABOUT, value_2035) in found
    assert (decision, ABOUT, value_2030) not in found


def test_one_name_two_values_a_decision_is_recorded_once():
    """A writer that gave no `id` leaves two values of one name; the
    decision belongs to the first, as it does with the ids of `tuple_ids`."""
    row = inputs.kwp_row()
    one = {"field": "value", "verdict": "wrong", "by": None, "at": None,
           "note": None}
    name = gold.identity.tuple_id("a", row)
    writer = provenance.Writer("https://graph.test/id/")
    writer.add("a", {"document": "https://graph.test/id/plan/a", "values": [
        {"about": "https://graph.test/id/value/0", "row": row},
        {"about": "https://graph.test/id/value/1", "row": row}]},
        decisions={name: [one]})
    assert writer.decisions == 1
    found = rdflib.Graph().parse(
        data=writer.header() + "\n" + "\n".join(writer.parts),
        format="turtle")
    decided = rdflib.URIRef(writer.term("Decision").strip("<>"))
    (decision,) = list(found.subjects(RDF_TYPE, decided))
    assert list(found.objects(decision, rdflib.URIRef(
        writer.term("about").strip("<>")))) == [
            rdflib.URIRef("https://graph.test/id/value/0")]


# ------------------------------------------ the decisions of a row not in it

def test_a_decision_on_a_row_the_harvest_does_not_hold_is_counted_and_named(
        tmp_path, caplog):
    rows = _harvested(tmp_path)
    path = gold.path_beside(tmp_path / "harvest")
    gold.decide(path, DOCUMENT, rows[0], "value", gold.CORRECT, by="Anna",
                at=AT)
    gone = dict(rows[0], quote="a passage nobody harvested")
    gold.decide(path, DOCUMENT, gone, "value", gold.WRONG, by="Ben", at=AT)
    gold.decide(path, DOCUMENT, gone, "year", gold.WRONG, by="Ben", at=AT)
    gold.decide(path, "plan_not_harvested", gone, "value", gold.WRONG, at=AT)
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        _text, found, _graph = _kwp(tmp_path, gold.Gold.load(path))
    (line,) = [r.getMessage() for r in caplog.records
               if "the harvest does not hold" in r.getMessage()]
    assert "3 decision(s) on 2 row(s)" in line
    assert f"{DOCUMENT}/{gold.row_key(DOCUMENT, gone)[1]}/energy_consumption" \
        in line
    assert "plan_not_harvested/" in line
    assert len(_decisions(found)) == 1, "only the row that is there"
    assert any("1 decision(s) on 1 row(s) of 1 document(s) read" in
               r.getMessage() for r in caplog.records)


def test_a_decision_on_a_row_that_is_there_is_not_called_a_stray(
        tmp_path, caplog):
    held = _decided(tmp_path, (0, "value", gold.CORRECT, None, None),
                    (1, "value", gold.WRONG, None, None))
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        _kwp(tmp_path, held)
    assert "the harvest does not hold" not in caplog.text


def test_a_log_line_names_some_rows_and_counts_the_rest(tmp_path, caplog):
    rows = _harvested(tmp_path)
    path = gold.path_beside(tmp_path / "harvest")
    many = serialize.NAMED + 3
    for index in range(many):
        gold.decide(path, DOCUMENT, dict(rows[0], quote=f"gone {index}"),
                    "value", gold.WRONG, at=AT)
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        _kwp(tmp_path, gold.Gold.load(path))
    (line,) = [r.getMessage() for r in caplog.records
               if "the harvest does not hold" in r.getMessage()]
    assert f"{many} decision(s) on {many} row(s)" in line
    assert line.count(f"{DOCUMENT}/") == serialize.NAMED
    assert line.endswith(" and 3 more")


def _record(**more):
    base = {"kind": gold.VERDICT, "document": "d", "parameter": "p",
            "field": "year", "by": "Anna", "at": AT, "note": None}
    base.update(more)
    return base


def test_decisions_in_names_what_it_found_and_what_it_did_not():
    rows = [inputs.kwp_row(year_state="read"),
            inputs.kwp_row(year_state="read", year=2035)]    # one name
    first, second = gold.identity.tuple_ids("d", rows)
    held = gold.Gold([
        _record(tuple=gold.row_key("d", rows[0])[1], shown=2030,
                verdict=gold.WRONG, row=gold.signature(rows[0]),
                parameter="energy_consumption", note="no"),
        _record(document="e", tuple="0" * 24, field="value", shown=1,
                verdict=gold.CORRECT, parameter="energy_consumption")])
    found, strays = gold.decisions_in(held, {"d": rows})
    assert found == {"d": {first: [{
        "field": "year", "verdict": gold.WRONG, "by": "Anna", "at": AT,
        "note": "no"}]}}
    assert strays == {("e", "0" * 24, "energy_consumption"): 1}
    # the second row is another row of the same name: not the one decided
    assert second.endswith(".2") and second not in found["d"]


def test_read_decisions_returns_what_it_counts_and_applies_nothing_to_a_stray(
        tmp_path, caplog):
    rows = _harvested(tmp_path)
    path = gold.path_beside(tmp_path / "harvest")
    gold.decide(path, DOCUMENT, rows[0], "value", gold.WRONG, at=AT)
    gold.decide(path, DOCUMENT, rows[0], "year", gold.CORRECT, at=AT)
    gold.decide(path, DOCUMENT, dict(rows[1], quote="gone"), "value",
                gold.WRONG, at=AT)
    harvest = {DOCUMENT: rows}
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        decided = serialize.read_decisions(gold.Gold.load(path), harvest,
                                           source="the file")
    assert serialize.count_decisions(decided) == 2
    assert list(decided) == [DOCUMENT]
    ((first, found),) = decided[DOCUMENT].items()
    assert first == gold.identity.tuple_ids(DOCUMENT, rows)[0]
    assert sorted(entry["field"] for entry in found) == ["value", "year"]
    assert ("2 decision(s) on 1 row(s) of 1 document(s) read from the file"
            in caplog.text)
    assert ("1 decision(s) on 1 row(s) are about rows the harvest does not "
            "hold" in caplog.text)
    # the same harvest with nobody having decided: nothing to count
    assert serialize.read_decisions(gold.Gold([]), harvest) == {}
    assert serialize.count_decisions({}) == 0


def test_decisions_in_holds_nothing_for_a_harvest_nobody_decided():
    rows = [inputs.kwp_row(year_state="read")]
    assert gold.decisions_in(gold.Gold([]), {"d": rows}) == ({}, {})


# --------------------------------------------- where the decisions are looked up

def test_the_rows_a_serializer_is_handed_carry_no_decision(tmp_path):
    from profiles.kwp import kg
    held = _decided(tmp_path, (0, "year", gold.WRONG, None, None))
    seen = {}
    write = kg.make_serializer(inputs.kwp_database(tmp_path))

    def spy(name, handed):
        seen[name] = json.loads(json.dumps(handed))
        return write(name, handed)

    spy.claims = write.claims
    serialize.run(tmp_path / "harvest", tmp_path / "graph.ttl", spy, None,
                  gold=held)
    on_disk = [json.loads(line) for line in (
        tmp_path / "harvest" / f"{DOCUMENT}.jsonl").read_text(
            encoding="utf-8").splitlines()]
    assert seen[DOCUMENT] == on_disk
    assert serialize.collect(tmp_path / "harvest")[DOCUMENT] == on_disk
    # the comparison can fail: a row that carried its decision differs
    marked = [dict(on_disk[0], decisions=["wrong"])] + on_disk[1:]
    assert marked != on_disk


def test_the_decisions_file_is_found_where_evaluate_finds_it(tmp_path):
    harvest = tmp_path / "corpus" / "harvest"
    assert gold.path_beside(harvest) \
        == (tmp_path / "corpus").resolve() / "gold.jsonl"
    assert gold.path_beside(harvest) != harvest / "gold.jsonl"


def _command(tmp_path, *more):
    """The exit code of `--serialize` over the harvest in *tmp_path*, and the
    provenance graph it wrote."""
    from docpipe.extraction import runner
    ttl = tmp_path / "graph.ttl"
    code = runner.main([str(inputs.kwp_database(tmp_path)), "no.index",
                        str(tmp_path / "harvest"), "--serialize", str(ttl),
                        "--profile", "kwp", *more])
    path = provenance.path_for(ttl)
    found = rdflib.Graph().parse(path, format="turtle") if path.is_file() \
        else None
    return code, found


def test_the_command_records_the_decisions_found_beside_the_harvest(tmp_path):
    held = _decided(tmp_path, (0, "value", gold.WRONG, "Anna", "no"))
    assert held.verdicts
    code, found = _command(tmp_path)
    assert code == 0
    (decision,) = _decisions(found)
    assert str(found.value(decision, CREATOR)) == "Anna"


def test_the_command_has_no_decisions_file_of_its_own_to_name(tmp_path):
    """The file is the one beside the harvest. A file elsewhere is not read,
    and the command does not take a flag for one."""
    mine = tmp_path / "elsewhere" / "mine.jsonl"
    rows = _harvested(tmp_path)
    gold.decide(mine, DOCUMENT, rows[0], "value", gold.WRONG, at=AT)
    assert not gold.path_beside(tmp_path / "harvest").exists()
    code, found = _command(tmp_path)
    assert code == 0 and _decisions(found) == []
    from docpipe.extraction import runner
    with pytest.raises(SystemExit):
        runner.main(["a.db", "no.index", str(tmp_path / "harvest"),
                     "--serialize", str(tmp_path / "again.ttl"),
                     "--profile", "kwp", "--gold", str(mine)])


def test_the_command_goes_on_without_a_decisions_file_or_a_provenance_file(
        tmp_path, caplog):
    none = _dir(tmp_path, "none")
    _harvest(none, DOCUMENT, _kwp_rows())
    code, found = _command(none)                        # no file at all
    assert code == 0 and _decisions(found) == []
    off = _dir(tmp_path, "off")
    assert _decided(off, (0, "value", gold.WRONG, None, None)).verdicts
    with caplog.at_level(logging.WARNING, logger="docpipe.extraction"):
        code, found = _command(off, "--no-provenance")
    assert code == 0 and found is None
    assert "1 decision(s) read and recorded nowhere" in caplog.text


def test_the_runner_reads_the_decisions_file_and_never_stops_on_it(
        tmp_path, caplog):
    from docpipe.extraction import runner
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.runner"):
        held, path = runner._decisions_file(harvest)
    assert held is None and path == tmp_path.resolve() / "gold.jsonl"
    assert "is not a file: no decision is recorded" in caplog.text
    caplog.clear()
    # a file that does not read: said, with the cause, and the run goes on
    (tmp_path / "gold.jsonl").write_text("{not json\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="docpipe.extraction.runner"):
        held, _path = runner._decisions_file(harvest)
    assert held is None
    assert "does not read, so no decision is recorded" in caplog.text
    assert "gold.jsonl:1: not JSON" in caplog.text
    # and one that does
    (tmp_path / "gold.jsonl").write_text("", encoding="utf-8")
    held, _path = runner._decisions_file(harvest)
    assert isinstance(held, gold.Gold)


def test_a_decisions_file_the_system_will_not_open_stops_no_run(
        tmp_path, caplog, monkeypatch):
    from docpipe.extraction import runner
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    (tmp_path / "gold.jsonl").write_text("", encoding="utf-8")

    def refuse(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(gold.Gold, "load", classmethod(
        lambda cls, path: refuse(path)))
    with caplog.at_level(logging.WARNING, logger="docpipe.extraction.runner"):
        held, _path = runner._decisions_file(harvest)
    assert held is None
    assert "does not read, so no decision is recorded" in caplog.text
    assert "Permission denied" in caplog.text


def test_the_review_page_looks_for_the_decisions_where_the_core_says(
        tmp_path, monkeypatch):
    """One rule for the file beside a harvest: config asks `path_beside`
    (a stand-in that answers differently shows it is the one asked), and
    a path named in the environment wins over it."""
    import importlib
    from docpipe.app import config
    harvest = tmp_path / "corpus" / "harvest"
    monkeypatch.setenv("INFERENCE_HARVEST_DIR", str(harvest))
    monkeypatch.delenv("INFERENCE_GOLD_PATH", raising=False)
    try:
        importlib.reload(config)
        assert config.GOLD_PATH == gold.path_beside(harvest)
        monkeypatch.setattr(gold, "path_beside", lambda _dir: tmp_path / "x")
        monkeypatch.setattr(config, "path_beside", gold.path_beside)
        importlib.reload(config)
        assert config.GOLD_PATH == tmp_path / "x"
        monkeypatch.setenv("INFERENCE_GOLD_PATH", str(tmp_path / "mine"))
        importlib.reload(config)
        assert config.GOLD_PATH == tmp_path / "mine"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# ------------------------------------------------- the core graph writer

def _core(tmp_path, held):
    """(graph text, provenance graph, the writer, the harvest's rows) of the
    core writer over the rows of its own tests, with the decisions *held*."""
    from docpipe.extraction import graph
    from tests.test_graph_writer import ROWS, spec
    folder = _harvest(tmp_path, "iea", ROWS)
    out = tmp_path / "graph.ttl"
    write = graph.make_serializer(spec())
    writer = provenance.Writer(write.base, write.provenance)
    serialize.run(folder, out, write, writer, gold=held)
    return (out.read_text(encoding="utf-8"),
            rdflib.Graph().parse(provenance.path_for(out), format="turtle"),
            writer, serialize.collect(folder)["iea"])


def _core_decide(tmp_path, *entries):
    from tests.test_graph_writer import ROWS
    rows = serialize.collect(_harvest(tmp_path, "iea", ROWS))["iea"]
    path = gold.path_beside(tmp_path / "harvest")
    for index, field, verdict in entries:
        gold.decide(path, "iea", rows[index], field, verdict, by="Anna",
                    at=AT)
    return gold.Gold.load(path)


def _term(writer, name):
    return rdflib.URIRef(writer.term(name).strip("<>"))


def test_the_core_writer_keeps_a_decision_beside_its_value_too(tmp_path):
    held = _core_decide(tmp_path, (1, "value", gold.WRONG))
    text, found, writer, rows = _core(_dir(tmp_path, "with"), held)
    without, plain, _writer, _rows = _core(_dir(tmp_path, "without"), None)
    (decision,) = list(found.subjects(RDF_TYPE, _term(writer, "Decision")))
    # it points at the statement of the pages row and at no other
    (target,) = list(found.objects(decision, _term(writer, "about")))
    assert str(target).endswith("/" + gold.identity.tuple_ids("iea", rows)[1])
    assert str(found.value(decision, CREATOR)) == "Anna"
    assert str(found.value(decision, RDF_VALUE)) == gold.WRONG
    # a wrong verdict leaves the value in the graph, which is the same graph
    assert text == without and "224" in text
    assert not list(plain.subjects(RDF_TYPE, _term(writer, "Decision")))


# -------------------------------------------------- the vocabulary and writer

def test_the_decision_is_a_term_the_header_defines(tmp_path):
    held = _decided(tmp_path, (0, "value", gold.CORRECT, "Anna", "n"))
    _text, found, _graph = _kwp(tmp_path, held)
    used = {str(term) for triple in found for term in triple
            if isinstance(term, rdflib.URIRef)
            and str(term).startswith(MHPX)}
    defined = {str(s) for s, _p, _o in found.triples((None, RDF_TYPE, None))
               if str(s).startswith(MHPX)}
    assert str(DECISION) in used and used <= defined


def test_a_decision_the_writer_was_given_no_value_for_is_recorded_nowhere():
    def one(field):
        return {"field": field, "verdict": "wrong", "by": None, "at": None,
                "note": None}

    writer = provenance.Writer("https://graph.test/id/")
    writer.add("a", {"document": "https://graph.test/id/plan/a", "values": [
        {"about": "https://graph.test/id/value/0", "row": inputs.kwp_row(),
         "id": "one"}]},
        decisions={"one": [one("value")], "two": [one("value"), one("year")]})
    assert writer.decisions == 1
    assert "".join(writer.parts).count(f"a {writer.term('Decision')}") == 1


def _accounts(caplog):
    return [r.getMessage() for r in caplog.records
            if "recorded beside their value" in r.getMessage()]


def test_every_decision_read_is_recorded_or_counted_as_left_out(tmp_path,
                                                                caplog):
    """The second document is none the writer has a plan for, so nothing of
    it reaches the graph: its decisions are among those left out."""
    rows = _harvested(tmp_path)
    _harvest(tmp_path, "plan_unwritten", _kwp_rows())
    elsewhere = serialize.collect(tmp_path / "harvest")["plan_unwritten"]
    path = gold.path_beside(tmp_path / "harvest")
    gold.decide(path, DOCUMENT, rows[0], "value", gold.CORRECT, at=AT)
    gold.decide(path, "plan_unwritten", elsewhere[0], "value", gold.WRONG,
                at=AT)
    gold.decide(path, "plan_unwritten", elsewhere[0], "year", gold.WRONG,
                at=AT)
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        _text, found, _graph = _kwp(tmp_path, gold.Gold.load(path))
    (line,) = _accounts(caplog)
    assert line.startswith("serialize: 1 of 3 decision(s) recorded")
    # two decisions on ONE row: the unit of the number is the decision
    assert "2 decision(s) are about rows the writer left out of the graph"         in line
    assert "2 rows" not in line
    assert len(_decisions(found)) == 1


def test_a_run_that_recorded_every_decision_says_none_were_left_out(
        tmp_path, caplog):
    held = _decided(tmp_path, (0, "value", gold.CORRECT, None, None))
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        _kwp(tmp_path, held)
    (line,) = _accounts(caplog)
    assert line.startswith("serialize: 1 of 1 decision(s) recorded")
    assert "0 decision(s) are about rows the writer left out" in line


def test_nobody_decided_nothing_is_said_about_decisions(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        _kwp(_dir(tmp_path, "empty"), gold.Gold([]))
        _kwp(_dir(tmp_path, "none"), None)
    assert not _accounts(caplog)
    assert "recorded nowhere" not in caplog.text


def _plain_serializer(name, rows):
    return f"# {name}\n"


def test_decisions_a_run_has_nowhere_to_record_are_said_so(tmp_path, caplog):
    """No provenance file and a serializer that takes none: read, and kept
    by nobody. The log says so, with the count."""
    held = _decided(tmp_path, (0, "year", gold.WRONG, None, None),
                    (0, "value", gold.WRONG, None, None))
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        serialize.run(tmp_path / "harvest", tmp_path / "graph.ttl",
                      _plain_serializer, None, gold=held)
    (line,) = [r.getMessage() for r in caplog.records
               if "recorded nowhere" in r.getMessage()]
    assert line.startswith("serialize: 2 decision(s) read and recorded "
                           "nowhere")


def test_a_run_with_a_place_for_decisions_does_not_say_it_has_none(
        tmp_path, caplog):
    """The provenance writer of kwp, and the comment lines of scenarios."""
    held = _decided(tmp_path, (0, "value", gold.WRONG, None, None))
    other = _dir(tmp_path, "scenarios")
    held_scenarios = _decided_scenarios(other, (0, "value", gold.WRONG, None,
                                                None))
    with caplog.at_level(logging.INFO, logger="docpipe.extraction.serialize"):
        _kwp(tmp_path, held)
        _scenarios(other, held_scenarios)
    assert "recorded nowhere" not in caplog.text


# ------------------------------------------------------- scenarios: a comment

def _scenario_rows():
    """As a harvest file holds them: every accepted row says it is one."""
    return [dict(row, kind="tuple") for row in inputs.scenarios_rows()]


def _scenarios(tmp_path, held, serializer=None):
    from profiles.scenarios import kg
    folder = _harvest(tmp_path, "outlook_2050", _scenario_rows())
    write = serializer or kg.make_serializer(
        inputs.scenarios_database(tmp_path))
    out = tmp_path / "graph.ttl"
    serialize.run(folder, out, write, None, gold=held)
    return out.read_text(encoding="utf-8")


def _triples(text):
    return [line for line in text.splitlines()
            if not line.lstrip().startswith("#")]


def _decided_scenarios(tmp_path, *entries):
    rows = serialize.collect(_harvest(
        tmp_path, "outlook_2050", _scenario_rows()))["outlook_2050"]
    path = gold.path_beside(tmp_path / "harvest")
    for index, field, verdict, by, note in entries:
        gold.decide(path, "outlook_2050", rows[index], field, verdict,
                    by=by, note=note, at=AT)
    return gold.Gold.load(path)


def test_a_decided_scenario_value_has_a_comment_line_above_it(tmp_path):
    held = _decided_scenarios(tmp_path, (0, "value", gold.WRONG, "Ben",
                                         "the title has a subtitle"))
    lines = _scenarios(tmp_path, held).splitlines()
    (at,) = [i for i, line in enumerate(lines)
             if line.lstrip().startswith("# decision:")]
    assert lines[at] == (
        "    # decision: value wrong, by Ben, 2026-10-05T10:00:00+00:00, "
        "note: the title has a subtitle")
    assert lines[at - 1] == "    # confidence: A"       # after the trust line
    assert lines[at + 1].lstrip().startswith("rdfs:label")  # above its value


def test_a_decision_reads_as_one_comment_line_with_what_is_known():
    from profiles.scenarios import kg
    said = {"field": "value", "verdict": gold.WRONG, "by": "Ben", "at": AT,
            "note": "a subtitle"}
    assert kg.decision_text(said) == (
        f"decision: value wrong, by Ben, {AT}, note: a subtitle")
    # what nobody gave is not written as a word
    bare = kg.decision_text(dict(said, by=None, at="", note=None))
    assert bare == "decision: value wrong"
    assert "None" not in bare


def test_a_note_cannot_end_the_comment_it_stands_in(tmp_path):
    """A line break and a statement typed into a note stay inside the one
    comment line: no triple is added to the graph."""
    held = _decided_scenarios(
        tmp_path, (0, "value", gold.WRONG, "Ben",
                   "x\n<urn:a> <urn:b> <urn:c> .\r\n# y"))
    text = _scenarios(tmp_path, held)
    (line,) = [line for line in text.splitlines() if "# decision:" in line]
    assert "<urn:a>" in line and line.lstrip().startswith("#")
    assert "<urn:a>" not in "\n".join(_triples(text))
    clean = _scenarios(_dir(tmp_path, "clean"), None)
    assert _triples(text) == _triples(clean)


def test_an_undecided_scenario_value_carries_no_comment(tmp_path):
    held = _decided_scenarios(tmp_path, (0, "value", gold.CORRECT, None,
                                         None))
    text = _scenarios(tmp_path, held)
    assert text.count("# decision:") == 1
    assert "decision: value correct, 2026-10-05T10:00:00+00:00" in text
    assert "by None" not in text and "note:" not in text


def test_a_wrong_verdict_leaves_the_scenario_value_in_the_graph(tmp_path):
    held = _decided_scenarios(tmp_path,
                              (0, "value", gold.WRONG, "Ben", "x"),
                              (2, "value", gold.WRONG, "Ben", "y"))
    with_decisions = _scenarios(_dir(tmp_path, "with"), held)
    without = _scenarios(_dir(tmp_path, "without"), None)
    assert with_decisions.count("# decision:") == 2
    # not one triple more or less: only comment lines are added
    assert _triples(with_decisions) == _triples(without)
    assert with_decisions != without                # the comparison can fail
    assert 'rdfs:label "The \\"Net Zero\\" Pathways \\\\ Outlook 2050"' \
        in with_decisions


def test_a_decision_on_a_row_that_backs_no_value_is_counted(tmp_path, caplog):
    # row 1 is the truncated running header of the title: it never wins
    held = _decided_scenarios(tmp_path, (1, "value", gold.WRONG, "Ben", "x"))
    with caplog.at_level(logging.INFO, logger="profiles.scenarios.kg"):
        text = _scenarios(tmp_path, held)
    assert "# decision:" not in text
    assert "1 decision(s) on 1 row(s) concern no value of the graph" \
        in caplog.text


def test_a_second_run_holds_none_of_the_first_runs_decisions(tmp_path):
    from profiles.scenarios import kg
    write = kg.make_serializer(inputs.scenarios_database(tmp_path))
    held = _decided_scenarios(tmp_path, (0, "value", gold.WRONG, "Ben", "x"))
    assert "# decision:" in _scenarios(tmp_path, held, serializer=write)
    again = _dir(tmp_path, "again")
    folder = _harvest(again, "outlook_2050", _scenario_rows())
    serialize.run(folder, again / "graph.ttl", write, None)
    assert "# decision:" not in (again / "graph.ttl").read_text(
        encoding="utf-8")


def test_the_evidence_nodes_run_records_the_decision_too(tmp_path,
                                                          monkeypatch):
    from profiles.scenarios import kg
    monkeypatch.setattr(kg, "EVIDENCE", True)
    held = _decided_scenarios(tmp_path, (0, "value", gold.WRONG, "Ben", "x"))
    assert "# decision: value wrong" in _scenarios(tmp_path, held)


# ------------------------------------------------------------- what is decided

def _one_row():
    row = {"parameter": "p", "value": 1, "quote": "q", "year": 2030,
           "year_state": "read"}
    return row, gold.row_key("d", row)[1]


def test_the_decision_that_settles_a_field_is_named():
    row, name = _one_row()
    shown = _record(tuple=name, shown=2030, verdict=gold.WRONG,
                    row=gold.signature(row))
    held = gold.Gold([shown])
    assert held.settled("d", row, "year") == (gold.WRONG, shown)
    assert held.verdict("d", row, "year") == gold.WRONG
    # named what is right: another reading of the field is settled by it
    named = _record(tuple=name, shown=2031, verdict=gold.WRONG, expected=2030,
                    row=gold.signature(row), by="Ben")
    verdict, record = gold.Gold([named]).settled("d", row, "year")
    assert (verdict, record["by"]) == (gold.CORRECT, "Ben")
    # other content found correct: this content is not
    other = _record(tuple=name, shown=2031, verdict=gold.CORRECT,
                    row=gold.signature(row), by="Cleo")
    verdict, record = gold.Gold([other]).settled("d", row, "year")
    assert (verdict, record["by"]) == (gold.WRONG, "Cleo")
    assert gold.Gold([other]).verdict("d", row, "year") == gold.WRONG


def test_nothing_is_settled_where_nobody_decided_the_field():
    row, name = _one_row()
    held = gold.Gold([_record(tuple=name, shown=2031, verdict=gold.WRONG,
                              row=gold.signature(row))])
    assert held.settled("d", row, "year") is None, "other content, found wrong"
    assert held.settled("d", row, "value") is None, "another field"
    assert gold.Gold([]).settled("d", row, "year") is None
    assert held.verdict("d", row, "year") is None
