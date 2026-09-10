"""The frame: which scenarios and which years, found once, before any value.

Measured on the M3 acceptance run, this is what it replaces. The year axis
produced 1,849 refusals against 0 readings, because every window after the
first excluded the row's own source and only that one could carry the year.
Asking per row for a coordinate that belongs to the document is the shape of
that failure, not an accident of the budget.

What the frame buys is paid for twice over, and both prices are pinned here:
the same table is read once per pair, and a pair the search misses loses every
value of that pair at once. The second is why the deterministic cross-check
exists, and why it reports and never decides.
"""
import json
from pathlib import Path

import pytest

from docpipe.extraction import fields, runner
from docpipe.extraction.pipeline import Batch, Source, WorkItem, apply_frame
from docpipe.extraction.spec import load as load_spec

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _spec():
    return load_spec(json.loads(
        (PROFILES / "kwp" / "extraction_spec.json").read_text(encoding="utf-8")))


def _slots(spec=None):
    return fields.frame_slots(spec or _spec(), ("scenario", "year"))


def _source(owner_id, text, title=None, kind="table"):
    return Source(kind, owner_id, text,
                  {"document_id": 7, "page": owner_id, "title": title})


class _Row:
    def __init__(self, label="R1", claim=None):
        self.label = label
        self.claim = dict(claim or {})
        self.item_index = 0


# ---------------------------------------------------------------------------
# Which coordinates span the frame is the profile's, never the core's
# ---------------------------------------------------------------------------

def test_the_profile_names_the_frame_and_the_core_resolves_it():
    """The core never names a coordinate. `FRAME` is the profile's, exactly
    like `SLICE`, and what comes back are the spec's own slots in the
    profile's order."""
    from profiles.kwp import extraction as profile
    assert profile.FRAME == ("scenario", "year")
    slots = _slots()
    assert [slot.name for slot in slots] == ["scenario", "year"]
    assert slots[0].kind == fields.CHOICE and slots[1].kind == fields.NUMBER


def test_a_frame_coordinate_no_parameter_has_yields_no_frame_at_all():
    """Half a frame is worse than none: a pair set silently missing a
    coordinate would put every value under a coordinate nobody chose."""
    assert fields.frame_slots(_spec(), ("scenario", "not_an_axis")) == []
    assert fields.frame_slots(_spec(), ()) == []


def test_the_frame_is_read_off_one_parameter_and_not_stitched_together():
    """A spec whose parameters disagreed about the frame would have two frames
    and no way to say which one a value hangs in, so it is read off the first
    parameter that has all of them rather than collected across them."""
    spec = _spec()
    numeric = [p for p in spec.parameters if p.axes]
    assert len(numeric) >= 2, "the point needs two parameters that have axes"
    slots = _slots(spec)
    owner = {s.name: s for s in fields.axis_slots(numeric[0])}
    assert [slots[0], slots[1]] == [owner["scenario"], owner["year"]]


# ---------------------------------------------------------------------------
# The deterministic cross-check
# ---------------------------------------------------------------------------

def test_the_cross_check_counts_year_shaped_numbers_and_reads_nothing():
    """A pair the frame does not have loses every value of that pair, and
    loses it silently -- which is the one failure this design has that the old
    one did not. So the same passages are scanned without a model."""
    sources = [_source(1, "Bilanzjahr 2022, Zieljahr 2045."),
               _source(2, "Nichts.", title="Tabelle 17: Bedarf 2030")]
    assert runner.years_in_sources(sources) == {2022, 2045, 2030}


def test_the_cross_check_takes_no_number_that_is_not_year_shaped():
    """Four digits, and inside a calendar range. 512045 is not a year and
    neither is 45."""
    sources = [_source(1, "512045 kWh, 45 Gebaeude, 1789, 3000, 20301.")]
    assert runner.years_in_sources(sources) == set()
    assert runner.years_in_sources([_source(1, "1990 und 2100")]) == {1990, 2100}
    assert runner.years_in_sources([_source(1, "1989 und 2101")]) == set()


# ---------------------------------------------------------------------------
# A pair carries its own evidence, twice
# ---------------------------------------------------------------------------

