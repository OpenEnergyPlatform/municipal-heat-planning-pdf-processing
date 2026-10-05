"""The pages of the chat app, run against a stand-in for Streamlit.

Streamlit is not part of the test installation, and the pages are the one
place where a typo only shows on a screen. So a small stand-in plays its
part here: every widget returns what a test says a person chose, and
everything put on the page is noted.

What is promised, sentence by sentence:

  * the review page is offered only where a harvest is configured;
  * a decision is appended for every field that was decided AND under the
    reviewer's name AND for no field left open AND the next row comes;
  * nothing is saved without a name AND nothing when no field was decided;
  * a field somebody decided before is not asked again;
  * a skipped row is not shown again in this session AND nothing is written;
  * a missing value and a document read whole are appended as such;
  * what was typed for a number is a number;
  * a question to the whole corpus is asked with no document AND shows the
    harvest's values before the answer AND keeps its own conversation;
  * a question to one document asks that document's harvest;
  * a question that is only an image does not ask the harvest;
  * the chat offers the search scopes the index holds vectors of AND no
    other, in the order of the fixed list;
  * an index built with another model than the one that embeds the questions
    is said so, in the profile's words, above a chat that still answers;
  * a question embedded by one model is never answered from the cached vector
    of another;
  * a citation shows the page it stands on, drawn from the PDF under the PDF
    folder with its quote marked, AND a download of that PDF; where the quote
    cannot be located the page is shown unmarked AND says so in the profile's
    words; where the page cannot be shown the expander says what is missing;
  * a link into an external viewer is shown only where a prefix is
    configured, and a fresh install configures none;
  * a chat with no profile says so in one line, naming that it runs on the
    built-in profile AND how to give another.
"""
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

from docpipe import settings
from docpipe.app import pdf_link
from docpipe.app.pdf_link import PageNotRendered
from docpipe.extraction import fields, gold
from docpipe.extraction.verify import TIER_TEXT
from docpipe.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docpipe" / "app" / "app.py"


class Rerun(Exception):
    pass


class Stop(Exception):
    pass


class Block:
    """A part of the page that is entered: the sidebar, a message, an
    expander. Entered as often as the app likes. An expander has its label,
    and what is put on the page while it is entered is noted under it."""

    def __init__(self, page, label=None):
        self.page = page
        self.label = label

    def __enter__(self):
        if self.label is not None:
            self.page.entered.append(self.label)
        return self.page

    def __exit__(self, *exc):
        if self.label is not None:
            self.page.entered.pop()
        return False


class Page:
    """What Streamlit is to the app: widgets that answer, a page that is
    written on."""

    def __init__(self):
        self.session_state = {}
        self.said = []              # (how, text)
        self.entered = []           # labels of the expanders entered now
        self.inside = {}            # expander label -> what was said in it
        self.links = []             # (label, url) of the link buttons
        self.downloads = []         # what each download button was given
        self.answers = {}           # label or key -> what was chosen
        self.pressed = set()        # labels of the buttons pressed
        self.sidebar = Block(self)
        self.question = None

    # ---- containers
    def _block(self, *args, **kwargs):
        return Block(self)

    def expander(self, label, **kwargs):
        self.said.append(("expander", label))
        return Block(self, label)

    chat_message = spinner = _block

    def columns(self, count):
        return [self for _ in range(count)]

    def cache_resource(self, function=None, **kwargs):
        return function if function is not None else (lambda fn: fn)

    def cache_data(self, function=None, **kwargs):
        """Streamlit's cache of data: a result is kept per arguments, so a
        page is not drawn twice and a changed argument draws it again."""
        def keep(fn):
            kept = {}

            def cached(*args):
                if args not in kept:
                    kept[args] = fn(*args)
                return kept[args]
            return cached
        return keep(function) if function is not None else keep

    # ---- what is put on the page
    def _note(self, how, text):
        self.said.append((how, text))
        for label in self.entered:
            self.inside.setdefault(label, []).append((how, text))

    def _say(how):
        def put(self, text="", *args, **kwargs):
            self._note(how, text)
        return put

    def link_button(self, label, url=None, **kwargs):
        self._note("link", label)
        self.links.append((label, url))

    def download_button(self, label, data=None, file_name=None, mime=None,
                        key=None, **kwargs):
        self._note("download", label)
        self.downloads.append({"label": label, "data": data,
                               "file_name": file_name, "mime": mime,
                               "key": key})

    title = _say("title")
    header = _say("header")
    subheader = _say("subheader")
    markdown = _say("markdown")
    caption = _say("caption")
    warning = _say("warning")
    error = _say("error")
    info = _say("info")
    toast = _say("toast")
    text = _say("text")
    code = _say("code")
    json = _say("json")
    image = _say("image")
    dataframe = _say("dataframe")

    def set_page_config(self, **kwargs):
        pass

    def divider(self):
        pass

    # ---- widgets
    def _answer(self, label, key, default):
        for name in (key, label):
            if name in self.answers:
                return self.answers[name]
        return default

    def checkbox(self, label, value=False, key=None, **kwargs):
        return self._answer(label, key, value)

    def radio(self, label, options, key=None, **kwargs):
        return self._answer(label, key, options[0])

    def selectbox(self, label, options, key=None, **kwargs):
        return self._answer(label, key, options[0] if options else None)

    def multiselect(self, label, options, default=None, key=None, **kwargs):
        return self._answer(label, key, list(default or []))

    def text_input(self, label, value="", key=None, **kwargs):
        return self._answer(label, key, value)

    text_area = text_input

    def button(self, label, key=None, **kwargs):
        return label in self.pressed

    def file_uploader(self, label, **kwargs):
        return self._answer(label, None, None)

    def chat_input(self, label):
        return self.question

    def rerun(self):
        raise Rerun()

    def stop(self):
        raise Stop()

    def texts(self, how=None):
        return [text for kind, text in self.said if how in (None, kind)]


