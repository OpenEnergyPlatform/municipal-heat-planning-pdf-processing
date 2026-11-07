"""One conversation per value (owner decisions 2026-11-07), each promise with
a case that breaks it by construction.

1. A round's quote stands exactly once in what the round showed AND holds
   its value exactly once, a name or number inside a longer one not
   counting; otherwise the round asks again.
2. Each message of a value's first conversation asks exactly one
   coordinate, in the order of the spec's groups and of each group's
   coordinates, AND carries the answers before it in the same conversation.
3. A coordinate is derived from the unit only where the unit was read as an
   entry of the parameter's list; otherwise it is asked.
4. A unit is never refused: a number whose unit is no entry stays read with
   the unit as printed and without a converted value, AND the harvest's
   summary counts that unit.
5. A value read off a figure's image is level C AND never A or B; without a
   figure there is no value read off.
6. The second conversation is a new conversation that shows the answers so
   far AND not the value's passage itself.
7. The search of a coordinate lists hits first and may only fetch them in
   its first message; its own searches come from the next message on.
8. A table whose frame coordinate is open on all its values is asked once,
   AND every value of it takes the answer with its quote.
9. A parameter whose walk down its list read no value is searched for by
   the model itself, AND every passage that search names is read for it and
   is one of its sources.
10. No reply format of the survey flow and no row it reads carries a column
    head.
"""
import json
from pathlib import Path

from docpipe.extraction import (combing, fields, reading, runner, survey,
                                surveyed, trust, verify)
from docpipe.extraction.pipeline import Batch, Source, WorkItem
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads((Path(__file__).resolve().parent.parent
                             / "profiles" / "kwp" / "extraction_spec.json")
                            .read_text(encoding="utf-8")))
ENERGY = SPEC.by_uri["energy_consumption"]


def passage(kind, number, text, title):
    return Source(kind, number, text, {"document_id": 7,
                                       "section_title": title})


def answered(thread, reply):
    """What the run keeps of an answer: the conversation goes on after it."""
    if thread is not None and isinstance(reply, dict):
        thread.messages = [*thread.messages, {"role": "user", "content": ""},
                           {"role": "assistant",
                            "content": json.dumps(reply)}]
    return reply


def found_of(source, *uris):
    owner = (source.owner_kind, source.owner_id)
    return survey.Found(True, {owner: survey.Answer(owner, list(uris), {},
                                                    [])}, [])


def unstated(slots):
    return {slot.name: {"value": fields.UNSTATED, "probe": "ein Satz"}
            for slot in slots}


# -- 1. the round's quote pins its value down ----------------------------------

ROW_TABLE = passage("table", 4, "| Träger | Bedarf | Anzahl | Anteil |\n"
                    "| Gas | 410.662,44 | 1.109 | 6% |\n"
                    "| Öl | 12.000,10 | 1.109 | 2% |", "Bestand")


def test_a_quote_that_stands_once_and_holds_its_value_once_is_taken():
    claim = {"source": "Q1", "value": 1109,
             "quote": "410.662,44 | 1.109 | 6%"}
    assert reading.round_failure(claim, [ROW_TABLE], [], ENERGY,
                                 "table") is None


def test_a_quote_that_stands_twice_in_the_passage_is_asked_again():
    claim = {"source": "Q1", "value": 1109, "quote": "| 1.109 |"}
    kind, _why = reading.round_failure(claim, [ROW_TABLE], [], ENERGY,
                                       "table")
    assert kind == reading.UNIQUE


def test_a_quote_that_holds_its_value_twice_is_asked_again():
    text = passage("section", 5, "Der Bedarf liegt bei 1.109 MWh, davon "
                   "1.109 MWh Wärme.", "Bedarf")
    claim = {"source": "Q1", "value": 1109, "quote": text.text}
    kind, _why = reading.round_failure(claim, [text], [], ENERGY, "section")
    assert kind == reading.UNIQUE


def test_a_number_inside_a_longer_one_is_no_second_occurrence():
    text = passage("section", 6, "Es sind 11.109 MWh und 1.109 MWh.", "Bedarf")
    claim = {"source": "Q1", "value": 1109,
             "quote": "Es sind 11.109 MWh und 1.109 MWh"}
    assert reading.round_failure(claim, [text], [], ENERGY,
                                 "section") is None


# -- 2. and 3. the first conversation, one coordinate per message ---------------

BALANCE = passage("section", 1, "Bilanz\nEs wurden rund 300 MWh verbraucht.",
                  "Bilanz")