_TABLE = "| Energietraeger | 2030 | 2045 |\n| Erdgas | 42.005 | 0 |"
_HEAD = "Zielszenario: Die Waermeversorgung wird bis 2045 klimaneutral."


def _reply(**over):
    entry = {"scenario": "Zielszenario", "scenario_raw": "Zielszenario",
             "scenario_quote": _HEAD, "scenario_source": "Q2",
             "year": 2045, "year_quote": _TABLE, "year_source": "Q1"}
    entry.update(over)
    return {"pairs": [entry], "status": "complete", "need_more": []}


def _shown():
    return [_source(1, _TABLE), _source(2, _HEAD, kind="section")]


def test_every_half_of_a_pair_quotes_for_itself():
    """A column header carries the years and a section heading carries the
    scenario. One passage can back both halves only when it prints both, so
    each coordinate is held to its OWN quote -- the same rule a field answer
    has, and not a weaker one because the answer arrived in a pair."""
    pairs = runner.frame_pairs(_reply(), _slots(), _shown())
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["scenario"] == "Zielszenario" and pair["year"] == 2045
    assert pair["scenario_source"] == ["section", 2]
    assert pair["year_source"] == ["table", 1]
    assert pair["year_quote"] == _TABLE


def test_a_pair_whose_quote_is_in_no_shown_passage_is_not_a_pair():
    """And the quote CARRIES the answer, which is the case that matters: a
    sentence the model wrote itself, with 2045 in it, reads like evidence and
    is not any. The passage has to be one that was really shown."""
    invented = "Im Zieljahr 2045 ist die Waermeversorgung klimaneutral."
    assert "2045" in invented
    assert all(invented not in (s.text or "") for s in _shown())
    assert runner.frame_pairs(_reply(year_quote=invented),
                              _slots(), _shown()) == []
    assert runner.frame_pairs(_reply(year_quote="steht nirgends"),
                              _slots(), _shown()) == []


def test_a_pair_whose_quote_does_not_carry_the_answer_is_not_a_pair():
    """The quote is in a shown passage and says nothing about 2050. That is
    the answer a whole-tuple request used to hide inside a tuple some other
    quote had already justified."""
    assert runner.frame_pairs(_reply(year=2050), _slots(), _shown()) == []


def test_a_frame_reading_may_quote_a_heading_anywhere_in_the_plan():
    """A frame reading is document-level by construction -- read once from a
    heading, inherited by every row -- and no reading in the harvest is asked
    how near its passage stands. The heading is a different owner on a far
    page from the table, and the pair stands."""
    far = [_source(1, _TABLE), _source(99, _HEAD, kind="section")]
    pairs = runner.frame_pairs(_reply(scenario_source="Q2"), _slots(), far)
    assert len(pairs) == 1 and pairs[0]["scenario_source"] == ["section", 99]


def test_a_year_that_came_back_as_text_is_still_an_integer():
    """`kg.py` writes the year into the value's identity and refuses anything
    that is not an int, so the coercion happens where the evidence is still
    in hand rather than in the serializer."""
    pairs = runner.frame_pairs(_reply(year="2045"), _slots(), _shown())
    assert pairs and pairs[0]["year"] == 2045
    assert isinstance(pairs[0]["year"], int)


def test_the_same_pair_twice_is_one_pair():
    reply = _reply()
    reply["pairs"] = reply["pairs"] * 3
    assert len(runner.frame_pairs(reply, _slots(), _shown())) == 1


def test_a_source_id_that_points_at_the_wrong_passage_is_repaired_not_refused():
    """The id is a convenience and the quote is the evidence. A model that
    mislabels which passage it copied from has still copied it."""
    pairs = runner.frame_pairs(_reply(year_source="Q2"), _slots(), _shown())
    assert pairs and pairs[0]["year_source"] == ["table", 1]


# ---------------------------------------------------------------------------
# The search itself
# ---------------------------------------------------------------------------

