"""A second reading of the values nobody can stand behind.

What is held here is mostly what the pass must NOT do. It re-reads one value
over a window narrowed to the two passages that value may legally quote from,
and the temptation in every direction is to let it decide more than it can: to
lift a level because the model agreed with itself, to write the second
reading's number onto the row, to accept a quote from a third passage, or to
drop the resume stamps and throw the whole reviewed harvest away on the next
run.

No model, no GPU, no database: `ask` and `sources_for` are stubs.
"""
import json
from pathlib import Path

import pytest

from docpipe.extraction import fields, review, runner, trust
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec, own_evidence

PROFILES = Path(__file__).resolve().parent.parent / "profiles"
PARAMETER = "energy_consumption"


def _spec(name="kwp"):
    return load_spec(json.loads(
        (PROFILES / name / "extraction_spec.json").read_text(encoding="utf-8")))


SPEC = _spec()
OWN = own_evidence(SPEC)
QUOTE = "| Erdgas | 241 | MWh/a |"
PARENT_TEXT = ("Abschnitt 4: Endenergieverbrauch. Die folgende Tabelle "
               "[p85_tbl0] zeigt den Verbrauch im Jahr 2020.")


def _row(**overrides):
    """One accepted tuple, read off its own table, with one foreign passage.

    The foreign passage is what makes it the lowest level: `carrier` is an
    axis the spec holds to the row's own source, and this one was read in
    table 999.
    """
    row = {
        "kind": "tuple", "parameter": PARAMETER, "value": 241.0,
        "value_target": 241.0, "unit": "MWh/a", "unit_raw": "MWh/a",
        "quote": QUOTE, "tier": "text_located", "flags": [],
        "carrier": "OEO_00000292", "carrier_raw": "Erdgas",
        "carrier_state": fields.READ, "carrier_source": ["table", 999],
        "carrier_quote": QUOTE,
        "year": 2020, "year_state": fields.READ, "year_source": ["table", 1],
        "provenance": {"document_id": 7, "owner_kind": "table",
                       "owner_id": 1, "parent_section": 5, "page": 85},
    }
    row.update(overrides)
    return row


def _sources(image_path=None):
    own = Source("table", 1, QUOTE, {"document_id": 7, "page": 85,
                                     "block_id": "p85_tbl0",
                                     "parent_section": 5},
                 image_path=image_path)
    parent = Source("section", 5, PARENT_TEXT,
                    {"document_id": 7, "page": 85, "via": "parent"})
    return [own, parent]


def _asker(reply, seen=None):
    def ask(row, shown, parameter, slots):
        if seen is not None:
            seen.append({"row": row, "shown": shown, "parameter": parameter,
                         "slots": slots})
        return reply
    return ask


def _agreeing():
    return {"value": 241.0, "unit": "MWh/a", "value_quote": QUOTE,
            "carrier": "Erdgas", "carrier_raw": "Erdgas",
            "carrier_quote": QUOTE}


def _harvest(tmp_path, rows, name="plan"):
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")
    return path


def _summary(**overrides):
    line = {"kind": "summary", "document_id": 7, "tuples": 1, "refusals": 0,
            "levels": {"A": 0, "B": 0, "C": 1}, "reasons": {"nonlocal:carrier": 1},
            "image_origin": 0}
    line.update(overrides)
    return line


# ---------------------------------------------------------------------------
# Which values, and which questions about them
# ---------------------------------------------------------------------------
def test_only_the_values_nobody_can_stand_behind_are_reviewed():
    """One request per value reviewed. A value whose passages are all its own
    and whose coordinates were all read has nothing a narrower window can
    find, so spending a request on it buys nothing."""
    good = _row(carrier_source=["table", 1])
    image = _row(carrier_source=["table", 1], tier="image")
    bad = _row()
    got = review.rows_to_review([good, image, bad], own=OWN)
    assert [trust.trust(r, own=OWN)["level"] for r in (good, image, bad)] == [
        "A", "B", "C"], "the fixture must really carry all three"
    assert got == [bad]


def test_a_row_is_reviewed_once():
    """The second answer to the same question is not a third opinion. Without
    this the pass re-reads its own work on every run and the flags say
    nothing about how many values were actually looked at."""
    done = _row(flags=[trust.REVIEW_UNBACKED])
    assert review.rows_to_review([done], own=OWN) == []
    assert review.rows_to_review([done], own=OWN, force=True) == [done]


