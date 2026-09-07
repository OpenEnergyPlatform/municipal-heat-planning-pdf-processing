"""The title of a table, and why it decides the year of every value in it.

Stage 2 links a caption block to an item by distance. In a plan whose tables
carry a rounding footnote it links the footnote: 15 of Kassel's 89 tables were
captioned "Hinweis: Wegen der Rundung von Zahlenwerten ..." while the sentence
that names them stood unlinked in the section text, three words before their
own placeholder.

That is not cosmetic. The caption is the only line of a table a model can
quote for the table's own year, so 240 of 379 tuples from the twelve titled
target tables carried a year read off another table's caption, and 88 of
Kassel's 100 contested value identities were exactly that.

The text in these tests is verbatim from waermeplan_kassel_20260326.pdf,
section 349525, because a made-up section proves nothing about how a plan
actually prints three captions in one paragraph.

No model, no GPU.
"""
import sqlite3

import pytest

from docpipe.inference.db import (fetch_owner_content, looks_like_a_caption,
                                  resolve_title, section_item_captions)

# Three tables, three captions, one paragraph. This is the shape the resolver
# has to get right: the caption of [p86_tbl0] is the sentence between the
# placeholder before it and itself, not the first or the last in the run.
KASSEL_349525 = (
    "r 2040 ergeben sich die in den nachfolgenden Tabellen zusammengestellten "
    "Kennzahlen. Weitere Kennzahlen für die Jahre 2030, 2035, 2045 sind im "
    "Anhang beigefügt. Tabelle 17: Endenergieverbrauch der Gesamtstadt nach "
    "Sektor und Energieträger im Zielszenario 2040 [p85_tbl0] Tabelle 18: "
    "CO2-Emissionen der Gesamtstadt nach Sektor und Energieträger im "
    "Zielszenario 2040 [p86_tbl0] Tabelle 19: Energieträger im Wärmenetz und "
    "ihr Beitrag zur Gesamtendenergie im Zielszenario 2040 [p87_tbl0] T")

FOOTNOTE = ("Hinweis: Wegen der Rundung von Zahlenwerten können beim manuellen "
            "Summieren der Zellenwerte Abweichungen zur Gesamtsumme auftreten.")

# The appendix, where three tables of the SAME quantity differ only by year.
# Getting the wrong one of these three is how a 2030 figure became a 2045 one.
KASSEL_349566 = (
    "Tabelle 28: Endenergieverbrauch der Gesamtstadt nach Sektor und "
    "Energieträger 2030 [p162_tbl0] Tabelle 29: Endenergieverbrauch der "
    "Gesamtstadt nach Sektor und Energieträger 2035 [p163_tbl0] Tabelle 30: "
    "Endenergieverbrauch der Gesamtstadt nach Sektor und Energieträger 2045 "
    "[p164_tbl0]")


@pytest.mark.parametrize("block_id,number,year", [
    ("p85_tbl0", "Tabelle 17", "2040"),
    ("p86_tbl0", "Tabelle 18", "2040"),
    ("p87_tbl0", "Tabelle 19", "2040"),
])
def test_each_table_of_a_run_gets_its_own_caption(block_id, number, year):
    got = resolve_title(FOOTNOTE, KASSEL_349525, block_id)
    assert got.startswith(number), got
    assert year in got
    assert "Hinweis" not in got, "the footnote is not a caption"
    assert "[p" not in got, "and it stops before the next item"


@pytest.mark.parametrize("block_id,year", [
    ("p162_tbl0", "2030"), ("p163_tbl0", "2035"), ("p164_tbl0", "2045")])
def test_three_appendix_tables_of_one_quantity_keep_their_years_apart(
        block_id, year):
    """The measured failure: all three were read as the first one's year."""
    got = resolve_title(FOOTNOTE, KASSEL_349566, block_id)
    assert year in got
    assert sum(y in got for y in ("2030", "2035", "2045")) == 1, got