PER_HEAD = passage("section", 2,
                   "Bilanz\nEs wurden rund 300 MWh/EW verbraucht.", "Bilanz")


def first_conversation(source, unit_reply):
    """The reading of ENERGY in *source*, one value, every coordinate but
    the unit answered not stated: [(slots asked, thread, messages before)]
    and the Reads."""
    asked = []
    values = iter([{"value": 300, "quote": source.text.split("\n")[1]
                    .rstrip(".")}, {"value": None}])

    def ask_values(src, parameter, context, read, thread, follow=None,
                   drawn=False):
        return answered(thread, next(values))

    def ask_text(src, parameter, group, slots, row, context, thread,
                 follow=None):
        if follow is None:
            asked.append(([slot.name for slot in slots], thread,
                          list(thread.messages)))
        if [slot.name for slot in slots] == [fields.UNIT]:
            return answered(thread, unit_reply)
        return answered(thread, unstated(slots))

    reader = reading.Reader(SPEC, ask_values, ask_text,
                            runner.frame_slots_of(SPEC))
    reads = reader(7, found_of(source, ENERGY.uri),
                   {(source.owner_kind, source.owner_id): source})
    return asked, reads


def spec_order(parameter, skip=()):
    """The parameter's coordinates in the order of the spec's groups and of
    each group's coordinates."""
    names = {slot.name for slot in reading.slots_of(SPEC, parameter)}
    return [name for group in SPEC.groups.values()
            for name in group.coordinates if name in names
            and name not in skip]


def derived_by_unit_names(parameter):
    return [slot.name for slot in reading.slots_of(SPEC, parameter)
            if slot.derive]


MWH = {"unit": {"value": "MWh", "value_raw": "MWh",
                "quote": "rund 300 MWh verbraucht"}}
PRINTED = {"unit": {"value": "", "value_raw": "MWh/EW",
                    "quote": "rund 300 MWh/EW verbraucht"}}


def test_each_message_asks_one_coordinate_in_the_order_of_the_spec():
    asked, _reads = first_conversation(BALANCE, MWH)
    assert all(len(names) == 1 for names, _t, _m in asked)
    assert [names[0] for names, _t, _m in asked] == spec_order(
        ENERGY, skip=derived_by_unit_names(ENERGY))


def test_each_message_carries_the_answers_before_it_in_one_conversation():
    asked, _reads = first_conversation(BALANCE, MWH)
    threads = {id(thread) for _n, thread, _m in asked}
    assert len(threads) == 1
    # Every message after the first has the answer of the one before it.
    for (names, _t, _m), (_n, _t2, before) in zip(asked, asked[1:]):
        assert any(names[0] in message["content"]
                   for message in before if message["role"] == "assistant")


def test_a_unit_read_as_an_entry_derives_what_it_decides_and_asks_it_not():
    asked, reads = first_conversation(BALANCE, MWH)
    derived = derived_by_unit_names(ENERGY)
    assert derived
    names = [names[0] for names, _t, _m in asked]
    assert not set(derived) & set(names)
    claim = reads[0].claims[0]
    assert all(claim.get(f"{name}_state") == fields.DERIVED
               for name in derived)


def test_a_unit_without_an_entry_derives_nothing_and_asks_it():
    asked, reads = first_conversation(PER_HEAD, PRINTED)
    names = [names[0] for names, _t, _m in asked]
    assert set(derived_by_unit_names(ENERGY)) <= set(names)
    assert names == spec_order(ENERGY)


# -- 4. a unit is never refused --------------------------------------------------

def test_a_unit_without_an_entry_is_read_as_printed_and_not_converted():
    _asked, reads = first_conversation(PER_HEAD, PRINTED)
    claim = reads[0].claims[0]
    assert claim.get(f"{fields.UNIT}_state") == fields.READ
    assert claim.get(fields.UNIT) is None
    assert claim.get(f"{fields.UNIT}_raw") == "MWh/EW"
    flags: list = []
    out, refusal = verify._check_value(
        {"value": 300, "unit": None, "unit_raw": "MWh/EW"}, ENERGY, flags)
    assert refusal is None and out["unit"] is None
    assert "value_target" not in out
    entry, refusal = verify._check_value(
        {"value": 300, "unit": "MWh", "unit_raw": "MWh"}, ENERGY, [])
    assert refusal is None and entry["value_target"] == 300.0


