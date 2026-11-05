from docpipe.preprocessing.models import Block, PageData
from docpipe.preprocessing.stage3_structure import (
    sections_to_dict, strip_running_headers, title_page_of)

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


# Promise: the title page is the page of the detected document title, else the
# first page; Stage 3 keeps the blocks of the first page AND of the title page,
# AND strips the running head everywhere else.
def _titled(pages, page):
    pg = next(p for p in pages if p.page_number == page)
    pg.blocks.append(Block(id="t", type="text", bbox=[50, 100, 400, 120],
                           content="Pathways to net zero", layout_label="doc_title"))


def test_title_page_is_the_page_of_the_doc_title():
    pages = _pages(6)
    _titled(pages, 2)
    assert title_page_of(pages) == 2


def _heads(pages):
    return [pg.page_number for pg in pages
            if any(b.id.startswith("h") for b in pg.blocks)]


def test_a_cover_page_one_and_title_page_two_both_keep_their_head():
    pages = _pages(6)
    _titled(pages, 2)
    strip_running_headers(pages)
    assert _heads(pages) == [1, 2]


def test_a_title_detected_far_in_costs_the_first_page_nothing():
    pages = _pages(8)
    _titled(pages, 6)
    assert title_page_of(pages) == 6
    strip_running_headers(pages)
    # the failure by construction: pages 2-5, 7, 8 lose their running head
    assert _heads(pages) == [1, 6]


def test_without_a_doc_title_the_first_page_is_the_title_page():
    pages = _pages(6)
    assert title_page_of(pages) == 1
    strip_running_headers(pages)
    assert [b.id for b in pages[0].blocks] == ["h1", "b1"]
    assert not any(b.id == "h2" for b in pages[1].blocks)


def test_an_empty_doc_title_does_not_count():
    pages = _pages(6)
    _titled(pages, 3)
    pages[2].blocks[-1].content = "  "
    assert title_page_of(pages) == 1


def test_the_title_page_reaches_sections_json_beside_the_sections():
    assert sections_to_dict([], 2)["title_page"] == 2
    assert "title_page" not in sections_to_dict([])
