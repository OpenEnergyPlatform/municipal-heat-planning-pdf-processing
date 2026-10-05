"""Two word lists that belong to the profile, not to the core.

Promised: the words by which stage 3 knows a directory heading are the
profile's (`preprocessing.py: DIRECTORY_TITLE_WORDS`), and for kwp, scenarios
and the built-in profile they are today's four, so every verdict on a title
stays what it was (VERDICTS is that, for a fixed list); AND the language tag
of the alternative labels a vocabulary snapshot keeps is the profile's
(`extraction.py: ALT_LABEL_LANGUAGE`), "de" for kwp and scenarios as before
and "en" for the built-in profile, AND the core fixes none.
"""
import inspect
import sys
from pathlib import Path

import pytest

from docpipe import ontology
from docpipe import profile as profiles
from docpipe.preprocessing import stage3_structure as s3
from docpipe.preprocessing.models import Section
from docpipe.profile import load_profile

PROFILE_NAMES = ["kwp", "scenarios", "default"]

# What the core's own pattern, `inhalt|verzeichnis|contents|directory` without
# regard to case, said of each of these titles before the words moved out.
VERDICTS = {
    "Inhaltsverzeichnis": True, "Inhalt": True, "INHALT": True,
    "Abbildungsverzeichnis": True, "Tabellenverzeichnis": True,
    "Stichwortverzeichnis": True, "Literaturverzeichnis": True,
    "Verzeichnis der Abkürzungen": True, "Inhaltsangabe": True,
    "Table of Contents": True, "Contents": True, "Directory": True,
    "Directory of figures": True,
    "Einleitung": False, "Zusammenfassung": False, "Anhang": False,
    "Executive Summary": False, "Introduction": False, "Index": False,
    "List of Figures": False, "Sommaire": False,
    "Table des matières": False, "Content": False, "Contenido": False,
    "": False,
}

# Ten listing entries, then prose: the listing is 39 percent of the section.
# That clears the bar a directory title brings (35) and not the bar a section
# without one has to clear (55), and the prose left over is past what the
# second rule allows. So only the title can make this section a directory.
LISTING = "".join(f"Kapitel{n} ............ {n * 5} " for n in range(1, 11))
PROSE = ("Die folgenden Seiten fassen zusammen, was die Stadt geplant hat "
         "und wie sie dabei vorgegangen ist. ") * 4
ONLY_THE_TITLE_DECIDES = LISTING + PROSE


def _dropped(title: str) -> bool:
    _kept, dropped = s3.drop_directory_sections(
        [Section(title=title, content=ONLY_THE_TITLE_DECIDES)])
    return dropped == 1


@pytest.fixture
def under(monkeypatch):
    """Run as the named profile, with what stage 3 remembers per profile."""
    def use(name):
        monkeypatch.setenv(profiles.ENV_VAR, name)
    return use


@pytest.fixture
def lone(tmp_path, monkeypatch):
    """A profile outside the repository: make(preprocessing_text) -> its name.

    What the process remembers of it is forgotten afterwards, so that a
    profile of the same name in a later test is read again.
    """
    package = sys.modules.get(profiles.PROFILES_PACKAGE)
    path = list(getattr(package, "__path__", ()))
    modules = set(sys.modules)
    made = []

    def make(preprocessing: str, name="wordlist_probe") -> str:
        home = tmp_path / name
        home.mkdir()
        (home / "__init__.py").write_text("", encoding="utf-8")
        (home / "profile.py").write_text(
            "from docpipe.profile import Profile\n"
            f"PROFILE = Profile(name={name!r}, extends='default')\n",
            encoding="utf-8")
        (home / "preprocessing.py").write_text(preprocessing,
                                               encoding="utf-8")
        monkeypatch.setenv(profiles.PATH_ENV, str(tmp_path))
        monkeypatch.setenv(profiles.ENV_VAR, name)
        made.append(name)
        return name

    yield make
    for name in sys.modules.keys() - modules:
        del sys.modules[name]
    if package is not None:
        package.__path__ = path
    profiles._BOUND = None
    for name in made:
        s3._dir_title.pop(name, None)
        for key in [k for k in profiles._values if k[0] == name]:
            del profiles._values[key]


# ---------------------------------------------------------------------------
# the directory title words
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_every_title_gets_the_verdict_it_got_before(name, under):
    under(name)
    got = {title: bool(s3._dir_title_re().search(title))
           for title in VERDICTS}
    assert got == VERDICTS


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_a_section_is_dropped_by_its_title_alone_as_before(name, under):
    under(name)
    # Not "Literaturverzeichnis": whether a bibliography title protects its
    # section is the other list's verdict, and differs between the profiles.
    titles = [title for title in VERDICTS if title != "Literaturverzeichnis"]
    got = {title: _dropped(title) for title in titles}
    assert got == {title: VERDICTS[title] for title in titles}


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_each_profile_states_the_four_words_itself(name):
    """Declared in its own module, not taken from the one it extends: a
    profile that loses its list would otherwise be answered for silently."""
    profile = load_profile(name)
    assert profile._own("preprocessing", "DIRECTORY_TITLE_WORDS") == (
        "inhalt", "verzeichnis", "contents", "directory")