def test_the_summary_counts_the_units_that_are_no_entry():
    rows = [{"tier": trust.TIER_TEXT, "unit": None, "unit_raw": "MWh/EW",
             "flags": ["unmapped:unit:MWh/EW"]},
            {"tier": trust.TIER_TEXT, "unit": "MWh", "unit_raw": "MWh"},
            {"tier": trust.TIER_TEXT, "unit": None, "unit_raw": "MWh/EW"}]
    summary = trust.document_summary(7, rows, [])
    assert summary["unlisted_units"] == {"MWh/EW": 2}


# -- 5. a value read off a figure ------------------------------------------------

def test_a_value_read_off_a_figure_is_level_c_and_never_a_or_b():
    row = {"tier": trust.TIER_TEXT, "flags": [verify.READ_OFF],
           "read_off": True, "reading": "Balken bei 120"}
    assert trust.trust(row)["level"] == trust.LEVEL_C
    plain = {"tier": trust.TIER_TEXT, "flags": []}
    assert trust.trust(plain)["level"] == trust.LEVEL_A


def test_without_a_figure_there_is_no_value_read_off():
    raw = {"value": 120, "read_off": True, "reading": "Balken bei 120"}
    assert verify.read_off(raw, "figure")
    assert not verify.read_off(raw, "section")
    # A reading without the image is no evidence: the claim keeps no reading.
    claim = reading.claim_of({"value": 120, "drawn": True,
                              "reading": "Balken bei 120"}, drawn=False)
    assert "reading" not in claim and not claim.get("read_off")
    text = passage("section", 8, "Ein Abschnitt ohne die Zahl.", "Text")
    assert reading.round_failure(
        {"source": "Q1", "value": 120, "read_off": True,
         "reading": "Balken bei 120"}, [text], [], ENERGY,
        "section") is not None


# -- 6. to 8. the second conversation --------------------------------------------

YEAR = next(slot for slot in reading.slots_of(SPEC, ENERGY)
            if slot.name == "year")
MIDDLE = passage("section", 2, "Methode\nDie Bilanz folgt dem Standard.",
                 "Methode")
OUTLOOK = passage("section", 3, "Ausblick\nDie Werte gelten für 2030.",
                  "Ausblick")


class Talk:
    """The combing's requests: each message with its payload, follow-up,
    reply format and conversation; *replies(payload, follow, shape)* answers
    them."""

    def __init__(self, replies):
        self.replies = replies
        self.messages = []

    def __call__(self, payload, shape, document_id, source, group=None,
                 example=None, thread=None, follow=None):
        self.messages.append({"payload": payload, "follow": follow,
                              "shape": shape, "thread": thread,
                              "before": list(thread.messages)
                              if thread is not None else []})
        return answered(thread, self.replies(payload, follow, shape))


def asked_gets(shape) -> list:
    more = shape["json_schema"]["schema"]["properties"].get("more")
    return list(more["items"]["properties"]["get"]["enum"]) if more else []


def read_value(source, **states):
    return {"source": "Q1", "value": 300,
            "quote": "Es wurden rund 300 MWh verbraucht",
            "unit": "MWh", "unit_raw": "MWh", "unit_state": fields.READ,
            "unit_quote": "rund 300 MWh verbraucht",
            "unit_source": [source.owner_kind, source.owner_id], **states}


def comb_year(replies, rank=None):
    talk = Talk(replies)
    comber = combing.Comber(SPEC, talk, rank, lambda claim, asked: {})
    passages = {(s.owner_kind, s.owner_id): s
                for s in (BALANCE, MIDDLE, OUTLOOK)}
    claim = read_value(BALANCE, year_state=fields.SAID_UNSTATED)
    result = comber.comb(7, ENERGY, BALANCE, [YEAR], [claim], passages, [],
                         probes={"year": "Die Werte gelten für 2030."})
    return talk, claim, result


def test_the_second_conversation_is_new_and_shows_the_answers_not_the_passage():
    talk, _claim, _result = comb_year(lambda p, f, s: unstated([YEAR]))
    first = talk.messages[0]
    assert first["payload"] is not None
    # A new conversation: nothing was said in it before its first message.
    assert first["thread"] is not None and first["before"] == []
    shown = json.dumps(first["payload"], ensure_ascii=False)
    assert "rund 300 MWh verbraucht" in json.dumps(first["payload"]["read"],
                                                   ensure_ascii=False)
    assert "source" not in first["payload"]
    assert "Es wurden rund 300 MWh verbraucht." not in shown.replace(
        '"quote": "Es wurden rund 300 MWh verbraucht"', "")


