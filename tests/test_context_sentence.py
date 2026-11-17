"""The sentence of context before each table and figure of the index (rule
`context_sentence`, docpipe/chunking/context.py; owner decision 2026-11-17,
from the literature on contextual retrieval).

Promises, each with a case that breaks it by construction:

1. On, the embedded text of a table and of a figure starts with the sentence,
   for the text input and for the text of the picture input. (A document that
   carries no sentence is embedded as before; a sentence of an item with no
   text is not embedded alone.)
2. The model is asked once for each table and figure, and a second build with
   the same caption, text and heading asks nothing: the sentence is kept. (A
   changed caption, text or heading asks again, and only for that item.)
3. Off, nothing is asked, nothing is read from what is kept, and the inputs are
   byte for byte what they were.
4. An answer out of form is asked again, as often as the other stages ask, and
   is never embedded.
5. `--step sync` takes a changed sentence for a changed entry (its vectors go)
   and an unchanged one for an unchanged entry (its vectors stay).
6. Nothing is cut (owner decision 2026-11-17): the request shows the whole
   text of a table or figure; one over the window is asked in parts, each
   with its caption, heading and head and every row in exactly one part, and
   a head that alone does not fit is named, never cut. Each part has its
   sentence, which the index puts before the rows of that part. A reply whose
   echo does not fit is asked anew with its cause, nothing of it shown.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.artifacts import DOCUMENT_JSON
from docpipe.chunking import context
from docpipe.chunking.chunking import build_embedding_inputs
from docpipe.chunking.config import CONTEXT_SENTENCES_JSON
from docpipe.refinement.config import MAX_RETRIES

from test_sync import Corpus, HEAD, section, table


def doc():
    """One section with a table and a figure, both with a picture on disk."""
    return {"sections": [{
        "title": "Endenergiebedarf", "content": "Bedarf [p1_tbl0] [p1_fig0]",
        "page_number": 1, "pages": [1],
        "tables": [{"id": "p1_tbl0", "caption": "Tabelle 1: Bedarf",
                    "markdown": HEAD + "\n| 2025 | 10 |",
                    "path": "images/p1_tbl0.png", "page_number": 1}],
        "figures": [{"id": "p1_fig0", "caption": "Abbildung 1: Verlauf",
                     "description": "Linie von 10 auf 8 GWh",
                     "path": "images/p1_fig0.png", "page_number": 1}]}]}


@pytest.fixture
def folder(tmp_path):
    """A document directory with its two pictures."""
    pdf_dir = tmp_path / "plan"
    (pdf_dir / "images").mkdir(parents=True)
    (pdf_dir / "results").mkdir()
    for name in ("p1_tbl0", "p1_fig0"):
        (pdf_dir / "images" / f"{name}.png").write_bytes(b"png")
    return pdf_dir


class Asker:
    """A stand-in for the model that says one sentence per request and counts."""

    def __init__(self, reply=None):
        self.requests = []
        self.reply = reply

    def __call__(self, request):
        self.requests.append(request)
        if self.reply is not None:
            return self.reply
        return f"Satz zu {request['kind']} {request['caption']}"


def table_text(*rows):
    """A table's text as the index shows it (`chunking.pieces`): its title,
    its head and its rows, the rule under the head only where the rule
    `table_rule_line` shows it."""
    head = HEAD.splitlines()
    shown = [head[0]] + ([head[1]] if rules.get("table_rule_line") else [])
    return "\n".join(["Tabelle 1: Bedarf", *shown, *rows])


def inputs_of(merged, pdf_dir):
    return {(i.embedding_type, i.item_id): i for i in
            build_embedding_inputs(merged, "plan", pdf_dir, log_counts=False)}


def with_sentence(merged, pdf_dir, asker):
    """The document after the sentences were asked for and read back."""
    context.ask_document(merged, pdf_dir, asker, salt="s")
    return context.attach(copy.deepcopy(merged), pdf_dir, salt="s")


# -- 1. the sentence stands before the text --------------------------------

def test_the_text_and_the_picture_text_of_a_table_and_a_figure_start_with_the_sentence(folder):
    merged = with_sentence(doc(), folder, Asker())
    got = inputs_of(merged, folder)
    assert {key for key in got if key[1]} == {
        ("table_text", "p1_tbl0"), ("table_vl", "p1_tbl0"),
        ("figure_text", "p1_fig0"), ("figure_vl", "p1_fig0")}
    for kind, name, caption in (("table", "p1_tbl0", "Tabelle 1: Bedarf"),
                                ("figure", "p1_fig0", "Abbildung 1: Verlauf")):
        sentence = f"Satz zu {kind} {caption}\n"
        for suffix in ("text", "vl"):
            text = got[(f"{kind}_{suffix}", name)].text
            assert text.startswith(sentence + caption)
        assert got[(f"{kind}_vl", name)].image.endswith(f"{name}.png")


def test_a_document_without_a_sentence_is_embedded_as_before(folder):
    got = inputs_of(doc(), folder)
    assert got[("table_text", "p1_tbl0")].text == table_text("| 2025 | 10 |")
    assert got[("figure_vl", "p1_fig0")].text == "Abbildung 1: Verlauf\nLinie von 10 auf 8 GWh"


def test_a_sentence_of_an_item_with_no_text_is_not_embedded_alone(folder):
    merged = doc()
    merged["sections"][0]["figures"][0].update(caption="", description="")
    merged["sections"][0]["figures"][0]["context_sentence"] = "Ein Satz."
    got = inputs_of(merged, folder)
    assert ("figure_text", "p1_fig0") not in got
    assert got[("figure_vl", "p1_fig0")].text == ""


# -- 2. asked once, kept ---------------------------------------------------

def test_the_model_is_asked_once_for_each_table_and_figure_and_then_nothing(folder):
    asker = Asker()
    first = context.ask_document(doc(), folder, asker, salt="s")
    assert first == {"asked": 2, "answered": 2, "kept": 0, "dropped": 0,
                     "too_long": 0}
    assert sorted(r["kind"] for r in asker.requests) == ["figure", "table"]
    assert (folder / CONTEXT_SENTENCES_JSON).is_file()

    again = context.ask_document(doc(), folder, asker, salt="s")
    assert again == {"asked": 0, "answered": 0, "kept": 2, "dropped": 0,
                     "too_long": 0}
    assert len(asker.requests) == 2


def test_the_request_shows_caption_whole_text_and_heading_of_the_section(folder):
    asker = Asker()
    context.ask_document(doc(), folder, asker, salt="s")
    request = next(r for r in asker.requests if r["kind"] == "table")
    assert request == {"kind": "table", "section_heading": "Endenergiebedarf",
                       "caption": "Tabelle 1: Bedarf",
                       "text": HEAD + "\n| 2025 | 10 |"}


@pytest.mark.parametrize("change", ["caption", "head", "heading"])
def test_a_changed_caption_head_or_heading_asks_again_and_only_for_that_item(folder, change):
    asker = Asker()
    context.ask_document(doc(), folder, asker, salt="s")
    changed = doc()
    section_ = changed["sections"][0]
    if change == "caption":
        section_["tables"][0]["caption"] = "Tabelle 1: Verbrauch"
    elif change == "head":
        section_["tables"][0]["markdown"] += "\n| 2030 | 9 |"
    else:
        section_["title"] = "Wärmebedarf"
    asked_before = len(asker.requests)

    counts = context.ask_document(changed, folder, asker, salt="s")

    # A new heading changes what both items show; a caption or a head, one.
    expected = 2 if change == "heading" else 1
    assert counts["asked"] == expected and len(asker.requests) == asked_before + expected
    if change != "heading":
        assert asker.requests[-1]["kind"] == "table"
    # What is kept is what the document shows now: the old sentences are gone.
    kept = json.loads((folder / CONTEXT_SENTENCES_JSON).read_text(encoding="utf-8"))
    assert len(kept["sentences"]) == 2


def test_a_changed_prompt_asks_again(folder):
    asker = Asker()
    context.ask_document(doc(), folder, asker, salt="one")
    context.ask_document(doc(), folder, asker, salt="two")
    assert len(asker.requests) == 4


def test_a_stale_sentence_is_not_attached(folder):
    asker = Asker()
    context.ask_document(doc(), folder, asker, salt="s")
    changed = doc()
    changed["sections"][0]["tables"][0]["caption"] = "Tabelle 1: Verbrauch"
    attached = context.attach(changed, folder, salt="s")
    assert "context_sentence" not in attached["sections"][0]["tables"][0]
    assert "context_sentence" in attached["sections"][0]["figures"][0]


# -- 3. off -----------------------------------------------------------------

def test_off_nothing_is_asked_and_nothing_is_written(tmp_path, folder):
    (folder / DOCUMENT_JSON).write_text(json.dumps(doc()), encoding="utf-8")
    asker = Asker()
    with rules.overlaid(context_sentence=False):
        assert context.ask_all(tmp_path, asker) == {}
    assert asker.requests == []
    assert not (folder / CONTEXT_SENTENCES_JSON).exists()


def test_off_what_is_kept_is_not_read_and_the_inputs_are_as_before(folder):
    (folder / DOCUMENT_JSON).write_text(json.dumps(doc()), encoding="utf-8")
    context.ask_document(doc(), folder, Asker(), salt=context.prompt_salt())
    with rules.overlaid(context_sentence=False):
        merged = context.load_document(folder)
    assert merged == doc()
    got = inputs_of(merged, folder)
    assert got[("table_vl", "p1_tbl0")].text == table_text("| 2025 | 10 |")
    with rules.overlaid(context_sentence=True):
        on = inputs_of(context.load_document(folder), folder)
    assert on[("table_vl", "p1_tbl0")].text.startswith("Satz zu table")


def test_on_ask_all_asks_each_document(tmp_path, folder):
    (folder / DOCUMENT_JSON).write_text(json.dumps(doc()), encoding="utf-8")
    asker = Asker()
    with rules.overlaid(context_sentence=True):
        total = context.ask_all(tmp_path, asker)
    assert total == {"asked": 2, "answered": 2, "kept": 0, "dropped": 0,
                     "too_long": 0}


# -- 4. an answer out of form ------------------------------------------------

class Client:
    """A chat client that answers with *contents* in turn."""

    def __init__(self, contents):
        self.contents = list(contents)
        self.messages = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.messages.append(kwargs["messages"])
        content = self.contents.pop(0)
        choice = SimpleNamespace(message=SimpleNamespace(content=content),
                                 finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=None)


def ask_with(client):
    return context.ask_model(client, {"kind": "table"}, system="s", model="m",
                             temperature=0.1, max_tokens=400,
                             max_retries=MAX_RETRIES, wait=lambda s: None)


def test_an_answer_out_of_form_is_asked_again_with_its_cause():
    client = Client(["Hier ist der Satz.", '{"other": "x"}', '{"sentence": "Ein Satz."}'])
    assert ask_with(client) == "Ein Satz."
    assert len(client.messages) == 3
    # The second request names what was wrong with the first answer.
    assert client.messages[1][-2] == {"role": "assistant", "content": "Hier ist der Satz."}
    assert client.messages[1][-1]["content"]


def test_an_answer_out_of_form_every_time_is_asked_as_often_as_the_other_stages_and_gives_none():
    client = Client(['{"sentence": ""}', "kein Objekt", '{"sentence": 3}', "[]"] * 2)
    assert ask_with(client) is None
    assert len(client.messages) == MAX_RETRIES


def test_an_answer_out_of_form_is_never_embedded_and_is_asked_again_next_time(folder):
    asker = Asker(reply=None)
    asker.reply = ""          # the model gave nothing usable
    counts = context.ask_document(doc(), folder, asker, salt="s")
    assert counts == {"asked": 2, "answered": 0, "kept": 0, "dropped": 2,
                      "too_long": 0}
    merged = context.attach(doc(), folder, salt="s")
    got = inputs_of(merged, folder)
    assert got[("table_text", "p1_tbl0")].text == table_text("| 2025 | 10 |")
    again = Asker()
    assert context.ask_document(doc(), folder, again, salt="s")["asked"] == 2


# -- 5. the sync step -------------------------------------------------------

def synced_corpus(tmp_path):
    base = {"sections": [section(
        "Wärme", "Bedarf [p1_tbl0]",
        tables=[table("p1_tbl0", "Tabelle 1: Bedarf", HEAD + "\n| 2025 | 10 |")])]}
    corpus = Corpus(tmp_path, base)
    return corpus, base


def keep_sentence(corpus, base, text):
    salt = context.prompt_salt()
    item = base["sections"][0]["tables"][0]
    request = context.shown("table", base["sections"][0], item)
    sentences = {context.key_of(request, salt): text}
    context.write_store(corpus.dir, sentences)


def test_sync_takes_a_new_sentence_for_a_changed_entry_and_an_unchanged_one_for_an_unchanged_entry(tmp_path):
    corpus, base = synced_corpus(tmp_path)
    ids = corpus.ids()
    keep_sentence(corpus, base, "Bedarf in MWh fuer 2025.")

    with rules.overlaid(context_sentence=True):
        first = corpus.sync()
    # Only the table's text vector changed; the section's and the title's stay.
    assert dict(first.dropped) == {"table_text": 1}
    assert corpus.held() == set(ids.values()) - {ids[("table_text", 0, "p1_tbl0", 0, 0)]}
    with sqlite3.connect(corpus.db) as conn:
        assert conn.execute("SELECT context_sentence FROM Tables").fetchone() == (
            "Bedarf in MWh fuer 2025.",)

    # The embed step gives the table a vector again; nothing changed since.
    with rules.overlaid(context_sentence=True):
        assert corpus.sync(dry_run=True).dropped == {}


def test_sync_takes_a_changed_sentence_for_a_changed_entry(tmp_path):
    corpus, base = synced_corpus(tmp_path)
    keep_sentence(corpus, base, "Erster Satz.")
    with rules.overlaid(context_sentence=True):
        corpus.sync()
    # Give the table's vector back, as the embed step does.
    from docpipe.chunking.database import EmbeddingWriter
    with EmbeddingWriter(corpus.db) as writer:
        writer.write("plan", [("table_text", 0, "p1_tbl0", 900)])
    keep_sentence(corpus, base, "Zweiter Satz.")

    with rules.overlaid(context_sentence=True):
        report = corpus.sync()
    assert dict(report.dropped) == {"table_text": 1}


def test_sync_with_the_rule_off_takes_a_kept_sentence_for_nothing(tmp_path):
    corpus, base = synced_corpus(tmp_path)
    keep_sentence(corpus, base, "Ein Satz.")
    with rules.overlaid(context_sentence=False):
        report = corpus.sync()
    assert report.changed == [] and not report.dropped


# -- 6. nothing is cut: the whole text, or parts that each carry its lines --

ROWS = [f"| {2000 + n} | {n} |" for n in range(40)]


def long_table():
    merged = doc()
    sec = merged["sections"][0]
    sec["tables"][0]["markdown"] = HEAD + "\n" + "\n".join(ROWS)
    return merged, sec, sec["tables"][0]


def small_window(request):
    """A window that holds the head and a few rows of the long table."""
    return len(request["text"].encode("utf-8")) <= 160


def test_the_request_shows_the_whole_text_of_a_table_however_long():
    _merged, sec, item = long_table()
    many = "\n".join(f"| {n} | {n} |" for n in range(2000))
    item["markdown"] = HEAD + "\n" + many
    got = context.shown("table", sec, item)
    assert got["text"] == HEAD + "\n" + many
    assert context.requests_of("table", sec, item) == [(got, None, None)]


def test_a_table_over_the_window_is_asked_in_parts_each_with_its_caption_heading_and_head():
    _merged, sec, item = long_table()
    asked = context.requests_of("table", sec, item, small_window)
    assert len(asked) > 1
    seen = []
    for request, first, last in asked:
        assert small_window(request)
        assert request["caption"] == "Tabelle 1: Bedarf"
        assert request["section_heading"] == "Endenergiebedarf"
        assert "| Jahr | MWh |" in request["text"]          # the head, carried
        assert first is not None and last is not None and first <= last
        seen += [row for row in ROWS if row in request["text"]]
    assert seen == ROWS                                     # every row once


def test_a_table_whose_head_alone_does_not_fit_is_named_never_cut():
    from docpipe.window import TooLong
    _merged, sec, item = long_table()
    with pytest.raises(TooLong):
        context.requests_of("table", sec, item,
                            lambda request: len(request["text"]) <= 10)


def test_each_part_has_its_sentence_and_the_index_puts_it_before_its_rows(folder):
    merged, _sec, _item = long_table()

    def ask(request):
        first = next((row for row in ROWS if row in request["text"]),
                     request["caption"])
        return f"Satz ab {first}"

    asked = context.requests_of("table", merged["sections"][0],
                                merged["sections"][0]["tables"][0],
                                small_window)
    counts = context.ask_document(merged, folder, ask, salt="s",
                                  fits=small_window)
    assert counts["asked"] == len(asked) + 1             # the parts, the figure
    item = context.attach(copy.deepcopy(merged), folder,
                          salt="s")["sections"][0]["tables"][0]
    said = context.sentences_of(item["context_sentence"])
    assert len(said) == len(asked)
    for (request, first, last), (s_first, s_last, sentence) in zip(asked, said):
        assert (s_first, s_last) == (first, last)
        assert sentence == ask(request)
        assert context.lead_of(item, first, last) == sentence + "\n"
    # The same parts again: nothing is asked.
    again = context.ask_document(merged, folder, ask, salt="s",
                                 fits=small_window)
    assert again["asked"] == 0 and again["kept"] == 2


def test_a_reply_whose_echo_does_not_fit_asks_anew_with_its_cause_only():
    broken = '{"sentence": "' + "x " * 500
    client = Client([broken, '{"sentence": "Ein Satz."}'])
    # The reply alone is over 1,000 characters: its echo does not fit,
    # the request anew with one sentence does.
    narrow = lambda request: (not isinstance(request, list)
                              or len(json.dumps(request)) <= 1000)
    got = context.ask_model(client, {"kind": "table"}, system="s", model="m",
                            temperature=0.1, max_tokens=400,
                            max_retries=MAX_RETRIES, wait=lambda s: None,
                            fits=narrow)
    assert got == "Ein Satz."
    second = client.messages[1]
    assert [m["role"] for m in second] == ["system", "user"]
    assert "x x x" not in json.dumps(second)
    assert "(syntax)" in second[-1]["content"]
    # The same reply with room: it goes back whole, as the model's turn.
    client = Client([broken, '{"sentence": "Ein Satz."}'])
    assert ask_with(client) == "Ein Satz."
    assert client.messages[1][-2] == {"role": "assistant", "content": broken}


# -- 7. an item that cannot be shown whole is named, the run goes on --------

def no_table_fits(request):
    """A window in which no table text fits, but a figure does."""
    return request["kind"] == "figure" or len(request["text"]) <= 10


def rows_doc():
    return long_table()[0]


def test_an_item_that_cannot_be_shown_is_named_left_out_and_the_run_goes_on(
        tmp_path, caplog):
    make = rows_doc
    for name in ("plan", "plan2"):
        pdf_dir = tmp_path / name
        (pdf_dir / "images").mkdir(parents=True)
        (pdf_dir / DOCUMENT_JSON).parent.mkdir(parents=True, exist_ok=True)
        (pdf_dir / DOCUMENT_JSON).write_text(json.dumps(make()),
                                             encoding="utf-8")
    asker = Asker()
    with rules.overlaid(context_sentence=True), \
            caplog.at_level("ERROR", logger=context.log.name):
        total = context.ask_all(tmp_path, asker, no_table_fits)
    # Both documents were done: the figure of each was asked, the table of
    # each was named in the log, counted as too long (a table, not a
    # request), and nothing was sent.
    assert [r["kind"] for r in asker.requests] == ["figure", "figure"]
    assert total == {"asked": 2, "answered": 2, "kept": 0, "dropped": 0,
                     "too_long": 2}
    named = [r.getMessage() for r in caplog.records]
    assert len(named) == 2 and all("p1_tbl0" in m and "plan" in m
                                   for m in named)
    for name in ("plan", "plan2"):
        merged = context.attach(make(), tmp_path / name,
                                salt=context.prompt_salt())
        sec = merged["sections"][0]
        assert "context_sentence" not in sec["tables"][0]
        assert "context_sentence" in sec["figures"][0]


def test_a_piece_of_carried_lines_only_that_do_not_fit_is_not_an_empty_list():
    # A piece with no own line whose carried lines (a title, a head) do not
    # fit: never an empty list, which asked nothing and said nothing.
    from docpipe.window import TooLong, split
    with pytest.raises(TooLong):
        split([], lambda numbers, replaced: "Tabelle 1\n| Jahr | MWh |",
              lambda n: "", lambda text: False, lambda line: [line],
              "table p1_tbl0")


def test_every_row_of_a_table_in_parts_gets_the_sentence_of_the_part_that_holds_it(folder):
    merged, sec, item = long_table()
    asked = context.requests_of("table", sec, item, small_window)
    context.ask_document(merged, folder,
                         lambda r: "Satz ab " + next(
                             (row for row in ROWS if row in r["text"]), "?"),
                         salt="s", fits=small_window)
    got = context.attach(copy.deepcopy(merged), folder,
                         salt="s")["sections"][0]["tables"][0]
    for request, first, last in asked:
        for n in range(first, last + 1):
            assert context.lead_of(got, n, n) == \
                context.lead_of(got, first, last)
            assert context.lead_of(got, n, n) != ""
    # An entry of carried lines only takes the first part's sentence.
    assert context.lead_of(got, None, None) == \
        context.lead_of(got, asked[0][1], asked[0][2])
    # A row no kept part holds (its part was not answered) has no sentence,
    # never another part's.
    dropped = {**got, "context_sentence": got["context_sentence"][1:]}
    assert context.lead_of(dropped, asked[0][1], asked[0][1]) == ""