def test_the_disputed_coordinate_is_the_one_the_reason_names():
    """Three of the reasons name a coordinate and five do not. Split on ":"
    without the whitelist and `review:disagree` asks for a coordinate called
    "disagree" on every row this pass has already seen."""
    assert review.disputed({"reasons": ["nonlocal:carrier"]}) == ["carrier"]
    assert review.disputed({"reasons": ["exhausted:year"]}) == ["year"]
    assert review.disputed({"reasons": ["unbacked:sector"]}) == ["sector"]
    assert review.disputed({"reasons": [
        "repaired", "computed", "not_located", "conflict",
        "page_transcribed", "review:disagree"]}) == []
    # And the row is then asked for its value and nothing else.
    parameter = SPEC.by_uri[PARAMETER]
    assert [s.name for s in review.review_fields(parameter, [])] == ["value"]
    assert [s.name for s in review.review_fields(parameter, ["carrier"])] == [
        "value", "carrier"]


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------
def test_the_request_shows_the_rows_own_table_and_its_section_and_nothing_else():
    """Exactly two passages, in that order, and the row says which is which.
    A rule the request does not state is a rule the model cannot follow."""
    parameter = SPEC.by_uri[PARAMETER]
    slots = review.review_fields(parameter, ["carrier"])
    payload = runner._review_payload(_row(), _sources(), parameter, slots)
    assert [s["id"] for s in payload["sources"]] == ["Q1", "Q2"]
    assert payload["sources"][0]["kind"] == "table"
    assert "via" not in payload["sources"][0]
    assert payload["sources"][1]["via"] == "parent"
    assert payload["row"]["source"] == "Q1"
    assert payload["row"]["section"] == "Q2"
    assert payload["row"]["value"] == 241.0
    assert [f["name"] for f in payload["fields"]] == ["value", "carrier"]
    assert payload["fields"][1]["options"], "a closed list is offered"


def test_a_long_section_arrives_cut_around_the_rows_own_placeholder(tmp_path):
    """The section a value stands in can be longer than any window. Cut from
    its first character it holds the title page of the chapter and not the
    sentence that dates the table, which is the whole reason the parent is
    shown at all."""
    import sqlite3
    path = tmp_path / "plans.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
        "CREATE TABLE Sections ("
        " id INTEGER PRIMARY KEY, document INTEGER, section_number INTEGER,"
        " title TEXT, content TEXT, page_number INTEGER);"
        "CREATE TABLE Tables ("
        " id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,"
        " caption TEXT, markdown TEXT, page_number INTEGER, path TEXT);"
        "CREATE TABLE Images ("
        " id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,"
        " caption TEXT, description TEXT, page_number INTEGER, path TEXT);")
    filler = "Fülltext. " * 800
    conn.execute("INSERT INTO Documents (id, filename) VALUES (7, 'plan.pdf')")
    conn.execute("INSERT INTO Sections (id, document, section_number, title, "
                 "content, page_number) VALUES (5, 7, 4, 'Verbrauch', ?, 85)",
                 (filler + "Tabelle 17: Verbrauch 2020 [p85_tbl0]" + filler,))
    conn.execute("INSERT INTO Tables (id, section, block_id, caption, "
                 "markdown, page_number, path) "
                 "VALUES (1, 5, 'p85_tbl0', 'Tabelle 17', ?, 85, NULL)",
                 (QUOTE,))
    conn.commit()
    conn.close()

    shown = runner.make_review_sources(path)(_row())
    assert [s.owner_kind for s in shown] == ["table", "section"]
    assert len(shown[1].text) <= runner.PARENT_CHARS + 200
    assert "[p85_tbl0" in shown[1].text
    assert shown[1].provenance.get("via") == "parent"


