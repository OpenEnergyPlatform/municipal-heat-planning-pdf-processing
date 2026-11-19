"""
The decisions of stage 1 (page text) are rules, and the stage decides by
them (owner request 2026-11-19, A1: "Die festen Werte werden Regeln mit dem
heutigen Wert als Standard").

The promises, each with a case that breaks it by construction:

1. Every rule of the stage has a default in the default profile's file that
   `rules.problem` takes, a title and a help; AND the defaults are the values
   the code held (the profiles that held other words say so in their own file).
2. A block of text is kept by `text_block_min_chars`, and its font is bold by
   `bold_block_share`: another value keeps or drops the same block.
3. A word broken at a line end is joined by `join_hyphenated_words` unless the
   next line opens with one of `hyphen_exceptions`: a switch off joins none,
   another word list keeps other hyphens.
4. A symbol font's glyphs are dropped by `drop_private_use_glyphs`.
5. A page is taken to lack its text by `page_text_min_chars`; the blocks of a
   page read by the model stand in `transcribed_text_area`; the picture the
   model reads has the resolution `page_transcribe_dpi`; the request has the
   temperature and the token limit of the rules where the prompt names none.
6. The sentence of the user's turn is the prompt `preprocessing/page_request`,
   word for word what the code sent, in the profile's language.
"""
import json
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from docpipe import prompts, rules
from docpipe.preprocessing import page_text, page_text_without_layer as ptwl
from docpipe.preprocessing.models import PageData
from docpipe.profile import load_profile
from docpipe.ruleset import stage_text

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = json.loads((ROOT / "docpipe/builtin/default/rules.json")
                     .read_text(encoding="utf-8"))["rules"]


# -- 1: the rules, their defaults and the values the code held ----------------

@pytest.mark.parametrize("one", stage_text.RULES, ids=lambda one: one.name)
def test_every_rule_has_a_default_a_title_and_a_help(one):
    assert one.tab == "stages" and one.group == stage_text.GROUP
    assert one.title.strip() and len(one.help.split()) > 10
    assert one.name in DEFAULT
    assert rules.problem(one.name, DEFAULT[one.name]) is None


def test_a_value_outside_the_bounds_is_no_value_of_the_rule():
    # the failure by construction: the check has to be able to fail
    assert rules.problem("text_block_min_chars", 0) is not None
    assert rules.problem("page_transcribe_dpi", 10) is not None
    assert rules.problem("transcribed_text_area", {"left": "a"}) is not None


def test_the_defaults_are_the_values_the_code_held():
    assert [DEFAULT[name] for name in (
        "text_block_min_chars", "bold_block_share", "join_hyphenated_words",
        "drop_private_use_glyphs", "page_text_min_chars",
        "page_transcribe_dpi", "page_transcribe_temperature",
        "page_transcribe_max_tokens")] == [3, 0.5, True, True, 60, 200, 0.1,
                                           4096]
    assert DEFAULT["transcribed_text_area"] == {
        "left": 0.08, "top": 0.07, "right": 0.92, "bottom": 0.95}
    english = DEFAULT["hyphen_exceptions"]
    assert len(english) == 30 and english[:3] == ["and", "or", "nor"]
    german = rules.load(load_profile("kwp"))["hyphen_exceptions"]
    assert len(german) == 37 and german[:2] == ["und", "oder"]
    # the scenarios profile held the English list: it says nothing of its own
    assert rules.load(load_profile("scenarios"))["hyphen_exceptions"] == english


# -- 2: blocks and bold -------------------------------------------------------

def test_a_text_block_is_kept_by_the_least_characters_of_the_rule():
    valid = page_text._is_valid_text_block
    assert valid("abc") and not valid("ab") and not valid("  a  ")
    assert not valid("...")                     # no letter, no digit: never
    with rules.overlaid(text_block_min_chars=2):
        assert valid("ab")
    with rules.overlaid(text_block_min_chars=5):
        assert not valid("abcd")


def _block(bold, plain):
    spans = []
    if bold:
        spans.append({"size": 10.0, "flags": 16, "font": "F", "chars": [{}] * bold})
    if plain:
        spans.append({"size": 10.0, "flags": 0, "font": "F", "chars": [{}] * plain})
    return {"lines": [{"spans": spans}]}


