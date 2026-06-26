"""Stage 4: carrying page provenance through LLM refinement."""
from scripts.preprocessing import stage4_refine as s4


def test_thread_provenance_keep_is_one_to_one():
    inp = [{"title": "A", "segments": [{"page": 1, "kind": "text", "text": "a"}], "pages": [1]},
           {"title": "B", "segments": [{"page": 2, "kind": "text", "text": "b"}], "pages": [2]}]
    out = [{"title": "A", "_action": "keep"}, {"title": "B", "_action": "keep"}]
    s4._thread_provenance(inp, out)
    assert out[0]["segments"][0]["page"] == 1
    assert out[1]["pages"] == [2]


def test_thread_provenance_split_children_reuse_last_input():
    inp = [{"title": "X", "segments": [{"page": 5, "kind": "text", "text": "x"}], "pages": [5]}]
    out = [{"title": "X1", "_action": "keep"}, {"title": "X2", "_action": "keep"}]
    s4._thread_provenance(inp, out)
    assert out[0]["pages"] == [5] and out[1]["pages"] == [5]


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