def test_a_value_whose_own_source_is_a_section_has_one_passage(tmp_path):
    """There is no second passage to show, and showing the section twice is
    the same passage paying twice."""
    import sqlite3
    path = tmp_path / "plans.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
        "CREATE TABLE Sections ("
        " id INTEGER PRIMARY KEY, document INTEGER, section_number INTEGER,"
        " title TEXT, content TEXT, page_number INTEGER);"
        "CREATE TABLE Tables ("
        " id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,"
        " caption TEXT, markdown TEXT, page_number INTEGER, path TEXT);"
        "CREATE TABLE Images ("
        " id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,"
        " caption TEXT, description TEXT, page_number INTEGER, path TEXT);")
    conn.execute("INSERT INTO Documents (id, filename) VALUES (7, 'plan.pdf')")
    conn.execute("INSERT INTO Sections (id, document, section_number, title, "
                 "content, page_number) VALUES (5, 7, 4, 'Verbrauch', ?, 85)",
                 (PARENT_TEXT,))
    conn.commit()
    conn.close()

    row = _row(provenance={"document_id": 7, "owner_kind": "section",
                           "owner_id": 5, "parent_section": 5, "page": 85})
    shown = runner.make_review_sources(path)(row)
    assert [(s.owner_kind, s.owner_id) for s in shown] == [("section", 5)]


def test_the_crop_rides_along_with_its_own_label(monkeypatch):
    """A table transcription is a model's reading of a picture. Reviewing the
    transcription alone reviews that first reading and nothing else."""
    parameter = SPEC.by_uri[PARAMETER]
    sent = {}

    class Client:
        def __init__(self, **kw):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            sent.update(kw)
            class Reply:
                finish_reason = "stop"
                message = type("M", (), {"content": "{}"})()
            return type("R", (), {"choices": [Reply()], "usage": None})()

    monkeypatch.setattr(runner, "_client", lambda: Client())
    monkeypatch.setattr(runner, "ATTACH_IMAGES", True)
    monkeypatch.setattr(runner, "_image_part",
                        lambda path: {"type": "image_url",
                                      "image_url": {"url": f"data:{path}"}})
    ask = runner.make_review_asker(Path("/bilder"))
    ask(_row(), _sources(image_path="p85_tbl0.png"), parameter,
        review.review_fields(parameter, []))

    content = sent["messages"][-1]["content"]
    assert isinstance(content, list)
    assert [part["type"] for part in content] == ["text", "text", "image_url"]
    assert "Q1" in content[1]["text"]


def test_the_review_names_no_coordinate_of_any_corpus():
    """One profile serves German heat plans, the other English scenario
    studies, and the core cannot know which. A pass that hard-codes a
    coordinate name works on one corpus and silently reviews nothing on the
    other."""
    import inspect
    for source in (inspect.getsource(review),
                   inspect.getsource(runner.make_review_asker),
                   inspect.getsource(runner._review_payload)):
        for word in ("carrier", "sector", "scenario", "Wärme", "heat"):
            assert word not in source, word


# ---------------------------------------------------------------------------
# What the answer decides
# ---------------------------------------------------------------------------
def test_agreement_writes_the_flag_and_moves_nothing_else():
    """The harvest row is what one run read. A pass that writes the second
    reading onto it destroys the thing a disagreement is a disagreement
    with."""
    parameter = SPEC.by_uri[PARAMETER]
    row = _row()
    before = json.dumps({k: v for k, v in row.items() if k != "flags"},
                        sort_keys=True)
    slots = review.review_fields(parameter, ["carrier"])
    # A second reading that DIFFERS and is backed: the case where writing it
    # onto the row would actually change something.
    other = "| Erdgas | 242 | MWh/a |"
    shown = [Source("table", 1, QUOTE + " " + other,
                    {"document_id": 7, "page": 85})]
    flag = review.review_row(row, parameter, slots, shown,
                             _asker({**_agreeing(), "value": 242.0,
                                     "value_quote": other,
                                     "carrier_quote": other}))
    assert flag == trust.REVIEW_DISAGREE
    assert row["flags"] == [trust.REVIEW_DISAGREE]
    assert json.dumps({k: v for k, v in row.items() if k != "flags"},
                      sort_keys=True) == before


