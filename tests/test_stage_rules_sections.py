"""
The decisions of stage 3 (sections) are rules, and the stage decides by them
(owner request 2026-11-19, A1: "Die festen Werte werden Regeln mit dem
heutigen Wert als Standard").

The promises, each with a case that breaks it by construction:

1. Every rule of the stage has a default in the default profile's file that
   `rules.problem` takes, a title and a help; AND the defaults are the values
   the code held, with the words each profile held for its language.
2. A page is read as columns by the rules of the column search: the blocks it
   needs, the gap and the steps it is searched in, the narrowest column, the
   blocks and share of the load each column holds, the left edges.
3. A running head or foot is removed by the rules of its band, length, share
   of the pages and repeats, AND the first pages keep theirs by the switch.
4. A section is a directory by the rules of its entries and shares, AND a
   bibliography is never one, by its title words.
5. A caption opens as `caption_opener_patterns` say; the text before the first
   heading and a part with no title are named by the rules; text is brought
   to the normal form of Unicode by the switch.
"""
import json
from pathlib import Path

import pytest

from docpipe import captions, rules
from docpipe.preprocessing import columns, sections
from docpipe.preprocessing.config import clean_data, clean_unicode
from docpipe.preprocessing.models import Block, PageData, Section
from docpipe.profile import load_profile
from docpipe.ruleset import stage_sections

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = json.loads((ROOT / "docpipe/builtin/default/rules.json")
                     .read_text(encoding="utf-8"))["rules"]


# -- 1: the rules, their defaults and the values the code held ----------------

@pytest.mark.parametrize("one", stage_sections.RULES, ids=lambda one: one.name)
def test_every_rule_has_a_default_a_title_and_a_help(one):
    assert one.tab == "stages" and one.group == stage_sections.GROUP
    assert one.title.strip() and len(one.help.split()) > 10
    assert one.name in DEFAULT
    assert rules.problem(one.name, DEFAULT[one.name]) is None


def test_a_value_outside_the_bounds_is_no_value_of_the_rule():
    # the failure by construction: the check has to be able to fail
    assert rules.problem("column_max_columns", 1) is not None
    assert rules.problem("running_header_band", 0.9) is not None
    assert rules.problem("directory_title_words", ["a", "a"]) is not None
    assert rules.problem("directory_title_words", []) is None    # may be empty
    assert rules.problem("bibliography_title_words", []) is not None


def test_the_defaults_are_the_values_the_code_held():
    assert [DEFAULT[n] for n in (
        "column_min_text_blocks", "column_gutter_width_pt",
        "column_search_step_pt", "column_run_join_steps",
        "column_max_span_share", "column_min_load_share",
        "column_min_blocks", "column_min_width_pt", "column_max_columns",
        "column_edge_tolerance_pt", "column_min_aligned_share",
        "column_edge_groups")] == [6, 8.0, 2.0, 1.5, 0.25, 0.5, 2, 60.0, 4,
                                   4.0, 0.75, 2]
    assert [DEFAULT[n] for n in (
        "strip_running_headers", "running_header_band",
        "running_header_max_chars", "running_header_min_chars",
        "running_header_page_share", "running_header_min_pages",
        "running_header_min_repeats", "running_header_number_digits",
        "keep_front_page_headers")] == [True, 0.12, 90, 4, 0.3, 4, 3, 4, True]
    assert [DEFAULT[n] for n in (
        "strip_directory_sections", "directory_min_entries",
        "directory_listing_share", "directory_titled_listing_share",
        "directory_head_chars", "directory_head_share",
        "directory_max_other_chars", "directory_min_chars",
        "directory_entry_max_chars")] == [True, 4, 0.55, 0.35, 120, 0.5, 350,
                                          40, 90]
    assert DEFAULT["sentence_end_marks"] == ".!?"
    assert DEFAULT["normalize_unicode_nfkc"] is True
    assert len(DEFAULT["caption_opener_patterns"]) == 3


