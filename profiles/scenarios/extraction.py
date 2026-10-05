"""Extraction stage wiring: where the ar6 spec lives, and the lists that are
only closed once a document is named.

Two of the ar6 fields have a finite set of correct answers, but the set is not
the same for every publication, so it cannot sit in the spec file:

  scenario / scenario_label  the AR6 scenarios THIS publication documents.
                             The corpus holds 1389 of them, one publication
                             documents up to 146, and the model has to pick
                             from that publication's own list.
  scenario_region            the 249 study regions the OEKG actually uses,
                             narrowed to those the document names at all.

The narrowing is not a guess. Every claim has to quote its source verbatim, and
the sources are exactly the section, table and figure texts scanned here, so a
region whose name appears nowhere in them could never have been quoted. What is
dropped is unreachable, not merely unlikely — and dropping it keeps the prompt
at the handful of countries a paper mentions instead of all 249.

Both lists carry `out:` entries, and they are the point of this file as much as
the real entries are. A closed list without an escape hatch does not stop the
model from answering; it stops it from answering CORRECTLY, and what comes back
is the nearest entry that is not quite right. The OEKG knows 249 countries and
no aggregates, while an AR6 scenario is usually global — so without
`out:global` the honest answer to "which region" does not exist in the list,
and a paper about worldwide emissions that happens to mention Germany once
invites "Germany". The same holds for a run identifier: naming a family is not
naming a run, and the model needs a way to say so that is not silence.

Silence is the other half of the argument. An empty field already meant
"unmapped" and was already counted, but it meant three different things at
once — nothing fitted, the model did not look, the reply was cut short. A
chosen `out:` entry means exactly one of them, and it is the one worth
counting.
"""
import json
import re
import sqlite3
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")
REGIONS_PATH = Path(__file__).with_name("regions.json")

# Every label is matched on word boundaries, short or long. "US" hides inside
# "thus" and "UK" inside "Ukraine", but so does Niger inside Nigeria, India
# inside Indiana and Chile inside Chilean — and those are the expensive ones,
# because they put a wrong country in front of the model as a valid choice.
# The cost is the other direction: a paper that only ever writes "Chilean" no
# longer offers Chile. That is the cheaper mistake, and it is a visible one —
# the model then has to choose the out: entry, which is counted.
_WORD = r"(?<!\w){}(?!\w)"


# The entries that are not a thing in the graph. `kg.py` refuses to mint an IRI
# or a link from any of them (see NOT_IN_GRAPH there) and counts them by name.
NOT_IN_GRAPH = "out:"

# The first label is the answer token: runner._parameter_payload renders a
# choice list as {labels[0]: labels[1:]} and the prompt says to copy it
# character for character. So labels[0] is short and quotable, and the
# explanation is an alternate — value_to_uri() maps every label, so both
# spellings resolve. The long gloss first was a mistake: an answer nobody can
# retype without a slip is an answer that arrives as an unmapped wording, and
# an unmapped wording is exactly what these entries exist to prevent.
#
# A scenario is global far more often than national, and the OEKG's region list
# is 249 countries with no aggregate — no World, no EU27, no OECD, no R5.
# Without these the correct answer for most AR6 scenarios is not in the list.
REGION_OUT = {
    "out:global": ["global", "weltweit", "worldwide",
                   u"global — die ganze Welt, kein einzelnes Land"],
    "out:multiregion": ["mehrere Regionen", "mehrere Länder", "EU27", "OECD",
                        u"mehrere Länder oder eine Region, die die Liste "
                        u"nicht führt"],
    "out:other": ["andere Region", "etwas anderes, das kein Land der Liste ist"],
}

# The AR6 identifiers are finer than the language of the papers: the pilot's
# 146-scenario document writes "NPi", and the database has EN_NPi2020_300f,
# _400 and _3000. That wording names a family, not a run, and `ambiguous()` in
# kg.py drops the link when it happens. It cannot tell that case apart from a
# scenario the publication simply does not have in AR6 — these two can.
SCENARIO_OUT = {
    "out:family": ["Szenario-Familie", "Familie",
                   "eine Szenario-Familie oder eine Beschreibung, die auf "
                   "mehrere Läufe passt und auf keinen genau",
                   "eine Szenario-Familie, kein einzelner Lauf"],
    "out:not_documented": ["nicht in AR6", "nicht in der AR6-Liste",
                           u"ein Szenario dieser Publikation, das nicht in "
                           u"ihrer AR6-Liste steht"],
}


def _regions() -> dict:
    return json.loads(REGIONS_PATH.read_text(encoding="utf-8"))


