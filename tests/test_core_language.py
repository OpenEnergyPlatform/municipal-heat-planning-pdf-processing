"""German leaves the core: what the picker tags a document with, what it calls
one, and what opens a caption are the profile's.

Promised: the picker's tag, the picker's noun and the pattern for a caption's
opening are asked of the profile in force, so kwp keeps its German words and
its one pattern character for character AND the built-in profile says them in
English and also reads the common English caption forms AND the core itself
holds none of those words or patterns.

Each AND is its own test below, and each has the case that breaks it: a
profile with other words, a prose sentence that opens like "Table 1", a list
that cannot be one, a core file that still carries the word.

No model, no GPU.
"""
import ast
import dataclasses
import re
import sqlite3
import types
from pathlib import Path

import pytest

from docpipe import captions
from docpipe.inference import catalog, wording
from docpipe.profile import ENV_VAR, Profile, load_profile
from profiles.kwp.catalog import document_label

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# the picker's words
# ---------------------------------------------------------------------------
@pytest.fixture
def conn(kwp_db):
    db_path, con = kwp_db
    con.executescript("""
        INSERT INTO Documents (id, filename, published, is_current)
             VALUES (2, 'alt.pdf', '2023q4', 0);
        UPDATE Documents SET published = '20240708' WHERE id = 1;
    """)
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def _worded(monkeypatch, **words):
    """A profile whose UI table is the built-in one with `words` over it."""
    table = {**load_profile("default")._own("inference", "UI"), **words}
    real = Profile.layers
    monkeypatch.setattr(
        Profile, "layers",
        lambda self, module, attr: ([table] if (module, attr) == ("inference", "UI")
                                    else real(self, module, attr)))
    monkeypatch.setattr(wording, "_ui_checked", {})
    return table


@pytest.mark.parametrize("name,current,old", [
    ("kwp", "(aktuell)", "(alt)"),
    ("default", "(current)", "(old)"),
    ("scenarios", "(current)", "(old)"),
])
def test_the_tag_after_a_document_is_the_profiles_word(conn, name, current, old):
    cat = catalog.Catalog(load_profile(name))
    labels = {e.id: e.label for e in cat.entries(conn, include_superseded=True)}
    assert labels[1] == f"doc · 2024-07-08 · {current}"
    assert labels[2] == f"alt · 2023 Q4 · {old}"


def test_a_profile_with_other_words_is_heard(conn, monkeypatch):
    """The case that breaks it: words no core ever wrote."""
    _worded(monkeypatch, version_current="(now)", version_old="(then)")
    cat = catalog.Catalog(Profile(name="probe_words", extends="default"))
    labels = {e.id: e.label for e in cat.entries(conn, include_superseded=True)}
    assert labels[1].endswith(" · (now)")
    assert labels[2].endswith(" · (then)")


