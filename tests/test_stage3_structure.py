"""Tests for Stage 3 deterministic section assembly."""
from docpipe.preprocessing.models import Block, PageData
from docpipe.preprocessing import stage3_structure as s3


def _page(n, blocks):
    pg = PageData(page_number=n, width_pt=595.0, height_pt=842.0)
    pg.blocks = blocks
    return pg


def test_title_opens_section_and_collects_text_and_media():
    blocks = [
        Block(id="p0_title0", type="text", bbox=[0, 0, 10, 5],
              content="Einleitung", layout_label="paragraph_title"),
        Block(id="p0_t0", type="text", bbox=[0, 6, 10, 12], content="Fließtext."),
        Block(id="p0_tbl0", type="table", bbox=[0, 13, 10, 20],
              path="images/p0_tbl0.png", caption="Cap"),
    ]
    sections = s3.build_sections([_page(1, blocks)])
    assert len(sections) == 1
    s = sections[0]
    assert s.title == "Einleitung"
    assert "Fließtext." in s.content and "[p0_tbl0]" in s.content
    assert s.tables[0].id == "p0_tbl0" and s.tables[0].caption == "Cap"


def test_leading_content_without_title_uses_dokument_section():
    blocks = [Block(id="p0_t0", type="text", bbox=[0, 0, 10, 5], content="Vorspann")]
    sections = s3.build_sections([_page(1, blocks)])
    assert sections[0].title == "Dokument"
    assert "Vorspann" in sections[0].content


def test_empty_leading_dokument_section_is_dropped():
    blocks = [Block(id="p0_title0", type="text", bbox=[0, 0, 10, 5],
                    content="Kapitel", layout_label="doc_title")]
    sections = s3.build_sections([_page(1, blocks)])
    assert [s.title for s in sections] == ["Kapitel"]


# ---------------------------------------------------------------------------
# The caption a table is stored with
#
# Stage 2 links a caption block by distance. In a plan whose tables carry a
# rounding footnote it links the footnote, and the sentence that names the
# table stays in the section text a few words before the placeholder: 15 of
# Kassel's 89 tables. The caption is the only line of a table a model can
# quote for the table's own year, so this is where 240 of 379 tuples from the
# twelve titled tables got a year off another table's caption.
# ---------------------------------------------------------------------------
FOOTNOTE = "Hinweis: Wegen der Rundung von Zahlenwerten kann es zu Abweichungen kommen."


def test_the_sentence_that_names_the_table_beats_the_linked_footnote():
    # Stage 2 removes the block it adopted, so the footnote reaches Stage 3
    # only as the table's caption; the sentence naming it is still page text.
    blocks = [
        Block(id="p0_t0", type="text", bbox=[0, 0, 10, 5],
              content="Tabelle 5: Endenergieverbrauch nach Sektoren 2040"),
        Block(id="p0_tbl0", type="table", bbox=[0, 12, 10, 20],
              path="images/p0_tbl0.png", caption=FOOTNOTE),
    ]
    section = s3.build_sections([_page(1, blocks)])[0]
    assert section.tables[0].caption == \
        "Tabelle 5: Endenergieverbrauch nach Sektoren 2040"
    # And the sentence stays where it was read: a quote of it is verified
    # against the section text, and taking it out would make the caption
    # unquotable in the one place the harvest looks.
    assert "Tabelle 5: Endenergieverbrauch" in section.content


def test_a_caption_that_already_opens_like_one_is_left_alone():
    """A link beats a guess: Stage 2 saw the two blocks on the page."""
    blocks = [
        Block(id="p0_t0", type="text", bbox=[0, 0, 10, 5],
              content="Tabelle 5: Falscher Satz"),
        Block(id="p0_tbl0", type="table", bbox=[0, 12, 10, 20],
              path="images/p0_tbl0.png", caption="Tabelle 6: Verlinkt"),
    ]
    section = s3.build_sections([_page(1, blocks)])[0]
    assert section.tables[0].caption == "Tabelle 6: Verlinkt"


def test_a_title_never_reaches_across_the_previous_placeholder():
    """Everything before the previous item's placeholder belongs to that item.
    Without the boundary the second table inherits the first one's name and
    both are then called Tabelle 5."""
    blocks = [
        Block(id="p0_t0", type="text", bbox=[0, 0, 10, 5],
              content="Tabelle 5: Erste"),
        Block(id="p0_tbl0", type="table", bbox=[0, 6, 10, 12],
              path="images/p0_tbl0.png", caption=FOOTNOTE),
        Block(id="p0_t1", type="text", bbox=[0, 13, 10, 18],
              content="Der Verbrauch sinkt."),
        Block(id="p0_tbl1", type="table", bbox=[0, 19, 10, 25],
              path="images/p0_tbl1.png", caption=FOOTNOTE),
    ]
    section = s3.build_sections([_page(1, blocks)])[0]
    assert section.tables[0].caption == "Tabelle 5: Erste"
    assert section.tables[1].caption == FOOTNOTE


def test_a_figure_is_named_the_same_way():
    blocks = [
        Block(id="p0_t0", type="text", bbox=[0, 0, 10, 5],
              content="Abbildung 2-3: Wärmedichte im Ist-Zustand"),
        Block(id="p0_img0", type="image", bbox=[0, 6, 10, 20],
              path="images/p0_img0.png", caption="Quelle: eigene Darstellung"),
    ]
    section = s3.build_sections([_page(1, blocks)])[0]
    assert section.figures[0].caption == "Abbildung 2-3: Wärmedichte im Ist-Zustand"