def test_a_complete_answer_ends_the_search():
    asked = []

    def ask(sources, slots, document_id=None, known=None, usage_out=None,
            candidates=None):
        asked.append(candidates)
        return _reply()

    pairs, status, missed = runner.find_frame(_shown(), _slots(), 7, ask)
    assert status == "complete" and len(pairs) == 1
    assert asked[0] is None, "the first round asks about nothing in particular"


def test_what_the_scan_found_and_the_model_did_not_name_is_asked_once_more():
    """The second pass. A pair the frame does not have is not one value lost,
    it is every value of that pair lost, so the numbers the scan found are put
    back in front of the model by name."""
    rounds = []

    def ask(sources, slots, document_id=None, known=None, usage_out=None,
            candidates=None):
        rounds.append(candidates)
        if candidates:
            return _reply(year=2030, year_quote=_TABLE)
        return _reply()

    pairs, status, missed = runner.find_frame(_shown(), _slots(), 7, ask)
    assert rounds[-1] == [2030], rounds
    assert sorted(p["year"] for p in pairs) == [2030, 2045]
    assert missed == []


def test_the_cross_check_never_puts_a_year_in_the_frame_by_itself():
    """"2045 MWh/a" is year-shaped and is not a year. A cross-check that
    decided would ask every table in the plan for a year the plan has not
    got."""
    def ask(sources, slots, document_id=None, known=None, usage_out=None,
            candidates=None):
        return {"pairs": [], "status": "complete", "need_more": []}

    pairs, status, missed = runner.find_frame(
        [_source(1, "Die Anlage liefert 2045 MWh/a.")], _slots(), 7, ask)
    assert pairs == []
    assert missed == [2045], "reported and not read"


def test_a_search_that_never_completes_says_exhausted_rather_than_complete():
    def ask(sources, slots, document_id=None, known=None, usage_out=None,
            candidates=None):
        return {"pairs": [], "status": "incomplete", "need_more": []}

    pairs, status, missed = runner.find_frame(_shown(), _slots(), 7, ask)
    assert status == "exhausted" and pairs == []


def test_a_profile_with_no_frame_asks_nothing_and_answers_at_once():
    def ask(*a, **kw):
        raise AssertionError("it must not ask")

    assert runner.find_frame(_shown(), [], 7, ask) == ([], "complete", [])


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------

def test_the_pair_is_written_onto_the_rows_with_the_passage_it_was_read_in():
    """`read`, not `derived`: `derived` means the SPEC decides a coordinate
    without anybody reading anything, and this is a model reading with a
    passage behind it. The window says `frame` so a reader can tell a
    coordinate read for the DOCUMENT from one read for the row."""
    slots = _slots()
    pair = runner.frame_pairs(_reply(), slots, _shown())[0]
    rows = [_Row("R1"), _Row("R2")]
    assert apply_frame(rows, pair, 3, slots) == 4
    for row in rows:
        assert row.claim["year"] == 2045
        assert row.claim["year_state"] == fields.READ
        assert row.claim["year_quote"] == _TABLE
        assert row.claim["year_source"] == ["table", 1]
        assert row.claim["year_window"] == ["frame", 3]
        assert row.claim["scenario"] == "Zielszenario"
        assert row.claim["scenario_window"] == ["frame", 3]


def test_a_coordinate_the_row_itself_answered_is_not_overwritten():
    """The same rule `merge_field` has: read and backed once is the reading.
    The frame is what the request asked for, and a row that carried a better
    answer of its own still wins."""
    slots = _slots()
    pair = runner.frame_pairs(_reply(), slots, _shown())[0]
    rows = [_Row("R1", {"year": 2030, "year_state": fields.READ})]
    assert apply_frame(rows, pair, 0, slots) == 1        # scenario only
    assert rows[0].claim["year"] == 2030


def test_no_pair_writes_no_coordinate():
    assert apply_frame([_Row()], None, 0, _slots()) == 0
    assert apply_frame([_Row()], {"year": 2045}, 0, []) == 0


# ---------------------------------------------------------------------------
# One request per pair
# ---------------------------------------------------------------------------

