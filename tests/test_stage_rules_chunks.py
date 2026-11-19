"""The decisions of stage 6 (pieces and vectors) are rules, with today's value as
their default (owner request 2026-11-19, point A1 of the review of that day:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard").

The promises, each with a case that breaks it by construction:

1. Every rule of stage 6 has a default in the default profile's rules.json that
   the rules take, a title and a help; a value out of its bounds, or a kind of
   item the rule does not know, is refused.
2. The index holds the vectors the rules name: a title vector for every titled
   section while embed_section_titles is on AND none while it is off; the text
   vectors of the kinds in embed_item_texts AND of no other kind; the picture
   vectors of the kinds in embed_item_pictures AND of no other kind, the
   picture of a kind left out never looked for.
3. A line is placed on a page by the beginnings of the lengths the rule names:
   a line shorter than the shortest length stands where the line before it
   stands AND is placed once the rule allows a shorter probe.
4. The merge joins a table that continues the table before it while the rule
   is on AND keeps every part a table of its own while it is off.
5. The embedder's instruction and the largest picture it takes are the rules:
   the chat of an item without instruction carries the sentence of the rule,
   AND an item that names its own keeps it; the window counts a picture by the
   most pixels of the rule.
6. A request for a context sentence has the reply room and the temperature of
   the rules where the header of its prompt gives none AND those of the header
   where it gives them; the sentence that names an empty reply is a prompt
   file, byte for byte what the code sent.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from docpipe import prompts, rules
from docpipe.chunking import context, merge, pieces
from docpipe.chunking.chunking import build_embedding_inputs
from docpipe.chunking.config import DOCUMENT_JSON, SECTIONS_REFINED_JSON, VISUALS_JSON
from docpipe.embedding import api
from docpipe.ruleset.stage_chunks import RULES

HEAD = "| Jahr | Wert |\n| --- | --- |"
EMPTY = ("The sentence is empty. Answer with one JSON object with a non-empty "
         "sentence.")


def doc():
    return {"sections": [
        {"title": "Endenergiebedarf", "content": "Bedarf [p1_tbl0] [p1_fig0]",
         "page_number": 1, "pages": [1],
         "tables": [{"id": "p1_tbl0", "caption": "Tabelle 1: Bedarf",
                     "markdown": HEAD + "\n| 2025 | 10 |",
                     "path": "images/p1_tbl0.png", "page_number": 1}],
         "figures": [{"id": "p1_fig0", "caption": "Abbildung 1: Verlauf",
                      "description": "Linie von 10 auf 8 GWh",
                      "path": "images/p1_fig0.png", "page_number": 1}]},
        {"title": "", "content": "Ein Satz ohne Titel im Text.",
         "page_number": 2, "pages": [2], "tables": [], "figures": []}]}


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "images").mkdir()
    for name in ("p1_tbl0", "p1_fig0"):
        (tmp_path / "images" / f"{name}.png").write_bytes(b"png")
    return tmp_path


def kinds(folder):
    return sorted(i.embedding_type for i in
                  build_embedding_inputs(doc(), "plan", folder, log_counts=False))


ALL = ["figure_text", "figure_vl", "section_text", "section_text",
       "section_title", "table_text", "table_vl"]


# -- 1. the rules ---------------------------------------------------------------

def test_every_rule_has_a_default_a_title_and_a_help():
    defaults = rules.default()
    assert len(RULES) == 9
    for one in RULES:
        assert one.tab == "stages" and one.group == "Stage 6: pieces and vectors"
        assert one.title and one.help and one.where
        assert rules.problem(one.name, defaults[one.name]) is None, one.name


def test_a_value_out_of_its_bounds_or_a_kind_the_rule_does_not_know_is_refused():
    assert rules.problem("embed_item_texts", ["table", "chart"])
    assert rules.problem("embed_item_pictures", ["table", "table"])
    assert rules.problem("embed_item_texts", []) is None        # may be left out
    assert rules.problem("embed_picture_max_pixels", 100)
    assert rules.problem("context_default_max_tokens", 4)
    assert rules.problem("context_default_temperature", 3)
    assert rules.problem("embed_instruction", "")
    assert rules.problem("page_locate_probe_chars", {"long": "48"})
    assert rules.problem("join_continued_tables", 1)


def test_the_defaults_are_the_values_the_code_held():
    defaults = rules.default()
    assert defaults["embed_picture_max_pixels"] == 1800 * 32 * 32
    assert defaults["embed_instruction"] == "Represent the user's input."
    assert defaults["embed_section_titles"] is True
    assert defaults["embed_item_texts"] == ["table", "figure"]
    assert defaults["embed_item_pictures"] == ["table", "figure"]
    assert defaults["page_locate_probe_chars"] == {"long": 48, "medium": 24,
                                                   "short": 12}
    assert defaults["context_default_max_tokens"] == 400
    assert defaults["context_default_temperature"] == 0.1
    assert defaults["join_continued_tables"] is True


# -- 2. the vectors -------------------------------------------------------------

def test_with_the_defaults_every_vector_is_built(folder):
    assert kinds(folder) == ALL


def test_a_title_vector_is_built_for_a_titled_section_only_while_the_rule_is_on(folder):
    with rules.overlaid(embed_section_titles=False):
        assert kinds(folder) == [k for k in ALL if k != "section_title"]


def test_the_text_vectors_are_those_of_the_kinds_the_rule_names(folder):
    with rules.overlaid(embed_item_texts=["table"]):
        assert kinds(folder) == [k for k in ALL if k != "figure_text"]
    with rules.overlaid(embed_item_texts=["figure"]):
        assert kinds(folder) == [k for k in ALL if k != "table_text"]
    with rules.overlaid(embed_item_texts=[]):
        assert kinds(folder) == [k for k in ALL
                                 if k not in ("table_text", "figure_text")]


def test_the_picture_vectors_are_those_of_the_kinds_the_rule_names(folder):
    with rules.overlaid(embed_item_pictures=["figure"]):
        assert kinds(folder) == [k for k in ALL if k != "table_vl"]
    with rules.overlaid(embed_item_pictures=[]):
        assert kinds(folder) == [k for k in ALL
                                 if k not in ("table_vl", "figure_vl")]


def test_a_picture_of_a_kind_left_out_is_not_even_looked_for(folder, monkeypatch):
    from docpipe.chunking import chunking
    looked = []
    real = chunking._picture

    def spy(item, kind, *args):
        looked.append(kind)
        return real(item, kind, *args)

    monkeypatch.setattr(chunking, "_picture", spy)
    with rules.overlaid(embed_item_pictures=["table"]):
        build_embedding_inputs(doc(), "plan", folder, log_counts=False)
    assert set(looked) == {"table"}


def test_a_picture_vector_shows_the_text_of_its_piece_whatever_the_text_rule(folder):
    with rules.overlaid(embed_item_texts=[]):
        made = [i for i in build_embedding_inputs(doc(), "plan", folder,
                                                  log_counts=False)
                if i.embedding_type == "table_vl"]
    assert made and made[0].image.endswith("p1_tbl0.png")
    assert "| 2025 | 10 |" in made[0].text


# -- 3. the probes ----------------------------------------------------------------

SECTION = {"page_number": 7, "segments": [
    {"kind": "text", "page": 7, "text": "Erster Satz über Wärme im Ort."},
    {"kind": "text", "page": 8, "text": "Kurzer Satz folgt hier."}]}
LINES = ["Erster Satz über Wärme im Ort.", "Kurzer Satz"]      # 10 letters


def test_a_line_shorter_than_the_shortest_probe_stands_where_the_line_before_stands():
    assert pieces.line_pages(LINES, SECTION) == [7, 7]
    probes = {"long": 24, "medium": 16, "short": 8}
    with rules.overlaid(page_locate_probe_chars=probes):
        assert pieces.line_pages(LINES, SECTION) == [7, 8]


def test_the_probes_are_tried_longest_first_whatever_their_order_in_the_rule():
    with rules.overlaid(page_locate_probe_chars={"long": 8, "medium": 24,
                                                 "short": 48}):
        assert pieces._probes() == (48, 24, 8)
    assert pieces._probes() == (48, 24, 12)


# -- 4. the join -------------------------------------------------------------------

def merged_of(tmp_path):
    (tmp_path / SECTIONS_REFINED_JSON).parent.mkdir(exist_ok=True)
    (tmp_path / SECTIONS_REFINED_JSON).write_text(json.dumps({"sections": [{
        "title": "Anhang", "page_number": 1, "content": "",
        "tables": [{"id": "t1", "page_number": 1}, {"id": "t2", "page_number": 2}],
        "figures": []}]}), encoding="utf-8")
    (tmp_path / VISUALS_JSON).write_text(json.dumps({"sections": [{"tables": [
        {"id": "t1", "page_number": 1, "markdown": HEAD + "\n| 2025 | 10 |",
         "after": None, "continues": False},
        {"id": "t2", "page_number": 2, "markdown": HEAD + "\n| 2026 | 11 |",
         "after": "t1", "continues": True}], "figures": []}]}),
        encoding="utf-8")
    return merge.merge_single(tmp_path, force=True)


def test_a_table_that_continues_the_one_before_is_joined_while_the_rule_is_on(tmp_path):
    got = merged_of(tmp_path)
    tables = got["sections"][0]["tables"]
    assert [t["id"] for t in tables] == ["t1"]
    assert "| 2026 | 11 |" in tables[0]["markdown"]


def test_every_part_stays_a_table_of_its_own_while_the_rule_is_off(tmp_path):
    with rules.overlaid(join_continued_tables=False):
        got = merged_of(tmp_path)
    tables = got["sections"][0]["tables"]
    assert [t["id"] for t in tables] == ["t1", "t2"]
    assert "| 2026 | 11 |" not in tables[0]["markdown"]
    assert (tmp_path / DOCUMENT_JSON).is_file()


# -- 5. the embedder ----------------------------------------------------------------

def test_an_item_without_instruction_is_embedded_under_the_instruction_of_the_rule():
    assert api.conversation({"text": "x"})[0]["content"][0]["text"] == (
        "Represent the user's input.")
    with rules.overlaid(embed_instruction="Find the passage for the question"):
        assert api.conversation({"text": "x"})[0]["content"][0]["text"] == (
            "Find the passage for the question")
        # an item that names its own keeps it
        own = api.conversation({"text": "x", "instruction": "Find the table"})
        assert own[0]["content"][0]["text"] == "Find the table."


def test_the_window_counts_a_picture_by_the_most_pixels_of_the_rule():
    from docpipe.chunking.embedding import window_of
    window = window_of(SimpleNamespace())
    missing = "no-such-picture.png"            # unreadable: costs the most
    assert window.picture(missing) == 1800 + 2
    with rules.overlaid(embed_picture_max_pixels=64 * 32 * 32):
        assert window_of(SimpleNamespace()).picture(missing) == 64 + 2


# -- 6. the context sentence ----------------------------------------------------------

def made_ask(monkeypatch, meta):
    seen = {}
    monkeypatch.setattr(context.prompts, "load", lambda _id: SimpleNamespace(
        meta=meta, text="system", sha256="x"))
    monkeypatch.setattr(context.providers, "client", lambda *a, **k: None)
    monkeypatch.setattr(context, "window_fits", lambda *a, **k: None)
    monkeypatch.setattr(context, "ask_model",
                        lambda client, request, **kwargs: seen.update(kwargs))
    ask, _fits = context.make_ask()
    ask({"kind": "table"})
    return seen


def test_a_context_request_has_the_room_and_temperature_of_the_rules_where_the_header_has_none(monkeypatch):
    seen = made_ask(monkeypatch, {})
    assert (seen["max_tokens"], seen["temperature"]) == (400, 0.1)
    with rules.overlaid(context_default_max_tokens=900,
                        context_default_temperature=0.5):
        seen = made_ask(monkeypatch, {})
        assert (seen["max_tokens"], seen["temperature"]) == (900, 0.5)
        # the header of the prompt, where it names them, decides
        seen = made_ask(monkeypatch, {"max_tokens": 200, "temperature": 0.0})
        assert (seen["max_tokens"], seen["temperature"]) == (200, 0.0)


class Client:
    def __init__(self, contents):
        self.contents = list(contents)
        self.messages = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.messages.append(kwargs["messages"])
        choice = SimpleNamespace(message=SimpleNamespace(
            content=self.contents.pop(0)), finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=None)


def test_the_sentence_naming_an_empty_reply_is_a_prompt_file_with_the_words_the_code_sent(monkeypatch):
    assert prompts.text("visuals/context_sentence_empty") == EMPTY
    client = Client(['{"sentence": ""}', '{"sentence": "Ein Satz."}'])
    got = context.ask_model(client, {"kind": "table"}, system="s", model="m",
                            temperature=0.1, max_tokens=400, max_retries=2,
                            wait=lambda s: None)
    assert got == "Ein Satz."
    assert EMPTY in json.dumps(client.messages[1], ensure_ascii=False)
    # the file is what is said: another text there is another thing said
    real = prompts.text
    monkeypatch.setattr(context.prompts, "text", lambda pid, **v: (
        "NAME THE CAUSE" if pid == context.EMPTY_PROMPT_ID else real(pid, **v)))
    client = Client(['{"sentence": ""}', '{"sentence": "Ein Satz."}'])
    context.ask_model(client, {"kind": "table"}, system="s", model="m",
                      temperature=0.1, max_tokens=400, max_retries=2,
                      wait=lambda s: None)
    assert "NAME THE CAUSE" in json.dumps(client.messages[1], ensure_ascii=False)
    assert EMPTY not in json.dumps(client.messages[1], ensure_ascii=False)
