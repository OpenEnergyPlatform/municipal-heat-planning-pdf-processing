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