def test_the_value_request_says_which_pair_it_is_for_and_asks_nothing():
    """The pair is already settled, so it rides in the request as a fact. A
    table with four year columns is four requests, each asking for one column
    -- which is the price this design pays on purpose, because it costs the
    model the room in which today's errors are made."""
    slots = _slots()
    pair = runner.frame_pairs(_reply(), slots, _shown())[0]
    batch = Batch(7, None, [WorkItem(7, None, _source(1, _TABLE))])
    batch.frame = pair
    payload = runner._batch_payload(batch, [], _spec())
    assert payload["frame"] == {"scenario": "Zielszenario", "year": 2045}
    # The evidence stays out of the request: it is what the pair was read
    # from, not something the model is asked to reproduce.
    assert not any(k.endswith(("_quote", "_source", "_raw"))
                   for k in payload["frame"])


def test_a_batch_with_no_frame_carries_none():
    batch = Batch(7, None, [WorkItem(7, None, _source(1, _TABLE))])
    assert "frame" not in runner._batch_payload(batch, [], _spec())


# ---------------------------------------------------------------------------
# The two requests: the sentence, and the frame
# ---------------------------------------------------------------------------

def test_the_anchor_is_one_sentence_per_parameter_written_for_this_document(
        make_client):
    """The QA app turns a question into ONE short statement before it
    searches, because a similarity search matches sentences. This stage
    searched with 24 frozen 600-character passages, and a 600-character
    passage is not an anchor: it is half a hit put back into the query."""
    seen = []

    def responder(kwargs):
        import types
        seen.append(json.loads(kwargs["messages"][1]["content"]))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=json.dumps(
                {"phrase": "Der Endenergieverbrauch fuer Waerme im "
                           "Stadtgebiet Kassel betrug 2022 rund 512 GWh/a."})))])

    spec = _spec()
    out = runner.document_anchor(spec, {"name": "Kassel", "caption": "Tabelle 17"},
                                 client=make_client(responder))
    assert set(out) == {p.uri for p in spec.parameters}
    assert all(len(v) == 1 and "Kassel" in v[0] for v in out.values())
    # The ontology annotation the spec inlines, and what the document said
    # about itself. Both, or the anchor is the same sentence for all 1,082
    # plans again.
    assert seen[0]["label"] and seen[0]["description"]
    assert seen[0]["document"] == {"name": "Kassel", "caption": "Tabelle 17"}


def test_a_parameter_whose_sentence_could_not_be_written_is_left_out(
        make_client, monkeypatch):
    """Not filled with the label. `plan_document` says out loud when it plans
    without anchors, and a probe that is a bare label is exactly the silently
    worse retrieval this stage exists to end."""
    import types
    monkeypatch.setattr(runner.time, "sleep", lambda *a, **k: None)

    def responder(kwargs):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content="kein JSON"))])

    assert runner.document_anchor(_spec(), {}, client=make_client(responder)) == {}


def test_the_frame_request_offers_the_closed_list_and_leaves_the_year_open():
    """Finite sets are a choice, not a generation -- and there is no list of
    years to choose from, so the one coordinate that has a vocabulary gets it
    and the other does not."""
    payload = runner._frame_payload(_shown(), _slots())
    assert [s["id"] for s in payload["sources"]] == ["Q1", "Q2"]
    assert "Zielszenario" in payload["scenarios"]
    assert not any(k.startswith("out:") for k in payload["scenarios"]), \
        "an out: entry is a way of saying no, not a scenario to look for"
    assert "years" not in payload and "candidates" not in payload


def test_the_frame_request_carries_what_is_already_known_and_what_to_recheck():
    payload = runner._frame_payload(
        _shown(), _slots(),
        known=[{"scenario": "Zielszenario", "year": 2045}],
        candidates=[2030])
    assert payload["known"] == [{"scenario": "Zielszenario", "year": 2045}]
    assert payload["candidates"] == [2030]