def test_each_profile_has_the_words_it_held_for_its_language():
    got = {name: rules.load(load_profile(name)) for name in
           ("default", "kwp", "scenarios")}
    assert [got[n]["front_section_title"] for n in got] == [
        "Document", "Dokument", "Dokument"]
    assert [got[n]["part_section_title"] for n in got] == [
        "Section", "Abschnitt", "Abschnitt"]
    assert got["kwp"]["directory_figure_words"] == [
        "Abbildung", "Tabelle", "Abb\\.", "Tab\\."]
    assert got["scenarios"]["directory_figure_words"][-1] == "Box"
    assert got["default"]["directory_figure_words"] == [
        "Figure", "Table", "Fig\\.", "Tab\\."]
    assert got["kwp"]["bibliography_title_words"][0] == "literatur"
    assert got["scenarios"]["bibliography_title_words"][0] == "references"
    assert (got["kwp"]["directory_title_words"]
            == got["default"]["directory_title_words"]
            == ["inhalt", "verzeichnis", "contents", "directory"])
    assert len(got["kwp"]["caption_opener_patterns"]) == 1
    assert len(got["default"]["caption_opener_patterns"]) == 3


# -- 2: columns ---------------------------------------------------------------

def _body(i, x0, x1, y):
    return Block(id=f"b{i}", type="text", bbox=[x0, y, x1, y + 10],
                 content="Text")


def _two_columns(left_edges=(50, 50, 50, 50), gap_to=350):
    """Four blocks in a column 200 wide at 50, four in one that starts at
    *gap_to* and ends at 550 (a gap of *gap_to* - 250 points)."""
    blocks = [_body(i, x, 250, 100 + 30 * i) for i, x in enumerate(left_edges)]
    blocks += [_body(10 + i, gap_to, 550, 100 + 30 * i) for i in range(4)]
    return blocks


def test_a_page_with_two_columns_has_one_gutter():
    gutters = columns.find_gutters(_two_columns(), 600)
    assert len(gutters) == 1 and 250 < gutters[0] < 350
    # the failure by construction: one column has nothing to split
    one = [_body(i, 50, 550, 100 + 30 * i) for i in range(8)]
    assert columns.find_gutters(one, 600) == []


def test_a_page_needs_the_least_text_blocks_of_the_rule():
    with rules.overlaid(column_min_text_blocks=9):
        assert columns.find_gutters(_two_columns(), 600) == []
    with rules.overlaid(column_min_text_blocks=8):
        assert columns.find_gutters(_two_columns(), 600) != []


def test_the_gap_between_columns_is_as_wide_as_the_rule_says():
    narrow = _two_columns(gap_to=280)                         # a gap of 30
    assert columns.find_gutters(narrow, 600) != []            # 8 is clear
    with rules.overlaid(column_gutter_width_pt=50):
        assert columns.find_gutters(narrow, 600) == []
        assert columns.find_gutters(_two_columns(), 600) != []   # 100 is clear


def test_a_column_is_as_wide_as_the_rule_needs():
    with rules.overlaid(column_min_width_pt=120):                # 200 wide
        assert columns.find_gutters(_two_columns(), 600) != []
    with rules.overlaid(column_min_width_pt=260):
        assert columns.find_gutters(_two_columns(), 600) == []


def test_a_column_has_the_left_edges_of_the_rules():
    scattered = _two_columns(left_edges=(50, 70, 90, 50))   # three edges
    assert columns.find_gutters(scattered, 600) != []       # 3 of 4 on two
    with rules.overlaid(column_min_aligned_share=0.9):
        assert columns.find_gutters(scattered, 600) == []
    with rules.overlaid(column_edge_groups=1):
        assert columns.find_gutters(scattered, 600) == []
    with rules.overlaid(column_edge_tolerance_pt=20, column_edge_groups=1):
        assert columns.find_gutters(scattered, 600) != []   # 3 on one edge


def test_the_blocks_that_cross_a_gap_are_counted_by_the_rule():
    wide = [_body(20, 50, 550, 60), _body(21, 50, 550, 70)]
    blocks = _two_columns() + wide                          # 2 of 10 cross
    assert columns.find_gutters(blocks, 600) != []
    with rules.overlaid(column_max_span_share=0.1):
        assert columns.find_gutters(blocks, 600) == []


