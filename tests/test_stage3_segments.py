"""Stage 3: per-segment page provenance."""
from scripts.preprocessing.models import Block, PageData
from scripts.preprocessing import stage3_structure as s3


def _page(n, blocks):
    pg = PageData(page_number=n, width_pt=595.0, height_pt=842.0)
    pg.blocks = blocks
    return pg


def test_section_spanning_pages_gets_segments_and_pages():
    p5 = [Block(id="p4_title0", type="text", bbox=[0, 0, 10, 5],
                content="Bestandsanalyse", layout_label="paragraph_title"),
          Block(id="p4_t0", type="text", bbox=[0, 6, 10, 12], content="Erster Absatz.")]
    p6 = [Block(id="p5_tbl0", type="table", bbox=[0, 0, 10, 20],
               path="images/p5_tbl0.png", caption="Energieträger")]
    p7 = [Block(id="p6_t0", type="text", bbox=[0, 0, 10, 6], content="Folgeabsatz.")]
    s = s3.build_sections([_page(5, p5), _page(6, p6), _page(7, p7)])[0].to_dict()

    assert s["pages"] == [5, 6, 7]
    assert s["page_number"] == 5
    assert [(seg["kind"], seg["page"]) for seg in s["segments"]] == [
        ("text", 5), ("table", 6), ("text", 7)]
    assert s["segments"][1]["ref"] == "p5_tbl0"
    assert s["segments"][0]["text"] == "Erster Absatz."


def test_consecutive_same_page_text_merges_into_one_segment():
    blocks = [Block(id="p0_t0", type="text", bbox=[0, 0, 10, 5], content="A"),
              Block(id="p0_t1", type="text", bbox=[0, 6, 10, 10], content="B")]
    s = s3.build_sections([_page(1, blocks)])[0]
    text_segs = [seg for seg in s.segments if seg["kind"] == "text"]
    assert len(text_segs) == 1
    assert text_segs[0]["text"] == "A B"
    assert s.pages == [1]