def test_a_caption_stage_two_did_link_is_never_replaced():
    """A link beats a guess. Table 10 of Kassel carries its own caption, and
    table 9's sentence is the last one standing before its placeholder because
    table 9's own placeholder is not in this section. Resolving anyway would
    move 36 tuples onto the wrong table and give them the wrong scenario."""
    linked = "Tabelle 10: Prognostizierter Nutzwärmebedarf bei erhöhter Ener"
    content = ("Tabelle 9: Prognostizierter Nutzwärmebedarf bei geringer "
               "Energieeinsparung nach Technikkatalog [p37_tbl0]")
    assert resolve_title(linked, content, "p37_tbl0") == linked, (
        "a stored caption that names a table is not overwritten")
    # And the guard is the only thing holding it: without a stored caption the
    # same text resolves to table 9.
    assert resolve_title(FOOTNOTE, content, "p37_tbl0").startswith("Tabelle 9")


def test_a_table_with_no_caption_of_its_own_does_not_borrow_the_last_one():
    """The failure this whole package is about, in one line: the caption that
    dates a table must stand between the table before it and itself.

    Reading further back finds the PREVIOUS table's caption, and a year read
    off it is the wrong year with a passage that verifies. That is how 240 of
    379 tuples from Kassel's twelve titled target tables were dated.
    """
    content = ("Tabelle 17: Endenergieverbrauch im Zielszenario 2040 "
               "[p85_tbl0] Der Verbrauch sinkt weiter. [p86_tbl0]")
    got = resolve_title(FOOTNOTE, content, "p86_tbl0")
    assert got == FOOTNOTE, "nothing of its own, so nothing is claimed"
    assert "Tabelle 17" not in got
    assert "2040" not in got


def test_the_caption_taken_is_the_one_nearest_the_placeholder():
    """Two captions in one run and only the second is placed: the nearer one
    is the table's own. Taking the first names it after its predecessor."""
    content = ("Tabelle 28: Endenergieverbrauch 2030 Tabelle 29: "
               "Endenergieverbrauch 2035 [p163_tbl0]")
    got = resolve_title(FOOTNOTE, content, "p163_tbl0")
    assert got.startswith("Tabelle 29"), got
    assert "2035" in got and "2030" not in got


def test_a_note_is_not_a_caption_and_a_numbered_phrase_is():
    """What separates them is the number, not a word list: 'Table 3:' and
    'Abbildung 2-3:' are captions in any report, 'Hinweis:' is a note."""
    assert not looks_like_a_caption(FOOTNOTE)
    assert not looks_like_a_caption("Quelle: eigene Darstellung")
    assert not looks_like_a_caption("")
    assert looks_like_a_caption("Tabelle 17: Endenergieverbrauch")
    assert looks_like_a_caption("Abbildung 2-3: Wärmedichte")
    assert looks_like_a_caption("Table 3: Final energy")


def test_nothing_to_resolve_leaves_the_caption_alone():
    assert resolve_title(FOOTNOTE, KASSEL_349525, "p99_tbl9") == FOOTNOTE
    assert resolve_title(FOOTNOTE, "", "p85_tbl0") == FOOTNOTE
    assert resolve_title(FOOTNOTE, None, None) == FOOTNOTE
    # A placeholder with only prose before it keeps what was stored: a
    # sentence that does not open like a caption is not one.
    assert resolve_title(FOOTNOTE, "Der Verbrauch sinkt. [p1_tbl0]",
                         "p1_tbl0") == FOOTNOTE