def test_the_frame_asker_sends_the_prompt_and_reads_one_object_back(
        monkeypatch, make_client):
    import types
    sent = []

    def responder(kwargs):
        sent.append(kwargs)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=json.dumps(_reply())))])

    client = make_client(responder)
    monkeypatch.setattr(runner, "_client", lambda: client)
    ask = runner.make_frame_asker()
    usage = {}
    reply = ask(_shown(), _slots(), 7, None, usage)
    assert reply["pairs"] and reply["status"] == "complete"
    assert sent[0]["temperature"] == 0, "a search anchor written twice is two "\
        "different searches nothing in the output distinguishes"
    assert "sources" in json.loads(sent[0]["messages"][1]["content"])


def test_a_frame_reply_that_is_no_object_is_retried_and_then_given_up_on(
        monkeypatch, make_client):
    import types
    tries = []

    def responder(kwargs):
        tries.append(1)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content="kein JSON"))])

    client = make_client(responder)
    monkeypatch.setattr(runner, "_client", lambda: client)
    monkeypatch.setattr(runner.time, "sleep", lambda *a, **k: None)
    assert runner.make_frame_asker()(_shown(), _slots(), 7) is None
    assert len(tries) == runner.MAX_RETRIES


def test_the_document_says_its_own_name_for_its_own_anchor(kwp_db):
    """The municipality lives in the profile's catalog join and in no query
    the core makes, so the core asks the profile rather than growing a second
    idea of what a document is."""
    from profiles.kwp import extraction as profile
    db, con = kwp_db
    con.execute("INSERT INTO OrganisationUnits (id, name) VALUES (1, 'Kassel')")
    con.execute("INSERT INTO Municipalities (ags, name, organisation_unit) "
                "VALUES (6611, 'Kassel', 1)")
    con.execute("INSERT INTO DocumentMeta (document, municipality_ags) "
                "VALUES (1, 6611)")
    con.commit()
    assert profile.document_context(con, 1) == {"name": "Kassel"}


def test_a_document_with_no_municipality_still_gets_an_anchor(kwp_db):
    """Missing metadata is not an error here. The anchor is written from the
    ontology annotation either way and the name only makes it sharper."""
    from profiles.kwp import extraction as profile
    db, con = kwp_db
    assert profile.document_context(con, 1) == {}
    assert profile.document_context(con, 4711) == {}


# ---------------------------------------------------------------------------
# The frame reads the whole plan
# ---------------------------------------------------------------------------

def test_the_frame_reads_every_window_of_the_plan_and_not_a_prefix():
    """A pair may only be quoted from a passage that was SHOWN, so a year
    printed past the cut cannot enter the frame at all, and a pair the frame
    does not have loses every value of that pair. Measured on Kassel: 12 of
    50 passages, 2 pairs, and 174 of the 234 table tuples the hand reading
    covers then carried a year printed on another table."""
    late = _source(99, "Tabelle 32: Zielszenario 2035\n| Erdgas | 42.005 |")
    sources = [_source(i, "Nichts zu holen.") for i in range(1, 30)] + [late]
    shown = []

    def ask(passages, slots, document_id=None, known=None, usage_out=None,
            candidates=None):
        shown.append([s.owner_id for s in passages])
        if late in passages:
            return _reply(year=2035,
                          year_quote="Tabelle 32: Zielszenario 2035",
                          scenario_quote="Tabelle 32: Zielszenario 2035")
        return {"pairs": [], "status": "complete", "need_more": []}

    pairs, status, missed = runner.find_frame(sources, _slots(), 7, ask)
    assert [p["year"] for p in pairs] == [2035]
    assert status == "complete" and missed == []
    assert len(shown) > 1, "one request over a prefix is the defect"
    assert {i for window in shown for i in window} \
        == {s.owner_id for s in sources}


def test_a_window_holds_what_one_request_can_carry():
    """Bounded by both, because a plan is fifty passages and a passage can be
    a whole table: the count keeps the request answerable and the characters
    keep it inside the model's window."""
    small = [_source(i, "x" * 10) for i in range(1, 40)]
    assert [len(w) for w in runner.frame_windows(small, max_sources=12,
                                                 max_chars=10_000)] \
        == [12, 12, 12, 3]
    big = [_source(i, "x" * 4000) for i in range(1, 6)]
    assert [len(w) for w in runner.frame_windows(big, max_sources=12,
                                                 max_chars=9_000)] \
        == [2, 2, 1]
    assert runner.frame_windows([]) == []


