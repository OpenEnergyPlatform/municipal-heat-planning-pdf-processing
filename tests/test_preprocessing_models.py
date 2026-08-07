"""Tests for the preprocessing dataclasses (serialisation round-trips)."""
from docpipe.preprocessing.models import Block, FigureRef, PageData, Section, TableRef


def test_block_roundtrip_rounds_confidence_and_omits_none():
    b = Block(id="p0_t0", type="text", bbox=[1, 2, 3, 4], content="hi", confidence=0.123456)
    d = b.to_dict()
    assert d["confidence"] == 0.123          # rounded to 3 decimals
    assert "path" not in d                    # None optionals omitted
    assert Block.from_dict(d).content == "hi"


def test_pagedata_roundtrip():
    pg = PageData(page_number=1, width_pt=595.0, height_pt=842.0)
    pg.blocks.append(Block(id="p0_t0", type="text", bbox=[0, 0, 1, 1], content="x"))
    pg2 = PageData.from_dict(pg.to_dict())
    assert pg2.page_number == 1
    assert pg2.blocks[0].id == "p0_t0"


def test_block_source_text_roundtrip_and_omit():
    b = Block(id="p0_tbl0", type="table", bbox=[0, 0, 1, 1],
              path="images/p0_tbl0.png", source_text="Erdgas 45,2")
    d = b.to_dict()
    assert d["source_text"] == "Erdgas 45,2"
    assert Block.from_dict(d).source_text == "Erdgas 45,2"
    # omitted when None
    assert "source_text" not in Block(id="p0_t0", type="text", bbox=[0, 0, 1, 1]).to_dict()


def test_tableref_source_text_roundtrip_and_omit():
    t = TableRef(id="p0_tbl0", path="images/p0_tbl0.png", source_text="a b 1")
    assert t.to_dict()["source_text"] == "a b 1"
    assert "source_text" not in TableRef(id="x", path="y").to_dict()


def test_section_to_dict_includes_and_omits_refs():
    s = Section(title="T", content="c", page_number=2)
    s.tables.append(TableRef(id="p1_tbl0", path="images/p1_tbl0.png", caption="cap", page_number=2))
    s.figures.append(FigureRef(id="p1_img0", path="images/p1_img0.png"))
    d = s.to_dict()
    assert d["tables"][0]["caption"] == "cap"
    assert "caption" not in d["figures"][0]   # None caption omitted