def _db(tmp_path):
    path = tmp_path / "mini.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);
        CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                               section_number INTEGER, title TEXT,
                               content TEXT, page_number INTEGER);
        CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER,
                             block_id TEXT, caption TEXT, markdown TEXT,
                             page_number INTEGER, path TEXT);
        CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER,
                             block_id TEXT, caption TEXT, description TEXT,
                             page_number INTEGER, path TEXT);
    """)
    conn.execute("INSERT INTO Documents VALUES (857, 'plan.pdf')")
    conn.execute("INSERT INTO Sections VALUES (349525, 857, 12, 'Zielszenario',"
                 " ?, 86)", (KASSEL_349525,))
    for tid, block, page in ((87457, "p85_tbl0", 86), (87458, "p86_tbl0", 87)):
        conn.execute("INSERT INTO Tables VALUES (?, 349525, ?, ?, ?, ?, ?)",
                     (tid, block, FOOTNOTE, "| Erdgas | 1 |", page,
                      f"tables/{block}.png"))
    conn.commit()
    return conn


def test_the_table_a_run_reads_carries_the_resolved_title(tmp_path):
    """The promise end to end: what the harvest is handed as `title` is the
    sentence that names the table, and the stored caption is kept beside it so
    a replacement can be told from a link."""
    conn = _db(tmp_path)
    got = fetch_owner_content(conn, "table", 87458)
    assert got["title"].startswith("Tabelle 18")
    assert "2040" in got["title"]
    assert got["caption_stored"] == FOOTNOTE

    # And the section names the same thing the table calls itself, so the two
    # do not disagree in one document.
    captions = section_item_captions(conn, 349525, KASSEL_349525)
    assert captions["p85_tbl0"].startswith("Tabelle 17")
    assert captions["p86_tbl0"].startswith("Tabelle 18")
    section = fetch_owner_content(conn, "section", 349525)
    assert "[p86_tbl0: Tabelle 18" in section["text"]


# ---------------------------------------------------------------------------
# Plans with no PDF text layer
#
# Eleven plans of the corpus have none. Stage 1 renders those pages and a
# model transcribes them, and from there everything runs unchanged: the
# section text of such a plan is itself a model reading, and so is every
# quote verified against it.
#
# The text below is verbatim from waermeplan_vg_maikammer_20260320.pdf
# (document 210), section 434053, and from waermeplan_leipzig_20260301.pdf
# (795), section 434... -- both transcribed pages, not PDF text.
# ---------------------------------------------------------------------------

MAIKAMMER_434053 = (
    "Nachfolgend nicht aufgeführt sind zusätzliche bilaterale Kontakte "
    "zwischen dem beauftragten Büro und diversen Akteur*innen zur Abstimmung "
    "einzelner Sachverhalte. Tabelle 1: Termine im Rahmen der Erarbeitung des "
    "Wärmeplans für die Verbandsgemeinde Maikammer [p16_tbl0] Mit den "
    "erfolgten Beteiligungsschritten sind die Vorgaben des WPG für beide "
    "Beteiligungsphasen erfüllt.")

# What Stage 2 stored for that table: the vision model's own reading of the
# same line, which is a paraphrase and carries no number.
MAIKAMMER_STORED = ("Zeitplan und Beteiligungsprozess der Kommunalen "
                    "Wärmeplanung für Maikammer")


def test_a_transcribed_page_still_yields_the_documents_own_caption():
    """Measured over the three textless plans (795 Leipzig, 1082
    Grevesmuehlen, 210 VG Maikammer): 169 tables, not one with a caption
    Stage 2 linked as a caption, and 23 whose numbered sentence stands in the
    transcribed section text and resolves. The stored caption is a paraphrase
    of the same line; the resolved one is the plan's own words, which is what
    a quote needs."""
    got = resolve_title(MAIKAMMER_STORED, MAIKAMMER_434053, "p16_tbl0")
    assert got.startswith("Tabelle 1: Termine im Rahmen")
    assert got.endswith("Verbandsgemeinde Maikammer")
    assert "Mit den erfolgten" not in got, "it stops at its own placeholder"


def test_a_caption_followed_by_prose_ends_where_the_caption_ends():
    """In a transcribed plan the caption and the paragraph after it are one
    run and the placeholder follows the paragraph. One of the 23 resolved
    titles carried sixty characters of the next sentence with it -- and a
    title is quoted for a table's year, so what rides along is what a model
    is invited to cite."""
    stored = "Endenergieverbrauch aufgeteilt nach Sektoren (2020)"
    content = ("Tabelle 3-2: Endenergieverbrauch aufgeteilt nach Sektoren "
               "(2020) Wie sich der sektorspezifische Wärmeverbrauch in den "
               "zurückliegenden Jahren entwickelt hat, zeigt die folgende "
               "Abbildung. [p19_tbl0]")
    got = resolve_title(stored, content, "p19_tbl0")
    assert got == "Tabelle 3-2: " + stored
    assert "Wie sich der" not in got

    # And the cut only fires where the document's own sentence really
    # contains the stored caption: Kassel's footnote is not in its title.
    assert resolve_title(FOOTNOTE, KASSEL_349525, "p85_tbl0").startswith(
        "Tabelle 17")