def test_the_second_pass_shows_the_passage_the_missed_year_stands_in():
    """The scan finds a year the model did not name, and it stands in a
    passage the model was not shown in the same request. Asking the first
    window again by name asks about a year that is not in front of it."""
    filler = [_source(i, "Nichts zu holen.") for i in range(1, 13)]
    late = _source(99, "Tabelle 32: Zielszenario 2035\n| Erdgas | 42.005 |")
    asked = []

    def ask(passages, slots, document_id=None, known=None, usage_out=None,
            candidates=None):
        asked.append(([s.owner_id for s in passages], candidates))
        if candidates and late in passages:
            return _reply(year=2035,
                          year_quote="Tabelle 32: Zielszenario 2035",
                          scenario_quote="Tabelle 32: Zielszenario 2035")
        return {"pairs": [], "status": "complete", "need_more": []}

    pairs, status, missed = runner.find_frame(filler + [late], _slots(), 7,
                                              ask)
    rechecks = [a for a in asked if a[1]]
    assert rechecks, "the scan found 2035 and nothing asked about it"
    assert all(99 in window for window, _c in rechecks)
    assert [p["year"] for p in pairs] == [2035] and missed == []


# ---------------------------------------------------------------------------
# A row belongs to the pair its passage names
# ---------------------------------------------------------------------------

_OWN = "Tabelle 30: Zielszenario 2045\n| Erdgas | 42.005 |"
_FOREIGN = "Tabelle 28: Zielszenario 2030\n| Erdgas | 17.000 |"


def _pair():
    return runner.frame_pairs(_reply(), _slots(), _shown())[0]


def _two_source_batch():
    batch = Batch(7, None, [WorkItem(7, None, _source(1, _OWN)),
                            WorkItem(7, None, _source(2, _FOREIGN))])
    batch.frame = _pair()
    return batch


_TUPLES = {"tuples": [
    {"source": "Q1", "value": 42005, "unit": "kWh/a", "unit_raw": "kWh/a",
     "quote": "| Erdgas | 42.005 |"},
    {"source": "Q2", "value": 17000, "unit": "kWh/a", "unit_raw": "kWh/a",
     "quote": "| Erdgas | 17.000 |"}]}


def test_a_passage_that_does_not_name_the_pair_yields_no_row():
    """The frame is a request, not a reading: what comes back is stamped with
    the pair and nothing else ever asks. So a passage that does not carry the
    pair is refused here, before its coordinates are paid for, and the request
    for ITS pair is where those values are found."""
    from docpipe.extraction.pipeline import rows_from_reply
    rows, orphans = rows_from_reply(_two_source_batch(), _TUPLES, _slots())
    assert [row.claim["value"] for row in rows] == [42005]
    assert [o["_why"] for o in orphans] == ["passage is not of this pair"]
    assert [o["value"] for o in orphans] == [17000]


def test_without_a_frame_every_passage_is_still_read():
    """The check is the frame's, not a new rule about passages. A run whose
    profile names no frame is untouched by it."""
    from docpipe.extraction.pipeline import rows_from_reply
    batch = _two_source_batch()
    batch.frame = None
    rows, orphans = rows_from_reply(batch, _TUPLES, _slots())
    assert sorted(row.claim["value"] for row in rows) == [17000, 42005]
    assert orphans == []
    # And a run that has a frame but does not tell the reader which axes span
    # it cannot refuse anything either.
    rows, orphans = rows_from_reply(_two_source_batch(), _TUPLES, None)
    assert len(rows) == 2 and orphans == []


def test_a_projected_coordinate_cites_the_rows_own_passage_where_it_says_so():
    """Both passages really say 2045, and only one of them tells a reader
    whether the row's own table does. The frame's passage stays the evidence
    where the row's own does not name the answer."""
    slots = _slots()
    rows = [_Row("R1")]
    apply_frame(rows, _pair(), 0, slots, [_source(5, _OWN)])
    assert rows[0].claim["year_source"] == ["table", 5]
    assert rows[0].claim["year_quote"] == "Tabelle 30: Zielszenario 2045"
    rows = [_Row("R1")]
    apply_frame(rows, _pair(), 0, slots, [_source(6, "Ohne Jahreszahl.")])
    assert rows[0].claim["year_source"] == ["table", 1]
    assert rows[0].claim["year_quote"] == _TABLE


