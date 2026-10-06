"""Pages with no text layer: what the model is asked for, and what is done
with the answer.

The eleven plans behind this module have no text layer at all. Every section
Stage 3 built for them was a body of bare [pNN_tbl0] markers, refinement read
that as an empty section and removed it, and 1270 transcribed tables and
figures went with it.
"""
import pytest

from docpipe.reading import Hole
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


def test_headings_carry_the_label_stage_three_opens_sections_on():
    """Stage 3 opens a section on layout_label in SECTION_TITLE_CLASSES, NOT on
    the font size. Without the label every transcribed page lands back in one
    pseudo-section, which is the failure this module exists to end. Measured on
    a real document before the label was set: 48 synthesized blocks, still 1
    section."""
    from docpipe.preprocessing.config import SECTION_TITLE_CLASSES

    page = _page(texts=())
    blocks = synthesize_blocks(page, "# Titel\n\nFliesstext hier.\n\n## Unterpunkt")
    assert [b.content for b in blocks] == ["Titel", "Fliesstext hier.", "Unterpunkt"]
    assert blocks[0].layout_label in SECTION_TITLE_CLASSES
    assert blocks[2].layout_label in SECTION_TITLE_CLASSES
    assert blocks[1].layout_label == "text", "body text must not open a section"
    assert blocks[0].font_bold and blocks[0].font_size > blocks[2].font_size


def test_stage_three_really_splits_a_transcribed_page_into_sections():
    """The end-to-end property, checked against Stage 3 itself rather than a
    stand-in for it."""
    from docpipe.preprocessing.stage3_structure import build_sections

    page = _page(texts=())
    page.blocks = synthesize_blocks(
        page, "# Bestandsanalyse\n\nDer Verbrauch lag bei 45.000 MWh.\n\n"
              "# Zielszenario\n\nBis 2040 sinkt er auf 20.000 MWh.")
    sections = build_sections([page], column_layout="auto")
    titles = [s.title for s in sections]
    assert "Bestandsanalyse" in titles and "Zielszenario" in titles, titles


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


def test_a_page_with_nothing_on_it_is_not_a_failed_page():
    """The prompt tells the model to answer "" for a page that is one large
    map, and a heat plan is full of those. Booking that as a failure reported
    106 broken calls for a run in which not one call broke."""
    report = fill_missing_page_text([_page(1, texts=())], render=lambda n: "img",
                                    transcribe=lambda img, n: "   ")
    assert report["pages_empty"] == 1
    assert report["pages_failed"] == 0
    assert report["pages_transcribed"] == 0


def test_a_broken_call_and_an_empty_page_are_counted_apart():
    """Both leave the page without text, and only one of them is a problem."""
    pages = [_page(n, texts=()) for n in range(1, 4)]

    def transcribe(img, n):
        if n == 1:
            raise RuntimeError("model timed out")
        return "" if n == 2 else "# Bestand\n\nDer Verbrauch."

    report = fill_missing_page_text(pages, render=lambda n: "img",
                                    transcribe=transcribe)
    assert (report["pages_failed"], report["pages_empty"],
            report["pages_transcribed"]) == (1, 1, 1)
    assert pages[0].blocks == [] and pages[1].blocks == []
    assert report["pages_missing_text"] == 3, "the total still adds up"


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

    monkeypatch.setattr(fb, "make_page_renderer", lambda pdf: (lambda n: None))
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


