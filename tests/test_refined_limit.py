"""Every section refinement hands on is at most SECTION_MAX_WORDS long, and the
cut changes and loses no word: a literature list is cut after whole entries,
other text where a line or a sentence ends, else after a run of words; a part
keeps the tables and figures its text marks, and the pages of the segments its
text holds."""
from docpipe.refinement.config import SECTION_MAX_WORDS
from docpipe.refinement.refine import _hold_to_limit
from docpipe.refinement.split import cut_to_limit


def sentence(n: int, word: str) -> str:
    return " ".join([word] * (n - 1)) + " end."


def words(section) -> list:
    content = section["content"]
    return " ".join(content if isinstance(content, list) else [content]).split()


def test_a_merged_section_is_cut_where_sentences_end_and_keeps_every_word():
    # As the model hands two halves back as one: no line break at all.
    text = " ".join(sentence(40, f"w{i}") for i in range(48))       # 1920 words
    section = {"title": "Introduction", "content": text,
               "tables": [], "figures": []}
    parts = cut_to_limit(section)
    assert len(parts) > 1
    assert all(len(words(p)) <= SECTION_MAX_WORDS for p in parts)
    assert [w for p in parts for w in words(p)] == text.split()
    assert all(p["content"].endswith("end.") for p in parts)
    assert {p["title"] for p in parts} == {"Introduction"}


def test_text_without_any_sentence_end_is_still_cut_to_the_limit():
    text = " ".join(f"w{i}" for i in range(2600))
    parts = cut_to_limit({"title": "T", "content": text})
    assert all(len(words(p)) <= SECTION_MAX_WORDS for p in parts)
    assert [w for p in parts for w in words(p)] == text.split()


def test_a_literature_list_is_cut_after_whole_entries():
    entries = [f"@article{{e{i}, title = {{{' '.join(['x'] * 60)}}}}}"
               for i in range(40)]                                  # 2440 words
    parts = cut_to_limit({"title": "[LITERATURE]", "content": entries})
    assert len(parts) > 1
    assert all(isinstance(p["content"], list) for p in parts)
    assert all(len(words(p)) <= SECTION_MAX_WORDS for p in parts)
    assert [e for p in parts for e in p["content"]] == entries
    assert {p["title"] for p in parts} == {"[LITERATURE]"}


def test_a_section_within_the_limit_is_left_as_it_is():
    section = {"title": "T", "content": sentence(SECTION_MAX_WORDS, "w")}
    assert cut_to_limit(section) == [section]
    short = {"title": "[LITERATURE]", "content": ["@misc{a, title = {A}}"]}
    assert cut_to_limit(short) == [short]


def test_tables_go_with_their_marker_and_an_unmarked_one_stays_first():
    text = (sentence(700, "a") + " See [p3_tbl0] here. "
            + sentence(700, "b"))
    tables = [{"id": "p3_tbl0", "page_number": 3},
              {"id": "p9_tbl1", "page_number": 9}]
    parts = cut_to_limit({"title": "T", "content": text, "tables": tables,
                          "figures": []})
    owner = [p for p in parts if "[p3_tbl0]" in p["content"]]
    assert [t["id"] for t in owner[0]["tables"]][:1] == ["p3_tbl0"]
    assert sum(t["id"] == "p3_tbl0" for p in parts for t in p["tables"]) == 1
    assert [t["id"] for t in parts[0]["tables"]][-1] == "p9_tbl1"


def test_each_part_takes_the_pages_of_its_own_text():
    first = " ".join(sentence(30, f"a{i}") for i in range(30))       # page 4
    second = " ".join(sentence(30, f"b{i}") for i in range(30))      # page 5
    merged = {"title": "Methods", "content": first + " " + second,
              "tables": [], "figures": [],
              "segments": [{"kind": "text", "page": 4, "text": first},
                           {"kind": "text", "page": 5, "text": second}]}
    parts = _hold_to_limit([merged])
    assert len(parts) == 4
    pages = [{s["page"] for s in p["segments"]} for p in parts]
    assert pages[0] == {4} and pages[-1] == {5}
    assert all(p["segments"] for p in parts)
    # The segments cut with the text lose and repeat no word.
    held = " ".join(s["text"] for p in parts for s in p["segments"])
    assert held.split() == (first + " " + second).split()
    # Where the page changes inside a part, that part holds both pages.
    assert set().union(*pages) == {4, 5}
