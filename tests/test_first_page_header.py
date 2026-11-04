from docpipe.preprocessing.models import Block, PageData
from docpipe.preprocessing.stage3_structure import strip_running_headers

H = 1000.0


def _blk(i, text, y):
    return Block(id=i, type="text", bbox=[50, y, 400, y + 10], content=text)


def _pages(n, header="Applied Energy 277 (2020) 115561"):
    pages = []
    for p in range(1, n + 1):
        blocks = [_blk(f"h{p}", header, 20), _blk(f"b{p}", f"Body paragraph number {p} " * 5, 500)]
        pages.append(PageData(page_number=p, width_pt=600.0, height_pt=H, blocks=blocks))
    return pages


def test_first_page_keeps_header_later_pages_lose_it():
    pages = _pages(6)
    dropped = strip_running_headers(pages)
    assert dropped == 5
    assert [b.id for b in pages[0].blocks] == ["h1", "b1"]
    for pg in pages[1:]:
        assert [b.id for b in pg.blocks] == [f"b{pg.page_number}"]


def test_first_page_counts_toward_detection():
    # recurs on pages 1, 2, 3 only: threshold is 3, so page 1 must count
    pages = _pages(6)
    for pg in pages[3:]:
        pg.blocks = [b for b in pg.blocks if not b.id.startswith("h")]
    assert strip_running_headers(pages) == 2
    assert [b.id for b in pages[0].blocks] == ["h1", "b1"]
    assert all(not b.id.startswith("h") for b in pages[1].blocks + pages[2].blocks)


def test_non_recurring_block_untouched():
    pages = _pages(6)
    pages[2].blocks.append(_blk("once", "Unique note in the header band", 25))
    strip_running_headers(pages)
    assert "once" in [b.id for b in pages[2].blocks]


def test_first_page_is_smallest_page_number_not_index():
    pages = _pages(6)
    for pg in pages:
        pg.page_number += 10
    strip_running_headers(pages)
    assert [b.id for b in pages[0].blocks] == ["h1", "b1"]