def _document_text(conn: sqlite3.Connection, document_id: int) -> str:
    """Everything a harvest of this document could ever quote from."""
    # The captions belong in here as much as the bodies do: a harvest quotes
    # the caption of a table as readily as its cells, so a country named only
    # in "Figure 3: Emissions in India" is quotable — and if the narrowing has
    # not seen it, the model is offered no class for it and answers with a
    # wording nobody can resolve.
    rows = conn.execute(
        "SELECT s.content FROM Sections s WHERE s.document = ? "
        "UNION ALL "
        "SELECT t.markdown FROM Tables t JOIN Sections s ON t.section = s.id "
        "WHERE s.document = ? "
        "UNION ALL "
        "SELECT t.caption FROM Tables t JOIN Sections s ON t.section = s.id "
        "WHERE s.document = ? "
        "UNION ALL "
        "SELECT i.description FROM Images i JOIN Sections s ON i.section = s.id "
        "WHERE s.document = ? "
        "UNION ALL "
        "SELECT i.caption FROM Images i JOIN Sections s ON i.section = s.id "
        "WHERE s.document = ?",
        (document_id,) * 5,
    ).fetchall()
    return "\n".join(str(r[0]) for r in rows if r[0])


def _acronym(label: str) -> bool:
    """A label that is only a word when its capitals are: US, UK, USA, U.S."""
    return len(label) <= 4 and label.upper() == label and label.lower() != label


def _mentioned(text: str, labels: list) -> bool:
    lowered = text.casefold()
    for label in labels:
        # "US" casefolds onto the English pronoun, and these publications are
        # English, so every one of them would be offered the United States as
        # a class next to the out: entries — reintroducing exactly the pull
        # those entries exist to remove. An all-caps acronym is matched with
        # its capitals; everything else is matched casefolded.
        if _acronym(label):
            if re.search(_WORD.format(re.escape(label)), text):
                return True
            continue
        needle = label.casefold()
        if needle not in lowered:
            continue
        if re.search(_WORD.format(re.escape(needle)), lowered):
            return True
    return False


def document_scenarios(conn: sqlite3.Connection, document_id: int) -> dict:
    """The AR6 scenarios this publication documents, as a choice list.

    Keyed by the AR6 name itself rather than an invented IRI: the name is the
    identity the corpus links against, and kg.py resolves it the same way.
    """
    rows = conn.execute(
        "SELECT sc.name FROM Scenarios sc "
        "JOIN DocumentScenarios ds ON ds.scenario = sc.id "
        "WHERE ds.document = ? ORDER BY sc.name",
        (document_id,),
    ).fetchall()
    return {str(r[0]): [str(r[0])] for r in rows if r[0]}


def document_regions(conn: sqlite3.Connection, document_id: int) -> dict:
    text = _document_text(conn, document_id)
    if not text:
        return {}
    return {iri: labels for iri, labels in _regions().items()
            if _mentioned(text, labels)}


def document_axes(conn: sqlite3.Connection, document_id: int) -> dict:
    """Per-document choice lists, keyed by axis name and by parameter uri.

    The out: entries are appended unconditionally, so every list exists even
    when the narrowing finds nothing. That case is not hypothetical — a
    publication with no runs in DocumentScenarios, or one that names no country
    at all, used to leave the field with no list, and a field with no list is
    free text again.
    """
    scenarios = dict(document_scenarios(conn, document_id))
    scenarios.update(SCENARIO_OUT)
    regions = dict(document_regions(conn, document_id))
    regions.update(REGION_OUT)
    return {
        "scenario": scenarios,          # the coordinate on the other fields
        "scenario_label": scenarios,    # and the value of the field itself
        "scenario_region": regions,
    }

# How the documents write the decimal. It decides what the digits leave
# open: "3,251" is 3251 here, and "1.234" is 1.234.
DECIMAL_MARK = "."