def test_each_pair_has_its_own_prior_so_one_does_not_silence_the_other():
    """`prior` says "do not repeat", and the same table read for 2035 is not
    a repeat of the same table read for 2040. One budget per pair, or the
    second pair is told its own values are already taken."""
    from docpipe.extraction.pipeline import build_sweeps, sweep_key
    first = Batch(7, None, [WorkItem(7, None, _source(1, _TABLE))])
    second = Batch(7, None, [WorkItem(7, None, _source(1, _TABLE))])
    first.frame_index, second.frame_index = 0, 1
    assert sweep_key(first) != sweep_key(second)
    assert len(build_sweeps([first, second], 1)) == 2
    assert len(build_sweeps([first, first], 1)) == 1


def test_the_prompt_bounds_completeness_by_the_frame():
    """Where this began. The prompt told the model to return every value of
    every passage, and told it in the input description to return only the
    ones of this pair. It followed the loud rule, and 174 of 234 checked
    tuples carried a foreign year."""
    text = (PROFILES / "kwp" / "prompts" / "extraction"
            / "rows.md").read_text(encoding="utf-8")
    rule = [line for line in text.splitlines()
            if "vollst" in line.lower() and "Eintrag" in line]
    assert len(rule) == 1, rule
    assert "Frame" in rule[0], rule[0]


# ---------------------------------------------------------------------------
# A table with a column per year is read under every pair it prints
# ---------------------------------------------------------------------------

def _pair_at(year):
    return runner.frame_pairs(_reply(year=year, year_quote=_TABLE),
                              _slots(), _shown())[0]


# One table, one scenario, a column per year: it prints both pairs.
_SHARED = ("Tabelle 30: Endenergie im Zielszenario" + chr(10) + _TABLE)


def test_a_passage_of_several_pairs_is_read_under_each_of_them():
    """The request for 2030 takes the 2030 column and the request for 2045
    the 2045 column, and both read the same table. Read only under the first
    pair it prints, the other columns were left to a per-row year sweep, and
    on Kassel 55 of 172 years stayed missing."""
    from docpipe.extraction.pipeline import rows_from_reply
    slots = _slots()
    kept = []
    for index, pair in enumerate([_pair_at(2030), _pair_at(2045)]):
        batch = Batch(7, None, [WorkItem(7, None, _source(1, _SHARED))])
        batch.frame, batch.frame_index = pair, index
        tuples = {"tuples": [{"source": "Q1", "value": 42005, "unit": "kWh/a",
                              "unit_raw": "kWh/a",
                              "quote": "| Erdgas | 42.005 | 0 |"}]}
        rows, orphans = rows_from_reply(batch, tuples, slots)
        assert orphans == [], orphans
        kept.append(len(rows))
    assert kept == [1, 1], kept


def test_every_row_gets_the_year_of_its_own_pair():
    """The pair is what the request asked for, so it is what its rows carry,
    and nothing is left open for a per-row sweep to decide."""
    slots = _slots()
    source = _source(1, _SHARED)
    for year in (2030, 2045):
        rows = [_Row("R1")]
        assert apply_frame(rows, _pair_at(year), 0, slots, [source]) == 2
        assert rows[0].claim["year"] == year
        assert rows[0].claim["year_state"] == fields.READ
        assert rows[0].claim["scenario"] == "Zielszenario"


