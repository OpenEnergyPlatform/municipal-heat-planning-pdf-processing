"""
Nothing the harvest shows a model is cut (owner decision 2026-11-17: "Nichts
kürzen, einfach ggf. clever aufteilen und darauf achten, dass die Zuordnung zu
Sektion und Seite etc. nicht verlieren gehen"): what fits the request's window
is shown whole, what does not is split at its natural boundaries, each part
with its title, head or heading.

The promises, each with a case that breaks it by construction (a text longer
than any former limit):

1. The second reading shows the whole parent section of a table, however long
   (no rule `review_parent_chars`).
2. The compute step shows the model the whole output of its code, AND keeps it
   whole in the run record and the trace (no rule `code_output_chars`).
3. A passage the compute step fetches comes whole where it fits the window,
   AND where it does not, in parts that each fit it, each with the title and
   head (a table) or heading (a section) of the passage, AND every word of the
   passage stands in exactly one part, AND the answer says which part of how
   many it is, AND the next part is fetched in turn (`get` "part"); a part
   that cannot be shown is missed, never cut (no rule `compute_fetch_pages`).
4. A hit starts at the part that holds its line, chosen by the line's
   number (a paragraph numbered by sentence included).
4a. Every part of a table shows the rows it stands under (group row, indented
   parent rows), AND a part is sized to the room left when it is fetched (the
   parts not shown yet are split anew, the shown keep their numbers), AND a
   hit list that does not fit comes in parts, every hit reachable, AND what is
   judged is the message as it is sent (the follow-up), not its bare texts.
5. A hit list shows the whole first line of a passage AND the whole line of a
   pattern hit (no rules `hit_line_chars`, `pattern_hit_chars`).
6. A question asked again shows the model the whole of its broken answer: the
   whole reply with the place of the error named, the whole text outside the
   object, in the harvest and in the stages that read a reply
   (`reading.read`); where the question with that answer does not fit the
   window, it starts anew and names the cause in one sentence (no rule
   `fault_excerpt_chars`).
7. The outline of a search lists every table and figure of the hits' sections
   the request does not show (no rule `hit_outline`).
8. The check of a filled node shows each quote in its whole piece, with the
   lines the piece carries (title, head, heading), AND a quote that stands in
   two pieces shows both (no rule `node_check_context_chars`).

Author: Felix Vossel
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from docpipe import reading as stage_reading
from docpipe import rules
from docpipe.extraction import lookup, reading, runner, units
from docpipe.extraction.pipeline import Source

from conftest import in_turn
from test_compute_step import (ANSWER, BALANCE, CODE, amount, answered,
                               computing, plan_of, run_step, share, take)
from test_rules_runner import database

LONG = 20_000


@pytest.fixture(autouse=True)
def fresh():
    rules.reset()
    yield
    rules.reset()


def words_of(texts) -> list:
    return [word for text in texts for word in text.split()]


# 1 -----------------------------------------------------------------------

def test_the_whole_parent_section_of_a_table_is_shown(tmp_path):
    body = " ".join(f"w{i}" for i in range(LONG // 4))
    section = body + " [T1] " + body
    path, _conn = database(tmp_path)
    content = {("section", 5): {"owner_kind": "section", "owner_id": 5,
                                "document_id": 1, "title": "",
                                "text": section}}
    parents = runner.make_parents(path, content=lambda _c, kind, owner:
                                  content.get((kind, owner)))
    own = Source("table", 9, "| 1 |", {"parent_section": 5, "block_id": "T1"})
    got = parents([own])[0].text
    # the failure by construction: the former rule gave 4,000 of these
    assert len(section) > 4 * 4000 and got == section


# 2 -----------------------------------------------------------------------

def test_the_whole_output_of_the_code_is_shown_and_kept(monkeypatch):
    output = "38892.0\n" + "x" * 5000
    out = {"ok": True, "stdout": output, "error": None}
    step, asked, _runs, events = computing(monkeypatch, CODE, ANSWER, ran=out)
    run_step(step, share(21), amount(185200))
    assert output.strip() in asked[1]["messages"][-1]["content"]
    (code,) = [e for e in events if e["t"] == "code"]
    assert code["stdout"] == output


# 3, 4 --------------------------------------------------------------------

def table_of(rows: int = 40) -> Source:
    text = ("Tabelle 1: Verbrauch\n| Träger | 2020 |\n| --- | --- |\n"
            + "\n".join(f"| Träger{i} | {i * 7} |" for i in range(rows)))
    return Source("table", 5, text, {"block_id": "p1_tbl0", "page": 1})


def section_of(words: int = 400) -> Source:
    text = "Überschrift\n" + " ".join(f"wort{i}" for i in range(words))
    return Source("section", 6, text, {"section_title": "Überschrift"})


def room(limit: int):
    """A window of *limit* characters for what one reply fetches."""
    return lambda texts: sum(len(text) for text in texts) <= limit


def parts_of(source: Source, ask: dict, limit: int):
    """Every part of what *ask* fetches of *source*, asked in turn."""
    gathered = reading.Gathered()
    order = [source]
    passages = {(source.owner_kind, source.owner_id): source}
    assert gathered.fetch([ask], order, passages, room(limit))
    first = gathered.shown[0]
    count = int(first["part"].split(" of ")[1])
    for which in range(1, count + 1):
        if which != int(first["part"].split(" of ")[0]):
            assert gathered.fetch([{"get": "part", "id": first["id"],
                                    "part": which}], order, passages,
                                  room(limit))
    return gathered, count


def test_a_passage_that_fits_the_window_comes_whole():
    source = Source("section", 6, "Überschrift\n" + "x " * 30_000, {})
    gathered = reading.Gathered(cursor={"next": ("section", 1)})
    before = Source("section", 1, "Davor\nEin Satz.", {})
    assert gathered.fetch([{"get": "next"}], [before, source], {},
                          room(10 ** 6))
    # the failure by construction: the former rule cut this to two pages
    assert gathered.shown[0]["text"] == source.text
    assert "part" not in gathered.shown[0]


def test_a_table_that_does_not_fit_comes_in_parts_with_title_and_head():
    source = table_of()
    gathered, count = parts_of(source, {"get": "item", "id": "p1_tbl0"}, 300)
    assert count > 2 and len(gathered.shown) == count
    rows = [line for line in source.text.splitlines()
            if line.startswith("| Träger") and "---" not in line
            and line != "| Träger | 2020 |"]
    for entry in gathered.shown:
        lines = entry["text"].splitlines()
        assert len(entry["text"]) <= 300
        assert lines[0] == "Tabelle 1: Verbrauch"
        assert lines[1] == "| Träger | 2020 |"
        assert entry["title"] == "Tabelle 1: Verbrauch"
    shown = [line for entry in gathered.shown
             for line in entry["text"].splitlines()[2:]
             if line.startswith("| Träger") and "---" not in line]
    # every row stands in exactly one part, in order
    assert shown == rows
    assert [entry["part"] for entry in gathered.shown] == [
        f"{i} of {count}" for i in range(1, count + 1)]


def test_a_section_that_does_not_fit_comes_in_parts_with_its_heading():
    source = section_of()
    gathered = reading.Gathered(cursor={"next": ("section", 1)})
    before = Source("section", 1, "Davor\nEin Satz.", {})
    order = [before, source]
    assert gathered.fetch([{"get": "next"}], order, {}, room(500))
    first = gathered.shown[0]
    count = int(first["part"].split(" of ")[1])
    for which in range(2, count + 1):
        assert gathered.fetch([{"get": "part", "id": first["id"],
                                "part": which}], order, {}, room(500))
    assert count > 2
    for entry in gathered.shown:
        assert entry["text"].startswith("Überschrift\n")
        assert len(entry["text"]) <= 500
    # every word of the section stands in exactly one part
    body = source.text.split("\n", 1)[1].split()
    got = [word for entry in gathered.shown
           for word in entry["text"].split("\n", 1)[1].split()]
    assert got == body


def test_a_word_longer_than_the_window_cannot_be_split_and_is_missed():
    source = Source("table", 5, "Tabelle 1: " + "t" * 400
                    + "\n| a | b |\n| --- | --- |\n| 1 | 2 |",
                    {"block_id": "p1_tbl0"})
    gathered = reading.Gathered()
    assert not gathered.fetch([{"get": "item", "id": "p1_tbl0"}], [source],
                              {}, room(100))
    assert gathered.shown == []
    assert gathered.missed[0]["why"] == reading.TOO_LONG


def test_the_next_part_is_asked_for_by_an_entry_and_a_number():
    source = table_of()
    gathered = reading.Gathered()
    order, passages = [source], {("table", 5): source}
    gathered.fetch([{"get": "item", "id": "p1_tbl0"}], order, passages,
                   room(300))
    entry = gathered.shown[0]["id"]
    # a part that does not exist, a passage that came whole, a part shown
    for ask in ({"get": "part", "id": entry, "part": 99},
                {"get": "part", "id": "M9", "part": 2},
                {"get": "part", "id": entry, "part": "2"}):
        assert not gathered.fetch([ask], order, passages, room(300))
    assert [m["why"] for m in gathered.missed] == [reading.UNKNOWN] * 3
    assert not gathered.fetch([{"get": "part", "id": entry, "part": 1}],
                              order, passages, room(300))
    # a part the window no longer holds is told, not cut
    assert not gathered.fetch([{"get": "part", "id": entry, "part": 2}],
                              order, passages, room(10))
    assert gathered.missed[-1]["why"] == reading.TOO_LONG
    assert len(gathered.shown) == 1
    assert gathered.fetch([{"get": "part", "id": entry, "part": 2}],
                          order, passages, room(300))
    assert gathered.shown[1]["part"].startswith("2 of ")


def test_a_hit_starts_at_the_part_that_holds_its_line():
    source = table_of()
    gathered = reading.Gathered()
    order, passages = [source], {("table", 5): source}
    gathered.fetch([{"get": "search", "pattern": "Träger33 "}], order,
                   passages, None)
    assert gathered.fetch([{"get": "hit", "id": "H1"}], order, passages,
                          room(300))
    (entry,) = gathered.shown
    assert "| Träger33 | 231 |" in entry["text"]
    assert not entry["part"].startswith("1 of ")


def test_the_parts_of_a_passage_the_model_has_all_of_say_so_in_the_tool():
    assert "part" in reading.PART_GETS and "part" not in reading.GETS
    props = reading.more_schema(reading.PART_GETS)["items"]["properties"]
    assert "part" in props["get"]["enum"] and "part" in props


# 5 -----------------------------------------------------------------------

def test_a_hit_list_shows_the_whole_first_line_and_the_whole_pattern_line():
    long = Source("section", 9, "Titel\n" + "x" * 5000, {"page": 1})
    assert reading.first_line(long) == "x" * 5000
    far = "x" * 500 + " needle " + "y" * 500
    hit = lookup.matching([Source("section", 1, "H\n" + far, {})], "needle",
                          10 ** 6).hits[0]
    assert hit["line"] == far.strip()


# 6 -----------------------------------------------------------------------

def reply_of(text, finish="stop"):
    return SimpleNamespace(finish_reason=finish, message=SimpleNamespace(
        content=text, reasoning_content=None))


def test_a_retry_shows_the_whole_reply_once_with_the_place_of_the_error(
        monkeypatch):
    monkeypatch.setattr(runner, "request_room",
                        lambda system, conversation, wanted, whole=False: 100)
    text = '{"a": "' + "w" * 3000 + '", "b": ,}'
    cause, said = runner._reply_fault(reply_of(text), 100)
    assert cause == "syntax"
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        assert f" {exc.pos} " in said          # the place is named
    # the reply stands whole as the model's own turn, and only there
    again = runner.asked_again("s", [{"role": "user", "content": "Frage"}],
                               text, said, cause, 10)
    assert again[1] == {"role": "assistant", "content": text}
    assert sum(str(m["content"]).count("w" * 3000) for m in again) == 1
    foreign = ("x " * 300) + '{"a": 1}' + ("y " * 300)
    cause, said = runner._reply_fault(reply_of(foreign), 100)
    again = runner.asked_again("s", [{"role": "user", "content": "Frage"}],
                               foreign, said, cause, 10)
    assert cause == "outside_text" and again[1]["content"] == foreign
    assert sum(str(m["content"]).count("x " * 300) for m in again) == 1


def test_the_stages_that_read_a_reply_show_it_whole_too():
    text = '{"rows": "' + "w" * 3000 + '", "b": ,}'
    choice = SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
        content=text, reasoning_content=None))
    _found, cause, said = stage_reading.read(choice, key="rows")
    assert cause == "syntax" and repr(text) in said
    foreign = ("x " * 300) + '{"rows": []}' + ("y " * 300)
    choice.message.content = foreign
    _found, cause, said = stage_reading.read(choice, key="rows")
    extra = (foreign[:foreign.index("{")]
             + foreign[foreign.index("}") + 1:]).strip()
    assert cause == "outside_text" and repr(extra) in said


def test_a_retry_that_does_not_fit_the_window_starts_anew(monkeypatch):
    def fits(system, conversation, wanted, whole=False):
        size = sum(len(str(m["content"])) for m in conversation)
        return 100 if size < 500 else None
    monkeypatch.setattr(runner, "request_room", fits)
    asked = [{"role": "user", "content": "Frage"}]
    short = runner.asked_again("s", asked, "kurz", "Korrektur", "syntax", 10)
    assert [m["role"] for m in short] == ["user", "assistant", "user"]
    assert short[1]["content"] == "kurz"
    long = runner.asked_again("s", asked, "w" * 2000, "Korrektur", "syntax",
                              10)
    # the failure by construction: the reply is not shown, not cut
    assert [m["role"] for m in long] == ["user"]
    assert long[0]["content"].startswith("Frage")
    assert "syntax" in long[0]["content"]
    assert "w" * 20 not in long[0]["content"]
    pictured = [{"role": "user", "content": [{"type": "text", "text": "F"}]}]
    again = runner.asked_again("s", pictured, "w" * 2000, "K", "empty", 10)
    assert again[0]["content"][0] == {"type": "text", "text": "F"}
    assert "empty" in again[0]["content"][-1]["text"]


# 7 -----------------------------------------------------------------------

def test_every_unshown_item_of_the_hits_sections_is_listed():
    from test_addressed import plan_of
    from test_hit_outline import ELSEWHERE, SECTION, SHOWN, ids, outline, table
    many = [table(100 + i, f"p9_t{i}", 2, f"Tabelle {i}: Weitere")
            for i in range(30)]
    plan = plan_of(SECTION, SHOWN, *many, ELSEWHERE, chunk_units=8)
    got = outline(plan, ("table", 3))
    assert ids(got) == [[f"p9_t{i}" for i in range(30)]]


# 8 -----------------------------------------------------------------------

def long_table() -> Source:
    text = ("Tabelle 2: Endenergie\n| Träger | Wert |\n| --- | --- |\n"
            + "\n".join(f"| Träger{i:02d} " + "." * 100 + f" | {i} |"
                        for i in range(30)))
    return Source("table", 7, text, {})


def test_the_check_shows_the_whole_piece_with_its_title_and_head():
    source = long_table()
    quote = f"| Träger20 " + "." * 100 + " | 20 |"
    got = runner.piece_text(source, quote, 8)
    lines = got.splitlines()
    assert lines[0] == "Tabelle 2: Endenergie" and lines[1] == "| Träger | Wert |"
    assert quote in lines
    # neighbours farther than 200 characters from the quote are in
    # (the former rule showed 200 characters around it)
    at = lines.index(quote)
    assert at > 2 and at + 1 < len(lines)
    far = [line for line in lines[2:] if abs(lines.index(line) - at) >= 2]
    assert far and all(len(line) > 100 for line in lines[2:])
    # and rows of other pieces are not
    passage = units.passage_of(source)
    piece = next(p for p in units.chunks_of(passage, 8)
                 if any(passage.line(n).text == quote for n in p.numbers))
    assert got == piece.text()
    assert "Träger00" not in got and "Träger29" not in got


def test_a_quote_over_two_pieces_shows_both():
    source = long_table()
    passage = units.passage_of(source)
    pieces = units.chunks_of(passage, 8)
    last, first = pieces[0].numbers[-1], pieces[1].numbers[0]
    quote = passage.line(last).text + " " + passage.line(first).text
    got = runner.piece_text(source, quote, 8)
    assert passage.line(last).text in got and passage.line(first).text in got
    assert passage.line(pieces[0].numbers[0]).text in got
    assert passage.line(pieces[1].numbers[-1]).text in got
    assert passage.line(pieces[2].numbers[0]).text not in got


def test_the_check_shows_the_heading_of_a_section_over_a_later_piece():
    # (a digit before a full stop reads as an ordinal, not a sentence end)
    sentences = [f"Satz {a}{b}." for a in "abcdefgh" for b in "ijklm"]
    text = "Überschrift\n" + " ".join(sentences)
    source = Source("section", 3, text, {"section_title": "Überschrift"})
    got = runner.piece_text(source, sentences[30], 8)
    assert got.startswith("Überschrift\n") and sentences[30] in got
    assert sentences[0] not in got
    assert runner.piece_text(source, "Satz zz.", 8) is None


def test_the_payload_of_the_check_carries_the_piece_of_each_quote():
    from test_node_check import PARAMETER, SLOTS, row_of
    source = long_table()
    quote = "| Träger20 " + "." * 100 + " | 20 |"
    row = row_of()
    row["quote"] = quote
    row["provenance"] = {"owner_kind": "table", "owner_id": 7}
    body = runner._node_check_payload(row, {("table", 7): source},
                                      PARAMETER, SLOTS)
    first = body["quotes"][0]
    assert first["quote"] == quote
    assert first["around"] == runner.piece_text(source, quote, 8)
    # a quote the passage does not hold carries no piece
    assert "around" not in body["quotes"][1]


# 3, 4 (follow-ups) ---------------------------------------------------------

def grouped_table() -> Source:
    rows = "\n".join(f"|     Erdgas{i:02d} | {i} |" for i in range(30))
    text = ("Tabelle 2: Verbrauch\n| Land | 2020 |\n| --- | --- |\n"
            "| AT | |\n| Wohngebäude | 100 |\n" + rows)
    return Source("table", 5, text, {"block_id": "p1_tbl0", "page": 1})


def test_every_part_of_a_table_shows_the_rows_it_stands_under():
    gathered, count = parts_of(grouped_table(),
                               {"get": "item", "id": "p1_tbl0"}, 200)
    assert count > 2
    for entry in gathered.shown:
        lines = entry["text"].splitlines()
        # the failure by construction: a later part lost its group row and
        # the parent row of its rows
        assert "| AT | |" in lines and "| Wohngebäude | 100 |" in lines
        assert lines.index("| AT | |") < lines.index("| Wohngebäude | 100 |")
        assert len(entry["text"]) <= 200
    rows = [line for entry in gathered.shown
            for line in entry["text"].splitlines() if "Erdgas" in line]
    assert rows == [f"|     Erdgas{i:02d} | {i} |" for i in range(30)]


def test_a_part_is_sized_to_the_room_left_when_it_is_fetched():
    source = table_of()
    gathered = reading.Gathered()
    order, passages = [source], {("table", 5): source}
    state = {"cap": 300}

    def fits(texts):
        return sum(len(text) for text in texts) <= state["cap"]
    assert gathered.fetch([{"get": "item", "id": "p1_tbl0"}], order, passages,
                          fits)
    first = gathered.shown[0]
    before = int(first["part"].split(" of ")[1])
    # The conversation has grown by part 1: the room is smaller now.
    state["cap"] = 120
    which = 2
    while gathered.fetch([{"get": "part", "id": first["id"], "part": which}],
                         order, passages, fits):
        which += 1
    # the failure by construction: the part sized for 300 no longer fits 120
    assert len(gathered.shown) > 2
    # only the ask past the last part found nothing
    assert [m["why"] for m in gathered.missed] == [reading.UNKNOWN]
    count = int(gathered.shown[-1]["part"].split(" of ")[1])
    assert count > before
    assert [entry["part"] for entry in gathered.shown[1:]] == [
        f"{i} of {count}" for i in range(2, count + 1)]
    assert all(len(entry["text"]) <= 120 for entry in gathered.shown[1:])
    rows = [line for entry in gathered.shown
            for line in entry["text"].splitlines() if "| Träger" in line
            and line != "| Träger | 2020 |"]
    # every row of the table in exactly one part, in order
    assert rows == [f"| Träger{i} | {i * 7} |" for i in range(40)]


def test_a_part_that_cannot_fit_even_split_anew_is_missed_and_changes_nothing():
    source = table_of()
    gathered = reading.Gathered()
    order, passages = [source], {("table", 5): source}
    gathered.fetch([{"get": "item", "id": "p1_tbl0"}], order, passages,
                   room(300))
    entry = gathered.shown[0]["id"]
    kept = list(gathered.parts[("table", 5)])
    assert not gathered.fetch([{"get": "part", "id": entry, "part": 2}],
                              order, passages, room(10))
    assert gathered.missed[-1]["why"] == reading.TOO_LONG
    assert gathered.parts[("table", 5)] == kept


def paragraphs_of(count: int = 12) -> Source:
    body = "\n".join(f"Erster Satz von Absatz{i}. Zweiter Satz von Absatz{i}. "
                     f"Dritter Satz von Absatz{i}." for i in range(count))
    return Source("section", 6, "Überschrift\n" + body,
                  {"section_title": "Überschrift"})


def test_a_hit_in_a_paragraph_of_sentences_starts_at_the_part_that_holds_it():
    source = paragraphs_of()
    gathered = reading.Gathered()
    order, passages = [source], {("section", 6): source}
    gathered.fetch([{"get": "search",
                     "pattern": r"Zweiter Satz von Absatz11\b"}], order,
                   passages, None)
    assert gathered.fetch([{"get": "hit", "id": "H1"}], order, passages,
                          room(200))
    (entry,) = gathered.shown
    # the failure by construction: the paragraph is not a substring of a
    # part, which holds its sentences on lines
    assert "Zweiter Satz von Absatz11." in entry["text"]
    assert not entry["part"].startswith("1 of ")
    assert entry["text"].startswith("Überschrift\n")


def test_a_hit_line_is_found_by_its_number_not_by_the_text_of_a_part():
    passage = units.passage_of(paragraphs_of(3))
    at = ("Erster Satz von Absatz2. Zweiter Satz von Absatz2. "
          "Dritter Satz von Absatz2.")
    first = lookup.hit_line(passage.lines, at)
    both = lookup.hit_line(passage.lines, at, r"Dritter Satz")
    assert passage.line(first).text == "Erster Satz von Absatz2."
    assert passage.line(both).text == "Dritter Satz von Absatz2."
    assert lookup.hit_line(passage.lines, "nirgends") is None


def hits_of(count: int = 300) -> list:
    return [Source("section", i, f"Titel{i}\nEin Treffer im Absatz{i}.", {})
            for i in range(count)]


def test_a_hit_list_beyond_the_room_comes_in_parts_and_every_hit_is_reachable():
    order = hits_of()
    gathered = reading.Gathered()
    assert gathered.fetch([{"get": "search", "pattern": "Treffer"}], order, {},
                          room(1000))
    first = gathered.hits[0]
    assert first["total"] == 300 and first["part"].startswith("1 of ")
    assert 0 < len(first["hits"]) < 300
    which = 2
    while gathered.fetch([{"get": "part", "id": first["id"], "part": which}],
                         order, {}, room(1000)):
        which += 1
    # the failure by construction: the first hits were all there was
    assert [h["id"] for listed in gathered.hits for h in listed["hits"]] == [
        f"H{i}" for i in range(1, 301)]
    assert [h["title"] for listed in gathered.hits
            for h in listed["hits"]] == [f"Titel{i}" for i in range(300)]
    for listed in gathered.hits:
        assert len(json.dumps(reading.shown_list(listed),
                              ensure_ascii=False)) <= 1000
        assert listed["total"] == 300
    # only the ask past the last part found nothing
    assert [m["why"] for m in gathered.missed] == [reading.UNKNOWN]
    # a hit of a late part is fetched by its id
    passages = {(s.owner_kind, s.owner_id): s for s in order}
    assert gathered.fetch([{"get": "hit", "id": "H300"}], order, passages,
                          None)
    # the same pattern again lists nothing twice
    lists = len(gathered.hits)
    assert not gathered.fetch([{"get": "search", "pattern": "Treffer"}],
                              order, {}, room(1000))
    assert len(gathered.hits) == lists


def test_a_hit_list_that_fits_comes_whole_with_no_id_of_its_own():
    gathered = reading.Gathered()
    assert gathered.fetch([{"get": "search", "pattern": "Treffer"}],
                          hits_of(3), {}, room(10 ** 6))
    (listed,) = gathered.hits
    assert len(listed["hits"]) == 3 and "part" not in listed
    assert "id" not in listed


def wrapped(follow: dict) -> str:
    """A stand-in for the follow-up message: words and indented JSON."""
    return "Here is what is new:\n\n" + json.dumps(
        follow, ensure_ascii=False, indent=2)


def test_what_is_judged_is_the_message_as_it_is_sent():
    text = "Überschrift\n" + " ".join(f"w{i:03d}" for i in range(30))
    source = Source("section", 6, text, {"section_title": "Überschrift"})
    cap = 200
    assert len(text) < cap

    def fetched(render):
        gathered = reading.Gathered(cursor={"next": ("section", 1)})
        order = [Source("section", 1, "Davor\nEin Satz.", {}), source]
        gathered.fetch([{"get": "next"}], order, {}, room(cap), render)
        return gathered, order
    # judged by its bare text it fits and is sent whole, over the window
    bare, _ = fetched(None)
    assert "part" not in bare.shown[0]
    assert len(wrapped(bare.since((0, 0, 0)))) > cap
    # judged as sent, it is split, and every message that is sent fits
    gathered, order = fetched(wrapped)
    first = gathered.shown[0]
    assert first["part"].startswith("1 of ")
    assert len(wrapped(gathered.since((0, 0, 0)))) <= cap
    which = 2
    while True:
        mark = gathered.mark()
        if not gathered.fetch([{"get": "part", "id": first["id"],
                                "part": which}], order, {}, room(cap),
                              wrapped):
            break
        assert len(wrapped(gathered.since(mark))) <= cap
        which += 1
    words = [w for entry in gathered.shown
             for w in entry["text"].split("\n", 1)[1].split()]
    assert words == text.split("\n", 1)[1].split()


def test_the_compute_step_judges_a_fetch_as_the_follow_up_it_sends(
        monkeypatch):
    sent = []
    real = reading.Gathered.fetch

    def spy(self, asks, order, passages, fits=None, render=None):
        mark = self.mark()
        got = real(self, asks, order, passages, fits, render)
        # a fetch that brought something is followed up, judged by *render*
        if got:
            sent.append(render(self.since(mark)) if render else None)
        return got
    monkeypatch.setattr(reading.Gathered, "fetch", spy)
    onward = json.dumps({"more": [{"get": "next"}]})
    step, asked, _runs, _events = computing(
        monkeypatch, onward, onward, take(), CODE,
        answered(38892.0, quote="Der Wärmeverbrauch der Stadt"),
        plan=plan_of(BALANCE, "Abschnitt danach."))
    run_step(step, share(21))
    # the failure by construction: a fetch given no message to judge
    assert sent and sent[0] is not None
    assert sent[0] == asked[1]["messages"][-1]["content"]


# 23 ----------------------------------------------------------------------

def shows_database(tmp_path, front_words=0, listed=0, figures_front=0):
    """A one-document corpus: a section on page 1 of *front_words* words, a
    section on page 5 with *listed* tables of a caption each, and a figure
    on page 1 of *figures_front* words."""
    import sqlite3
    path = tmp_path / "shows.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                is_current INTEGER);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               section_number INTEGER, title TEXT,
                               content TEXT, page_number INTEGER);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             block_id TEXT, page_number INTEGER,
                             caption TEXT, markdown TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             block_id TEXT, page_number INTEGER,
                             caption TEXT, description TEXT);
        INSERT INTO Documents VALUES (1, 'a.pdf', 1);
    """)
    conn.execute("INSERT INTO Sections VALUES (1, 1, 1, 'Front', ?, 1)",
                 (" ".join(["word"] * front_words),))
    conn.execute("INSERT INTO Sections VALUES (2, 1, 2, 'Later', 'text', 5)")
    conn.executemany(
        "INSERT INTO Tables VALUES (?, 2, ?, 5, ?, 'a | b')",
        [(i, f"T{i}", f"Table {i} of the heat demand") for i in range(listed)])
    conn.execute("INSERT INTO Images VALUES (1, 1, 'F1', 1, 'Figure', ?)",
                 (" ".join(["pixel"] * figures_front),))
    conn.commit()
    conn.close()
    return path


