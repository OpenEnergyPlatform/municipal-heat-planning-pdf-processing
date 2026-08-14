"""The check that stands between a model's edit list and the corpus.

Asking for changes instead of whole sections is what makes the stage cheap. It
is also what makes it dangerous: a find/replace quoted from memory rewrites a
sentence nobody asked it to touch, and unlike a truncated JSON reply that
failure is silent. Every rule here exists to make it loud instead.
"""
from docpipe.refinement.corrections import MAX_SHRINK, apply_corrections

TEXT = ("The decarboni- sation pathway is described in [p3_tbl0]. "
        "Efficiency gains follow in the second half of the period.")


def test_a_clean_edit_is_applied():
    out, rep = apply_corrections(TEXT, [{"find": "decarboni- sation",
                                   "replace": "decarbonisation"}])
    assert "decarbonisation pathway" in out
    assert rep.applied == 1 and rep.ok


def test_an_edit_that_is_not_there_is_refused():
    """The model quoting from memory — the likeliest failure of the whole
    design, and the one that would otherwise corrupt silently."""
    out, rep = apply_corrections(TEXT, [{"find": "carbon capture",
                                   "replace": "CCS"}])
    assert out == TEXT, "nothing may change when the anchor is absent"
    assert not rep.ok
    assert "not found" in rep.rejected[0][1]


def test_an_ambiguous_edit_is_refused():
    """Two occurrences means the model cannot say which one it meant."""
    text = "the value the value"
    out, rep = apply_corrections(text, [{"find": "the value", "replace": "X"}])
    assert out == text
    assert "ambiguous" in rep.rejected[0][1]


def test_an_edit_may_not_swallow_a_placeholder():
    """A placeholder is a table living in its own file; losing it detaches the
    image from the text that explains it."""
    out, rep = apply_corrections(TEXT, [{"find": "in [p3_tbl0]", "replace": "above"}])
    assert out == TEXT
    assert "placeholder" in rep.rejected[0][1]


def test_an_edit_may_not_invent_a_placeholder():
    out, rep = apply_corrections(TEXT, [{"find": "second half",
                                   "replace": "second half [p9_img4]"}])
    assert out == TEXT
    assert "placeholder" in rep.rejected[0][1]


def test_a_wholesale_deletion_is_refused():
    """An edit pass fixes artefacts. Removing a third of the section is not
    that, whatever the model believed it was doing."""
    text = "keep " * 100
    out, rep = apply_corrections(text, [{"find": "keep " * 60, "replace": ""}])
    assert out == text
    assert "shrank" in rep.rejected[-1][1]
    assert f"{100 * MAX_SHRINK:.0f}%" in rep.rejected[-1][1]


def test_edits_are_checked_against_the_running_text_not_the_original():
    """The second edit must see what the first one did, or an edit pair that
    overlaps would apply twice."""
    filler = " padding" * 40          # keep the shrink guard out of this test
    out, rep = apply_corrections(
        "alpha beta gamma" + filler,
        [{"find": "alpha beta", "replace": "alpha"},
         {"find": "alpha gamma", "replace": "done"}])
    assert out == "done" + filler
    assert rep.applied == 2 and rep.ok


def test_one_bad_edit_does_not_discard_the_good_ones_but_is_reported():
    out, rep = apply_corrections(TEXT, [
        {"find": "decarboni- sation", "replace": "decarbonisation"},
        {"find": "not present anywhere", "replace": "x"},
    ])
    assert "decarbonisation" in out
    assert rep.applied == 1
    assert not rep.ok, "the caller has to be able to see that one failed"


def test_malformed_input_is_refused_rather_than_crashing():
    for bad in ("not a list", [{"find": 5, "replace": "x"}],
                [{"find": "a"}], ["nonsense"], [{"replace": "x"}]):
        out, rep = apply_corrections(TEXT, bad)
        assert out == TEXT
        assert not rep.ok


def test_an_empty_edit_list_is_a_no_op_and_not_an_error():
    """28% of sections need nothing done to them; that is the common case."""
    out, rep = apply_corrections(TEXT, [])
    assert out == TEXT
    assert rep.ok and rep.applied == 0


# ---------------------------------------------------------------------------
# Rebuilding a section from an edit reply
# ---------------------------------------------------------------------------

from docpipe.refinement.refine import _materialise_corrections   # noqa: E402


def _window():
    return [{
        "title": "4.1 Wärme- bedarf",
        "content": "Die Wärme- versorgung stützt sich auf Netze. [p2_tbl0] zeigt es. 17",
        "page_number": 12,
        "segments": [{"page": 12, "kind": "text", "text": "..."}],
        "tables": [{"id": "p2_tbl0", "path": "images/p2_tbl0.png",
                    "caption": "Abbildung 2: Energieträger", "page_number": 12}],
        "figures": [],
    }]


def test_path_and_page_number_come_from_the_original_not_the_model():
    """The field the model used to drop. It never makes the round trip now, so
    it cannot come back missing or altered."""
    window = _window()
    out = _materialise_corrections([{
        "index": 0, "_action": "keep", "title": "Wärmebedarf",
        "captions": {"p2_tbl0": "Energieträger"},
        "corrections": [{"find": "Wärme- versorgung", "replace": "Wärmeversorgung"}],
    }], window)
    table = out[0]["tables"][0]
    assert table["path"] == "images/p2_tbl0.png"
    assert table["page_number"] == 12
    assert table["caption"] == "Energieträger", "the caption IS the model's"
    assert out[0]["title"] == "Wärmebedarf"
    assert "Wärmeversorgung stützt" in out[0]["content"]


def test_a_refused_edit_leaves_that_text_alone():
    window = _window()
    before = window[0]["content"]
    out = _materialise_corrections([{
        "index": 0, "_action": "keep",
        "corrections": [{"find": "text that was never there", "replace": "x"}],
    }], window)
    assert out[0]["content"] == before


def test_a_reply_naming_a_section_outside_the_window_is_dropped():
    """Otherwise an off-by-one would write one section's edits onto another."""
    out = _materialise_corrections([{"index": 7, "_action": "keep", "corrections": []}],
                             _window())
    assert out == []


def test_bibliography_still_carries_its_own_text():
    """The one action that legitimately writes the section out in full."""
    out = _materialise_corrections([{
        "index": 0, "_action": "replace", "title": "[LITERATURE]",
        "content": ["@article{smith2021, title = {X}}"],
    }], _window())
    assert out[0]["content"] == ["@article{smith2021, title = {X}}"]
    assert out[0]["_action"] == "replace"