def test_a_passage_that_prints_a_pair_is_read_under_it_whichever_search_found_it():
    """Each pair's own search and the document's search keep fifty passages
    each, cut from two rankings. A table the document's search found that
    prints 2045, below the cut of the 2045 search, was in no batch at all:
    not under the pair, whose search had not kept it, and not in the rest,
    which is what prints none of the pairs. Found by review on 2026-09-10."""
    slots = _slots()
    pairs = [_pair_at(2030), _pair_at(2045)]
    only_2030 = WorkItem(7, None, _source(
        1, "Tabelle 4: Endenergie im Zielszenario 2030\n| Erdgas | 42.005 |"))
    only_2045 = WorkItem(7, None, _source(
        2, "Tabelle 5: Endenergie im Zielszenario 2045\n| Erdgas | 0 |"))
    both = WorkItem(7, None, _source(3, _SHARED))
    prose = WorkItem(7, None, _source(4, "Kassel liegt an der Fulda.",
                                      kind="section"))
    document_search = [only_2030, only_2045, prose]

    def read_under(batches):
        out: dict = {}
        for batch in batches:
            assert batch.frame is pairs[batch.frame_index]
            out.setdefault(batch.frame_index, set()).update(
                item.source.owner_id for item in batch.items)
        return out

    # The 2045 search kept only the prose, and `both` only the 2030 search.
    batches, rest, added = runner.pair_batches(
        document_search, pairs, [[only_2030, both], [prose]], slots,
        [("a",), ("b",)])
    assert read_under(batches) == {0: {1, 3}, 1: {4, 2, 3}}
    assert [item.source.owner_id for item in rest] == [4]
    assert added == 2
    assert {b.anchors for b in batches if b.frame_index == 1} == {("b",)}

    # The 2045 search failed: the pair is read over what the others found.
    batches, _rest, _added = runner.pair_batches(
        document_search, pairs, [[only_2030, both], None], slots, [(), ()])
    assert read_under(batches) == {0: {1, 3}, 1: {2, 3}}


def test_a_passage_of_one_pair_still_gets_that_pair_written():
    """A passage that prints one of the pairs and not the others is that
    pair's, and its rows are stamped as before."""
    only = _source(2, "Tabelle 30: Zielszenario 2045\n| Erdgas | 42.005 |")
    rows = [_Row("R1")]
    apply_frame(rows, _pair_at(2045), 1, _slots(), [only])
    assert rows[0].claim["year"] == 2045
    assert rows[0].claim["year_state"] == fields.READ


# ---------------------------------------------------------------------------
# One answer for many rows
# ---------------------------------------------------------------------------

_HEADER = "| Energietraeger | 2030 | 2045 |"
_LINE = "| Erdgas | 42.005 | 17.000 |"


def _year_slot():
    return _slots()[1]


def test_a_group_answer_is_held_to_its_quote_and_to_nothing_else():
    """The quote stands in a shown passage and carries 2030, so the answer
    stands for every row of the group. Which cell of the table a row sits in
    is the model's reading and not a rule of the check."""
    from docpipe.extraction.pipeline import merge_field
    source = _source(1, _HEADER + "\n" + _LINE)
    rows = [_Row("R1", {"quote": _LINE, "value": 42005}),
            _Row("R2", {"quote": _LINE, "value": 17000})]
    got = merge_field(rows, [source], _year_slot(),
                      {"groups": [{"rows": ["R1", "R2"], "value": 2030,
                                   "quote": _HEADER}]})
    assert got["filled"] == 2 and got["failed"] == []
    assert [row.claim["year"] for row in rows] == [2030, 2030]


def test_one_answer_still_holds_for_rows_of_the_same_column():
    """A table's thirteen rows really do share one year, and repeating the
    caption thirteen times is how a reply runs into the token wall. One group
    answers for all of them."""
    from docpipe.extraction.pipeline import merge_field
    slot = _year_slot()
    source = _source(1, _HEADER + "\n| Erdgas | 42.005 |\n| Holz | 17.000 |")
    rows = [_Row("R1", {"quote": "| Erdgas | 42.005 |", "value": 42005}),
            _Row("R2", {"quote": "| Holz | 17.000 |", "value": 17000})]
    rows[0].item_index = rows[1].item_index = 0
    got = merge_field(rows, [source], slot,
                      {"groups": [{"rows": ["R1", "R2"], "value": 2030,
                                   "quote": _HEADER}]})
    assert got["filled"] == 2
    assert [row.claim["year"] for row in rows] == [2030, 2030]
