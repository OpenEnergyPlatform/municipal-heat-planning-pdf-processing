"""Extraction stage wiring: the kwp spec, the slice gate, the frame, and what
a plan says about itself."""
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")

# Which coordinates decide whether a value belongs in the graph at all, in the
# order they are asked, and which answers keep the row. They are asked FIRST
# and alone: a row that falls out here costs three requests instead of eight.
# Measured on the 20-plan draft, of 6,763 harvested tuples the serializer
# dropped 1,554 for a quantity the graph does not hold.
#
# THE SCENARIO NO LONGER GATES. It did, and it was the bigger half: 2,510 of
# those 6,763 tuples were dropped for being a status quo, a trend or a
# potential rather than the target scenario, and dropping them was a decision
# about the graph rather than about the plan. MHPO names all three
# (aggregated inventory analysis MHPO_00020005, aggregated potential analysis
# MHPO_00020006) and OEO names the reference scenarios, so a heat plan's
# inventory belongs in the graph as much as its target does and the row has
# to be asked its coordinates to get there.
#
# What still gates is the quantity, and only through its out: entries: those
# are deliberate non-classes the model chose (a share, a specific figure, a
# generation amount), and no ontology term is waiting for them.
#
# None means "any class the graph takes", which is every entry that does not
# start with out:. A tuple names the answers that keep the row.
SLICE = {"quantity": None}


def document_context(conn, document_id: int) -> dict:
    """What this plan says about itself, for the sentence it is searched with.

    The municipality, because a plan writes its own name into headings,
    captions and table titles, and a search anchor that carries it ranks this
    plan's own sections above the boilerplate every plan shares. It lives in
    the catalog join and in no query the core makes, so the core asks the
    profile for it rather than growing a second idea of what a document is.

    Missing metadata is not an error here. The anchor is written from the
    ontology annotation either way and this only makes it sharper.
    """
    try:
        row = conn.execute("""
            SELECT m.name
            FROM Documents d
            LEFT JOIN DocumentMeta dm  ON dm.document = d.id
            LEFT JOIN Municipalities m ON dm.municipality_ags = m.ags
            WHERE d.id = ?
        """, (document_id,)).fetchone()
    except Exception:
        return {}
    # By position. Whether a connection carries a row factory is the caller's
    # business, and a hook that only works on one of the two shapes is a hook
    # that works until somebody passes a plain connection.
    name = row[0] if row else None
    return {"name": name} if name else {}


# Which coordinates belong to the DOCUMENT and not to the row. A plan has
# three scenario containers and a handful of reference years, and they stand
# in headings, captions and column headers -- the carrier and the sector stand
# in the table row itself and are different in every cell. So these two are
# found ONCE, before any value, and every value request afterwards asks for
# one of the pairs that were really found.
#
# Not a cross product. A plan with a target scenario for 2030/2035/2040/2045
# and an inventory for 2022 has five pairs, not twenty.
#
# Measured on M3, this is what it replaces: the year axis produced 1,849
# refusals against 0 readings, because every window after the first excluded
# the row's own source and only that one could carry the year.
FRAME = ("scenario", "year")


# Which frame pairs are the plan's own state. Their years are the plan's base
# years, each with the frame's quote that prints it. A row whose table says
# only "Basisjahr", "Ist-Zustand" or "Bilanzjahr" answers one of them and
# cites the passage with that word; the number is proven by the frame's
# passage (owner decision 2026-09-22, the model chooses among them). corpus_m5
# dropped 127,233 year answers whose wording stood in their quote and whose
# number did not, "Basisjahr" among the most common.
BASE_YEAR = {"scenario": "status_quo"}


# How far past its own passage a coordinate is looked for, as a share of the
# search budget (FIELD_MAX_WINDOWS, REST_MAX_WINDOWS). Under one budget on
# corpus_m5, the sector's search filled 4 percent of its 392,541 requests and
# the aggregation's 3 percent of 65,285; the scope's and the scenario's filled
# 23 to 25 percent. A coordinate not named here searches with the whole
# budget. One whose search is cut short ends `exhausted`, never `unstated`
# (owner decision 2026-09-23).
SEARCH_SHARE = {"sector": 0.5, "aggregation": 0.5}

# How the documents write the decimal. It decides what the digits leave
# open: "3,251 GWh" is 3.251 here, and "1.234" is 1234.
DECIMAL_MARK = ","

# The language tag of the ontology's alternative labels that the vocabulary
# snapshot keeps for this profile, the words its spec is held against.
ALT_LABEL_LANGUAGE = "de"

# The language of the core's contract text in this profile's prompts: the
# parts files of its own that name a template (`template: rows`) are put
# together with the template of this language. Not inherited by a profile that
# extends this one with parts files of its own.
CONTRACT_LANGUAGE = "de"


# What the preflight (`docpipe preflight`) holds this profile's prompts to,
# beyond the keys the stage reads by name: a wording the run depends on. The
# prompts are in the profile's language, so the passage is too.
# (what is checked, prompt, passage, True: has to be there, False: must not)
PROMPT_CHECKS = (
    ("field prompt asks one field", "extraction/field",
     "GENAU EIN Feld", True),
    ("rows prompt no longer fixes one parameter", "extraction/rows",
     '"parameter": die gesucht', False),
)


# What the stage says to the model outside its prompts: why an answer was not
# taken, what was wrong with a reply, what stands beside an image. In the
# language of the prompts, and read by docpipe/extraction/wording.py, which
# says what each name is filled with.
PHRASES = {
    # the closed list as a request shows it: protocol keys, so English in
    # every profile, and the field prompt names them in its rule 7
    "option_means": 'means',
    "option_spellings": 'spellings',
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
    # The key of the frame request that holds the entries of a closed frame
    # coordinate. The frame prompt reads them there.
    "frame_options": "scenarios",
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