def test_a_page_has_at_most_the_columns_of_the_rule():
    three = [_body(i, x, x + 90, 100 + 30 * (i // 3))
             for i, x in enumerate((50, 250, 450) * 3)]
    assert len(columns.find_gutters(three, 600)) == 2
    with rules.overlaid(column_max_columns=2):
        assert columns.find_gutters(three, 600) == []


def test_the_blocks_are_read_column_by_column_with_the_gutters_found():
    page = PageData(page_number=1, width_pt=600, height_pt=800,
                    blocks=_two_columns())
    assert columns.sort_page(page)
    assert [b.id for b in page.blocks] == (
        [f"b{i}" for i in range(4)] + [f"b{10 + i}" for i in range(4)])


def test_every_column_holds_the_blocks_the_rule_asks():
    assert columns.find_gutters(_two_columns(), 600) != []    # 4 and 4
    with rules.overlaid(column_min_blocks=5):
        assert columns.find_gutters(_two_columns(), 600) == []


def test_every_column_holds_its_share_of_the_average_load():
    uneven = [_body(i, 50, 250, 100 + 30 * i) for i in range(6)] \
        + [_body(10 + i, 350, 550, 100 + 30 * i) for i in range(2)]
    assert columns.find_gutters(uneven, 600) != []     # 2 of an average 4
    with rules.overlaid(column_min_load_share=0.75):   # asks for 3
        assert columns.find_gutters(uneven, 600) == []


def test_the_search_for_a_gap_goes_in_the_steps_of_the_rule():
    narrow = _two_columns(gap_to=270)          # clear from 254 to 266
    assert columns.find_gutters(narrow, 600) != []
    # steps of 20 from 50 stand at 250 and 270, both in a column
    with rules.overlaid(column_search_step_pt=20):
        assert columns.find_gutters(narrow, 600) == []


def test_clear_places_closer_than_the_rule_make_one_gap():
    # three narrow blocks in the middle of the gap block the places around
    # 300, so the clear places are two runs, 12 points apart
    bodies = _two_columns() + [_body(20 + i, 299, 301, 100 + 30 * i)
                               for i in range(3)]
    two = columns._clear_runs(bodies, 50, 550, 2, 4.0)
    assert len(two) == 2
    with rules.overlaid(column_run_join_steps=5.0):    # 10 points: still two
        assert len(columns._clear_runs(bodies, 50, 550, 2, 4.0)) == 2
    with rules.overlaid(column_search_step_pt=3.0,     # 15 points: one
                        column_run_join_steps=5.0):
        assert len(columns._clear_runs(bodies, 50, 550, 2, 4.0)) == 1


# -- 3: running heads and feet ------------------------------------------------

H = 1000.0


def _plain(i, text, y):
    return Block(id=i, type="text", bbox=[50, y, 400, y + 10], content=text)


def _run(n, header=lambda p: "Applied Energy 277 (2020) 115561", y=200,
         repeats=None):
    pages = []
    for p in range(1, n + 1):
        blocks = [_plain(f"b{p}", f"Body paragraph number {p} " * 5, 500)]
        if repeats is None or p <= repeats:
            blocks.insert(0, _plain(f"h{p}", header(p), y))
        pages.append(PageData(page_number=p, width_pt=600.0, height_pt=H,
                              blocks=blocks))
    return pages


def test_a_line_in_the_band_that_repeats_is_removed_from_later_pages():
    # y 200 is outside the band of 0.12 of 1000
    assert sections.strip_running_headers(_run(6, y=200)) == 0
    pages = _run(6, y=100)
    assert sections.strip_running_headers(pages) == 5
    assert [b.id for b in pages[0].blocks] == ["h1", "b1"]    # the first stays


def test_the_band_is_as_high_as_the_rule_says():
    with rules.overlaid(running_header_band=0.3):
        assert sections.strip_running_headers(_run(6, y=200)) == 5
    with rules.overlaid(running_header_band=0.02):
        assert sections.strip_running_headers(_run(6, y=100)) == 0


def test_the_switch_off_removes_no_running_line():
    with rules.overlaid(strip_running_headers=False):
        assert sections.strip_running_headers(_run(6, y=100)) == 0


def test_a_document_has_the_least_pages_of_the_rule():
    with rules.overlaid(running_header_min_pages=7):
        assert sections.strip_running_headers(_run(6, y=100)) == 0
    assert sections.strip_running_headers(_run(4, y=100, repeats=4)) == 3


def test_a_line_repeats_on_the_pages_of_the_rule():
    assert sections.strip_running_headers(_run(9, y=100, repeats=3)) == 2
    with rules.overlaid(running_header_min_repeats=4):
        assert sections.strip_running_headers(_run(9, y=100, repeats=3)) == 0
    # 3 of 9 pages is a share of 0.33: 0.5 asks for 4 pages
    with rules.overlaid(running_header_page_share=0.5):
        assert sections.strip_running_headers(_run(9, y=100, repeats=3)) == 0


def test_a_running_line_is_as_long_as_the_rule_allows():
    with rules.overlaid(running_header_max_chars=10):
        assert sections.strip_running_headers(_run(6, y=100)) == 0
    with rules.overlaid(running_header_min_chars=50):
        assert sections.strip_running_headers(_run(6, y=100)) == 0


def test_the_page_number_in_a_running_line_has_the_digits_of_the_rule():
    def header(p):
        return f"Wärmeplan Stadt {10000 + p}"
    assert sections.strip_running_headers(_run(6, header, y=100)) == 0
    with rules.overlaid(running_header_number_digits=5):
        assert sections.strip_running_headers(_run(6, header, y=100)) == 5


def test_the_first_pages_keep_their_lines_by_the_switch():
    with rules.overlaid(keep_front_page_headers=False):
        pages = _run(6, y=100)
        assert sections.strip_running_headers(pages) == 6
        assert [b.id for b in pages[0].blocks] == ["b1"]


def test_a_footnote_follows_a_text_that_ends_with_a_mark_of_the_rule():
    assert sections._ends_sentence("Das war es.") and sections._ends_sentence(
        "Das war es.”")
    assert not sections._ends_sentence("Das war es")
    with rules.overlaid(sentence_end_marks="!?"):
        assert not sections._ends_sentence("Das war es.")
        assert sections._ends_sentence("Wirklich?")


# -- 4: directories -----------------------------------------------------------

ENTRIES = "".join(f"Kapitel {i} Wärmebedarf der Stadt ........ {i + 2}\n"
                  for i in range(6))
PROSE = ("Dieser Abschnitt beschreibt den Wärmebedarf der Stadt im Detail. "
         * 4)


def _section(title, content):
    return Section(title=title, content=content)


def test_a_section_of_entries_is_a_directory():
    assert sections._is_directory_section(_section("Inhalt", ENTRIES))
    # the failure by construction: prose with no entry
    assert not sections._is_directory_section(_section("Inhalt", PROSE))


def test_a_directory_has_the_least_entries_of_the_rule():
    with rules.overlaid(directory_min_entries=7):
        assert not sections._is_directory_section(_section("Inhalt", ENTRIES))
    with rules.overlaid(directory_min_entries=6):
        assert sections._is_directory_section(_section("Inhalt", ENTRIES))


def test_the_switch_off_keeps_the_directory_sections():
    kept = [_section("Inhalt", ENTRIES)]
    assert sections.drop_directory_sections(kept) == ([], 1)
    with rules.overlaid(strip_directory_sections=False):
        assert sections.drop_directory_sections(kept) == (kept, 0)


def _mixed():
    # entries are about 40 per cent of the section, the rest is prose
    return ENTRIES + PROSE


def test_a_titled_directory_has_the_lower_share_of_the_rule():
    content = _mixed()
    share = sections._directory_metrics(content)[0]
    assert 0.35 < share < 0.55
    assert sections._is_directory_section(_section("Inhalt", content))
    assert not sections._is_directory_section(_section("Kapitel", content))
    with rules.overlaid(directory_titled_listing_share=0.5):
        assert not sections._is_directory_section(_section("Inhalt", content))
    with rules.overlaid(directory_title_words=["zzz"]):
        assert not sections._is_directory_section(_section("Inhalt", content))
    with rules.overlaid(directory_title_words=[]):
        assert not sections._is_directory_section(_section("Inhalt", content))


def test_an_untitled_directory_has_the_share_and_residual_of_the_rules():
    assert sections._is_directory_section(_section("Kapitel", ENTRIES))
    with rules.overlaid(directory_listing_share=0.99):
        assert not sections._is_directory_section(_section("Kapitel", ENTRIES))
    with rules.overlaid(directory_head_share=0.99):
        assert not sections._is_directory_section(_section("Kapitel", ENTRIES))
    content = ENTRIES + "Nachwort. " * 20            # a residual of 200
    assert sections._is_directory_section(_section("Kapitel", content))
    with rules.overlaid(directory_max_other_chars=100):
        assert not sections._is_directory_section(_section("Kapitel", content))


def test_the_opening_that_is_checked_has_the_length_of_the_rule():
    content = PROSE[:100] + ENTRIES               # the opening is prose
    assert not sections._is_directory_section(_section("Kapitel", content))
    with rules.overlaid(directory_head_chars=20, directory_head_share=0.1,
                        directory_listing_share=0.3):
        assert sections._directory_metrics(content[:20])[0] == 0.0


def test_a_short_section_has_no_entries_by_the_rule():
    short = "Kapitel 1 ...... 3"                        # 18 characters
    assert sections._directory_metrics(short)[1] == 0
    with rules.overlaid(directory_min_chars=10):
        assert sections._directory_metrics(short)[1] == 1


def test_an_entry_is_as_long_as_the_rule_allows():
    line = ("K" * 100 + " ........ 3 ") * 3
    share = sections._directory_metrics(line)[0]
    assert share < 0.9                                   # 90 of 100 letters
    with rules.overlaid(directory_entry_max_chars=150):
        assert sections._directory_metrics(line)[0] > 0.95
    with rules.overlaid(directory_entry_max_chars=20):
        assert sections._directory_metrics(line)[0] < share


def test_a_list_of_figures_opens_with_the_words_of_the_rule():
    lines = "".join(f"Abbildung {i} Wärmebedarf 2020 {i + 10}\n"
                    for i in range(5))
    assert sections._directory_metrics(lines)[1] == 5        # kwp
    with rules.overlaid(directory_figure_words=["Figure"]):
        assert sections._directory_metrics(lines)[1] == 0


def test_a_bibliography_is_never_a_directory():
    assert not sections._is_directory_section(_section("Literatur", ENTRIES))
    with rules.overlaid(bibliography_title_words=["zzz"]):
        assert sections._is_directory_section(_section("Literatur", ENTRIES))
    with rules.overlaid(bibliography_title_words=["verzeichnis"]):
        assert not sections._is_directory_section(
            _section("Inhaltsverzeichnis", ENTRIES))


# -- 5: captions, names, unicode ----------------------------------------------

def test_a_text_opens_a_caption_as_the_patterns_of_the_rule_say():
    assert captions.looks_like_a_caption("Tabelle 3: Bedarf")
    assert not captions.looks_like_a_caption("Bild 3: Bedarf") is False
    with rules.overlaid(caption_opener_patterns=[r"^Zzz\s+\d+:"]):
        assert not captions.looks_like_a_caption("Tabelle 3: Bedarf")
        assert captions.looks_like_a_caption("Zzz 3: Bedarf")


def test_a_pattern_that_matches_every_text_is_refused():
    with rules.overlaid(caption_opener_patterns=["x*"]):
        with pytest.raises(ValueError, match="empty text"):
            captions.looks_like_a_caption("Tabelle 3: Bedarf")
    with rules.overlaid(caption_opener_patterns=["("]):
        with pytest.raises(ValueError, match="does not compile"):
            captions.looks_like_a_caption("Tabelle 3: Bedarf")


def _text_page():
    return PageData(page_number=1, width_pt=600, height_pt=800,
                    blocks=[_plain("a", "Ein Satz ohne Überschrift.", 100)])


def test_the_text_before_the_first_heading_is_named_by_the_rule():
    assert sections.build_sections([_text_page()], "single")[0].title \
        == "Dokument"                                           # kwp
    with rules.overlaid(front_section_title="Vorspann"):
        assert sections.build_sections([_text_page()], "single")[0].title \
            == "Vorspann"


def test_a_part_with_no_title_is_named_by_the_rule():
    from docpipe.refinement.split import apply_cuts
    section = {"title": "", "segments": [
        {"kind": "text", "text": "Eins", "page": 1},
        {"kind": "text", "text": "Zwei", "page": 1}]}
    parts = apply_cuts(section, [{"at": 1, "title": ""}])
    assert [p["title"] for p in parts] == ["Abschnitt (1)", "Abschnitt (2)"]
    with rules.overlaid(part_section_title="Teil"):
        parts = apply_cuts(section, [{"at": 1, "title": ""}])
    assert [p["title"] for p in parts] == ["Teil (1)", "Teil (2)"]


def test_text_is_brought_to_the_normal_form_by_the_switch():
    assert clean_unicode("m² ﬁx") == "m2 fix"
    with rules.overlaid(normalize_unicode_nfkc=False):
        assert clean_unicode("m² ﬁx") == "m² ﬁx"
        # the removals are made in either case
        assert clean_unicode("a\ud800b") == "ab"
        assert clean_data({"k": ["m²"]}) == {"k": ["m²"]}
    assert clean_data({"k": ["m²"]}) == {"k": ["m2"]}