def test_the_title_page_and_the_outline_are_counted_off_the_database(
        tmp_path):
    small = runner.shows_tokens(shows_database(tmp_path))
    base = tmp_path / "base"
    base.mkdir()
    big = runner.shows_tokens(shows_database(base, front_words=900,
                                             listed=40))
    per = rules.get("window_words_per_token")
    # nothing is capped: 900 words of page 1 are counted whole (each line
    # with its number), 40 listed tables each with its id and title
    assert big["title_page"] - small["title_page"] >= int(900 * per)
    assert big["outline"] > small["outline"] + int(40 * 4 * per)
    # the failure by construction: the headings alone do not grow with them
    assert big["headings"] == small["headings"]


def test_a_figure_on_the_title_page_counts_only_where_the_rule_shows_it(
        tmp_path):
    path = shows_database(tmp_path, front_words=3, figures_front=500)
    without = runner.shows_tokens(path)["title_page"]
    with rules.overlaid(title_page_with_figures=True):
        with_figures = runner.shows_tokens(path)["title_page"]
    assert with_figures > without


def test_the_budget_counts_the_shows_the_flow_shows_and_no_others(monkeypatch):
    from test_rules_runner import prompt_of
    prompt = prompt_of(100)
    standard = runner.context_budget(prompt)
    monkeypatch.setattr(runner, "shown_by_flow",
                        lambda: {"title_page": True, "outline": True})
    assert runner.context_budget(prompt, title_page=700, outline=300) \
        == standard + 1000
    monkeypatch.setattr(runner, "shown_by_flow",
                        lambda: {"title_page": False, "outline": True})
    assert runner.context_budget(prompt, title_page=700, outline=300) \
        == standard + 300
    monkeypatch.setattr(runner, "shown_by_flow",
                        lambda: {"title_page": True, "outline": False})
    assert runner.context_budget(prompt, title_page=700, outline=300) \
        == standard + 700
    monkeypatch.setattr(runner, "shown_by_flow",
                        lambda: {"title_page": False, "outline": False})
    assert runner.context_budget(prompt, title_page=700, outline=300) \
        == standard