def test_rendering_is_bounded_but_transcription_is_not():
    """Render and transcribe used to share one slot, so eight workers meant
    eight requests at a server that schedules hundreds — and every one of them
    spent part of its slot in PyMuPDF and the PNG encoder holding the GIL.

    Not timing-based: the barrier only clears if four transcriptions are in
    flight at once, and the render counter is read while renders are blocked.
    (conftest patches time.sleep globally, so a sleep here would prove
    nothing.)
    """
    import threading

    from docpipe.preprocessing.page_text_fallback import fill_missing_page_text

    lock = threading.Lock()
    live = 0
    peak = 0
    blocked = threading.Event()          # never set: Event.wait is a real wait
    together = threading.Barrier(4, timeout=10)
    cleared = []

    def render(page_number):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        blocked.wait(0.05)
        with lock:
            live -= 1
        return f"page{page_number}.png"

    def transcribe(image, page_number):
        try:
            together.wait()
            cleared.append(page_number)
        except threading.BrokenBarrierError:
            pass
        return "Ein Satz mit genug Text."

    pages = [_page(n) for n in range(1, 33)]
    fill_missing_page_text(pages, render, transcribe, workers=16,
                           render_workers=2)

    assert peak <= 2, f"{peak} renders at once, limit was 2"
    assert len(cleared) >= 4, (
        "four transcriptions never overlapped — the model call is still held "
        "to the render limit")


# ---------------------------------------------------------------------------
# A reply that is not the one object is a page with no text and a cause.
#
# Promised: a page's text is the `markdown` of exactly one JSON object AND a
# reply that is anything else leaves the page without text and names the cause
# in the report AND "" is an answer, not a failure AND a cut reply is asked once
# more with more room (tests/test_room.py: how much) and is a hole if cut
# again.
# ---------------------------------------------------------------------------

from types import SimpleNamespace as NS


def _answer(content, finish="stop"):
    return NS(choices=[NS(finish_reason=finish, message=NS(
        content=content, reasoning_content=None))], usage=None)


def _transcriber(*answers):
    """(transcribe, requests): the live transcriber over a scripted server."""
    from docpipe.preprocessing.page_text_fallback import make_transcriber

    asked, queue = [], list(answers)

    def create(**kwargs):
        asked.append(kwargs)
        return queue.pop(0) if queue else answers[-1]

    client = NS(chat=NS(completions=NS(create=create)))
    return make_transcriber(None, client=client, model="m"), asked


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "p.png"
    p.write_bytes(b"\x89PNG\r\n")
    return p


def _report_for(transcribe, png):
    pages = [_page(1, texts=())]
    # The page image is deleted after its call, so every call gets its own.
    return fill_missing_page_text(
        pages, render=lambda n: _copy(png), transcribe=transcribe), pages


def _copy(png):
    import shutil
    own = png.with_name(f"own_{len(list(png.parent.iterdir()))}.png")
    shutil.copy(png, own)
    return own


def test_the_object_with_its_markdown_is_the_pages_text(png):
    transcribe, asked = _transcriber(_answer('{"markdown": "# Bestand\\n\\nText."}'))
    report, pages = _report_for(transcribe, png)
    assert report["pages_transcribed"] == 1 and report["failed_pages"] == []
    assert [b.content for b in pages[0].blocks] == ["Bestand", "Text."]
    assert asked[0]["response_format"]["json_schema"]["name"] == "page_reply", (
        "the schema goes out as the grammar of the request")


def test_an_empty_markdown_is_an_answer_and_not_a_failure(png):
    """The page is one large map and holds no prose."""
    transcribe, asked = _transcriber(_answer('{"markdown": ""}'))
    report, pages = _report_for(transcribe, png)
    assert (report["pages_empty"], report["pages_failed"]) == (1, 0)
    assert len(asked) == 1, "an answer is not asked again"


@pytest.mark.parametrize("content, cause", [
    ('{"text": "Seite"}', "missing_key"),
    ('{"markdown": 5}', "missing_key"),
    ('["markdown"]', "not_an_object"),
    ('Hier die Seite: {"markdown": "Text"}', "outside_text"),
    ('{"markdown": "Text"', "syntax"),
    ('', "empty"),
])
def test_a_reply_that_is_not_the_object_leaves_the_page_without_text_and_says_why(
        png, content, cause):
    """The case that violates the promise by construction: the model keeps
    answering something else, and nothing of it becomes the page's text."""
    transcribe, asked = _transcriber(_answer(content))
    report, pages = _report_for(transcribe, png)
    assert pages[0].blocks == [], "nothing was cut out of the reply"
    assert report["pages_failed"] == 1 and report["pages_transcribed"] == 0
    assert report["failed_pages"] == [{"page": 1, "why": cause}]


