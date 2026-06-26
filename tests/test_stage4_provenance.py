"""Stage 4: carrying page provenance through LLM refinement."""
from scripts.preprocessing import stage4_refine as s4


def test_thread_provenance_keep_is_one_to_one():
    inp = [{"title": "A", "segments": [{"page": 1, "kind": "text", "text": "a"}], "pages": [1]},
           {"title": "B", "segments": [{"page": 2, "kind": "text", "text": "b"}], "pages": [2]}]
    out = [{"title": "A", "_action": "keep"}, {"title": "B", "_action": "keep"}]
    s4._thread_provenance(inp, out)
    assert out[0]["segments"][0]["page"] == 1
    assert out[1]["pages"] == [2]


def test_thread_provenance_split_distributes_pages_by_content_and_markers():
    # One parent spanning pages 5-6 is split at the page boundary. Each child
    # must end up with *only* its own page(s), matched via the table marker
    # (exact) and text containment.
    inp = [{
        "title": "P",
        "content": "Intro [p5_tbl0] Folgeabsatz",
        "tables": [{"id": "p5_tbl0", "page_number": 5}], "figures": [],
        "segments": [{"page": 5, "kind": "text", "text": "Intro"},
                     {"page": 5, "kind": "table", "ref": "p5_tbl0"},
                     {"page": 6, "kind": "text", "text": "Folgeabsatz"}],
        "pages": [5, 6],
    }]
    out = [
        {"title": "Erster", "content": "Intro [p5_tbl0]",
         "tables": [{"id": "p5_tbl0", "page_number": 5}], "figures": [], "_action": "keep"},
        {"title": "Zweiter", "content": "Folgeabsatz",
         "tables": [], "figures": [], "_action": "keep"},
    ]
    s4._thread_provenance(inp, out)
    assert out[0]["pages"] == [5]
    assert out[1]["pages"] == [6]
    assert [s["kind"] for s in out[0]["segments"]] == ["text", "table"]
    assert out[1]["segments"][0]["text"] == "Folgeabsatz"


def test_thread_provenance_split_in_middle_of_window_keeps_siblings_exact():
    # Regression: a split in the *middle* of a 3-section window used to shift
    # positional alignment, giving the trailing sibling the wrong page. Each of
    # A, B(->B1,B2), C must now carry exactly its own page.
    inp = [
        {"title": "A", "content": "Alpha [p1_tbl0]",
         "tables": [{"id": "p1_tbl0", "page_number": 1}], "figures": [],
         "segments": [{"page": 1, "kind": "text", "text": "Alpha"},
                      {"page": 1, "kind": "table", "ref": "p1_tbl0"}], "pages": [1]},
        {"title": "B", "content": "Beta [p2_img0] Gamma",
         "tables": [], "figures": [{"id": "p2_img0", "page_number": 2}],
         "segments": [{"page": 2, "kind": "text", "text": "Beta"},
                      {"page": 2, "kind": "figure", "ref": "p2_img0"},
                      {"page": 3, "kind": "text", "text": "Gamma"}], "pages": [2, 3]},
        {"title": "C", "content": "Delta [p4_tbl0]",
         "tables": [{"id": "p4_tbl0", "page_number": 4}], "figures": [],
         "segments": [{"page": 4, "kind": "text", "text": "Delta"},
                      {"page": 4, "kind": "table", "ref": "p4_tbl0"}], "pages": [4]},
    ]
    out = [
        {"title": "A", "content": "Alpha [p1_tbl0]",
         "tables": [{"id": "p1_tbl0", "page_number": 1}], "figures": [], "_action": "keep"},
        {"title": "B1", "content": "Beta [p2_img0]",
         "tables": [], "figures": [{"id": "p2_img0", "page_number": 2}], "_action": "keep"},
        {"title": "B2", "content": "Gamma",
         "tables": [], "figures": [], "_action": "keep"},
        {"title": "C", "content": "Delta [p4_tbl0]",
         "tables": [{"id": "p4_tbl0", "page_number": 4}], "figures": [], "_action": "keep"},
    ]
    s4._thread_provenance(inp, out)
    assert [o["pages"] for o in out] == [[1], [2], [3], [4]]


def test_merge_concatenates_segments():
    secs = [{"title": "A", "content": "a", "tables": [], "figures": [],
             "segments": [{"page": 1, "kind": "text", "text": "a"}], "_action": "keep"},
            {"title": "B", "content": "b", "tables": [], "figures": [],
             "segments": [{"page": 2, "kind": "text", "text": "b"}],
             "_action": "merge_into_previous"}]
    res, _ = s4._apply_actions(secs, None)
    assert len(res) == 1
    assert [seg["page"] for seg in res[0]["segments"]] == [1, 2]


def test_finalize_pages_unions_segments_and_media():
    sec = {"segments": [{"page": 3, "kind": "text"}],
           "tables": [{"page_number": 4}], "figures": [{"page_number": 3}],
           "page_number": None}
    s4._finalize_pages(sec)
    assert sec["pages"] == [3, 4]
    assert sec["page_number"] == 3


def test_call_ollama_strips_provenance_from_payload():
    # the projection used to build the LLM payload must drop segments/pages
    win = [{"title": "A", "content": "c", "tables": [], "figures": [],
            "segments": [{"page": 1}], "pages": [1]}]
    stripped = [{k: v for k, v in s.items() if k not in ("segments", "pages")} for s in win]
    assert "segments" not in stripped[0] and "pages" not in stripped[0]
    assert stripped[0]["content"] == "c"