def test_the_search_lists_hits_first_and_searches_itself_only_after():
    def replies(payload, follow, shape):
        carried = payload or follow or {}
        if "hits" in carried and asked_gets(shape) == ["hit"]:
            return {"more": [{"get": "hit", "id": "H1"}]}
        if "more" in carried:
            return {"year": {"value": 2030,
                             "quote": "Die Werte gelten für 2030"}}
        return unstated([YEAR])
    talk, claim, _result = comb_year(
        replies, rank=lambda document_id, probes, exclude: [OUTLOOK])
    searched = [m for m in talk.messages
                if "hits" in (m["payload"] or m["follow"] or {})]
    assert searched and asked_gets(searched[0]["shape"]) == ["hit"]
    later = talk.messages[talk.messages.index(searched[0]) + 1:]
    assert later and set(asked_gets(later[0]["shape"])) == set(reading.GETS)
    assert claim.get("year") == 2030
    assert claim.get("year_state") == fields.READ


TABLE = passage("table", 9, "Verbrauch nach Trägern\n| Träger | MWh |\n"
                "| Gas | 300 |\n| Öl | 120 |", "Ausblick")


def test_a_table_with_its_frame_open_on_all_values_is_asked_once():
    passages = {(s.owner_kind, s.owner_id): s
                for s in (TABLE, OUTLOOK)}
    batch = Batch(7, ENERGY, [WorkItem(7, ENERGY, TABLE)])
    claims = [{"source": "Q1", "value": value, "quote": quote,
               "unit": "MWh", "unit_state": fields.READ,
               "unit_raw": "MWh", "unit_quote": "| Träger | MWh |",
               "unit_source": ["table", 9],
               **{f"{name}_state": fields.SAID_UNSTATED
                  for name in ("scenario", "year", "period_start")}}
              for value, quote in ((300, "| Gas | 300 |"),
                                   (120, "| Öl | 120 |"))]
    read = reading.Read(batch, claims)

    def replies(payload, follow, shape):
        carried = json.dumps(payload or follow or {}, ensure_ascii=False)
        if '"year"' in carried:
            return {"year": {"value": 2030,
                             "quote": "Die Werte gelten für 2030"}}
        return {}

    def year_conversations(reads) -> tuple:
        talk = Talk(replies)
        comber = combing.Comber(SPEC, talk, None, lambda claim, asked: {})
        comber(7, reads, passages, [], None)
        asks = [m for m in talk.messages if '"year"' in json.dumps(
            (m["payload"] or {}).get("coordinates")
            or (m["follow"] or {}).get("coordinates") or {},
            ensure_ascii=False)]
        return {id(m["thread"]) for m in asks}, [
            m for m in talk.messages if asks and m["payload"]
            and m["thread"] is asks[0]["thread"]]

    threads, opening = year_conversations([read])
    assert len(threads) == 1
    # The conversation that asked it shows the whole table.
    assert opening and opening[0]["payload"].get("whole_table")
    assert all(claim.get("year") == 2030 for claim in claims)
    assert all(claim.get("year_quote") == "Die Werte gelten für 2030"
               for claim in claims)
    # Each value in a table of its own: asked once per value.
    apart = [reading.Read(Batch(7, ENERGY, [WorkItem(7, ENERGY, table)]),
                          [dict(claim, year_state=fields.SAID_UNSTATED,
                                year=None)])
             for table, claim in ((TABLE, claims[0]),
                                  (passage("table", 10, TABLE.text,
                                           "Ausblick"), claims[1]))]
    threads, _asks = year_conversations(apart)
    assert len(threads) == 2


# -- 9. the model's own search after the list ------------------------------------

class NoRanking:
    trace = None

    def rank(self, document_id, probes, exclude):
        return []

    def session(self, document_id, shown, pairs, budget, bases=None,
                **plan):
        return combing.Session(combing.Comber(SPEC, None, None, None),
                               document_id, shown, pairs, budget, bases)


def free_harvest(places):
    """A harvest whose survey named no passage for ENERGY, whose search
    ranks nothing, and whose own search names *places*: the readings asked
    and the searches made."""
    asked, searched = [], []

    def make_reader(spec):
        def run(document_id, found, shown, budget, **plan):
            named = found.passages_of(ENERGY.uri)
            asked.append(list(named))
            return []
        return run

    def seeker(document_id, parameter, passages, walked, budget):
        searched.append(parameter.uri)
        return list(places)

    whole = surveyed.SurveyedHarvest(
        SPEC, lambda spec, only, scope: (lambda document_id, passages:
                                         survey.Found(True)),
        make_reader, lambda spec: NoRanking(),
        lambda document_id: [BALANCE, OUTLOOK], lambda document_id: 2,
        make_seeker=lambda spec: seeker)
    return whole, asked, searched