def test_a_corroborated_row_is_still_a_c():
    """The same model over a narrower window agreeing with itself does not
    make the passage it cites belong to the row. A level lifted here would be
    a signal that fires on the corpus and separates nothing."""
    parameter = SPEC.by_uri[PARAMETER]
    row = _row()
    plain = trust.trust(row, own=OWN)
    review.review_row(row, parameter,
                      review.review_fields(parameter, ["carrier"]),
                      _sources(), _asker(_agreeing()))
    assert row["flags"] == [trust.REVIEW_AGREE]
    verdict = trust.trust(row, own=OWN)
    assert verdict["corroborated"] is True
    assert verdict["level"] == trust.LEVEL_C
    assert verdict["reasons"] == plain["reasons"]


def test_a_disagreement_is_a_reason_a_curator_can_count():
    """A flag written and never read is the failure this module is about. It
    has to reach the reasons and the summary, or a disagreement is invisible
    to everyone who does not grep the raw file."""
    parameter = SPEC.by_uri[PARAMETER]
    row = _row()
    reply = {**_agreeing(), "carrier": "Fernwärme", "carrier_raw": "Fernwärme",
             "carrier_quote": "| Fernwärme | 241 | MWh/a |"}
    shown = [Source("table", 1, QUOTE + " | Fernwärme | 241 | MWh/a |",
                    {"document_id": 7, "page": 85})]
    flag = review.review_row(row, parameter,
                             review.review_fields(parameter, ["carrier"]),
                             shown, _asker(reply))
    assert flag == trust.REVIEW_DISAGREE
    verdict = trust.trust(row, own=OWN)
    assert "review:disagree" in verdict["reasons"]
    summary = trust.document_summary(7, [row], [], own=OWN)
    assert summary["reasons"]["review:disagree"] == 1


def test_a_review_answer_whose_quote_is_in_neither_passage_decides_nothing():
    """The quote is the only thing that separates a reading from an opinion,
    and there are exactly two passages it may come from."""
    parameter = SPEC.by_uri[PARAMETER]
    row = _row()
    reply = {**_agreeing(),
             "value_quote": "Aus einem ganz anderen Abschnitt: 241 MWh/a"}
    flag = review.review_row(row, parameter,
                             review.review_fields(parameter, []),
                             _sources(), _asker(reply))
    assert flag == trust.REVIEW_UNBACKED
    assert row["flags"] == [trust.REVIEW_UNBACKED]
    assert trust.trust(row, own=OWN)["corroborated"] is False


def test_a_review_answer_whose_quote_does_not_carry_it_decides_nothing():
    """The second clause, held on its own: a passage that sits in the source
    proves the model read something, only one that contains the answer proves
    it read this."""
    parameter = SPEC.by_uri[PARAMETER]
    row = _row()
    reply = {**_agreeing(), "value_quote": PARENT_TEXT[:60]}
    flag = review.review_row(row, parameter,
                             review.review_fields(parameter, []),
                             _sources(), _asker(reply))
    assert flag == trust.REVIEW_UNBACKED


def test_the_value_is_compared_by_the_number_the_graph_carries():
    """The harvest converts onto the spec's own unit. Compared against the
    printed number instead, every value the document states in kWh comes back
    as a disagreement with itself."""
    parameter = SPEC.by_uri[PARAMETER]
    text = "Der Verbrauch betrug 241000 kWh/a im Jahr 2020."
    shown = [Source("table", 1, text, {"document_id": 7, "page": 85})]
    same = _row()
    assert review.review_row(
        same, parameter, review.review_fields(parameter, []), shown,
        _asker({"value": 241000, "unit": "kWh/a", "value_quote": text})
    ) == trust.REVIEW_AGREE

    other = "Der Verbrauch betrug 242 MWh/a im Jahr 2020."
    shown = [Source("table", 1, other, {"document_id": 7, "page": 85})]
    row = _row()
    assert review.review_row(
        row, parameter, review.review_fields(parameter, []), shown,
        _asker({"value": 242, "unit": "MWh/a", "value_quote": other})
    ) == trust.REVIEW_DISAGREE


def test_a_unit_the_spec_does_not_accept_decides_nothing():
    """Not a disagreement about the number: an answer nothing can be compared
    with. Converted unguarded it is a crash in the middle of a corpus pass."""
    parameter = SPEC.by_uri[PARAMETER]
    row = _row()
    flag = review.review_row(
        row, parameter, review.review_fields(parameter, []), _sources(),
        _asker({"value": 241.0, "unit": "Gigawattstunden",
                "value_quote": QUOTE}))
    assert flag == trust.REVIEW_UNBACKED


