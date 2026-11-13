"""A section that is a heading and nothing else is not lost: its heading opens
the next section's text, in order, and only a heading with no text after it,
or one before a literature list, goes as it did. A section the model removes
leaves its heading the same way, and is no section to merge into; the
profile's name for the text before any heading is never handed on."""
from docpipe.profile import profile_value
from docpipe.refinement.refine import (_apply_actions, _fold_bare_headings,
                                       _is_empty_section)

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


def test_a_removed_section_leaves_its_heading_to_the_section_after_it():
    applied, _ = _apply_actions([
        {**section(TITLE, "Introduction ..... 1"), "_action": "remove"},
        {**section("Introduction", "The study"), "_action": "keep"}], None)
    folded = [s for s in _fold_bare_headings(applied)
              if not _is_empty_section(s)]
    assert folded == [section("Introduction", f"{TITLE}\nIntroduction\nThe study")]


def test_a_continuation_after_a_removed_section_joins_the_section_before_it():
    before = section("Methods", "We model")
    applied, last = _apply_actions([
        {**section("Contents", "1 ..... 3"), "_action": "remove"},
        {**section("", "and solve it"), "_action": "merge_into_previous"}],
        before)
    assert before["content"] == "We model and solve it" and last is before
    assert [s["title"] for s in applied] == ["Contents"]


def test_the_text_before_the_first_heading_stays_and_its_name_is_never_handed_on():
    front = profile_value("preprocessing", "FRONT_SECTION_TITLE")
    applied, _ = _apply_actions([
        {**section(front, f"Energy Policy 110 {TITLE}"), "_action": "remove"},
        {**section(front), "_action": "keep"},
        {**section("Abstract", "This study"), "_action": "keep"}], None)
    assert _fold_bare_headings(applied) == [
        section(front, f"Energy Policy 110 {TITLE}"),
        section("Abstract", "This study")]
