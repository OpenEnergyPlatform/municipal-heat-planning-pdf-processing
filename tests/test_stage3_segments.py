"""Stage 3: per-segment page provenance."""
from docpipe.preprocessing.models import Block, PageData
from docpipe.preprocessing import stage3_structure as s3


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


def test_text_run_splits_into_per_page_segments():
    # Two text blocks on consecutive pages with no heading between → one section
    # with two page-tagged text segments (the per-page-segment invariant that
    # Stage 4 redistribution relies on for exact split attribution).
    p1 = [Block(id="p1_t0", type="text", bbox=[0, 0, 10, 6], content="Seite eins Text.")]
    p2 = [Block(id="p2_t0", type="text", bbox=[0, 0, 10, 6], content="Seite zwei Text.")]
    s = s3.build_sections([_page(1, p1), _page(2, p2)])[0]
    text_segs = [seg for seg in s.segments if seg["kind"] == "text"]
    assert [seg["page"] for seg in text_segs] == [1, 2]
    assert s.pages == [1, 2]


def test_dokument_page_number_derived_from_first_content_page():
    # A leading blank/cover page emits no blocks; first prose is on page 2. The
    # synthetic "Dokument" section's primary page must be 2, not a hardcoded 1.
    p2 = [Block(id="p2_t0", type="text", bbox=[0, 0, 10, 6], content="Erster echter Absatz.")]
    s = s3.build_sections([_page(1, []), _page(2, p2)])[0]
    assert s.title == "Dokument"
    assert s.pages == [2]
    assert s.page_number == 2
