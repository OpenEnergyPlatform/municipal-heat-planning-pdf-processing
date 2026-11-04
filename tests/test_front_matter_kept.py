"""Stage 4 never removes a section of the first page's front matter, whatever
action the model returns; a section further in that the model removes goes."""
from docpipe.refinement.refine import _apply_actions, _page_of


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
                                _page_of(DOC))
    assert [s["content"] for s in applied] == ["a Institute, Tokyo"]


def test_without_the_first_page_the_same_remove_takes_the_text():
    # the failure by construction: no first page known, the text goes
    applied, _ = _apply_actions([remove(DOC[0])], None, None)
    assert [s["content"] for s in applied] == [""]


def test_a_body_section_the_model_removes_still_goes():
    applied, _ = _apply_actions([remove(DOC[2])], None, _page_of(DOC))
    assert [s["content"] for s in applied] == [""]


def test_the_first_page_is_the_lowest_page_any_section_carries():
    assert _page_of(DOC) == 1
    assert _page_of([{"title": "x", "content": ""}]) is None