def test_a_parameter_the_walk_found_no_value_of_is_searched_and_read():
    whole, asked, searched = free_harvest([OUTLOOK])
    taken = whole(7)
    assert ENERGY.uri in searched
    assert any(("section", 3) in named for named in asked)
    assert ("section", 3) in taken.sources_of[ENERGY.uri]


def test_a_search_that_names_nothing_reads_nothing_more():
    whole, asked, searched = free_harvest([])
    taken = whole(7)
    assert ENERGY.uri in searched
    assert not any(("section", 3) in named for named in asked)
    assert ("section", 3) not in taken.sources_of[ENERGY.uri]


# -- 10. no column head ----------------------------------------------------------

def keys_of(schema) -> set:
    out: set = set()
    if isinstance(schema, dict):
        out |= set((schema.get("properties") or {}).keys())
        for value in schema.values():
            out |= keys_of(value)
    elif isinstance(schema, list):
        for value in schema:
            out |= keys_of(value)
    return out


def test_no_reply_format_and_no_row_read_carries_a_head():
    slots = reading.slots_of(SPEC, ENERGY)
    formats = [reading.values_response_format(ENERGY),
               reading.values_response_format(ENERGY, drawn=True),
               combing.comb_response_format(slots),
               combing.near_response_format(slots)]
    formats += [reading.text_response_format([slot]) for slot in slots]
    assert all("head" not in keys_of(shape) for shape in formats)
    _asked, reads = first_conversation(BALANCE, MWH)
    assert reads[0].claims and all("head" not in claim
                                   for claim in reads[0].claims)


# -- the plan's settings and the model's own search ------------------------------

from docpipe.extraction import seeking, settings  # noqa: E402

METHOD = passage("section", 11, "Methode\nDas Basisjahr ist das Jahr 2022.",
                 "Methode")


def test_a_setting_is_taken_only_where_its_quote_holds_what_it_settles():
    taken, wrong = settings.PlanSettings.checked({"settings": [
        {"about": "Basisjahr", "value": "2022",
         "quote": "Das Basisjahr ist das Jahr 2022"},
        {"about": "Basisjahr", "value": "2021",
         "quote": "Das Basisjahr ist das Jahr 2022"},
        {"about": "Zieljahr", "value": "2040",
         "quote": "2040"}]}, [METHOD])
    assert [(s["about"], s["value"], s["source"]) for s in taken] == [
        ("Basisjahr", "2022", ["section", 11])]
    assert [w["value"] for w in wrong] == ["2021", "2040"]


def test_the_own_search_returns_the_passages_it_names_and_tells_an_unknown_id():
    order = {(s.owner_kind, s.owner_id): s for s in (BALANCE, MIDDLE, METHOD)}
    replies = iter([{"places": [], "more": [{"get": "next"}]},
                    {"places": [{"id": "M1"}, {"id": "M9"}]},
                    {"places": []}])
    sent = []

    def ask(payload, document_id, thread, follow):
        sent.append(follow or {})
        return answered(thread, next(replies))
    search = seeking.FreeSearch(ask)
    found = search(7, ENERGY, order, [], None)
    assert [(s.owner_kind, s.owner_id) for s in found] == [("section", 2)]
    # The id no hit and no fetched passage has is told once.
    told = [entry for one in sent for entry in one.get("corrections", ())]
    assert [entry["id"] for entry in told] == ["M9"]


# A coordinate only the second reading re-reads ends exhausted where its
# request came back unread, never with the state the first conversation
# left; by construction, an answer read leaves the state it gives.
def test_an_unread_second_reading_leaves_a_coordinate_it_alone_asks_exhausted():
    what = next(slot for slot in reading.slots_of(SPEC, ENERGY)
                if slot.name == "what")
    passages = {(s.owner_kind, s.owner_id): s
                for s in (BALANCE, MIDDLE, OUTLOOK)}
    for answer, state in ((None, fields.EXHAUSTED),
                          (unstated([what]), fields.SAID_UNSTATED)):
        talk = Talk(lambda p, f, s, answer=answer: answer)
        comber = combing.Comber(SPEC, talk, None, lambda claim, asked: {})
        claim = read_value(BALANCE, what_state=fields.SAID_UNSTATED)
        comber.comb(7, ENERGY, BALANCE, [what], [claim], passages, [])
        assert claim.get("what_state") == state
