"""A section that is a heading and nothing else is not lost: its heading opens
the next section's text, in order, and only a heading with no text after it,
or one before a literature list, goes as it did."""
from docpipe.refinement.refine import _fold_bare_headings, _is_empty_section

TITLE = "Implications of Japan's 2030 target for long-term low emission pathways"


def section(title, content="", **rest):
    return {"title": title, "content": content, "tables": [], "figures": [],
            **rest}


def test_a_papers_title_opens_the_text_after_it():
    folded = _fold_bare_headings([
        section("Dokument", "Energy Policy 110 (2017) 581-587"),
        section(TITLE),
        section("Ken Oshiro, Mikiko Kainuma", "a Environment and Energy")])
    kept = [s for s in folded if not _is_empty_section(s)]
    assert [s["title"] for s in kept] == ["Dokument",
                                         "Ken Oshiro, Mikiko Kainuma"]
    assert kept[1]["content"].startswith(TITLE + "\n")
    assert kept[1]["content"].endswith("a Environment and Energy")


def test_a_title_broken_over_headings_reads_in_its_order():
    folded = _fold_bare_headings([section("pathways to"),
                                  section("deep decarbonization"),
                                  section("in India", "Published by SDSN")])
    assert folded == [section(
        "in India",
        "pathways to\ndeep decarbonization\nin India\nPublished by SDSN")]


def test_a_heading_with_nothing_after_it_and_a_literature_list_stay_as_they_were():
    bibtex = ["@article{a, title={X}}"]
    folded = _fold_bare_headings([section("Intro", "Text"),
                                  section("References"),
                                  section("Literature", bibtex),
                                  section("Appendix")])
    assert folded == [section("Intro", "Text"), section("Literature", bibtex)]