def test_a_reply_cut_off_twice_is_a_hole_after_one_request_with_more_room(png):
    """No preflight was asked here, so the window is not known and the room is
    twice (the room a known window leaves is held in tests/test_room.py)."""
    transcribe, asked = _transcriber(
        _answer('{"markdown": "Ein Anfang der', "length"))
    report, pages = _report_for(transcribe, png)
    assert report["failed_pages"] == [{"page": 1, "why": "cut_off"}]
    assert pages[0].blocks == [], "half a page is not a page"
    assert [r["max_tokens"] for r in asked] == [
        asked[0]["max_tokens"], 2 * asked[0]["max_tokens"]]


def test_the_failed_pages_are_the_pages_that_were_counted_failed():
    pages = [_page(n, texts=()) for n in range(1, 6)]
    cuts = {2: Hole("cut_off"), 4: Hole("syntax")}
    report = fill_missing_page_text(
        pages, render=lambda n: "img", workers=4,
        transcribe=lambda img, n: cuts.get(n) or ("" if n == 5 else "Text."))
    assert report["pages_failed"] == len(report["failed_pages"]) == 2
    assert report["failed_pages"] == [{"page": 2, "why": "cut_off"},
                                      {"page": 4, "why": "syntax"}]
    assert (report["pages_empty"], report["pages_transcribed"]) == (1, 2)


def test_a_transcriber_that_answers_neither_text_nor_a_hole_is_an_error_hole():
    report = fill_missing_page_text([_page(1, texts=())], render=lambda n: "img",
                                    transcribe=lambda img, n: None)
    assert report["failed_pages"] == [{"page": 1, "why": "error"}]


def test_a_page_that_cannot_be_rendered_is_an_error_hole():
    report = fill_missing_page_text([_page(1, texts=())], render=lambda n: None,
                                    transcribe=lambda img, n: "never asked")
    assert report["failed_pages"] == [{"page": 1, "why": "error"}]


def test_the_budget_of_the_page_request_counts_one_reply():
    """The vision server is started for the largest request: the prompt, one
    page image and ONE reply. A page cut at its limit is asked again with more
    room, which comes out of what the served window leaves beyond this number
    and is not part of it."""
    from docpipe import prompts
    from docpipe.preprocessing.page_text_fallback import (
        PAGE_MAX_TOKENS, PAGE_TRANSCRIBE_PROMPT_ID, page_request_tokens)
    from docpipe.visuals.config import IMAGE_TOKENS, TOKENS_PER_WORD

    prompt = prompts.load(PAGE_TRANSCRIBE_PROMPT_ID, None)
    room = int((prompt.meta or {}).get("max_tokens", PAGE_MAX_TOKENS))
    assert page_request_tokens(None) == int(
        len(prompt.text.split()) * TOKENS_PER_WORD + IMAGE_TOKENS + room)
    # the case built to violate it: a budget with a second reply in it
    assert page_request_tokens(None) != int(
        len(prompt.text.split()) * TOKENS_PER_WORD + IMAGE_TOKENS + 2 * room)


# ---------------------------------------------------------------------------
# The document level: what is said, what is kept, what the exit code is.
# ---------------------------------------------------------------------------

def test_a_document_with_failed_pages_adds_one_entry_in_pages_and_causes(
        tmp_path, monkeypatch):
    from docpipe.preprocessing import page_text_fallback as fb
    from docpipe.preprocessing import pipeline as pl

    monkeypatch.setattr(fb, "make_page_renderer", lambda pdf: (lambda n: "img"))
    monkeypatch.setattr(fb, "make_transcriber", lambda profile: (
        lambda img, n: Hole("cut_off") if n < 3 else "Text."))
    holes = []
    pages = [_page(n, texts=()) for n in range(1, 5)]
    out = tmp_path / "doc"
    pl._fill_missing_page_text(tmp_path / "doc.pdf", out, pages,
                               profile=object(), holes=holes)
    assert holes == [{"document": "doc", "pages": 2, "causes": {"cut_off": 2}}]
    assert "2 page(s) in 1 document(s)" in pl.summarise(holes)
    assert "cut_off 2" in pl.summarise(holes)