def test_a_reply_that_never_arrives_leaves_no_trace():
    """Nothing happened, so nothing is recorded and the row is asked again
    next time. A flag here would retire a value nobody has read twice."""
    parameter = SPEC.by_uri[PARAMETER]
    row = _row()
    assert review.review_row(row, parameter,
                             review.review_fields(parameter, []),
                             _sources(), _asker(None)) == ""
    assert row["flags"] == []


@pytest.mark.parametrize("profile", ["kwp", "scenarios"])
def test_a_reviewed_row_still_validates_against_the_checked_in_schema(profile):
    """The flags are published or they are not readable. An alternative
    missing from the pattern makes every reviewed row invalid against the
    schema everyone downstream reads instead of the file."""
    import jsonschema
    schema = json.loads((PROFILES / profile / "extraction_schema.json")
                        .read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        {"$schema": schema["harvest"]["$schema"],
         "$defs": schema["harvest"]["$defs"],
         **schema["harvest"]["$defs"][f"tuple_{_spec(profile).parameters[0].uri}"]})
    row = _row(parameter=_spec(profile).parameters[0].uri)
    row = {k: v for k, v in row.items()
           if k in schema["harvest"]["$defs"][
               f"tuple_{row['parameter']}"]["properties"]}
    for flag in (trust.REVIEW_AGREE, trust.REVIEW_DISAGREE,
                 trust.REVIEW_UNBACKED):
        errors = list(validator.iter_errors({**row, "flags": [flag]}))
        assert not [e for e in errors if "flags" in list(e.absolute_path)], (
            flag, [e.message for e in errors])


# ---------------------------------------------------------------------------
# The file, and the stamp
# ---------------------------------------------------------------------------
def test_the_review_rewrites_the_summary_it_invalidated(tmp_path):
    """A disagreement is a reason, and the summary counts reasons. Carried
    forward it reports the run before the review."""
    path = _harvest(tmp_path, [_row(), _summary()])
    other = "| Fernwärme | 241 | MWh/a |"
    shown = [Source("table", 1, QUOTE + " " + other,
                    {"document_id": 7, "page": 85})]
    review.run(tmp_path, SPEC,
               ask=_asker({**_agreeing(), "carrier": "Fernwärme",
                           "carrier_raw": "Fernwärme",
                           "carrier_quote": other}),
               sources_for=lambda row: shown)
    rows = [json.loads(line) for line
            in path.read_text(encoding="utf-8").strip().splitlines()]
    assert rows[-1]["kind"] == "summary"
    assert rows[-1]["reasons"]["review:disagree"] == 1
    assert sum(rows[-1]["levels"].values()) == 1


