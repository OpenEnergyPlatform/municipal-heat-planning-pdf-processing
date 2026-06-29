"""Tests for the deterministic cleanup passes added before the rerun:
running header/footer stripping + directory removal (Stage 3) and the
title-cleanup guarantee (Stage 4)."""
from scripts.preprocessing.models import Block, PageData, Section
from scripts.preprocessing import stage3_structure as s3
from scripts.preprocessing import stage4_refine as s4


def _page(n, blocks, h=842.0):
    pg = PageData(page_number=n, width_pt=595.0, height_pt=h)
    pg.blocks = blocks
    return pg


# ── running header / footer stripping ──────────────────────────────────────

def _hdr_block(pno):
    # top zone (y_center 60 < 0.12*842 = 101)
    return Block(id=f"p{pno}_h", type="text", bbox=[157, 46, 527, 74],
                 content="Kommunale Wärmeplanung Osnabrück")


def _body_block(pno):
    return Block(id=f"p{pno}_t", type="text", bbox=[71, 400, 527, 500],
                 content=f"Echter Fließtext auf Seite {pno} mit Inhalt.")


def test_running_header_block_is_stripped_across_pages():
    pages = [_page(p, [_hdr_block(p), _body_block(p)]) for p in range(1, 7)]
    n = s3.strip_running_headers(pages)
    assert n == 6  # one header per page removed
    remaining = [b.content for pg in pages for b in pg.blocks]
    assert all("Kommunale Wärmeplanung" not in c for c in remaining)
    assert any("Echter Fließtext" in c for c in remaining)


def test_header_zone_title_block_is_not_stripped():
    # Same repeated text but labelled as a section title → must survive.
    pages = []
    for p in range(1, 7):
        t = Block(id=f"p{p}_h", type="text", bbox=[157, 46, 527, 74],
                  content="Anhang", layout_label="paragraph_title")
        pages.append(_page(p, [t, _body_block(p)]))
    n = s3.strip_running_headers(pages)
    assert n == 0
    assert any(b.content == "Anhang" for pg in pages for b in pg.blocks)


def test_non_repeating_top_block_is_kept():
    pages = [_page(p, [_body_block(p)]) for p in range(1, 7)]
    # a one-off heading-zone block on a single page
    pages[0].blocks.insert(0, Block(id="x", type="text", bbox=[157, 46, 527, 74],
                                    content="Nur einmal hier oben"))
    n = s3.strip_running_headers(pages)
    assert n == 0


def test_header_strip_noop_for_short_docs():
    pages = [_page(p, [_hdr_block(p), _body_block(p)]) for p in range(1, 4)]
    assert s3.strip_running_headers(pages) == 0  # < 4 pages → skip


# ── directory / index section removal ──────────────────────────────────────

def _sec(title, content, **kw):
    return Section(title=title, content=content, **kw)


def test_toc_section_is_dropped():
    toc = _sec("Inhaltsverzeichnis",
               "Einleitung ............ 10 Grundlagen ............ 15 "
               "Methodik ............ 20 Ergebnisse ............ 25 ")
    prose = _sec("Einleitung", "Dies ist ein normaler Fließtext über die Wärmeplanung der Stadt.")
    kept, dropped = s3.drop_directory_sections([toc, prose])
    assert dropped == 1
    assert [s.title for s in kept] == ["Einleitung"]


def test_list_of_figures_section_is_dropped():
    lof = _sec("Abbildungsverzeichnis",
               "Abbildung 1: Organisationsstruktur der KWP 13 "
               "Abbildung 2: Ansatz der Faktoren 19 "
               "Abbildung 3: Verwendungsmöglichkeiten 27 "
               "Abbildung 4: Übersicht der Arbeitsphasen 31 ")
    kept, dropped = s3.drop_directory_sections([lof])
    assert dropped == 1 and kept == []


