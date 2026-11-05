"""Extraction stage wiring: the kwp spec, the slice gate, the frame, and what
a plan says about itself."""
import json
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
# are deliberate non-classes the model chose (a share, a specific figure), and
# no ontology term is waiting for them.
#
# None means "any class the graph takes", which is every entry that does not
# start with out:. A tuple names the answers that keep the row.
#
# The year closes no row and stands here for its order alone: every axis behind
# it reads with the year known. Asked side by side, up to 1,368 tuples of
# corpus_m7_100 took the scenario of a chart's title for a year it does not
# hold (owner decision 2026-11-02).
#
# Quantities of their own the ontology has no class for yet are read on every
# axis into the harvest, and reach the graph once a class does (owner decision
# 2026-11-03). Every other out: entry still closes its row.
READ_IN_FULL = ("out:useful_energy", "out:generation", "out:saving",
                "out:avoided")


def kept_quantities() -> tuple:
    """Every class of the spec's quantity lists, and READ_IN_FULL."""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    entries = {uri for parameter in spec["parameters"]
               for uri in ((parameter.get("axes") or {}).get("quantity")
                           or {}).get("vocabulary", {})}
    return tuple(sorted(uri for uri in entries
                        if not uri.startswith("out:") or uri in READ_IN_FULL))


SLICE = {"quantity": kept_quantities(), "year": None}


# What a plan says about itself: asked once more over the opening of the
# document in a harvest field by field, and searched with a sentence written
# for this plan where the survey named no passage for it
# (`runner.make_seek_probes`, owner decision 2026-11-05). The spec asks for no
# such field of a heat plan, so every parameter is searched with a sentence
# written once per run.
FRONT_PAGE_PARAMETERS: tuple = ()


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

# What counts as a year here: a zone number printed beside a value (169002)
# was answered as its year, in the frame and on a row (owner decision
# 2026-11-01).
YEAR_RANGE = (1900, 2100)

# Which frame pairs are the plan's target. Their years are the plan's target
# years, each with the frame's quote that prints it. A row whose table says
# only "Zieljahr" answers one of them the same way (owner decision
# 2026-10-06, the model chooses among them): the current harvest dropped
# about 14,500 year answers whose quote carried the plan's word for its
# target and not the number, "Zieljahr" 12,369 of them.
TARGET_YEAR = {"scenario": "target"}


# How far past its own passage a coordinate is looked for, as a share of the
# search budget (FIELD_MAX_WINDOWS, REST_MAX_WINDOWS). Under one budget on
# corpus_m5, the sector's search filled 4 percent of its 392,541 requests and
# the aggregation's 3 percent of 65,285; the scope's and the scenario's filled
# 23 to 25 percent. A coordinate not named here searches with the whole
# budget. One whose search is cut short ends `exhausted`, never `unstated`
# (owner decision 2026-09-23).
#
# 0 reads the value's own passage alone (owner decision 2026-10-22): the
# MHPKG schema leaves an emission's carrier and sector optional, because the
# law asks for the total, and every technology optional. A key may name the
# parameter, `<parameter>.<axis>`, and is read before the bare axis.
SEARCH_SHARE = {"sector": 0.5, "aggregation": 0.5, "subject": 0, "whole": 0,
                "emission.carrier": 0, "emission.sector": 0,
                "technology": 0}

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
    "kind_year": 'ein Kalenderjahr mit vier Ziffern',
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
    "value_outside_quote": (
        'Diese Zahlen stehen nicht in dem "quote", unter dem du sie angegeben '
        'hast: {values}. Gib nur diese Einträge noch einmal an, jede Zahl '
        'unter dem Zitat der Zeile, die sie druckt, und lass eine Zahl weg, '
        'die keine Zeile druckt.'),
    "compute_output": (
        'Ausgabe des Codes:\n{output}\n\nAntworte jetzt mit "value" und '
        '"used".'),
    "compute_needs_code": (
        'Eine Zahl ohne Code ist nicht belegt. Rechne sie mit dem '
        'Aktions-Objekt aus, oder antworte mit "value": null.'),
    "compute_taken": (
        '{label} steht jetzt unter "numbers", im Code als '
        'numbers["{label}"].'),
    "compute_not_taken": (
        'Die Zahl unter "take" ist nicht übernommen: {reason}. Schreibe ihr '
        'Zitat Zeichen für Zeichen aus der gezeigten Passage ab, in der sie '
        'steht, mit der Zahl darin.'),
    "compute_quote": (
        'Dein "quote" steht nicht in der Passage von {label}. Schreibe aus '
        'dieser Passage Zeichen für Zeichen ab, was {label} ist.'),
    "value_in_several_rows": (
        'Das "quote" dieser Zahlen läuft über mehrere Tabellenzeilen, und '
        'mehr als eine davon druckt die Zahl: {values}. Gib nur diese '
        'Einträge noch einmal an, jeden mit genau der einen Zeile, in der '
        'er steht, als "quote".'),
    # eine Runde der Werte einer Passage, je ein Wert
    "value_already_read": (
        'Diesen Wert hast du schon genannt: {value} mit dem Zitat {quote!r}. '
        'Nenne den nächsten Wert, der noch nicht unter "read" steht, oder '
        'antworte mit "next": null.'),
    "head_not_in_table": (
        'Der Kopf {head!r} steht in keiner Kopfzeile der Tabelle. Schreib '
        'den Kopf der Spalte des Werts Zeichen für Zeichen, wie er dort '
        'steht.'),
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
