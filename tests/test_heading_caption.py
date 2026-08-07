"""Tests for font-based heading promotion and caption intervener detection."""
from docpipe.preprocessing import stage2_layout as s2
from docpipe.preprocessing.models import Block, PageData


def _text(bid, y, content, size=10.0, bold=False, label=None):
    return Block(id=bid, type="text", bbox=[0.0, y, 100.0, y + 10.0], content=content,
                 font_size=size, font_bold=bold, layout_label=label)


def _page(blocks, n=1):
    pg = PageData(page_number=n, width_pt=100.0, height_pt=800.0)
    pg.blocks = blocks
    return pg


# ── body font detection ─────────────────────────────────────────────────────

def test_body_font_size_is_most_common_by_chars():
    pgs = [_page([
        _text("a", 0, "lots of regular body text here and there", size=10.0),
        _text("b", 100, "Heading", size=20.0),
    ])]
    assert s2._body_font_size(pgs) == 10.0


# ── heading heuristic ───────────────────────────────────────────────────────

def test_heading_by_size():
    assert s2._looks_like_heading("Bestandsanalyse", 14.0, False, 10.0)     # 14 >= 10*1.2
    assert not s2._looks_like_heading("a normal body line", 10.0, False, 10.0)


def test_heading_by_bold_requires_strictly_larger():
    assert s2._looks_like_heading("Zusammenfassung", 12.0, True, 10.0)      # bold AND larger
    assert not s2._looks_like_heading("Hinweis", 10.0, True, 10.0)          # bold but same size
    too_long = "a bold sentence that runs on and on for far longer than any real heading would ever plausibly be in this document"
    assert not s2._looks_like_heading(too_long, 12.0, True, 10.0)            # exceeds max chars


def test_heading_prose_guard():
    # ends in a full stop / contains a sentence boundary → not a heading
    assert not s2._looks_like_heading("Die Anlage ist sehr wichtig.", 16.0, False, 10.0)
    assert not s2._looks_like_heading("Erstens dies. Zweitens das", 16.0, False, 10.0)
    assert s2._looks_like_heading("Wärmebedarf nach Sektoren", 16.0, False, 10.0)


def test_heading_allcaps_but_not_acronym():
    assert s2._looks_like_heading("POTENTIALANALYSE", None, False, None)
    assert not s2._looks_like_heading("BHKW", None, False, None)            # too short → acronym


def test_heading_excludes_caption_prefix():
    assert not s2._looks_like_heading("Abbildung 3", 20.0, True, 10.0)


# ── promotion pass ──────────────────────────────────────────────────────────

def test_promote_headings_by_font():
    pgs = [_page([
        _text("a", 0, "Wärmebedarfsanalyse", size=16.0),                    # heading by size
        _text("b", 50, "regular body paragraph text " * 12, size=10.0),    # body dominates
        _text("c", 100, "Existing Title", size=16.0, label="paragraph_title"),
    ])]
    s2.promote_headings_by_font(pgs)
    labels = {b.id: b.layout_label for b in pgs[0].blocks}
    assert labels["a"] == "paragraph_title"   # promoted
    assert labels["b"] is None                 # body untouched
    assert labels["c"] == "paragraph_title"    # pre-existing title untouched


def test_promote_skips_block_sharing_row_with_media():
    # heading-sized text that vertically overlaps a table shares its row →
    # likely an inline label, not a section heading → must NOT be promoted.
    table = Block(id="p0_tbl0", type="table", bbox=[50, 0, 100, 20],
                  path="images/x.png", layout_label="table")
    inline = _text("a", 5, "Wichtige Kennwerte", size=16.0)   # bbox [0,5,100,15] overlaps table row
    body = _text("b", 200, "regular body text here " * 12, size=10.0)
    pgs = [_page([table, inline, body])]
    s2.promote_headings_by_font(pgs)
    assert {b.id: b.layout_label for b in pgs[0].blocks}["a"] is None


def test_promote_disabled(monkeypatch):
    monkeypatch.setattr(s2, "FONT_HEADING_ENABLE", False)
    pgs = [_page([_text("a", 0, "Wärmebedarfsanalyse", size=16.0)])]
    s2.promote_headings_by_font(pgs)
    assert pgs[0].blocks[0].layout_label is None


# ── caption intervener detection ────────────────────────────────────────────

def test_title_between():
    assert s2._title_between(10, 100, [50])
    assert not s2._title_between(10, 100, [5, 200])
    assert not s2._title_between(10, 100, [10, 100])   # boundaries are exclusive


def test_resolve_captions_rejects_caption_across_heading():
    fig = Block(id="p0_img0", type="image", bbox=[0, 195, 100, 205], path="images/x.png")
    title = _text("p0_title0", 220, "Neuer Abschnitt", label="paragraph_title")  # y≈225
    cap = _text("p0_t1", 245, "Energieträger 2023")                               # y≈250, dist 50 < 60
    s2.resolve_captions([_page([fig, title, cap])])
    assert fig.caption is None     # not linked across the heading


def test_resolve_captions_links_when_no_intervener():
    fig = Block(id="p0_img0", type="image", bbox=[0, 195, 100, 205], path="images/x.png")
    cap = _text("p0_t1", 210, "Energieträger 2023")                               # y≈215, dist 15
    s2.resolve_captions([_page([fig, cap])])
    assert fig.caption == "Energieträger 2023"