def test_literature_section_is_protected_from_directory_drop():
    # Looks list-like, but the title marks it as a bibliography → keep for BibTeX.
    lit = _sec("Quellenverzeichnis",
               "Mueller, H. (2023): Wärmeplanung. 10 "
               "Schmidt, K. (2022): Energie. 15 "
               "Weber, L. (2021): Netze. 20 "
               "Klein, P. (2020): Wende. 25 ")
    kept, dropped = s3.drop_directory_sections([lit])
    assert dropped == 0 and kept[0].title == "Quellenverzeichnis"


def test_media_placeholder_section_is_protected():
    # An appendix of maps: figure references with real placeholders → keep.
    anhang = _sec("Anhang A",
                  "[p5_img0] Abbildung 37: Stadtteil Bardenbach 13 "
                  "[p6_img0] Abbildung 45: Büschfeld 19 "
                  "[p7_img0] Abbildung 53: Dagstuhl 27 "
                  "[p8_img0] Abbildung 61: Gehweiler 31 ")
    kept, dropped = s3.drop_directory_sections([anhang])
    assert dropped == 0 and kept[0].title == "Anhang A"


def test_real_prose_section_is_kept():
    prose = _sec("Fazit und Ausblick",
                 "Mit der Erstellung des kommunalen Wärmeplans hat die "
                 "Gemeindeverwaltung einen wichtigen Schritt getan. Die Umsetzung "
                 "erfolgt schrittweise bis 2040.")
    kept, dropped = s3.drop_directory_sections([prose])
    assert dropped == 0


def test_mistitled_toc_fragment_is_dropped():
    # A TOC page whose section title is a chapter heading, but whose content is
    # pure dot-leader listing from the very start → dropped via head+residual.
    toc = _sec("5 Räumliches Verbrauchs- und Versorgungskonzept",
               "5.1 Zielszenario ............ 62 5.2 Eignungsgebiete ............ 71 "
               "5.3 Teilgebietssteckbriefe ............ 80 "
               "5.4 Umsetzungspfade ............ 90 ")
    kept, dropped = s3.drop_directory_sections([toc])
    assert dropped == 1 and kept == []


def test_section_with_prose_intro_then_listing_is_kept():
    # A "Maßnahmen" overview that opens with a real sentence before listing the
    # measure steckbriefe → the prose intro must protect it from the drop.
    mix = _sec("Übersicht Maßnahmensteckbriefe",
               "Nachfolgend werden die hier aufgeführten Maßnahmen als Steckbriefe "
               "ausführlich beschrieben und in ihrer Wirkung bewertet. "
               "M-1: Vorstudien ............ 45 M-2: Sanierungsfahrplan ............ 48 "
               "M-3: Wärmenetz ............ 51 M-4: Monitoring ............ 54 ")
    kept, dropped = s3.drop_directory_sections([mix])
    assert dropped == 0 and kept[0].title == "Übersicht Maßnahmensteckbriefe"


# ── deterministic title cleanup (Stage 4) ──────────────────────────────────

def test_numbering_prefix_is_stripped():
    assert s4._normalize_title("6.1 Wärmebedarfsanalyse") == "Wärmebedarfsanalyse"
    assert s4._normalize_title("3.3.3 Szenarien") == "Szenarien"
    assert s4._normalize_title("4 Anhang") == "Anhang"
    assert s4._normalize_title("A. Methodik") == "Methodik"
    assert s4._normalize_title("IV. Ziele") == "Ziele"


def test_all_caps_is_deshouted_keeping_acronyms():
    assert s4._normalize_title("POTENTIALANALYSE") == "Potentialanalyse"
    # short acronyms preserved
    assert s4._normalize_title("KWP Grundlagen") == "KWP Grundlagen"


def test_literature_sentinel_and_years_untouched():
    assert s4._normalize_title("[LITERATURE]") == "[LITERATURE]"
    assert s4._normalize_title("2030 Ziele") == "2030 Ziele"   # year, not a prefix
    assert s4._normalize_title("Wärmebedarfsanalyse") == "Wärmebedarfsanalyse"
