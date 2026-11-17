"""
What is stored is stored whole (owner decision 2026-11-17: "Nichts kürzen").

1. A caption taken from the text is the whole sentence that names the item,
   a caption broken over lines is one sentence, and a long one is not cut.
2. A Turtle comment carries every word of its text, over as many lines as it
   needs, and every line of it is a comment.
3. A cell of a working list (review, curation, harvest lists) holds the whole
   quote, with no ellipsis.
"""
import importlib.util
import re
from pathlib import Path

from docpipe import captions
from docpipe.extraction import review
from docpipe.extraction.graphkit import ttl_comment

ROOT = Path(__file__).resolve().parent.parent


def _script(name):
    spec = importlib.util.spec_from_file_location(
        f"_nc_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_caption_from_the_text_is_its_whole_sentence_however_long():
    long_sentence = "Energy demand by carrier " + "and sector " * 80 + "in 2030."
    content = f"Intro text. Table 3: {long_sentence} Further prose.\n[p1_tbl0]"
    title = captions.resolve_title("", content, "p1_tbl0")
    assert title == f"Table 3: {long_sentence}"
    assert len(title) > 300


def test_a_caption_broken_over_two_lines_is_one_sentence():
    content = "Table 4: Heat demand of the\nmunicipality by year. Next sentence.\n[p1_tbl0]"
    title = captions.resolve_title("", content, "p1_tbl0")
    assert title == "Table 4: Heat demand of the municipality by year."


def test_a_caption_without_a_sentence_end_is_taken_whole():
    content = "Table 5: " + "word " * 100 + "\n[p1_tbl0]"
    title = captions.resolve_title("", content, "p1_tbl0")
    assert title.split() == ["Table", "5:"] + ["word"] * 100


def test_a_turtle_comment_keeps_every_word_on_comment_lines():
    words = [f"w{i}" for i in range(500)]
    out = ttl_comment("“" + " ".join(words) + "”", indent="    ")
    lines = out.split("\n")
    assert len(lines) > 1
    assert all(line.startswith("    # ") for line in lines)
    body = " ".join(line[len("    # "):] for line in lines)
    assert body == "“" + " ".join(words) + "”"


def test_a_turtle_comment_with_newlines_and_a_huge_word_stays_whole():
    word = "x" * 700
    out = ttl_comment(f"a\nb\t{word}  c")
    assert all(line.startswith("# ") for line in out.split("\n"))
    assert [w for line in out.split("\n") for w in line[2:].split()] == [
        "a", "b", word, "c"]
    assert not re.search(r"\n(?!# )", out)


def test_a_cell_of_every_working_list_holds_the_whole_quote():
    text = "Wärme  bedarf\n" + "wort " * 400
    flat = " ".join(text.split())
    for cell in (review._cell, _script("curation_list")._cell,
                 _script("harvest_lists")._cell):
        got = cell(text)
        assert got == flat
        assert "…" not in got