def test_a_block_is_bold_by_the_share_of_its_bold_characters():
    assert page_text._dominant_font(_block(5, 5))[1] is True       # half
    assert page_text._dominant_font(_block(4, 6))[1] is False
    with rules.overlaid(bold_block_share=0.3):
        assert page_text._dominant_font(_block(4, 6))[1] is True
    with rules.overlaid(bold_block_share=0.9):
        assert page_text._dominant_font(_block(5, 5))[1] is False


# -- 3: hyphens ---------------------------------------------------------------

def _lines(*lines):
    return {"lines": [{"spans": [{"chars": [{"c": c} for c in line]}]}
                      for line in lines]}


def test_a_word_broken_at_a_line_end_is_joined():
    assert page_text._spans_to_text(_lines("Wärmever-", "sorgung")) \
        == "Wärmeversorgung"
    # the failure by construction: an upper-case letter after the break
    assert page_text._spans_to_text(_lines("Wärme-", "Versorgung")) \
        == "Wärme- Versorgung"


def test_the_switch_off_joins_no_word():
    with rules.overlaid(join_hyphenated_words=False):
        assert page_text._spans_to_text(_lines("Wärmever-", "sorgung")) \
            == "Wärmever- sorgung"


def test_a_line_that_opens_with_an_exception_keeps_the_hyphen():
    # kwp is the ambient profile: its list holds "und"
    assert page_text._spans_to_text(_lines("Wärme-", "und Kälte")) \
        == "Wärme- und Kälte"
    with rules.overlaid(hyphen_exceptions=["zzz"]):
        assert page_text._spans_to_text(_lines("Wärme-", "und Kälte")) \
            == "Wärmeund Kälte"
        assert page_text._spans_to_text(_lines("Wärme-", "zzz Kälte")) \
            == "Wärme- zzz Kälte"


# -- 4: symbol font glyphs ----------------------------------------------------

def test_the_glyphs_of_a_symbol_font_are_dropped_by_the_switch():
    from docpipe.preprocessing.config import strip_private_use
    assert strip_private_use("ab") == ("ab", 1)
    assert strip_private_use("ab") == ("ab", 0)
    with rules.overlaid(drop_private_use_glyphs=False):
        assert strip_private_use("ab") == ("ab", 0)


# -- 5: pages without a text layer --------------------------------------------

def _page(text):
    block = ptwl.Block(id="b", type="text", bbox=[0, 0, 10, 10], content=text)
    return PageData(page_number=1, width_pt=600.0, height_pt=800.0,
                    blocks=[block])


def test_a_page_has_no_text_below_the_rules_characters():
    page = _page("x" * 40)
    assert ptwl.needs_transcription(page)               # 40 < 60
    with rules.overlaid(page_text_min_chars=30):
        assert not ptwl.needs_transcription(page)
    with rules.overlaid(page_text_min_chars=0):
        assert not ptwl.needs_transcription(_page(""))
    assert ptwl.needs_transcription(page, 41)           # the argument wins


def test_the_filling_asks_for_the_pages_the_rule_names():
    pages = [_page("x" * 40)]
    asked = []

    def read(image, number):
        asked.append(number)
        return "Text"
    with rules.overlaid(page_text_min_chars=30):
        report = ptwl.fill_missing_page_text(pages, lambda n: None, read)
    assert report["pages_missing_text"] == 0 and asked == []


def test_the_blocks_of_a_transcribed_page_stand_in_the_rules_area():
    page = _page("")
    blocks = ptwl.synthesize_blocks(page, "Eins\n\nZwei")
    assert blocks[0].bbox[0] == 48.0 and blocks[-1].bbox[2] == 552.0
    assert blocks[0].bbox[1] == 56.0 and blocks[-1].bbox[3] == 760.0
    with rules.overlaid(transcribed_text_area={
            "left": 0.1, "top": 0.1, "right": 0.5, "bottom": 0.5}):
        other = ptwl.synthesize_blocks(page, "Eins\n\nZwei")
    assert other[0].bbox[0] == 60.0 and other[-1].bbox[2] == 300.0
    assert other[0].bbox[1] == 80.0 and other[-1].bbox[3] == 400.0