def test_a_document_without_failed_pages_adds_no_entry(tmp_path, monkeypatch):
    from docpipe.preprocessing import page_text_fallback as fb
    from docpipe.preprocessing import pipeline as pl

    monkeypatch.setattr(fb, "make_page_renderer", lambda pdf: (lambda n: "img"))
    monkeypatch.setattr(fb, "make_transcriber",
                        lambda profile: (lambda img, n: ""))
    holes = []
    pl._fill_missing_page_text(tmp_path / "doc.pdf", tmp_path / "doc",
                               [_page(1, texts=())], profile=object(),
                               holes=holes)
    assert holes == [], "an empty page is an answer, not a hole"


def _stage3_cache(tmp_path, monkeypatch, transcribed, holes=None, seen=None,
                  page_server=None):
    """run_single over a stored page cache whose Stage 3 file already exists.
    *seen*, when given, is filled with the keywords the page transcription was
    called with."""
    from docpipe.artifacts import SECTIONS_JSON
    from docpipe.preprocessing import pipeline as pl

    out = tmp_path / "out"
    cache = out / SECTIONS_JSON
    cache.parent.mkdir(parents=True)
    cache.write_text('{"sections": [{"title": "old", "tables": [], '
                     '"figures": []}]}', encoding="utf-8")
    built = []

    def fill(*args, **kwargs):
        if seen is not None:
            seen.update(kwargs)
        return {"pages_transcribed": transcribed}

    monkeypatch.setattr(pl, "_load_pages_cache", lambda o: [_page(1, texts=())])
    monkeypatch.setattr(pl, "_fill_missing_page_text", fill)
    monkeypatch.setattr(pl, "build_sections",
                        lambda pages, column_layout="auto": built.append(1) or [])
    monkeypatch.setattr(pl, "sections_to_dict", lambda *a, **k: {
        "sections": [{"title": "new", "tables": [], "figures": []}]})
    monkeypatch.setattr(pl, "save_output", lambda *a, **k: None)
    result = pl.run_single(pdf_path=tmp_path / "doc.pdf", output_dir=out,
                           transcribe_missing_text=True, holes=holes,
                           page_server=page_server)
    return result, built


def test_a_run_that_transcribed_pages_does_not_reuse_the_stage_three_built_before(
        tmp_path, monkeypatch):
    result, built = _stage3_cache(tmp_path, monkeypatch, transcribed=2)
    assert built == [1], "Stage 3 was built again from the richer pages"
    assert result["sections"][0]["title"] == "new"


def test_a_run_that_transcribed_nothing_keeps_the_stage_three_cache(
        tmp_path, monkeypatch):
    """The case that makes the one above able to fail: dropping the cache on
    every run would be a rebuild that nothing asked for."""
    result, built = _stage3_cache(tmp_path, monkeypatch, transcribed=0)
    assert built == [], "nothing changed, so the cache stands"
    assert result["sections"][0]["title"] == "old"


# ---------------------------------------------------------------------------
# The list of holes travels from the command to the page transcription
# ---------------------------------------------------------------------------

def test_a_document_hands_its_page_holes_to_the_transcription(tmp_path,
                                                              monkeypatch):
    """Nothing else in this file runs run_single over the transcription: a
    document that dropped the list would leave every other test green and the
    run saying nothing of its pages."""
    holes, seen = [], {}
    _stage3_cache(tmp_path, monkeypatch, transcribed=0, holes=holes, seen=seen)
    assert seen["holes"] is holes


