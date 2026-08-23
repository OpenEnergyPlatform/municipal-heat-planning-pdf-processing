"""Pages with no text layer: what the model is asked for, and what is done
with the answer.

The eleven plans behind this module have no text layer at all. Every section
Stage 3 built for them was a body of bare [pNN_tbl0] markers, refinement read
that as an empty section and removed it, and 1270 transcribed tables and
figures went with it.
"""
import pytest

from docpipe.preprocessing.models import Block, PageData
from docpipe.preprocessing.page_text_fallback import (
    fill_missing_page_text, needs_transcription, page_text_length,
    split_into_blocks, synthesize_blocks)


def _page(number=1, texts=(), width=595.0, height=842.0):
    page = PageData(page_number=number, width_pt=width, height_pt=height)
    for i, t in enumerate(texts):
        page.blocks.append(Block(id=f"p{number-1}_t{i}", type="text",
                                 bbox=[50.0, 50.0 + 20 * i, 500.0, 65.0 + 20 * i],
                                 content=t))
    return page


def _table_block(number=1):
    return Block(id=f"p{number-1}_tbl0", type="table",
                 bbox=[40.0, 300.0, 550.0, 600.0], path="images/t.png")


# ---------------------------------------------------------------------------
# what counts as "no text layer"
# ---------------------------------------------------------------------------

def test_a_page_with_no_text_blocks_needs_the_model():
    page = _page(texts=())
    page.blocks.append(_table_block())
    assert page_text_length(page) == 0
    assert needs_transcription(page)


def test_a_stamped_page_number_is_not_a_text_layer():
    """A vector-graphic page often carries a page number or a copyright line
    from a digital overlay. That is text by the letter and nothing by the
    meaning, so the threshold is not zero."""
    assert needs_transcription(_page(texts=("Seite 14",)))


def test_an_ordinary_page_is_left_alone():
    body = "Der Endenergieverbrauch der Gemeinde betrug im Jahr 2020 " \
           "insgesamt 45.000 MWh, verteilt auf die Sektoren."
    assert not needs_transcription(_page(texts=(body,)))


# ---------------------------------------------------------------------------
# turning a transcription into blocks
# ---------------------------------------------------------------------------

def test_a_heading_always_starts_its_own_block():
    """Stage 3 finds titles by font size and boldness, and a transcription has
    neither. A heading has to arrive as its own block to have any chance."""
    blocks = split_into_blocks("# Bestandsanalyse\nErster Absatz.\n\nZweiter.")
    assert blocks == ["# Bestandsanalyse", "Erster Absatz.", "Zweiter."]


def test_headings_become_the_font_signal_stage_three_reads():
    page = _page(texts=())
    blocks = synthesize_blocks(page, "# Titel\n\nFliesstext hier.\n\n## Unterpunkt")
    assert [b.content for b in blocks] == ["Titel", "Fliesstext hier.", "Unterpunkt"]
    assert blocks[0].font_bold and blocks[0].font_size > blocks[2].font_size
    assert not blocks[1].font_bold, "body text is not a heading"


def test_every_synthesized_box_says_it_was_not_measured():
    """A stacked rectangle points at the right page and region. It is not a
    located line, and nothing downstream may present it as one."""
    blocks = synthesize_blocks(_page(texts=()), "# A\n\nB\n\nC")
    assert all(b.bbox_approx for b in blocks)
    assert all(b.to_dict()["bbox_approx"] is True for b in blocks), \
        "the flag has to survive into pages.json"


def test_boxes_run_down_the_page_in_reading_order():
    blocks = synthesize_blocks(_page(texts=()), "Erster.\n\nZweiter.\n\nDritter.")
    tops = [b.bbox[1] for b in blocks]
    assert tops == sorted(tops)
    assert blocks[0].bbox[1] >= 0 and blocks[-1].bbox[3] <= 842.0


def test_an_empty_transcription_yields_no_blocks():
    assert synthesize_blocks(_page(texts=()), "   \n\n  ") == []


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------

def test_only_the_pages_without_text_reach_the_model():
    pages = [_page(1, texts=()), _page(2, texts=("Ein ordentlicher Absatz mit "
                                                 "genug Text, um als Textlayer "
                                                 "zu zaehlen.",)),
             _page(3, texts=())]
    asked = []

    report = fill_missing_page_text(
        pages, render=lambda n: f"image-{n}",
        transcribe=lambda img, n: asked.append(n) or f"# Seite {n}\n\nInhalt.")
    assert asked == [1, 3], "the page that had text was not sent"
    assert report["pages_missing_text"] == 2
    assert report["pages_transcribed"] == 2
    assert report["blocks_added"] == 4


def test_the_transcription_replaces_the_junk_text_layer_and_keeps_the_media():
    page = _page(1, texts=("Seite 14",))
    page.blocks.append(_table_block())
    fill_missing_page_text([page], render=lambda n: "img",
                           transcribe=lambda img, n: "# Bestand\n\nDer Verbrauch.")
    kinds = [b.type for b in page.blocks]
    assert kinds.count("table") == 1, "Stage 2's table survived"
    assert "Seite 14" not in [b.content for b in page.blocks], \
        "the junk text layer was replaced, not appended to"
    assert [b.content for b in page.blocks if b.type == "text"] == \
        ["Bestand", "Der Verbrauch."]