def test_a_reviewed_document_is_still_current(tmp_path, monkeypatch):
    """The review changes nothing a resume decides on. Reported stale, the
    next harvest reads the corpus again and throws the review away -- the 93
    GPU hours the per-parameter stamp keys exist to avoid."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    path = _harvest(tmp_path, [_row(), _summary()])
    stamp = tmp_path / "plan.stamp.json"
    # A stamp as the 1.082 stored ones are: written before this prompt
    # existed, so it names no review prompt at all. That is the case that
    # decides it -- a key absent from a stored stamp counts as changed.
    current = {k: v for k, v in
               runner._stamp_current("sha", "anchors", SPEC).items()
               if k != runner.REVIEW_PROMPT_ID}
    stamp.write_text(json.dumps(current), encoding="utf-8")

    review.run(tmp_path, SPEC, ask=_asker(_agreeing()),
               sources_for=lambda row: _sources(),
               prompt_sha="abc123", model="ein-modell")

    stored = json.loads(stamp.read_text(encoding="utf-8"))
    assert stored["review/prompt"] == "abc123"
    assert stored["review/model"] == "ein-modell"
    assert runner.stale(stamp, runner._stamp_current("sha", "anchors",
                                                     SPEC)) == []


def test_a_document_with_no_stamp_keeps_having_none(tmp_path, monkeypatch):
    """A stamp created here says a document was harvested that never was, and
    every later run skips it."""
    monkeypatch.setattr(runner.prompts, "versions",
                        lambda ids: {i: "v1" for i in ids})
    _harvest(tmp_path, [_row(), _summary()])
    review.run(tmp_path, SPEC, ask=_asker(_agreeing()),
               sources_for=lambda row: _sources(),
               prompt_sha="abc123", model="ein-modell")
    assert list(tmp_path.glob("*.stamp.json")) == []
    assert runner.already_done("plan", tmp_path, "sha", spec=SPEC) is False


def test_the_review_leaves_the_trace_files_alone(tmp_path):
    """A trace is not a harvest, and reading one as a harvest rewrites it into
    a file with a summary line and no events."""
    _harvest(tmp_path, [_row(), _summary()])
    trace_path = tmp_path / "plan.trace.jsonl"
    # No trailing newline, so a rewrite is one byte away from identical.
    trace_path.write_text('{"t": "rows", "ms": 10}', encoding="utf-8")
    before = trace_path.read_bytes()
    review.run(tmp_path, SPEC, ask=_asker(_agreeing()),
               sources_for=lambda row: _sources())
    assert trace_path.read_bytes() == before


def test_the_working_list_carries_the_second_reading_and_the_harvest_does_not(
        tmp_path):
    """What the second reading said is worth having and is not evidence: the
    harvest holds what one run read, and the disagreement is only readable if
    the other reading is written down somewhere."""
    path = _harvest(tmp_path, [_row(), _summary()])
    other = "| Fernwärme | 241 | MWh/a |"
    shown = [Source("table", 1, QUOTE + " " + other,
                    {"document_id": 7, "page": 85})]
    review.run(tmp_path, SPEC,
               ask=_asker({**_agreeing(), "carrier": "Fernwärme",
                           "carrier_raw": "Fernwärme",
                           "carrier_quote": other}),
               sources_for=lambda row: shown)
    import csv
    with (tmp_path / "review.csv").open(encoding="utf-8") as handle:
        lines = list(csv.DictReader(handle))
    assert [line["field"] for line in lines] == ["value", "carrier"]
    assert lines[1]["second"] == "Fernwärme"
    assert lines[1]["verdict"] == "review:disagree"
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["carrier_raw"] == "Erdgas", "the harvest is untouched"


def test_the_limit_bounds_the_whole_run_and_not_each_document(tmp_path):
    """A budget per document is no budget: 1.082 documents times one is 1.082
    requests, which is the run the flag exists to bound."""
    _harvest(tmp_path, [_row(), _summary()], name="plan_a")
    _harvest(tmp_path, [_row(), _summary()], name="plan_b")
    seen = []
    review.run(tmp_path, SPEC, ask=_asker(_agreeing(), seen),
               sources_for=lambda row: _sources(), limit=1)
    assert len(seen) == 1

def test_the_value_is_held_to_the_same_containment_rule_as_the_harvest():
    """`verify.value_in_quote` is the harvest's own answer to "is the value in
    the passage it cites", and the review asks the identical question one pass
    later. Two copies of that rule drift apart the first time either is
    fixed, so there is one, and it is public because a second caller now
    needs it."""
    from docpipe.extraction.verify import value_in_quote
    parameter = SPEC.by_uri[PARAMETER]
    assert value_in_quote({"value": 241}, parameter, QUOTE)
    assert not value_in_quote({"value": 242}, parameter, QUOTE)
    # The same rule the review reaches it through.
    assert review.backed(parameter, 241, None, QUOTE, _sources())
    assert not review.backed(parameter, 242, None, QUOTE, _sources())


def test_a_document_with_nothing_to_review_is_rewritten_unchanged(tmp_path):
    """`review_file` reads and rewrites the file whether or not it spends a
    request, so a document whose values are all above the lowest level must
    come back saying exactly what it said."""
    good = _row(carrier_source=["table", 1])
    path = _harvest(tmp_path, [good, _summary(levels={"A": 1, "B": 0, "C": 0},
                                              reasons={})])
    before = path.read_text(encoding="utf-8")
    seen = []
    stats = review.review_file(path, SPEC, ask=_asker(_agreeing(), seen),
                               sources_for=lambda row: _sources(), own=OWN)
    assert seen == [], "no request was worth spending"
    assert stats["reviewed"] == 0
    assert path.read_text(encoding="utf-8") == before