def _two_cached_pdfs(tmp_path):
    """A folder of two PDFs whose extraction is cached, so that no layout
    model is loaded."""
    from docpipe.artifacts import PAGES_JSON

    source = tmp_path / "in"
    source.mkdir()
    for name in ("a", "b"):
        (source / f"{name}.pdf").write_bytes(b"%PDF")
        pages = tmp_path / "out" / name / PAGES_JSON
        pages.parent.mkdir(parents=True)
        pages.write_text("[]", encoding="utf-8")
    return source, tmp_path / "out"


def test_the_list_reaches_every_document_of_a_folder_and_a_single_file(
        tmp_path, monkeypatch):
    from docpipe.preprocessing import pipeline as pl

    given = []
    monkeypatch.setattr(pl, "run_single",
                        lambda **kw: given.append(kw["holes"]) or {})
    holes = []
    source, out = _two_cached_pdfs(tmp_path)

    pl.run(source, out, transcribe_missing_text=True, holes=holes)
    assert len(given) == 2 and all(g is holes for g in given), (
        "each of the two documents of the folder was given the list")

    given.clear()
    pl.run(source / "a.pdf", out, transcribe_missing_text=True, holes=holes)
    assert len(given) == 1 and given[0] is holes


def test_the_command_says_the_pages_a_document_of_the_run_could_not_read(
        tmp_path, monkeypatch, caplog):
    """From the command through `run` to the document: a hole a document adds
    is said once, at the end, in pages and documents, and the exit code is 0."""
    from docpipe.preprocessing import pipeline as pl

    def document(**kw):
        kw["holes"].append({"document": "in", "pages": 2,
                            "causes": {"cut_off": 2}})
        return {}

    monkeypatch.setattr(pl, "run_single", document)
    (tmp_path / "in.pdf").write_bytes(b"%PDF")
    code, _ = _main(monkeypatch, tmp_path, "--transcribe-missing-text",
                    run=pl.run)
    assert code == 0
    said = [r.getMessage() for r in caplog.records
            if "could not be read" in r.getMessage()]
    assert len(said) == 1 and "2 page(s) in 1 document(s)" in said[0]


# ---------------------------------------------------------------------------
# The command: a hole never changes the exit code, an unserved schema does.
# ---------------------------------------------------------------------------

def _main(monkeypatch, tmp_path, *flags, run=None, server=None):
    from docpipe import reading
    from docpipe.preprocessing import pipeline as pl

    said = []
    monkeypatch.setattr(reading, "phrases",
                        lambda *a, **k: said.append("phrases") or {})
    monkeypatch.setattr(pl, "_assert_page_server",
                        server or (lambda profile: said.append("server")))
    monkeypatch.setattr(pl, "run", run or (lambda **kw: {}))
    monkeypatch.setattr("sys.argv", ["prog", str(tmp_path / "in.pdf"),
                                     str(tmp_path / "out"), *flags])
    with pytest.raises(SystemExit) as exit_info:
        pl.main()
    return exit_info.value.code, said


def test_pages_without_text_leave_the_exit_code_at_zero_and_are_said_once(
        tmp_path, monkeypatch, caplog):
    def run(**kw):
        kw["holes"].append({"document": "d", "pages": 3,
                            "causes": {"syntax": 2, "cut_off": 1}})
        return {}

    code, _ = _main(monkeypatch, tmp_path, "--transcribe-missing-text", run=run)
    assert code == 0
    said = [r.getMessage() for r in caplog.records
            if "could not be read" in r.getMessage()]
    assert len(said) == 1 and "3 page(s) in 1 document(s)" in said[0]
    assert "cut_off 1, syntax 2" in said[0]


def test_a_run_without_holes_says_nothing_about_them(tmp_path, monkeypatch,
                                                     caplog):
    code, _ = _main(monkeypatch, tmp_path, "--transcribe-missing-text")
    assert code == 0
    assert not [r for r in caplog.records
                if "could not be read" in r.getMessage()]


def test_the_sentences_are_checked_first_and_a_run_without_such_pages_asks_no_server(
        tmp_path, monkeypatch):
    """Owner decision 2026-10-06: the server is asked when a page needs it.
    The run here sends no page, so the check it was handed is never called."""
    order = []
    code, said = _main(monkeypatch, tmp_path, "--transcribe-missing-text",
                       run=lambda **kw: order.append("run") or {})
    assert code == 0 and said == ["phrases"] and order == ["run"]


