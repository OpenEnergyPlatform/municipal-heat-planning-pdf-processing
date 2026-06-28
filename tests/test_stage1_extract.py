"""Tests for Stage 1 text helpers (hyphenation, block validity)."""
from scripts.preprocessing import stage1_extract as s1


def _block(*lines):
    """Builds a rawdict-style text block from plain lines."""
    return {"lines": [
        {"spans": [{"chars": [{"c": ch} for ch in line]}]} for line in lines
    ]}


def test_dehyphenates_german_compound_across_line_break():
    txt = s1._spans_to_text(_block("Die Wärme-", "versorgung ist"))
    assert "Wärmeversorgung" in txt


def test_keeps_hyphen_before_conjunction_exception():
    # "Strom-" + "und ..." → not merged because "und" is a hyphen exception word
    txt = s1._spans_to_text(_block("Strom-", "und Wärme"))
    assert "Strom-" in txt and "und Wärme" in txt


def test_no_merge_when_next_line_starts_uppercase():
    txt = s1._spans_to_text(_block("Nord-", "Süd"))
    assert "Nord-" in txt          # uppercase after the dash → kept, not joined


def test_is_valid_text_block():
    assert s1._is_valid_text_block("abc")
    assert not s1._is_valid_text_block("   ")     # whitespace only
    assert not s1._is_valid_text_block("a")        # below TEXT_BLOCK_MIN_CHARS
    assert not s1._is_valid_text_block("!!!")       # no alphanumeric content


def _span(text, size, flags=0, font="Arial"):
    return {"size": size, "flags": flags, "font": font,
            "chars": [{"c": c} for c in text]}


def test_dominant_font_size_and_bold():
    block = {"lines": [{"spans": [_span("Heading", 24.0, flags=16, font="Arial-Bold")]}]}
    size, bold = s1._dominant_font(block)
    assert size == 24.0 and bold is True


def test_dominant_font_weighted_by_chars():
    # one long regular span dominates a tiny bold span
    block = {"lines": [{"spans": [
        _span("regular body text here", 10.0, flags=0),
        _span("x", 24.0, flags=16, font="Arial-Bold"),
    ]}]}
    size, bold = s1._dominant_font(block)
    assert size == 10.0       # dominant by char count
    assert bold is False      # bold is a minority


def test_dominant_font_empty():
    assert s1._dominant_font({"lines": []}) == (None, False)