def test_without_a_profile_the_picker_speaks_the_built_in_profiles_words(
        conn, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    cat = catalog.Catalog()
    assert [e.label for e in cat.entries(conn)] == ["doc · 2024-07-08 · (current)"]
    assert cat.document_noun == "document"


def test_a_profile_with_no_words_of_its_own_says_so_and_does_not_use_german(conn):
    """A profile that stands alone and words nothing has no tag to print. The
    picker names what is missing instead of printing a word nobody chose."""
    cat = catalog.Catalog(Profile(name="mute"))
    with pytest.raises(LookupError, match="inference.UI of profile 'mute'"):
        cat.entries(conn)


@pytest.mark.parametrize("name,noun", [
    ("kwp", "Dokument"), ("scenarios", "document"), ("default", "document")])
def test_a_profile_that_names_no_noun_gets_its_fallback_noun(name, noun):
    nameless = dataclasses.replace(load_profile(name), document_noun="")
    assert catalog.Catalog(nameless).document_noun == noun


def test_a_noun_the_profile_names_is_the_one_used(monkeypatch):
    _worded(monkeypatch, document_noun_fallback="thing")
    assert catalog.Catalog(Profile(name="probe_words", extends="default",
                                   document_noun="plan")).document_noun == "plan"
    assert catalog.Catalog(Profile(name="probe_words", extends="default",
                                   document_noun="")).document_noun == "thing"


def _row(**kw):
    base = {"municipality_name": "Flensburg", "organisation_unit_name": None,
            "published": "20240701", "is_current": 1,
            "filename": "waermeplan_flensburg_20240701.pdf"}
    base.update(kw)
    return base


def test_kwps_own_label_is_what_it_was_character_for_character():
    assert document_label(_row(), ["Flensburg"]) == \
        "Flensburg · 2024-07-01 · (aktuell)"
    assert document_label(_row(is_current=0), ["Flensburg"]) == \
        "Flensburg · 2024-07-01 · (alt)"
    convoy = _row(municipality_name="Gemmrigheim",
                  organisation_unit_name="GVV Besigheim",
                  published="20260401",
                  filename="waermeplan_konvoi_hessigheim_20260401.pdf")
    assert document_label(convoy, ["Gemmrigheim", "Hessigheim", "Mundelsheim",
                                   "Walheim"]) == \
        "GVV Besigheim · Konvoi · 4 Gemeinden · 2026-04-01 · (aktuell)"


def test_kwps_own_label_reads_the_words_of_its_table_and_does_not_repeat_them(
        monkeypatch):
    """The case that breaks it: other words in the table. A label that still
    wrote "(aktuell)" itself would keep the old words and say the table's
    entries were not the ones in use."""
    from profiles.kwp import inference
    monkeypatch.setitem(inference.UI, "version_current", "(now)")
    monkeypatch.setitem(inference.UI, "version_old", "(then)")
    assert document_label(_row(), ["Flensburg"]).endswith(" · (now)")
    assert document_label(_row(is_current=0), ["Flensburg"]).endswith(" · (then)")


# ---------------------------------------------------------------------------
# the noun of a document
# ---------------------------------------------------------------------------
def test_a_profile_that_names_no_noun_says_document():
    assert Profile(name="x").document_noun == "document"


def _names_a_noun(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Profile":
            return any(keyword.arg == "document_noun" for keyword in node.keywords)
    return False


def _homes():
    return sorted(home for root in (ROOT / "profiles", ROOT / "docpipe" / "builtin")
                  for home in root.iterdir() if (home / "profile.py").is_file())


def test_every_profile_of_this_repository_names_its_own_noun():
    homes = _homes()
    assert {"kwp", "scenarios", "default"} <= {home.name for home in homes}
    for home in homes:
        assert _names_a_noun((home / "profile.py").read_text(encoding="utf-8")), (
            f"{home.name} leaves its noun to the default")
    nouns = {home.name: load_profile(home.name).document_noun for home in homes}
    assert {name: nouns[name] for name in ("default", "kwp", "scenarios")} == {
        "default": "document", "kwp": "Wärmeplan", "scenarios": "Publikation"}


def test_a_profile_file_that_names_no_noun_is_seen():
    assert not _names_a_noun('PROFILE = Profile(name="x", title="X")')
    assert _names_a_noun('PROFILE = Profile(name="x", document_noun="plan")')


# ---------------------------------------------------------------------------
# what opens a caption
# ---------------------------------------------------------------------------
# The pattern the core carried before the profile was asked, as it stood.
LEGACY = (r"(?:^|(?<=[\s\]]))([A-ZÄÖÜ][A-Za-zÄÖÜäöüß.]{2,14}"
          r"\s+\d+(?:[-.–]\d+)*\s*:)")

# What that pattern said of each line, taken before it was moved.
VERDICTS = [
    ("Tabelle 17: Endenergieverbrauch der Gesamtstadt", True),
    ("Abbildung 2-3: Wärmedichte", True),
    ("Abb. 4: Karte der Wärmedichte", True),
    ("Tab. 2: Kennzahlen", True),
    ("Übersicht 5: Maßnahmen", True),
    ("Karte 3: Wärmedichte", True),
    ("Anlage 2: Fragebogen", True),
    ("Abbildung 3.2: Verlauf", True),
    ("Tabelle 17 : Endenergieverbrauch", True),
    ("Tabelle 17 Endenergieverbrauch", False),
    ("Tabelle 17.", False),
    ("Tabelle A.1: Anhang", False),
    ("Abbildung 3", False),
    ("Hinweis: Wegen der Rundung von Zahlenwerten können Abweichungen "
     "auftreten.", False),
    ("Quelle: eigene Darstellung", False),
    ("siehe Tabelle 17: Endenergieverbrauch", False),
    ("", False),
    ("   ", False),
    ("Table 3: Final energy", True),
    ("Figure 2-1: Emissions by sector", True),
    ("Fig. 2: Primary energy", True),
    ("Figure 3.", False),
    ("Fig. 2", False),
    ("Table 1", False),
    ("Table A.1:", False),
    ("Table 1 shows the totals", False),
    ("Table 1. Annual totals", False),
    ("Box 2 Definitions", False),
    ("Note 2: see appendix", True),
    ("Gráfico 3: Emisiones", False),
    ("Рисунок 3: Выбросы", False),
    ("Şekil 3: Emisyonlar", False),
]

# Two sections as a plan prints them: captions in the running text, one of
# them behind a footnote, and a sentence that only refers to a table.
RUN = ("Die Werte stehen in Tabelle 4: Endenergie 2040 [p4_tbl0] Hinweis: "
       "Rundung. Tabelle 5: CO2-Emissionen [p5_tbl0] Siehe Tabelle 6. "
       "Table 3: Final energy [p6_tbl0] Fig. 2 Primary energy [p7_img0]")


@pytest.fixture
def fresh(monkeypatch):
    """What was compiled for another profile is not this test's."""
    monkeypatch.setattr(captions, "_openers", {})


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_they_declare_exactly_the_pattern_the_core_carried(name):
    assert load_profile(name)._own("preprocessing", "CAPTION_START") == (LEGACY,)


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_every_line_is_decided_as_the_core_decided_it(name, monkeypatch, fresh):
    monkeypatch.setenv(ENV_VAR, name)
    wrong = [(line, verdict) for line, verdict in VERDICTS
             if captions.looks_like_a_caption(line) is not verdict]
    assert not wrong, wrong


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_every_opening_in_a_run_is_found_where_the_core_found_it(
        name, monkeypatch, fresh):
    """The titles `resolve_title` takes out of a section start where this
    pattern finds an opening, so the same spans are the same titles."""
    monkeypatch.setenv(ENV_VAR, name)
    spans = [m.span() for m in captions._caption_start().finditer(RUN)]
    assert spans == [m.span() for m in re.finditer(LEGACY, RUN)]
    assert len(spans) == 3
    assert captions.resolve_title("Hinweis: Rundung.", RUN, "p5_tbl0") \
        .startswith("Tabelle 5: CO2-Emissionen")


# What the built-in profile reads besides that shape.
ENGLISH_CAPTIONS = [
    "Figure 3.", "Fig. 2", "Table 1", "Table A.1:", "Table 3: Final energy",
    "Figure 2-1: Emissions by sector", "Fig. 2 Primary energy",
    "Table 1. Annual totals", "Box 2 Definitions", "Figure 3. Global emissions",
    "Fig 2", "Table A1: Annex", "Tab. 4: Totals", "Plate 2",
]
ENGLISH_PROSE = [
    "Table 1 shows the totals", "see Table 1.", "In Table 1 Germany leads",
    "Table 12 shows that", "Figure out the rest", "Table of contents", "Table",
    "Note: sources differ", "Source: own calculation",
    "Tabelle 17 Endenergieverbrauch", "",
]


@pytest.mark.parametrize("line", ENGLISH_CAPTIONS)
def test_the_built_in_profile_reads_the_common_english_forms(
        line, monkeypatch, fresh):
    monkeypatch.setenv(ENV_VAR, "default")
    assert captions.looks_like_a_caption(line), line


@pytest.mark.parametrize("line", ENGLISH_PROSE)
def test_the_built_in_profile_still_reads_prose_as_prose(line, monkeypatch, fresh):
    """The case that breaks it: a sentence that opens like a caption."""
    monkeypatch.setenv(ENV_VAR, "default")
    assert not captions.looks_like_a_caption(line), line


def test_the_built_in_profile_keeps_the_shape_the_others_have(monkeypatch, fresh):
    monkeypatch.setenv(ENV_VAR, "default")
    assert captions.looks_like_a_caption("Tabelle 17: Endenergieverbrauch")
    assert not captions.looks_like_a_caption(
        "Hinweis: Wegen der Rundung von Zahlenwerten")


def test_the_profile_decides_and_not_the_core(monkeypatch, fresh):
    """The same line, three profiles: the answer follows the one in force."""
    verdicts = {}
    for name in ("kwp", "default", "scenarios", "kwp"):
        monkeypatch.setenv(ENV_VAR, name)
        verdicts.setdefault(name, []).append(captions.looks_like_a_caption("Table 1"))
    assert verdicts == {"kwp": [False, False], "default": [True],
                        "scenarios": [False]}


def test_a_title_is_taken_from_a_caption_without_a_colon(monkeypatch, fresh):
    monkeypatch.setenv(ENV_VAR, "default")
    content = ("Emissions fall. Table 2 Annual totals [p3_tbl0] Figure 5. "
               "Primary energy [p4_img0]")
    assert captions.resolve_title("Source: x", content, "p3_tbl0") == \
        "Table 2 Annual totals"
    assert captions.resolve_title("Source: x", content, "p4_img0") == \
        "Figure 5. Primary energy"


def test_a_sentence_that_only_refers_to_a_table_is_not_taken_for_its_title(
        monkeypatch, fresh):
    """The case that breaks it, in a running text: a reference in prose stands
    right before the placeholder and must not replace what Stage 2 stored."""
    monkeypatch.setenv(ENV_VAR, "default")
    for content, block in [
            ("The values stand in Table 1 Germany leads the ranking [p5_tbl0]",
             "p5_tbl0"),
            ("The shares are given in Figure 4. [p6_img0]", "p6_img0"),
            ("The totals follow from Table 6 [p7_tbl0]", "p7_tbl0")]:
        assert captions.resolve_title("Source: x", content, block) == "Source: x"


def test_the_core_asks_the_profile_in_force_and_holds_no_pattern(
        monkeypatch, fresh):
    own = types.SimpleNamespace(
        name="probe", require=lambda module, attr: (
            r"(?:^|(?<=[\s\]]))(Zzz\s+\d+:)",))
    monkeypatch.setattr(captions, "load_profile", lambda name: own)
    monkeypatch.setenv(ENV_VAR, "probe")
    assert captions.looks_like_a_caption("Zzz 4: whatever")
    assert not captions.looks_like_a_caption("Tabelle 17: Endenergieverbrauch")
    assert not captions.looks_like_a_caption("Table 3: Final energy")


def test_without_a_profile_in_force_the_built_in_one_reads(monkeypatch, fresh):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert captions.looks_like_a_caption("Table 1")
    assert captions.looks_like_a_caption("Tabelle 17: Endenergieverbrauch")


@pytest.mark.parametrize("patterns", [(), [], "Tabelle", ("fine", 3), None, 5])
def test_a_list_that_cannot_be_one_is_refused_and_does_not_match_everything(
        patterns):
    """An empty alternation matches every text, and a bare string is read
    letter by letter: both are the profile's mistake, said so."""
    with pytest.raises(ValueError, match="preprocessing.CAPTION_START"):
        captions._compile("probe", patterns)


def test_a_pattern_that_does_not_compile_is_named():
    with pytest.raises(ValueError, match="'probe'.*does not compile"):
        captions._compile("probe", (r"(unclosed",))


@pytest.mark.parametrize("patterns", [
    ("",), (r"Tabelle\s+\d+:", ""), (r"x*",), (r"(?:^|(?<=\s))",)])
def test_a_pattern_that_matches_the_empty_text_is_refused(patterns):
    """The case that breaks it: a list that is not empty and still takes every
    text for a caption, because one of its patterns needs no text at all."""
    with pytest.raises(ValueError, match="'probe'.*empty text"):
        captions._compile("probe", patterns)


@pytest.mark.parametrize("listed", [(), "Tabelle", (r"(unclosed",), ("",), None])
def test_a_list_the_profile_gets_wrong_is_refused_where_the_core_asks(
        listed, monkeypatch, fresh):
    """Through the path a stage takes, not only through `_compile`: the
    profile is named, nothing is remembered of the refusal, and a corrected
    list is read the next time."""
    state = {"listed": listed}
    own = types.SimpleNamespace(
        name="probe", require=lambda module, attr: state["listed"])
    monkeypatch.setattr(captions, "load_profile", lambda name: own)
    monkeypatch.setenv(ENV_VAR, "probe")
    with pytest.raises(ValueError, match="profile 'probe'.*CAPTION_START"):
        captions.looks_like_a_caption("Tabelle 17: Endenergieverbrauch")
    assert "probe" not in captions._openers
    state["listed"] = (r"(?:^|(?<=[\s\]]))(Tabelle\s+\d+\s*:)",)
    assert captions.looks_like_a_caption("Tabelle 17: Endenergieverbrauch")


@pytest.mark.parametrize("name", [home.name for home in _homes()])
def test_every_profile_of_this_repository_reads_its_own_caption_and_not_a_note(
        name, monkeypatch, fresh):
    """A profile added here without a usable list is found by this test and
    not in the first stage that asks it."""
    monkeypatch.setenv(ENV_VAR, name)
    caption = "Tabelle 17: Endenergieverbrauch" if name == "kwp" \
        else "Table 3: Final energy"
    assert captions.looks_like_a_caption(caption)
    assert not captions.looks_like_a_caption("Hinweis: Wegen der Rundung")
    assert not captions.looks_like_a_caption("")


def test_a_profile_that_lists_none_and_extends_nothing_fails_loudly(
        tmp_path, monkeypatch, fresh):
    alone = Profile(name="alone", home=tmp_path)
    monkeypatch.setattr(captions, "load_profile", lambda name: alone)
    monkeypatch.setenv(ENV_VAR, "alone")
    with pytest.raises(LookupError, match="preprocessing.CAPTION_START"):
        captions.looks_like_a_caption("Tabelle 17: Endenergieverbrauch")


# ---------------------------------------------------------------------------
# the core itself
# ---------------------------------------------------------------------------
CORE_FILES = ["docpipe/inference/catalog.py", "docpipe/profile.py",
              "docpipe/captions.py"]


@pytest.mark.parametrize("word", [
    "aktuell", "(alt)", "Dokument", "ÄÖÜ", "_CAPTION_START"])
@pytest.mark.parametrize("path", CORE_FILES)
def test_the_core_holds_none_of_the_words_that_moved(path, word):
    text = (ROOT / path).read_text(encoding="utf-8")
    assert word not in text, f"{path} still carries {word!r}"