def test_the_server_is_asked_by_the_first_page_that_needs_it_and_once(
        tmp_path, monkeypatch):
    """Two documents with pages to send are one question to the server."""
    def run(**kw):
        kw["page_server"]()
        kw["page_server"]()
        return {}

    code, said = _main(monkeypatch, tmp_path, "--transcribe-missing-text",
                       run=run)
    assert code == 0 and said == ["phrases", "server"]


def _refuse(profile):
    from docpipe.llm_preflight import PreflightError
    raise PreflightError("page transcription: no server at the address")


def test_a_server_that_is_not_there_ends_the_run_when_a_page_needs_it(
        tmp_path, monkeypatch):
    sent = []

    def run(**kw):
        kw["page_server"]()
        sent.append("a page")
        return {}

    code, _ = _main(monkeypatch, tmp_path, "--transcribe-missing-text",
                    server=_refuse, run=run)
    assert code == 1 and sent == [], "no page went out after the refusal"


def test_a_server_that_is_not_there_is_no_matter_to_a_run_without_such_pages(
        tmp_path, monkeypatch):
    """The case the one above needs to be able to fail: the flag alone, with
    every page carrying its text, ends as it did before the check existed."""
    code, _ = _main(monkeypatch, tmp_path, "--transcribe-missing-text",
                    server=_refuse, run=lambda **kw: {})
    assert code == 0


def test_a_run_without_the_flag_is_handed_no_check(tmp_path, monkeypatch):
    seen = {}
    code, _ = _main(monkeypatch, tmp_path,
                    run=lambda **kw: seen.update(kw) or {})
    assert code == 0 and seen["page_server"] is None


def test_a_page_to_send_calls_the_check_before_anything_is_sent():
    order = []
    report = fill_missing_page_text(
        [_page(1, texts=())],
        render=lambda n: order.append("render") or "image",
        transcribe=lambda image, n: (order.append("transcribe")
                                     or "Text der Seite, lang genug."),
        before_first=lambda: order.append("check"))
    assert order == ["check", "render", "transcribe"]
    assert report["pages_transcribed"] == 1


def test_a_document_whose_pages_all_have_text_never_calls_the_check():
    body = "Der Endenergieverbrauch der Gemeinde betrug im Jahr 2020 " \
           "insgesamt 45.000 MWh, verteilt auf die Sektoren."
    called = []
    report = fill_missing_page_text(
        [_page(1, texts=(body,))], render=lambda n: 1 / 0,
        transcribe=lambda image, n: 1 / 0,
        before_first=lambda: called.append(1))
    assert called == [] and report["pages_missing_text"] == 0


def test_a_check_that_raises_sends_no_page():
    from docpipe.llm_preflight import PreflightError

    sent = []

    def check():
        raise PreflightError("no server")

    with pytest.raises(PreflightError):
        fill_missing_page_text(
            [_page(1, texts=())], render=lambda n: sent.append(n) or "image",
            transcribe=lambda image, n: "x", before_first=check)
    assert sent == []


def test_the_check_travels_from_the_run_to_every_document(tmp_path,
                                                         monkeypatch):
    """Dropped at the entry point or in the folder loop, the server would
    never be asked and every other test would stay green."""
    from docpipe.preprocessing import pipeline as pl

    def check():
        return None

    given = []
    monkeypatch.setattr(pl, "run_single",
                        lambda **kw: given.append(kw["page_server"]) or {})
    source, out = _two_cached_pdfs(tmp_path)
    pl.run(source, out, transcribe_missing_text=True, page_server=check)
    assert given == [check, check]
    given.clear()
    pl.run(source / "a.pdf", out, transcribe_missing_text=True,
           page_server=check)
    assert given == [check]