def test_the_request_budget_passes_the_shows_to_every_prompt(monkeypatch):
    seen = []
    monkeypatch.setattr(runner, "survey_prompt_ids", lambda: ["a", "b"])
    monkeypatch.setattr(runner.prompts, "load", lambda pid, profile: pid)
    monkeypatch.setattr(
        runner, "context_budget",
        lambda prompt, spec, headings, title_page, outline:
        seen.append((headings, title_page, outline)) or 1)
    runner.request_budget(None, headings=1, title_page=2, outline=3)
    assert seen == [(1, 2, 3), (1, 2, 3)]


def test_the_flow_shows_the_title_page_and_the_outline_of_its_boxes(
        monkeypatch):
    # "find" shows the title page and no outline, "search" the outline of
    # its hits' sections (the input `hit_outline`)
    find = {"id": "f", "box": "ask", "preset": "find"}
    search = {"id": "s", "box": "ask", "preset": "search"}
    tree = [find]
    monkeypatch.setattr(runner.flow_map, "tree_of", lambda profile=None: tree)
    assert runner.shown_by_flow() == {"title_page": True, "outline": False}
    tree[:] = [find, search]
    assert runner.shown_by_flow() == {"title_page": True, "outline": True}
    # a box that never shows the title page, a search that may fetch no
    # item, one that may not fetch, boxes that are off
    tree[:] = [{**find, "rules": {"show_title_page": "never"}}]
    assert runner.shown_by_flow()["title_page"] is False
    tree[:] = [find, {**search, "rules": {"fetches": ["next"]}}]
    assert runner.shown_by_flow()["outline"] is False
    tree[:] = [find, {**search, "set": {"fetch": False}}]
    assert runner.shown_by_flow()["outline"] is False
    tree[:] = [find, {**search, "off": True}]
    assert runner.shown_by_flow() == {"title_page": True, "outline": False}
    tree[:] = [{**find, "off": True}, {**search, "off": True}]
    assert runner.shown_by_flow() == {"title_page": False, "outline": False}