def test_the_profile_decides_which_words_make_a_title(lone):
    """A profile with other words gets other verdicts. Under the pattern the
    core used to carry, "Inhaltsverzeichnis" would still be dropped here and
    "Sommaire" would still be kept."""
    lone('DIRECTORY_TITLE_WORDS = ("sommaire",)\n')
    assert _dropped("Sommaire") is True
    assert _dropped("Table des Sommaires") is True
    assert _dropped("Inhaltsverzeichnis") is False
    assert _dropped("Contents") is False


def test_a_profile_without_title_words_has_no_directory_title(lone):
    """Not "every title is one": the words joined into a pattern would be the
    empty pattern, which matches everything."""
    lone("DIRECTORY_TITLE_WORDS = ()\n")
    assert s3._dir_title_re().search("Inhaltsverzeichnis") is None
    assert s3._dir_title_re().search("") is None
    assert _dropped("Inhaltsverzeichnis") is False


def test_a_profile_that_extends_the_default_without_the_words_gets_its_four(lone):
    lone("CAPTION_MAX_WORDS = 7\n")
    assert _dropped("Inhaltsverzeichnis") is True
    assert _dropped("Einleitung") is False


@pytest.mark.parametrize("word", ["inhalt", "verzeichnis"])
def test_the_core_holds_none_of_the_german_title_words(word):
    """The case that breaks it: the pattern put back into the core file."""
    core = Path(s3.__file__).read_text(encoding="utf-8").lower()
    assert word not in core


# ---------------------------------------------------------------------------
# the language of the alternative labels
# ---------------------------------------------------------------------------

TINY = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .
@prefix oeo:  <https://openenergyplatform.org/ontology/oeo/> .

<https://openenergyplatform.org/ontology/oeo/> a owl:Ontology ;
    owl:versionIRI <https://openenergyplatform.org/ontology/oeo/releases/1/oeo.owl> .

oeo:OEO_00020039 a owl:Class ; rdfs:label "energy carrier" .
oeo:OEO_00000292 a owl:Class ; rdfs:label "natural gas" ;
    rdfs:subClassOf oeo:OEO_00020039 ;
    obo:IAO_0000118 "Erdgas"@de, "natural gas fuel"@en, "gaz naturel"@fr .
oeo:OEO_00000293 a owl:Class ; rdfs:label "hard coal" ;
    rdfs:subClassOf oeo:OEO_00020039 ;
    obo:IAO_0000118 "coal, hard" .
"""
OEO = "https://openenergyplatform.org/ontology/oeo/"
SETS = {"energy_carrier": ("class", OEO + "OEO_00020039")}
SPEC = {"parameters": [{"uri": "p", "kg": {"class": "OEO_00000292"}}]}


@pytest.fixture
def closure(tmp_path):
    pytest.importorskip("rdflib")
    path = tmp_path / "tiny.ttl"
    path.write_text(TINY, encoding="utf-8")
    return path


def _labels(closure, language):
    built = ontology.build(closure, SETS, SPEC, base=OEO, language=language)
    return {uri: term["alt_labels"] for uri, term in built["terms"].items()
            if uri.startswith("OEO_0000029")}


def test_the_snapshot_keeps_the_labels_of_the_language_it_is_given(closure):
    assert _labels(closure, "de")["OEO_00000292"] == ["Erdgas"]
    assert _labels(closure, "en")["OEO_00000292"] == ["natural gas fuel"]
    assert _labels(closure, "fr")["OEO_00000292"] == ["gaz naturel"]


def test_a_language_the_term_lacks_gives_no_label_of_another(closure):
    """Nothing tagged "it" and nothing untagged on this term: an empty list,
    not the German or the English word offered as an Italian one."""
    assert _labels(closure, "it")["OEO_00000292"] == []


def test_an_untagged_label_is_what_a_term_without_the_tag_falls_back_to(
        closure):
    for language in ("de", "en"):
        assert _labels(closure, language)["OEO_00000293"] == ["coal, hard"]


def test_the_core_names_no_language_of_its_own(closure):
    with pytest.raises(TypeError, match="language"):
        ontology.build(closure, SETS, SPEC, base=OEO)


@pytest.mark.parametrize("function", [ontology.index, ontology.build])
def test_neither_function_of_the_core_has_a_default_language(function):
    """`index` is where the tag is used. A default there would be the core's
    own language again, behind a `build` that passes the profile's."""
    parameter = inspect.signature(function).parameters["language"]
    assert parameter.default is inspect.Parameter.empty


@pytest.mark.parametrize("name, tag", [("kwp", "de"), ("scenarios", "de"),
                                       ("default", "en")])
def test_each_profile_says_the_language_of_its_labels(name, tag):
    assert load_profile(name).require("extraction",
                                      "ALT_LABEL_LANGUAGE") == tag


@pytest.mark.parametrize("name", ["kwp", "scenarios"])
def test_a_vocabulary_module_builds_with_its_profiles_tag(name, monkeypatch):
    """The module asks the profile and passes what it says on. A tag written
    into the module (or left to the core) would not move with the profile."""
    import importlib
    vocabulary = importlib.import_module(f"profiles.{name}.vocabulary")
    extraction = importlib.import_module(f"profiles.{name}.extraction")
    seen = []

    def spy(closure, sets, spec_raw, **kwargs):
        seen.append(kwargs["language"])
        return {"pin": {}}

    monkeypatch.setattr(ontology, "build", spy)
    vocabulary.build(Path("closure.owl"))
    monkeypatch.setattr(extraction, "ALT_LABEL_LANGUAGE", "fr")
    vocabulary.build(Path("closure.owl"))
    assert seen == ["de", "fr"]
