"""Stage 4 never removes a section of the front matter of the first page or of
the title page, whatever action the model returns; a section elsewhere that
the model removes goes."""
from docpipe.refinement.refine import _apply_actions, _front_pages, _page_of


def section(title, content, page):
    return {"title": title, "content": content, "tables": [], "figures": [],
            "segments": [{"page": page}], "pages": [page]}


def remove(sec):
    return {**sec, "_action": "remove"}


DOC = [section("Ken Oshiro, Mikiko Kainuma", "a Institute, Tokyo", 1),
       section("Introduction", "The study", 1),
       section("Contents", "1 ..... 3", 3)]


def test_the_author_section_of_the_first_page_survives_a_remove():
    applied, _ = _apply_actions([remove(s) for s in DOC[:1]], None,
                                _front_pages(DOC, None))
    assert [s["content"] for s in applied] == ["a Institute, Tokyo"]


def test_without_the_first_page_the_same_remove_takes_the_text():
    # the failure by construction: no first page known, the text goes
    applied, _ = _apply_actions([remove(DOC[0])], None, set())
    assert [s["content"] for s in applied] == [""]


def test_a_body_section_the_model_removes_still_goes():
    applied, _ = _apply_actions([remove(DOC[2])], None, _front_pages(DOC, None))
    assert [s["content"] for s in applied] == [""]


def test_the_first_page_is_the_lowest_page_any_section_carries():
    assert _page_of(DOC) == 1
    assert _page_of([{"title": "x", "content": ""}]) is None


# Promise: the front pages are the lowest page any section carries AND Stage
# 3's title page; Stage 4 removes no section starting on either, AND removes
# one starting elsewhere.
COVERED = [section("Repository cover", "Open access archive", 1),
           section("Ken Oshiro, Mikiko Kainuma", "a Institute, Tokyo", 2),
           section("Methods", "We model", 3)]


def test_the_front_pages_are_the_first_page_and_the_title_page():
    assert _front_pages(COVERED, 2) == {1, 2}
    assert _front_pages(COVERED, 89) == {1, 89}
    assert _front_pages(COVERED, None) == {1}
    assert _front_pages([{"title": "x", "content": ""}], None) == set()


def test_a_cover_and_the_author_section_of_title_page_two_survive_a_remove():
    applied, _ = _apply_actions([remove(s) for s in COVERED[:2]], None,
                                _front_pages(COVERED, 2))
    assert [s["content"] for s in applied] == ["Open access archive",
                                               "a Institute, Tokyo"]


def test_a_section_after_the_title_page_the_model_removes_goes():
    applied, _ = _apply_actions([remove(COVERED[2])], None,
                                _front_pages(COVERED, 2))
    assert [s["content"] for s in applied] == [""]


def test_a_section_starting_on_the_title_page_survives_though_it_runs_on():
    running = {**section("Ken Oshiro", "a Institute, Tokyo", 2),
               "segments": [{"page": 2}, {"page": 3}], "pages": [2, 3]}
    applied, _ = _apply_actions([remove(running)], None, {1, 2})
    assert [s["content"] for s in applied] == ["a Institute, Tokyo"]