P = "energy_consumption"


def row(value=241.0, quote="| Erdgas | 241 |", year=2040):
    return {"kind": "tuple", "parameter": P, "value": value,
            "value_raw": str(value), "unit": "GWh/a", "tier": TIER_TEXT,
            "quote": quote, "provenance": {"document_id": 1, "page": 12},
            "year": year, "year_state": fields.READ}


@pytest.fixture
def page(monkeypatch):
    made = Page()
    stub = types.ModuleType("streamlit")
    for name in dir(made):
        if not name.startswith("_"):
            setattr(stub, name, getattr(made, name))
    monkeypatch.setitem(sys.modules, "streamlit", stub)
    return made


def load_app():
    spec = importlib.util.spec_from_file_location("_app_under_test", APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_harvest(tmp_path):
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    (harvest / "kassel.jsonl").write_text(
        json.dumps(row()) + "\n"
        + json.dumps(row(5.0, "| Kohle | 5 |", 2030)) + "\n",
        encoding="utf-8")
    return harvest


@pytest.fixture
def app(page, monkeypatch, tmp_path):
    """The app's module, loaded with the stand-in and a harvest of two
    values in one document."""
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    module = load_app()
    harvest = write_harvest(tmp_path)
    monkeypatch.setattr(module.config, "HARVEST_DIR", harvest)
    monkeypatch.setattr(module.config, "GOLD_PATH", tmp_path / "gold.jsonl")
    monkeypatch.setattr(module.config, "DB_PATH", None)
    monkeypatch.setattr(module.config, "PDF_URL_PREFIX", "")
    monkeypatch.setattr(module, "get_documents", lambda: {})
    module.T.update(module.wording.ui(module.WORDS_PROFILE))
    return module


def first_open(app):
    """The row the review page shows first."""
    rows = gold.harvest(app.config.HARVEST_DIR)
    return gold.queue(rows, gold.Gold.load(app.config.GOLD_PATH))[0]


def decide(app, page, document, shown, **verdicts):
    """Choose a verdict per field of the shown row, as its radios are
    keyed."""
    key = gold.row_name(document, shown)
    for field, verdict in verdicts.items():
        page.answers[f"{key}:{field}"] = app.T[f"review_{verdict}"]
    return key


# ---------------------------------------------- what the pages below replace

def test_the_app_reads_harvest_documents_and_prompt_where_it_is_told(
        page, monkeypatch, tmp_path):
    """Every page test hands the app its harvest and its documents. Here
    it reads them itself: the values with the mark of a transcribed
    document, the documents by the name their harvest file has, what the
    catalog calls them, and the prompt the harvest is asked with."""
    from docpipe.store import schema
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    module = load_app()
    database = tmp_path / "corpus.db"
    conn = schema.connect(database)
    conn.execute('INSERT INTO "Documents" ("id", "filename", '
                 '"page_text_transcribed") '
                 "VALUES (1, 'kassel.pdf', 3)")
    conn.execute('INSERT INTO "Documents" ("id", "filename", "is_current") '
                 "VALUES (2, 'older.pdf', 0)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(module.config, "DB_PATH", database)
    monkeypatch.setattr(module.config, "HARVEST_DIR", write_harvest(tmp_path))

    store, rows = module.get_values()
    assert [len(found) for found in rows.values()] == [2]
    assert len(store) == 2
    assert all("page_transcribed" in value["reasons"]
               for value in store.find(document="kassel")["values"])
    assert module.get_documents() == {"kassel": (1, "kassel.pdf"),
                                      "older": (2, "older.pdf")}
    labels = module.get_labels()
    assert set(labels) == {1, 2}            # the superseded one too
    assert labels[1].startswith("kassel")
    assert "{{" not in module.get_coordinate_prompt().text
    # no word index was built beside this database: the search says so by
    # returning none, and none is asked for where it is turned off
    assert module.get_lexical() is None
    monkeypatch.setattr(module.config, "LEXICAL", False)
    monkeypatch.setattr(module.lexical, "connect", lambda path: 1 / 0)
    assert module.get_lexical() is None

    # where no harvest is configured there is no store and nothing is read
    monkeypatch.setattr(module.config, "HARVEST_DIR", None)
    assert module.get_values() == (None, {})


# ------------------------------------------------------------------- the menu

def test_the_review_page_is_offered_only_where_there_is_a_harvest(
        app, page, monkeypatch):
    called = []
    monkeypatch.setattr(app, "chat_page", lambda: called.append("chat"))
    monkeypatch.setattr(app, "review_page", lambda: called.append("review"))
    page.answers["page"] = app.T["page_review"]
    app.main()
    assert called == ["review"]
    page.answers["page"] = app.T["page_chat"]
    app.main()
    assert called == ["review", "chat"]
    monkeypatch.setattr(app.config, "HARVEST_DIR", None)
    page.answers["page"] = app.T["page_review"]     # nobody can choose it
    app.main()
    assert called == ["review", "chat", "chat"]


# ------------------------------------------------------------------ reviewing

def test_a_decision_is_appended_for_every_field_that_was_decided(app, page):
    document, shown = first_open(app)
    key = decide(app, page, document, shown, value="correct", year="wrong")
    page.answers[f"{key}:year:expected"] = "2035"
    page.answers[f"{key}:note"] = "column header"
    page.answers[app.T["review_by"]] = "fv"
    page.pressed.add(app.T["review_save"])
    with pytest.raises(Rerun):
        app.review_page()
    written = gold.read(app.config.GOLD_PATH)
    assert {(r["field"], r["verdict"]) for r in written} == {
        ("value", "correct"), ("year", "wrong")}   # the unit was left open
    by_field = {r["field"]: r for r in written}
    assert by_field["year"]["expected"] == 2035     # a number, not "2035"
    assert all(r["by"] == "fv" and r["note"] == "column header"
               and r["document"] == "kassel" for r in written)
    assert (app.T["review_saved"].format(n=2)) in page.texts("toast")
    held = gold.Gold.load(app.config.GOLD_PATH)
    assert held.verdict(document, shown, "value") == gold.CORRECT


def test_a_field_decided_before_is_not_asked_again(app, page):
    document, shown = first_open(app)
    gold.decide(app.config.GOLD_PATH, document, shown, "value", gold.CORRECT)
    page.answers[app.T["review_by"]] = "fv"
    app.review_page()
    asked = [text for kind, text in page.said if kind == "markdown"]
    radios = []
    original = page.radio
    page.radio = lambda label, options, **kw: (radios.append(label),
                                               original(label, options,
                                                        **kw))[1]
    sys.modules["streamlit"].radio = page.radio
    app.review_page()
    assert not [label for label in radios if "value" in label.split(":")[0]
                and "241" in label]
    assert any("year" in label for label in radios)
    assert asked                                    # and the row is shown


def test_nothing_is_saved_without_a_name(app, page):
    document, shown = first_open(app)
    decide(app, page, document, shown, value="correct")
    page.pressed.add(app.T["review_save"])
    app.review_page()
    assert app.T["review_by_missing"] in page.texts("error")
    assert not app.config.GOLD_PATH.exists()


def test_nothing_is_saved_when_no_field_was_decided(app, page):
    page.answers[app.T["review_by"]] = "fv"
    page.pressed.add(app.T["review_save"])
    app.review_page()
    assert app.T["review_nothing_decided"] in page.texts("warning")
    assert not app.config.GOLD_PATH.exists()


def test_a_skipped_row_is_not_shown_again_in_this_session(app, page):
    document, shown = first_open(app)
    page.answers[app.T["review_by"]] = "fv"
    page.pressed.add(app.T["review_skip"])
    with pytest.raises(Rerun):
        app.review_page()
    assert not app.config.GOLD_PATH.exists()
    page.pressed.clear()
    page.said.clear()
    app.review_page()
    quotes = [text for text in page.texts("markdown") if text.startswith(">")]
    assert quotes and shown["quote"] not in quotes[0]
    assert app.T["review_progress"].format(open=1) in page.texts("caption")


def test_when_nothing_is_open_the_page_says_so(app, page):
    rows = gold.harvest(app.config.HARVEST_DIR)
    for document, entries in rows.items():
        for entry in entries:
            for field in gold.fields_of(entry):
                gold.decide(app.config.GOLD_PATH, document, entry, field,
                            gold.CORRECT)
    app.review_page()
    assert app.T["review_none_open"] in page.texts("info")


def test_a_missing_value_is_appended_as_one(app, page):
    page.answers.update({
        app.T["review_by"]: "fv", "missing:document": "kassel",
        "missing:parameter": P, "missing:value": "88,5",
        "missing:unit": "GWh/a", "missing:quote": "Bedarf 88,5 GWh",
        "missing:page": "14"})
    page.session_state.update({"missing:value": "88,5",
                               "missing:quote": "Bedarf 88,5 GWh",
                               "missing:document": "kassel"})
    page.pressed.add(app.T["review_missing_save"])
    with pytest.raises(Rerun):
        app.review_page()
    # the form is empty for the next value; which document stays chosen
    assert set(page.session_state) & {"missing:value", "missing:quote",
                                      "missing:document"} \
        == {"missing:document"}
    (record,) = [r for r in gold.read(app.config.GOLD_PATH)
                 if r["kind"] == gold.MISSING]
    assert (record["document"], record["parameter"], record["value"]) == (
        "kassel", P, 88.5)
    assert (record["unit"], record["quote"], record["page"]) == (
        "GWh/a", "Bedarf 88,5 GWh", 14)
    assert record["by"] == "fv"


def test_a_missing_value_needs_its_value(app, page):
    page.answers.update({app.T["review_by"]: "fv",
                         "missing:document": "kassel",
                         "missing:parameter": P})
    page.pressed.add(app.T["review_missing_save"])
    app.review_page()
    assert app.T["review_missing_needs"] in page.texts("warning")
    assert not app.config.GOLD_PATH.exists()


@pytest.mark.parametrize("chosen, parameter", [(P, P), (None, None)])
def test_a_document_read_whole_is_appended_as_one(app, page, chosen,
                                                  parameter):
    page.answers.update({app.T["review_by"]: "fv",
                         "checked:document": "kassel"})
    page.answers["checked:parameter"] = chosen or app.T["review_checked_all"]
    page.pressed.add(app.T["review_checked_save"])
    app.review_page()
    (record,) = gold.read(app.config.GOLD_PATH)
    assert record["kind"] == gold.CHECKED
    assert (record["document"], record["parameter"]) == ("kassel", parameter)
    assert gold.Gold.load(app.config.GOLD_PATH).is_checked("kassel", P)


def test_without_a_harvest_the_review_page_says_so(app, page, monkeypatch):
    monkeypatch.setattr(app.config, "HARVEST_DIR", None)
    app.review_page()
    assert app.T["review_no_harvest"] in page.texts("warning")


@pytest.mark.parametrize("text, like, typed", [
    ("2035", 2040, 2035), ("88,5", 1.0, 88.5), ("88.5", 1.0, 88.5),
    ("2035", 1.0, 2035.0), ("soon", 2040, "soon"), ("gas", "coal", "gas"),
    ("  ", 2040, None), ("12", "text", "12"), ("1", True, "1"),
    ("1,234.5", 1.0, 1234.5), ("1,234", 1.0, 1234.0), ("-3.5", 1.0, -3.5),
    ("\u22123.5", 1.0, -3.5), ("+12", 5, 12), ("-2", 5, -2),
    # not a number of a document: kept as what was typed, never a float
    ("inf", 1.0, "inf"), ("nan", 1.0, "nan"), ("1e5", 1.0, "1e5"),
    ("-", 1.0, "-"),
])
def test_what_was_typed_for_a_number_is_a_number(app, text, like, typed):
    got = app._typed(text, like)
    assert got == typed and type(got) is type(typed)


@pytest.mark.parametrize("text, like, typed", [
    ("1.234,5", 1.0, 1234.5), ("1.234", 1.0, 1234.0), ("2.030", 2040, 2030),
    ("88,5", 1.0, 88.5), ("1.234.567", 1.0, 1234567.0),
    ("-1.234,5", 1.0, -1234.5),
])
def test_a_typed_number_is_read_as_the_profiles_documents_write_one(
        app, monkeypatch, text, like, typed):
    """Where the documents write a decimal comma, a point groups
    thousands: "2.030" is the year 2030 and not 2.03."""
    from docpipe.profile import load_profile
    monkeypatch.setattr(app, "WORDS_PROFILE", load_profile("kwp"))
    got = app._typed(text, like)
    assert got == typed and type(got) is type(typed)


def test_two_rows_of_one_quote_and_value_are_decided_one_by_one(app, page):
    """A table row that prints the same number under two years. Deciding
    the one leaves the other open in every field, under keys of its own:
    what was chosen for the first is not chosen for the second."""
    quote = "| Kohle | 0 | 0 |"
    (app.config.HARVEST_DIR / "kassel.jsonl").write_text(
        json.dumps(row(0.0, quote, 2030)) + "\n"
        + json.dumps(row(0.0, quote, 2040)) + "\n", encoding="utf-8")
    page.answers[app.T["review_by"]] = "fv"
    document, shown = first_open(app)
    decide(app, page, document, shown, value="correct", unit="correct",
           year="correct")
    page.pressed.add(app.T["review_save"])
    with pytest.raises(Rerun):
        app.review_page()
    assert len(gold.read(app.config.GOLD_PATH)) == 3
    page.said.clear()
    _document, other = first_open(app)
    assert other["year"] != shown["year"]
    app.review_page()               # save is still pressed, nothing chosen
    assert app.T["review_progress"].format(open=1) in page.texts("caption")
    assert app.T["review_nothing_decided"] in page.texts("warning")
    assert len(gold.read(app.config.GOLD_PATH)) == 3


# ------------------------------------------------------------------- the chat

class Catalog:
    document_noun = "document"
    facets = ()

    def entries(self, conn, include_superseded=False):
        return [types.SimpleNamespace(id=1, label="Kassel 2024", facets={},
                                      detail=[])]


ALL_TYPES = ("section_title", "section_text", "table_text", "table_vl",
             "figure_text", "figure_vl")


@pytest.fixture
def chat(app, page, monkeypatch, tmp_path):
    from docpipe.store import schema
    asked = {"turns": [], "values": []}
    # a database whose index holds all six kinds of vector and records no
    # model: the scopes and the notice are read from it, not stood in for
    held = schema.connect(tmp_path / "corpus.db")
    held.executemany(
        'INSERT INTO "Embeddings" ("faiss_id", "embedding_type", '
        '"owner_kind", "owner_id") VALUES (?, ?, ?, 1)',
        [(n, kind, kind.split("_")[0]) for n, kind in enumerate(ALL_TYPES)])
    held.commit()
    asked["db"] = held

    def turn(task, image_bytes, image_only, document_id, scopes,
             as_json=False, history=None):
        asked["turns"].append({"task": task, "document": document_id,
                               "history": list(history or []),
                               "scopes": list(scopes)})
        return {"answer": "The demand is 241 GWh.", "answer_text": None,
                "citations": [], "n_hits": 3, "as_json": False,
                "phrase": "demand", "examined": [["section", 4]]}

    def values(task, document_id):
        asked["values"].append(document_id)
        return {"route": "values", "total": 3, "values": [{
            "id": "x", "document": "kassel", "parameter": P,
            "label": "Final energy consumption", "value": 241.0,
            "unit": "GWh/a", "coordinates": {}, "quote": "| Erdgas | 241 |",
            "page": 12, "level": "B", "reasons": []}]}

    monkeypatch.setattr(app, "get_catalog", lambda: Catalog())
    monkeypatch.setattr(app, "get_db", lambda: held)
    monkeypatch.setattr(app, "run_turn", turn)
    monkeypatch.setattr(app, "run_values_turn", values)
    return asked


def test_a_question_to_the_whole_corpus(app, page, chat):
    page.answers[app.T["whole_corpus"]] = True
    page.question = "How much gas?"
    app.chat_page()
    assert chat["turns"][0]["document"] is None
    assert chat["values"] == [None]
    said = page.texts("markdown")
    heading = said.index(f"**{app.T['values_heading']}**")
    answer = said.index("The demand is 241 GWh.")
    assert heading < answer                 # the harvest's values come first
    line = said[heading + 1]
    assert "241.0 GWh/a" in line and "kassel, p. 12" in line
    assert app.T["values_level"].format(level="B") in line
    assert app.T["values_more"].format(shown=1, total=3) \
        in page.texts("caption")
    assert app.T["anchor"].format(phrase="demand") in page.texts("caption")
    # asked again: the corpus has a conversation of its own
    page.question = "And coal?"
    app.chat_page()
    assert [turn["task"] for turn in chat["turns"][1]["history"]] \
        == ["How much gas?"]
    assert page.session_state["doc_ids"] == ["corpus"]


def test_a_question_to_one_document_asks_that_documents_harvest(
        app, page, chat):
    page.question = "How much gas?"
    app.chat_page()
    assert chat["turns"][0]["document"] == 1
    assert chat["values"] == [1]
    assert page.session_state["doc_ids"] == [1]
    assert set(page.session_state["turns_by_doc"]) == {1}


def test_a_question_that_is_only_an_image_does_not_ask_the_harvest(
        app, page, chat):
    page.answers[app.T["image_upload"]] = types.SimpleNamespace(
        getvalue=lambda: b"png")
    page.answers[app.T["image_mode"]] = app.T["image_only"]
    page.question = "What is this?"
    app.chat_page()
    assert chat["values"] == [] and len(chat["turns"]) == 1
    assert f"**{app.T['values_heading']}**" not in page.texts("markdown")


def test_an_answer_nothing_backs_says_so_in_the_profiles_words(
        app, page, chat, monkeypatch):
    monkeypatch.setattr(app, "run_values_turn", lambda task, document: None)
    monkeypatch.setattr(app, "run_turn", lambda *a, **k: {
        "answer": None, "citations": [], "n_hits": 0, "as_json": False,
        "phrase": None})
    page.question = "Anything?"
    app.chat_page()
    assert app.T["no_hits"] in page.texts("markdown")
    turns = page.session_state["turns_by_doc"][1]
    assert turns[0]["answer"] == app.T["no_answer_context"]


def test_without_a_question_nothing_is_asked(app, page, chat):
    app.chat_page()
    assert chat["turns"] == [] and chat["values"] == []


def test_the_harvests_answer_for_a_document_is_asked_by_its_file_name(
        app, monkeypatch):
    seen = {}

    def answer(task, store, **more):
        seen.update(more, store=store)
        return {"route": "rag", "reason": "no_parameter"}

    monkeypatch.setattr(app, "get_values", lambda: ("the store", {}))
    monkeypatch.setattr(app, "get_db", lambda: None)
    monkeypatch.setattr(app.db, "document_filename",
                        lambda conn, document: "kassel_2024.pdf")
    monkeypatch.setattr(app.values_route, "answer_from_values", answer)
    assert app.run_values_turn("How much?", 7) is None   # nothing held
    assert seen["document"] == "kassel_2024" and seen["store"] == "the store"
    assert seen["limit"] == app.config.VALUES_LIMIT
    app.run_values_turn("How much?", None)
    assert seen["document"] is None
    monkeypatch.setattr(app, "get_values", lambda: (None, {}))
    seen.clear()
    assert app.run_values_turn("How much?", 7) is None and not seen


# ------------------------------------------- what the index holds, and its model

def _options_offered(app, page):
    """The options of the scope picker, as the app handed them to it."""
    offered = []
    original = page.multiselect

    def multiselect(label, options, default=None, key=None, **kwargs):
        if label == app.T["scopes"]:
            offered.append((list(options), list(default or [])))
        return original(label, options, default=default, key=key, **kwargs)

    page.multiselect = multiselect
    sys.modules["streamlit"].multiselect = multiselect
    return offered


def test_the_chat_offers_every_scope_of_an_index_that_holds_every_type(
        app, page, chat):
    offered = _options_offered(app, page)
    page.question = "How much gas?"
    app.chat_page()
    assert offered == [(app.config.ALL_SCOPES, app.config.ALL_SCOPES)]
    assert chat["turns"][0]["scopes"] == app.config.ALL_SCOPES


def test_the_chat_offers_no_scope_over_pictures_where_the_index_has_none(
        app, page, chat):
    chat["db"].execute("DELETE FROM Embeddings WHERE embedding_type "
                       "LIKE '%_vl'")
    chat["db"].commit()
    offered = _options_offered(app, page)
    page.question = "How much gas?"
    app.chat_page()
    config = app.config
    text_only = [config.SCOPE_HEADINGS, config.SCOPE_TEXT,
                 config.SCOPE_TABLES_TEXT, config.SCOPE_FIGURES_TEXT]
    assert offered == [(text_only, text_only)]
    assert chat["turns"][0]["scopes"] == text_only      # and so is the search


def test_an_index_built_with_another_model_is_said_so_and_still_answers(
        app, page, chat, monkeypatch):
    from docpipe.store import schema
    schema.set_meta(chat["db"], {"embedding/model": "built-with"})
    monkeypatch.setattr(app.config, "EMBEDDING_MODEL", "asked-with")
    page.question = "How much gas?"
    app.chat_page()
    notice = app.T["index_model_differs"].format(built="built-with",
                                                 queried="asked-with")
    assert notice in page.texts("warning")
    assert len(chat["turns"]) == 1                      # a notice, no refusal
    assert page.texts("error") == []


def test_the_notice_is_in_the_words_of_the_profile(
        app, page, chat, monkeypatch):
    from docpipe.profile import load_profile
    from docpipe.store import schema
    schema.set_meta(chat["db"], {"embedding/model": "built-with"})
    monkeypatch.setattr(app.config, "EMBEDDING_MODEL", "asked-with")
    app.T.clear()
    app.T.update(app.wording.ui(load_profile("kwp")))
    app.chat_page()
    said = page.texts("warning")
    assert len(said) == 1 and said[0].startswith("Der Index wurde mit built-with")
    app.T.clear()
    app.T.update(app.wording.ui(load_profile("scenarios")))
    page.said.clear()
    app.chat_page()
    assert page.texts("warning")[0].startswith("The index was built with")


def test_there_is_no_notice_where_the_models_are_the_same_or_none_is_recorded(
        app, page, chat, monkeypatch):
    from docpipe.store import schema
    app.chat_page()                                     # none recorded
    assert page.texts("warning") == []
    schema.set_meta(chat["db"], {"embedding/model": "the-model"})
    monkeypatch.setattr(app.config, "EMBEDDING_MODEL", "the-model")
    app.chat_page()
    assert page.texts("warning") == []


def test_a_question_is_never_answered_from_the_cached_vector_of_another_model(
        app, page, chat, monkeypatch, tmp_path):
    import docpipe.embedding as embedding
    from docpipe.embedding import config as embedding_config
    from docpipe.inference import query_cache

    class _Model:
        """One vector per model, and a count of the questions it was asked."""
        asked = []

        def embed_one(self, item):
            self.asked.append((embedding_config.EMBEDDING_MODEL, item["text"]))
            return [1.0, 0.0] if embedding_config.EMBEDDING_MODEL == "m1" \
                else [0.0, 1.0]

    cache = query_cache.connect(tmp_path / "cache.db")
    monkeypatch.setattr(app, "get_cache", lambda: cache)
    monkeypatch.setattr(app, "get_index", lambda: (None, {}))
    monkeypatch.setattr(app, "get_request_log", lambda: None)
    monkeypatch.setattr(app, "get_lexical", lambda: None)
    monkeypatch.setattr(embedding, "get_embedder", lambda: _Model())

    def ask(model):
        monkeypatch.setattr(embedding_config, "EMBEDDING_MODEL", model)
        vector, from_cache = app._corpus().embed({"text": "How much gas?"})
        return list(vector), from_cache

    assert ask("m1") == ([1.0, 0.0], False)
    assert ask("m1") == ([1.0, 0.0], True)          # the same model: a hit
    assert ask("m2") == ([0.0, 1.0], False)         # another one: embedded
    assert ask("m1") == ([1.0, 0.0], True)          # and each keeps its own
    assert _Model.asked == [("m1", "How much gas?"), ("m2", "How much gas?")]


# ------------------------------------------------------- the page a citation is on

SEGMENT = "Der Wärmebedarf beträgt 241 GWh im Jahr 2024 und sinkt bis 2040."
QUOTE = "Der Wärmebedarf beträgt 241 GWh im Jahr"
MARK = [[10.0, 20.0, 200.0, 32.0]]


def citation(**more):
    """A section's citation. Its page is 3 here and 12 in the raw segments:
    the page drawn is the one the quote is found on."""
    return {"document_id": 1, "owner_kind": "section", "owner_id": 4,
            "page_number": 3, "quote": QUOTE, "text": "", "image_path": None,
            **more}


@pytest.fixture
def cited(app, page, monkeypatch, tmp_path):
    """A document whose PDF lies in the PDF folder, and a stand-in for the
    one call that draws it: it notes what it was asked to draw."""
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    pdf = pdfs / "kassel.pdf"
    pdf.write_bytes(b"%PDF-1.7 the file as it lies on disk")
    drawn = []
    found = {"rects": MARK}

    def draw(path, number, rects=None, zoom=2.0):
        drawn.append({"path": Path(path), "page": number, "rects": rects})
        return b"PNG"

    monkeypatch.setattr(app.config, "PDF_ROOT", pdfs)
    monkeypatch.setattr(app.pdf_link, "render_page", draw)
    monkeypatch.setattr(app.pdf_link, "best_quote_rects",
                        lambda path, number, quote: found["rects"])
    monkeypatch.setattr(app, "get_db", lambda: None)
    monkeypatch.setattr(app.db, "document_filename",
                        lambda conn, document: "kassel.pdf")
    monkeypatch.setattr(app.db, "section_segments",
                        lambda conn, owner: [(12, SEGMENT)])
    monkeypatch.setattr(app.chunker, "citation_label",
                        lambda cit: "Kassel, p. 12")
    return types.SimpleNamespace(drawn=drawn, found=found, pdf=pdf)


def shown_page(app, number=12):
    return app.T["show_page"].format(page=number)


def test_a_citation_shows_its_page_with_the_quote_marked(app, page, cited):
    app._render_citation(citation())
    (drawn,) = cited.drawn
    assert drawn["path"] == cited.pdf       # from the PDF folder, nowhere else
    assert drawn["page"] == 12              # where the quote is, not page 3
    assert drawn["rects"] == MARK           # the rectangles that were located
    inside = page.inside[shown_page(app)]
    assert ("image", b"PNG") in inside      # in the citation's expander
    assert app.T["page_not_located"] not in page.texts()


def test_the_page_comes_with_a_download_of_the_pdf(app, page, cited):
    app._render_citation(citation())
    (download,) = page.downloads
    assert download["data"] == cited.pdf.read_bytes()
    assert download["file_name"] == "kassel.pdf"
    assert download["mime"] == "application/pdf"
    assert ("download", app.T["download_pdf"]) in page.inside[shown_page(app)]


def test_two_citations_of_one_document_are_two_downloads_of_their_own(
        app, page, cited):
    """Streamlit refuses two widgets of one identity in a run."""
    app._render_citation(citation())
    app._render_citation(citation(owner_id=5))
    keys = [download["key"] for download in page.downloads]
    assert len(keys) == 2 and len(set(keys)) == 2


def test_a_quote_that_cannot_be_located_leaves_the_page_unmarked_and_says_so(
        app, page, cited):
    cited.found["rects"] = None
    app._render_citation(citation())
    (drawn,) = cited.drawn
    assert not drawn["rects"]               # no rectangle was invented
    inside = page.inside[shown_page(app)]
    assert ("image", b"PNG") in inside      # the page is shown all the same
    assert ("caption", app.T["page_not_located"]) in inside


def test_what_is_not_located_is_said_in_the_profiles_words(app, page, cited):
    cited.found["rects"] = None
    app.T.clear()
    app.T.update(app.wording.ui(load_profile("kwp")))
    app._render_citation(citation())
    said = page.inside[app.T["show_page"].format(page=12)]
    assert ("caption", app.T["page_not_located"]) in said
    assert "lokalisiert" in app.T["page_not_located"]
    assert app.T["show_page"].format(page=12) == "Seite 12 anzeigen"


def test_a_table_is_shown_unmarked_without_looking_for_its_title(
        app, page, cited, monkeypatch):
    """The quote of a table or a figure is its title or a reading, not a
    passage of the page: it is not looked for there, and not reported as
    not located."""
    def never(path, number, quote):
        raise AssertionError("a table's quote is not looked for on the page")

    monkeypatch.setattr(app.pdf_link, "best_quote_rects", never)
    app._render_citation(citation(owner_kind="table", quote="Wärmebedarf"))
    (drawn,) = cited.drawn
    assert drawn["page"] == 3 and not drawn["rects"]
    assert app.T["page_not_located"] not in page.texts()


def test_a_page_whose_pdf_is_not_in_the_folder_says_what_is_missing(
        app, page, cited):
    cited.pdf.unlink()
    app._render_citation(citation())
    assert cited.drawn == []                # nothing was drawn from nothing
    said = page.inside[shown_page(app)]
    assert ("caption", app.T["page_no_file"].format(file="kassel.pdf")) in said
    assert not [how for how, _ in said if how in ("image", "download")]
    # where the server keeps its PDFs is not a reader's to see
    assert not [text for _, text in said
                if str(app.config.PDF_ROOT) in str(text)]


WHY = [(pdf_link.NOT_INSTALLED, "page_failed_library"),
       (pdf_link.NOT_OPENED, "page_failed_open"),
       (pdf_link.NO_SUCH_PAGE, "page_failed_range"),
       (pdf_link.NOT_DRAWN, "page_failed_draw")]


@pytest.mark.parametrize("reason, word", WHY)
def test_a_page_that_cannot_be_drawn_says_why_and_keeps_the_download(
        app, page, cited, monkeypatch, caplog, reason, word):
    def broken(path, number, rects=None, zoom=2.0):
        raise PageNotRendered("the file does not open (damaged)", reason)

    monkeypatch.setattr(app.pdf_link, "render_page", broken)
    with caplog.at_level("WARNING", logger=app.log.name):
        app._render_citation(citation())
    said = page.inside[shown_page(app)]
    assert ("caption", app.T[word].format(page=12)) in said
    assert "image" not in [how for how, _ in said]
    assert ("download", app.T["download_pdf"]) in said   # the file is there
    # the operator reads the cause where the reader reads the reason
    assert "page 12 of kassel.pdf" in caplog.text
    assert "the file does not open (damaged)" in caplog.text


@pytest.mark.parametrize("reason, word", WHY)
def test_what_cannot_be_drawn_is_said_in_the_profiles_language_only(
        app, page, cited, monkeypatch, reason, word):
    """The exception's message is English, for the log. A German page that
    quoted it would be half in the other language."""
    def broken(path, number, rects=None, zoom=2.0):
        raise PageNotRendered("the file does not open (damaged)", reason)

    monkeypatch.setattr(app.pdf_link, "render_page", broken)
    app.T.clear()
    app.T.update(app.wording.ui(load_profile("kwp")))
    app._render_citation(citation())
    said = [text for how, text in page.inside[shown_page(app, 12)]
            if how == "caption"]
    assert said == [app.T[word].format(page=12)]
    assert said[0].startswith("Seite 12 konnte nicht gezeigt werden")
    assert "damaged" not in said[0] and "does not open" not in said[0]


def test_a_pdf_replaced_on_disk_is_drawn_again_and_an_unchanged_one_is_not(
        app, page, cited):
    app._render_citation(citation())
    app._render_citation(citation())
    assert len(cited.drawn) == 1            # remembered while it is the same
    later = cited.pdf.stat().st_mtime + 10
    cited.pdf.write_bytes(b"%PDF-1.7 another file")
    os.utime(cited.pdf, (later, later))
    app._render_citation(citation())
    assert len(cited.drawn) == 2
    assert page.downloads[-1]["data"] == b"%PDF-1.7 another file"


def test_a_citation_of_an_unknown_document_shows_no_page(
        app, page, cited, monkeypatch):
    monkeypatch.setattr(app.db, "document_filename",
                        lambda conn, document: None)
    app._render_citation(citation())
    assert cited.drawn == [] and page.downloads == []
    assert shown_page(app) not in page.texts("expander")


def test_a_link_into_an_external_viewer_is_shown_only_where_one_is_set(
        app, page, cited, monkeypatch):
    app._render_citation(citation())
    assert page.links == []                 # no prefix: no link, no dead one
    monkeypatch.setattr(app.config, "PDF_URL_PREFIX", "/pdf")
    app._render_citation(citation())
    (label, url), = page.links
    assert label == app.T["open_pdf"].format(page=12)
    assert url.startswith("/pdf/kassel.pdf#page=12")
    # the page is drawn here as well: the link is an addition, not a swap
    assert len(page.downloads) == 2


def fresh_config():
    """The app's configuration as a process that has just started reads it."""
    spec = importlib.util.spec_from_file_location(
        "_config_under_test", ROOT / "docpipe" / "app" / "config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_fresh_install_has_no_prefix_to_link_to(monkeypatch):
    """Nothing ships that serves a viewer, so no default may point at one.
    A deployment that has one sets the names, and they are read."""
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    monkeypatch.delenv("PDF_URL_PREFIX", raising=False)
    monkeypatch.delenv("PDF_VIEWER_PREFIX", raising=False)
    assert fresh_config().PDF_URL_PREFIX == ""
    assert fresh_config().PDF_VIEWER_PREFIX == ""
    for name in ("PDF_URL_PREFIX", "PDF_VIEWER_PREFIX"):
        assert not settings.BY_ENV[name].default
    monkeypatch.setenv("PDF_URL_PREFIX", "/pdfs")
    monkeypatch.setenv("PDF_VIEWER_PREFIX", "/viewer/web")
    module = fresh_config()
    assert (module.PDF_URL_PREFIX, module.PDF_VIEWER_PREFIX) == (
        "/pdfs", "/viewer/web")


def test_the_page_is_read_from_the_profiles_pdf_folder_unless_one_is_named(
        monkeypatch, tmp_path):
    """The folder a citation's page is drawn from is the profile's, and an
    explicit INFERENCE_PDF_ROOT replaces it."""
    monkeypatch.delenv("INFERENCE_PDF_ROOT", raising=False)
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    assert fresh_config().PDF_ROOT == load_profile("default").pdf_dir
    monkeypatch.setenv("INFERENCE_PDF_ROOT", str(tmp_path))
    assert fresh_config().PDF_ROOT == tmp_path
    monkeypatch.delenv("DOCPIPE_PROFILE")
    assert fresh_config().PDF_ROOT == tmp_path        # still the named one
    monkeypatch.delenv("INFERENCE_PDF_ROOT")
    assert fresh_config().PDF_ROOT == Path("data/pdf")


# ---------------------------------------------------------- the chat, no profile

def test_a_chat_with_no_profile_says_so_in_one_line(app, page, monkeypatch):
    monkeypatch.setattr(app, "chat_page", lambda: None)
    monkeypatch.setattr(app.config, "HARVEST_DIR", None)
    assert app.config.PROFILE is None
    app.main()
    (line,) = page.texts("warning")
    assert "\n" not in line
    assert "--profile" in line and "DOCPIPE_PROFILE" in line \
        and "docpipe.toml" in line      # how to give one
    assert "`default`" in line and "any folder" in line
    # what holds now: the chat runs, and the line says on what
    assert "runs on the built-in profile" in line
    assert "cannot be answered" not in line


def test_a_chat_with_a_profile_does_not_say_it(app, page, monkeypatch):
    monkeypatch.setattr(app, "chat_page", lambda: None)
    monkeypatch.setattr(app.config, "HARVEST_DIR", None)
    monkeypatch.setattr(app.config, "PROFILE", load_profile("default"))
    app.main()
    assert page.texts("warning") == []