def test_an_area_that_lacks_a_side_is_said():
    with rules.overlaid(transcribed_text_area={"left": 0.1}):
        with pytest.raises(ValueError, match="top"):
            ptwl.synthesize_blocks(_page(""), "Eins")


def test_the_picture_the_model_reads_has_the_rules_resolution(tmp_path):
    doc = fitz.open()
    doc.new_page(width=200, height=100)
    path = tmp_path / "p.pdf"
    doc.save(path)
    doc.close()
    sizes = {}
    for dpi in (72, 144):
        with rules.overlaid(page_transcribe_dpi=dpi):
            image = ptwl.make_page_renderer(path, tmp_path / f"d{dpi}")(1)
        from PIL import Image
        sizes[dpi] = Image.open(image).size
    assert sizes[72] == (200, 100) and sizes[144] == (400, 200)


def _asked_with(monkeypatch, strip_meta):
    """What the transcriber hands the vision call, with the page prompt
    as it is, or without the temperature and the limit of its front matter."""
    from docpipe.visuals import vision
    seen = {}

    def call(client, system, user, image, **more):
        seen.update(more, system=system, user=user)
        return {"markdown": "Text"}

    real = prompts.load

    def load(prompt_id, profile=None, use_ambient=True):
        prompt = real(prompt_id, profile, use_ambient)
        if strip_meta and prompt_id == ptwl.PAGE_TRANSCRIBE_PROMPT_ID:
            return replace(prompt, meta={})
        return prompt
    monkeypatch.setattr(vision, "call_vision", call)
    monkeypatch.setattr(prompts, "load", load)
    transcribe = ptwl.make_transcriber(load_profile("kwp"), client=object(),
                                       model="m")
    assert transcribe("page.png", 7) == "Text"
    return seen


def test_the_request_has_the_rules_values_where_the_prompt_names_none(monkeypatch):
    seen = _asked_with(monkeypatch, strip_meta=True)
    assert (seen["temperature"], seen["max_tokens"]) == (0.1, 4096)
    with rules.overlaid(page_transcribe_temperature=0.7,
                        page_transcribe_max_tokens=999):
        seen = _asked_with(monkeypatch, strip_meta=True)
    assert (seen["temperature"], seen["max_tokens"]) == (0.7, 999)


def test_the_prompts_own_values_win_over_the_rules(monkeypatch):
    with rules.overlaid(page_transcribe_temperature=0.7,
                        page_transcribe_max_tokens=999):
        seen = _asked_with(monkeypatch, strip_meta=False)
    assert (seen["temperature"], seen["max_tokens"]) == (0.1, 4096)


# -- 6: the sentence of the user's turn ---------------------------------------

@pytest.mark.parametrize("name, said", [
    ("default", "Page 7. Return the text of this page."),
    ("kwp", "Seite 7. Gib den Text dieser Seite zurück."),
    ("scenarios", "Page 7. Return the text of this page."),
])
def test_the_page_request_is_the_sentence_the_code_sent(name, said):
    prompt = prompts.load(ptwl.PAGE_REQUEST_PROMPT_ID, load_profile(name))
    assert prompt.placeholders == {"page"}
    assert prompt.render(page=7) == said


def test_the_request_the_vision_call_gets_is_that_sentence(monkeypatch):
    seen = _asked_with(monkeypatch, strip_meta=False)
    assert seen["user"] == "Seite 7. Gib den Text dieser Seite zurück."


def test_a_page_request_without_its_place_for_the_page_is_refused():
    prompt = prompts.load(ptwl.PAGE_REQUEST_PROMPT_ID, load_profile("kwp"))
    with pytest.raises(KeyError):
        prompt.render()


def test_the_doctor_checks_the_page_request_with_the_page_prompt():
    from docpipe import doctor
    assert ptwl.PAGE_REQUEST_PROMPT_ID in doctor._prompt_ids("preprocess")