def test_a_failed_page_keeps_an_empty_text_layer_rather_than_an_invented_one():
    pages = [_page(1, texts=()), _page(2, texts=())]

    def transcribe(img, n):
        if n == 1:
            raise RuntimeError("model timed out")
        return "Zweite Seite gelesen."

    report = fill_missing_page_text(pages, render=lambda n: "img",
                                    transcribe=transcribe)
    assert report["pages_failed"] == 1 and report["pages_transcribed"] == 1
    assert pages[0].blocks == [], "nothing was invented for the failed page"


def test_an_empty_reply_counts_as_a_failure_not_as_a_blank_page():
    report = fill_missing_page_text([_page(1, texts=())], render=lambda n: "img",
                                    transcribe=lambda img, n: "   ")
    assert report["pages_failed"] == 1 and report["pages_transcribed"] == 0


def test_a_corpus_wide_run_is_capped_rather_than_spending_the_night():
    pages = [_page(n, texts=()) for n in range(1, 11)]
    asked = []
    report = fill_missing_page_text(
        pages, render=lambda n: "img",
        transcribe=lambda img, n: asked.append(n) or "Text.",
        max_pages=3)
    assert len(asked) == 3
    assert report["pages_missing_text"] == 10, "the count still tells the truth"


def test_a_document_that_needs_nothing_makes_no_calls():
    page = _page(1, texts=("Ein ordentlicher Absatz mit reichlich Text darin, "
                           "mehr als die Schwelle verlangt.",))
    calls = []
    report = fill_missing_page_text(
        [page], render=lambda n: calls.append(n),
        transcribe=lambda img, n: "sollte nie passieren")
    assert calls == [] and report["pages_transcribed"] == 0


# ---------------------------------------------------------------------------
# the wiring: off by default, and it leaves a report behind
# ---------------------------------------------------------------------------

def test_the_fallback_is_off_unless_asked_for(tmp_path, monkeypatch):
    """Preprocessing is deterministic and needs no model server. The one part
    that does must never switch itself on, or every run starts depending on an
    endpoint being up."""
    from docpipe.preprocessing import pipeline as pl

    called = []
    monkeypatch.setattr(pl, "_fill_missing_page_text",
                        lambda *a, **k: called.append(1) or {})
    monkeypatch.setattr(pl, "_load_pages_cache",
                        lambda out: [_page(1, texts=("Ein Absatz mit Text.",))])
    monkeypatch.setattr(pl, "build_sections", lambda pages, column_layout="auto": [])
    monkeypatch.setattr(pl, "sections_to_dict", lambda *a, **k: {"sections": []})
    monkeypatch.setattr(pl, "save_output", lambda *a, **k: None)

    pl.run_single(pdf_path=tmp_path / "doc.pdf", output_dir=tmp_path / "out")
    assert called == [], "the model was asked without anyone asking for it"


def test_the_report_is_written_even_when_nothing_needed_doing(tmp_path,
                                                             monkeypatch):
    """An empty report is checked-and-clean. A missing one means nobody
    looked, and those two must not be indistinguishable."""
    import json

    from docpipe.artifacts import PAGE_TRANSCRIPTION_REPORT_JSON
    from docpipe.preprocessing import pipeline as pl
    from docpipe.preprocessing import page_text_fallback as fb

    monkeypatch.setattr(fb, "make_page_renderer", lambda pdf, out: (lambda n: None))
    monkeypatch.setattr(fb, "make_transcriber", lambda profile: (lambda img, n: None))

    out = tmp_path / "out"
    page = _page(1, texts=("Ein ordentlicher Absatz mit reichlich Text darin, "
                           "deutlich mehr als die Schwelle verlangt.",))
    report = pl._fill_missing_page_text(tmp_path / "doc.pdf", out, [page],
                                        profile=object())
    written = json.loads((out / PAGE_TRANSCRIPTION_REPORT_JSON).read_text(
        encoding="utf-8"))
    assert written == report
    assert written["pages_missing_text"] == 0


def test_concurrent_reading_still_applies_pages_in_order(monkeypatch):
    """The GPU is only busy if pages go out together, but the result must not
    depend on which page the server happened to finish first."""
    pages = [_page(n, texts=()) for n in range(1, 6)]
    report = fill_missing_page_text(
        pages, render=lambda n: f"img-{n}",
        transcribe=lambda img, n: f"Seite {n}.", workers=4)
    assert report["pages_transcribed"] == 5
    assert [p.blocks[0].content for p in pages] == \
        [f"Seite {n}." for n in range(1, 6)]


def test_one_failing_page_does_not_take_the_others_down_when_concurrent():
    pages = [_page(n, texts=()) for n in range(1, 5)]

    def transcribe(img, n):
        if n == 2:
            raise RuntimeError("timeout")
        return f"Seite {n}."

    report = fill_missing_page_text(pages, render=lambda n: "img",
                                    transcribe=transcribe, workers=4)
    assert report["pages_transcribed"] == 3 and report["pages_failed"] == 1
    assert pages[1].blocks == []