# What the stage says to the model outside its prompts: why an answer was not
# taken, what was wrong with a reply, what stands beside an image. In the
# language of the prompts, and read by docpipe/extraction/wording.py, which
# says what each name is filled with.
PHRASES = {
    # the closed list as a request shows it
    "option_means": 'bedeutet',
    "option_spellings": 'Schreibweisen',
    "unstated_means": 'in diesen Passagen steht es nicht',
    "unstated_spelling": 'steht in diesen Passagen nicht',
    # why a coordinate's answer was not taken
    "kind_whole_number": 'eine ganze Zahl',
    "kind_text": 'eine Angabe als Text',
    "not_an_option": (
        'Dein "value" {given!r} ist keiner der Einträge aus "options". '
        'Wähle genau einen Namen daraus, Zeichen für Zeichen '
        'abgeschrieben, auch einen mit "out:". Passt keiner, obwohl die '
        'Passage die Angabe nennt, dann lass "value" weg und gib die '
        'Bezeichnung in "value_raw".'),
    "wrong_type": (
        'Dein "value" {given!r} ist nicht {wrong}. Antworte mit {wrong}, '
        'genau wie die Passage es schreibt.'),
    "quote_not_in_source": (
        'Dein "quote" steht in keiner der gezeigten Quellen. Kopiere '
        'eine Passage Zeichen für Zeichen aus "sources" oder aus dem '
        '"quote" der Zeile selbst.'),
    "quote_too_short": (
        'Dein "quote" ist zu kurz, um eine Stelle zu benennen '
        '(mindestens {minimum} Zeichen). Zitier den ganzen Satz oder die '
        'ganze Zeile, in der die Antwort steht.'),
    "answer_not_in_quote": (
        'Dein "quote" enthält {answer!r} nicht. Zitier die Stelle, an '
        'der es wirklich steht, oder antworte mit "{unstated}".'),
    # why a pair of the document's frame was not taken
    "frame_missing": 'In einem Paar fehlte "{slot}".',
    "frame_no_quote": 'Zu {slot}={given!r} fehlte "{slot}_quote".',
    "frame_quote_not_in_source": (
        'Das Zitat zu {slot}={given!r} steht in keiner der gezeigten '
        'Passagen: {quote!r}. Kopiere es Zeichen für Zeichen aus '
        '"sources".'),
    "frame_answer_not_in_quote": (
        '{slot}={given!r} steht nicht in seinem Zitat {quote!r}. Schreib '
        'die Formulierung des Plans in "{slot}_raw".'),
    "frame_not_an_option": (
        '{given!r} ist keiner der Schlüssel aus "scenarios". Wähle genau '
        'einen daraus, Zeichen für Zeichen abgeschrieben, und schreib '
        'das Wort des Plans in "{slot}_raw".'),
    "frame_not_a_year": (
        '{slot}={given!r} ist keine ganze Jahreszahl. Gib das Jahr '
        'vierstellig an.'),
    # a reply that could not be read
    "shape_rule": (
        ' Gib NUR das JSON-Objekt aus, in EINER Zeile, ohne Text davor '
        'oder danach, ohne Codefence, ohne <think>-Block und ohne ein '
        'zweites Objekt. Anführungszeichen INNERHALB eines Zitats müssen '
        'als \\" escaped sein — ist das mühsam, kürz das Zitat auf eine '
        'Stelle ohne Anführungszeichen.'),
    "cut_off": (
        'Deine Antwort wurde nach {limit} Tokens abgeschnitten und ist '
        'deshalb kein vollständiges JSON-Objekt. '),
    "shorter": (
        'Antworte kürzer: zitiere nur die kurze Stelle, an der die '
        'Angabe steht.'),
    "shorter_frame": (
        'Antworte mit weniger Paaren und zitiere nur die kurze Stelle, '
        'an der das Szenario oder das Jahr steht.'),
    "shorter_rows": (
        'Antworte mit weniger Tupeln und zitiere nur die kurze Stelle, '
        'an der die Zahl steht.'),
    "shorter_field": (
        'Fasse Zeilen mit derselben Antwort in "groups" zusammen und '
        'zitiere nur die kurze Stelle, an der die Angabe steht.'),
    "shorter_review": (
        'Zitiere nur die kurze Stelle, an der die Angabe steht, und lass '
        'jedes Feld weg, das die zwei Passagen nicht tragen.'),
    "reasoning_only": (
        'Du hast nur nachgedacht und nichts geantwortet: dein Beitrag '
        'war leer. Denk nicht vor, sondern gib direkt das Ergebnis aus.'),
    "empty": 'Deine Antwort war leer.',
    "no_object": 'Deine Antwort enthielt gar kein JSON-Objekt.',
    "syntax": (
        'Dein JSON bricht bei Zeichen {position} ab ({message}), an '
        'dieser Stelle: {around!r}.'),
    "outside_text": 'Neben dem JSON-Objekt stand noch Text: {extra!r}.',
    "not_an_object": (
        'Deine Antwort war eine {kind}-Struktur und kein JSON-Objekt.'),
    "key_missing": 'In deiner Antwort fehlte "{key}".',
    "key_not_a_list": 'In deiner Antwort war keine Liste "{key}".',
    "wrong_shape": 'Deine Antwort hatte nicht die Form, die verlangt war.',
    # what the model gets back after a calculation
    "code_failed": (
        'Der Code lief nicht: {error}. Antworte jetzt ohne Berechnung, '
        'oder korrigiere den Code.'),
    "code_error_unknown": 'unbekannt',
    "code_silent": (
        'Der Code lief, hat aber nichts ausgegeben. Gib jedes Ergebnis '
        'mit print() aus, oder antworte ohne Berechnung.'),
    "code_output": (
        'Ausgabe des Codes:\n{output}\n\nAntworte jetzt mit dem '
        'Tupel-Objekt. Berechnete Werte tragen "computed": true.'),
    # labels inside a request
    "image_for": 'Bild zu {label}:',
    "anchor_parameter": 'Kennzahl',
    "anchor_unit": 'Einheit',
}
