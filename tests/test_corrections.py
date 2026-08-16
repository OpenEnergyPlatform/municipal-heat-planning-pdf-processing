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


def test_a_reply_naming_a_section_outside_the_window_changes_nothing():
    """The edit is refused — an off-by-one would otherwise write one section's
    edits onto another — but the section it was aimed at still comes back."""
    window = _window()
    out = _materialise_corrections(
        [{"index": 7, "_action": "keep", "corrections": []}], window)
    assert [s["content"] for s in out] == [window[0]["content"]]


def test_a_section_the_reply_never_mentions_survives():
    """A reply that answers about two of three sections is ordinary. Emitting
    only the sections it named cost this corpus 123 sections in one document
    and 237 in another — text that was in the PDF and not in the output."""
    window = [
        {"title": "A", "content": "First.", "tables": [], "figures": []},
        {"title": "B", "content": "Second.", "tables": [], "figures": []},
        {"title": "C", "content": "Third.", "tables": [], "figures": []},
    ]
    out = _materialise_corrections(
        [{"index": 1, "_action": "keep", "corrections": []}], window)
    assert [s["title"] for s in out] == ["A", "B", "C"]
    assert [s["content"] for s in out] == ["First.", "Second.", "Third."]


def test_bibliography_still_carries_its_own_text():
    """The one action that legitimately writes the section out in full."""
    out = _materialise_corrections([{
        "index": 0, "_action": "replace", "title": "[LITERATURE]",
        "content": ["@article{smith2021, title = {X}}"],
    }], _window())
    assert out[0]["content"] == ["@article{smith2021, title = {X}}"]
    assert out[0]["_action"] == "replace"


# ---------------------------------------------------------------------------
# Telling a quoting habit apart from an invention
# ---------------------------------------------------------------------------

def test_a_whitespace_only_miss_is_named_as_such():
    """The model retyping a quote tends to collapse double spaces and line
    breaks. That refusal and a hallucinated quote both read as 'not found',
    and they call for opposite fixes — a tolerant match versus a better
    prompt. The reason has to separate them."""
    text = "the  decarbonisation\npathway is described"
    out, rep = apply_corrections(
        text, [{"find": "the decarbonisation pathway", "replace": "X"}])
    assert out == text, "still refused — this is diagnosis, not a new behaviour"
    assert "whitespace-only miss" in rep.rejected[0][1]


def test_a_genuine_invention_is_named_as_absent():
    out, rep = apply_corrections(
        TEXT, [{"find": "a sentence that was never in the document",
                "replace": "x"}])
    assert out == TEXT
    assert "absent even loosely" in rep.rejected[0][1]


# ---------------------------------------------------------------------------
# The misfiling that dominated every other failure
# ---------------------------------------------------------------------------

def _two_section_window():
    return [
        {"title": "A", "content": "Alpha section about decarboni- sation here.",
         "page_number": 1, "tables": [], "figures": []},
        {"title": "B", "content": "Beta section about effi- ciency instead.",
         "page_number": 2, "tables": [], "figures": []},
    ]


def test_a_correction_filed_under_the_wrong_section_still_lands():
    """56% of all "not found" refusals were this: the model quotes the passage
    correctly and names the wrong section. The quote decides, not the label."""
    window = _two_section_window()
    out = _materialise_corrections([{
        "index": 0, "_action": "keep",
        "corrections": [{"find": "effi- ciency", "replace": "efficiency"}],
    }], window)
    beta = [s for s in out if s["title"] == "B"]
    assert beta and "efficiency instead" in beta[0]["content"], \
        "the correction belongs to the section its text is in"


def test_relocation_never_guesses_between_two_candidates():
    """If the quote fits two sections of the window, moving it would be a coin
    toss. It stays where it was claimed and is refused there."""
    window = [
        {"title": "A", "content": "the same phrase here", "tables": [], "figures": []},
        {"title": "B", "content": "the same phrase here", "tables": [], "figures": []},
    ]
    out = _materialise_corrections([{
        "index": 0, "_action": "keep",
        "corrections": [{"find": "the same phrase", "replace": "X"}],
    }], window)
    assert all("the same phrase here" == s["content"] for s in out), \
        "an ambiguous quote must change nothing"


def test_a_correction_that_fits_its_own_section_is_left_alone():
    window = _two_section_window()
    out = _materialise_corrections([{
        "index": 0, "_action": "keep",
        "corrections": [{"find": "decarboni- sation", "replace": "decarbonisation"}],
    }], window)
    alpha = [s for s in out if s["title"] == "A"][0]
    assert "decarbonisation here" in alpha["content"]