def test_a_document_hands_the_check_to_its_page_transcription(tmp_path,
                                                             monkeypatch):
    def check():
        return None

    seen = {}
    _stage3_cache(tmp_path, monkeypatch, transcribed=0, seen=seen,
                  page_server=check)
    assert seen["page_server"] is check


def test_the_page_transcription_calls_the_check_before_its_first_page(
        tmp_path, monkeypatch):
    from docpipe.preprocessing import page_text_fallback as fallback
    from docpipe.preprocessing import pipeline as pl

    def check():
        return None

    handed = {}
    monkeypatch.setattr(fallback, "fill_missing_page_text",
                        lambda pages, **kw: handed.update(kw) or {
                            "pages_transcribed": 0, "pages_failed": 0,
                            "failed_pages": []})
    monkeypatch.setattr(fallback, "make_page_renderer", lambda pdf: None)
    monkeypatch.setattr(fallback, "make_transcriber", lambda profile: None)
    pl._fill_missing_page_text(tmp_path / "doc.pdf", tmp_path / "report", [],
                               profile=object(), page_server=check)
    assert handed["before_first"] is check


def test_a_missing_server_ends_the_folder_and_is_not_one_failed_document(
        tmp_path, monkeypatch):
    """The folder loop turns a document's error into a failed document and
    goes on. A server that is not there is the run's error: it must come out
    of the loop, and the next document must not be started."""
    from docpipe.llm_preflight import PreflightError
    from docpipe.preprocessing import pipeline as pl

    started = []

    def document(**kw):
        started.append(kw["pdf_path"].name)
        raise PreflightError("no server")

    monkeypatch.setattr(pl, "run_single", document)
    source, out = _two_cached_pdfs(tmp_path)
    with pytest.raises(PreflightError):
        pl.run_folder(source, out, transcribe_missing_text=True)
    assert started == ["a.pdf"]


def test_another_error_of_a_document_still_leaves_the_folder_running(
        tmp_path, monkeypatch):
    """The case that keeps the one above honest: only the missing server ends
    the run, a broken document is one failed document as before."""
    from docpipe.preprocessing import pipeline as pl

    started = []

    def document(**kw):
        started.append(kw["pdf_path"].name)
        raise RuntimeError("this PDF is broken")

    monkeypatch.setattr(pl, "run_single", document)
    source, out = _two_cached_pdfs(tmp_path)
    results = pl.run_folder(source, out, transcribe_missing_text=True)
    assert started == ["a.pdf", "b.pdf"] and set(results.values()) == {None}


def test_the_page_check_asks_the_vision_server_for_the_page_schema_and_room(
        monkeypatch):
    """The check is the one that asks the server for `page_reply` (a stage
    that leaves its shape out is never refused), at the size of the largest
    page request."""
    from docpipe import llm_preflight
    from docpipe.preprocessing import pipeline as pl
    from docpipe.preprocessing.page_text_fallback import page_request_tokens

    seen = {}
    monkeypatch.setattr(llm_preflight, "assert_serving",
                        lambda *a, **k: seen.update(args=a, kwargs=k))
    pl._assert_page_server(None)
    assert list(seen["kwargs"]["shapes"]) == ["page_reply"]
    assert seen["args"][3] == page_request_tokens(None)
    assert seen["kwargs"]["role"] == "vlm"


def test_a_rebuild_of_stage_three_asks_the_model_nothing_even_with_the_flag(
        tmp_path, monkeypatch):
    """The rebuild reads the pages cache and sends no page to the model, so a
    server that is down, or a profile without the retry sentences, is no reason
    for it to end. The flag alone must not make the command need either."""
    code, said = _main(monkeypatch, tmp_path, "--transcribe-missing-text",
                       "--rebuild-stage3")
    assert code == 0 and said == []


def test_a_run_that_does_not_ask_for_the_model_needs_no_server(tmp_path,
                                                               monkeypatch):
    """Preprocessing without the flag is deterministic: no check, no phrases."""
    code, said = _main(monkeypatch, tmp_path)
    assert code == 0 and said == []
