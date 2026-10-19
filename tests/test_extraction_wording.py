"""What the extraction stage says to the model outside its prompts.

Promised: the sentences are the profile's (`extraction.py: PHRASES`) AND for
kwp they are, byte for byte, what the core said while they were German
literals in it, except the two keys of a closed list, which are the English
ones in every profile (EXPECTED is that, for a fixed set of cases); scenarios
says the same things in English, as the built-in profile does (EXPECTED_EN is
that, for the same cases); every phrase is in all three tables with the same
names to fill in; and a profile that lacks one is told which.
"""
import string
from types import SimpleNamespace as NS

import pytest

from docpipe import prompts
from docpipe.extraction import fields, pipeline, runner, wording
from docpipe.extraction.pipeline import Row, Source
from docpipe.extraction.spec import load as load_spec
from docpipe.profile import Profile, load_profile

# What the core said before the sentences moved into the profiles.
EXPECTED = {'anchor_labels': [['#parameter', 'Kennzahl'], ['#unit', 'Einheit']],
 'answerable': [{'Erdgas': {'means': 'ein Gas',
                            'spellings': ['Gas H']},
                 'Strom': {'spellings': ['Elektrizität']},
                 'out:unstated': {'means': 'in diesen Passagen steht es '
                                           'nicht'}},
                {'GHD': ['Gewerbe'],
                 'out:unstated': ['steht in diesen Passagen nicht']}],
 'compute': ['Der Code lief nicht: boom. Antworte jetzt ohne Berechnung, '
             'oder korrigiere den Code.',
             'Der Code lief nicht: unbekannt. Antworte jetzt ohne '
             'Berechnung, oder korrigiere den Code.',
             'Der Code lief, hat aber nichts ausgegeben. Gib jedes '
             'Ergebnis mit print() aus, oder antworte ohne Berechnung.',
             'Ausgabe des Codes:\n'
             '42\n'
             '\n'
             'Antworte jetzt mit dem Tupel-Objekt. Berechnete Werte tragen '
             '"computed": true.'],
 'frame_pairs': {'answer_not_in_quote': ["scenario='target' steht nicht in "
                                         "seinem Zitat 'im Jahr 2020 bei "
                                         '120 GWh im gesamten '
                                         "Stadtgebiet'. Schreib die "
                                         'Formulierung des Plans in '
                                         '"scenario_raw".'],
                 'missing': ['In einem Paar fehlte "scenario".'],
                 'no_quote': ["Zu scenario='target' fehlte "
                              '"scenario_quote".'],
                 'not_a_year': ["year='Jahr 2020' steht nicht in seinem "
                                "Zitat 'im Jahr 2020 bei 120 GWh im "
                                "gesamten Stadtgebiet'. Schreib die "
                                'Formulierung des Plans in "year_raw".'],
                 'not_an_option': ["'Stadtgebiet' ist keiner der Schlüssel "
                                   'aus "scenarios". Wähle genau einen '
                                   'daraus, Zeichen für Zeichen '
                                   'abgeschrieben, und schreib das Wort '
                                   'des Plans in "scenario_raw".'],
                 'quote_not_in_source': ["Das Zitat zu scenario='target' "
                                         'steht in keiner der gezeigten '
                                         "Passagen: 'das steht nicht da'. "
                                         'Kopiere es Zeichen für Zeichen '
                                         'aus "sources".']},
 'merge_field': {'answer_not_in_quote': ['Dein "quote" enthält 2030 nicht. '
                                         'Zitier die Stelle, an der es '
                                         'wirklich steht, oder antworte '
                                         'mit "out:unstated".'],
                 'not_an_option': ['Dein "value" \'Kohle\' ist keiner der '
                                   'Einträge aus "options". Wähle genau '
                                   'einen Namen daraus, Zeichen für '
                                   'Zeichen abgeschrieben, auch einen mit '
                                   '"out:". Passt keiner, obwohl die '
                                   'Passage die Angabe nennt, dann lass '
                                   '"value" weg und gib die Bezeichnung in '
                                   '"value_raw".'],
                 'quote_not_in_source': ['Dein "quote" steht in keiner der '
                                         'gezeigten Quellen. Kopiere eine '
                                         'Passage Zeichen für Zeichen aus '
                                         '"sources" oder aus dem "quote" '
                                         'der Zeile selbst.'],
                 'quote_too_short': ['Dein "quote" ist zu kurz, um eine '
                                     'Stelle zu benennen (mindestens 8 '
                                     'Zeichen). Zitier den ganzen Satz '
                                     'oder die ganze Zeile, in der die '
                                     'Antwort steht.'],
                 'wrong_type': ['Dein "value" \'2020-2030\' ist nicht eine '
                                'ganze Zahl. Antworte mit eine ganze Zahl, '
                                'genau wie die Passage es schreibt.']},
 'reply_fault': {'cut_off': ['cut_off',
                             'Deine Antwort wurde nach 512 Tokens '
                             'abgeschnitten und ist deshalb kein '
                             'vollständiges JSON-Objekt. Antworte kürzer: '
                             'zitiere nur die kurze Stelle, an der die '
                             'Angabe steht.'],
                 'cut_off_shorter': ['cut_off',
                                     'Deine Antwort wurde nach 512 Tokens '
                                     'abgeschnitten und ist deshalb kein '
                                     'vollständiges JSON-Objekt. Mach es '
                                     'kurz.'],
                 'empty': ['empty',
                           'Deine Antwort war leer. Gib NUR das '
                           'JSON-Objekt aus, in EINER Zeile, ohne Text '
                           'davor oder danach, ohne Codefence, ohne '
                           '<think>-Block und ohne ein zweites Objekt. '
                           'Anführungszeichen INNERHALB eines Zitats '
                           'müssen als \\" escaped sein — ist das mühsam, '
                           'kürz das Zitat auf eine Stelle ohne '
                           'Anführungszeichen.'],
                 'key_not_a_list': ['missing_key',
                                    'In deiner Antwort war keine Liste '
                                    '"tuples". Gib NUR das JSON-Objekt '
                                    'aus, in EINER Zeile, ohne Text davor '
                                    'oder danach, ohne Codefence, ohne '
                                    '<think>-Block und ohne ein zweites '
                                    'Objekt. Anführungszeichen INNERHALB '
                                    'eines Zitats müssen als \\" escaped '
                                    'sein — ist das mühsam, kürz das Zitat '
                                    'auf eine Stelle ohne '
                                    'Anführungszeichen.'],
                 'missing_key': ['missing_key',
                                 'In deiner Antwort fehlte "tuples". Gib '
                                 'NUR das JSON-Objekt aus, in EINER Zeile, '
                                 'ohne Text davor oder danach, ohne '
                                 'Codefence, ohne <think>-Block und ohne '
                                 'ein zweites Objekt. Anführungszeichen '
                                 'INNERHALB eines Zitats müssen als \\" '
                                 'escaped sein — ist das mühsam, kürz das '
                                 'Zitat auf eine Stelle ohne '
                                 'Anführungszeichen.'],
                 'no_object': ['no_object',
                               'Deine Antwort enthielt gar kein '
                               'JSON-Objekt. Gib NUR das JSON-Objekt aus, '
                               'in EINER Zeile, ohne Text davor oder '
                               'danach, ohne Codefence, ohne <think>-Block '
                               'und ohne ein zweites Objekt. '
                               'Anführungszeichen INNERHALB eines Zitats '
                               'müssen als \\" escaped sein — ist das '
                               'mühsam, kürz das Zitat auf eine Stelle '
                               'ohne Anführungszeichen.'],
                 'not_an_object': ['not_an_object',
                                   'Deine Antwort war eine list-Struktur '
                                   'und kein JSON-Objekt. Gib NUR das '
                                   'JSON-Objekt aus, in EINER Zeile, ohne '
                                   'Text davor oder danach, ohne '
                                   'Codefence, ohne <think>-Block und ohne '
                                   'ein zweites Objekt. Anführungszeichen '
                                   'INNERHALB eines Zitats müssen als \\" '
                                   'escaped sein — ist das mühsam, kürz '
                                   'das Zitat auf eine Stelle ohne '
                                   'Anführungszeichen.'],
                 'outside_text': ['outside_text',
                                  'Neben dem JSON-Objekt stand noch Text: '
                                  "'Hier:  fertig'. Gib NUR das "
                                  'JSON-Objekt aus, in EINER Zeile, ohne '
                                  'Text davor oder danach, ohne Codefence, '
                                  'ohne <think>-Block und ohne ein zweites '
                                  'Objekt. Anführungszeichen INNERHALB '
                                  'eines Zitats müssen als \\" escaped '
                                  'sein — ist das mühsam, kürz das Zitat '
                                  'auf eine Stelle ohne '
                                  'Anführungszeichen.'],
                 'reasoning_only': ['reasoning_only',
                                    'Du hast nur nachgedacht und nichts '
                                    'geantwortet: dein Beitrag war leer. '
                                    'Denk nicht vor, sondern gib direkt '
                                    'das Ergebnis aus. Gib NUR das '
                                    'JSON-Objekt aus, in EINER Zeile, ohne '
                                    'Text davor oder danach, ohne '
                                    'Codefence, ohne <think>-Block und '
                                    'ohne ein zweites Objekt. '
                                    'Anführungszeichen INNERHALB eines '
                                    'Zitats müssen als \\" escaped sein — '
                                    'ist das mühsam, kürz das Zitat auf '
                                    'eine Stelle ohne Anführungszeichen.'],
                 'syntax': ['syntax',
                            'Dein JSON bricht bei Zeichen 17 ab (Expecting '
                            'value), an dieser Stelle: \'{"tuples": [1, '
                            "2,, 3]}'. Gib NUR das JSON-Objekt aus, in "
                            'EINER Zeile, ohne Text davor oder danach, '
                            'ohne Codefence, ohne <think>-Block und ohne '
                            'ein zweites Objekt. Anführungszeichen '
                            'INNERHALB eines Zitats müssen als \\" escaped '
                            'sein — ist das mühsam, kürz das Zitat auf '
                            'eine Stelle ohne Anführungszeichen.'],
                 'wrong_shape': ['wrong_shape',
                                 'Deine Antwort hatte nicht die Form, die '
                                 'verlangt war. Gib NUR das JSON-Objekt '
                                 'aus, in EINER Zeile, ohne Text davor '
                                 'oder danach, ohne Codefence, ohne '
                                 '<think>-Block und ohne ein zweites '
                                 'Objekt. Anführungszeichen INNERHALB '
                                 'eines Zitats müssen als \\" escaped sein '
                                 '— ist das mühsam, kürz das Zitat auf '
                                 'eine Stelle ohne Anführungszeichen.']},
 'shape_rule': ' Gib NUR das JSON-Objekt aus, in EINER Zeile, ohne Text '
               'davor oder danach, ohne Codefence, ohne <think>-Block und '
               'ohne ein zweites Objekt. Anführungszeichen INNERHALB eines '
               'Zitats müssen als \\" escaped sein — ist das mühsam, kürz '
               'das Zitat auf eine Stelle ohne Anführungszeichen.',
 'wrong_type': ['eine ganze Zahl',
                'eine ganze Zahl',
                'eine ganze Zahl',
                'eine Angabe als Text',
                None]}


# What scenarios says since it is English: the same cases as above, in the
# English sentences of its table.
EXPECTED_EN = {'anchor_labels': [['#parameter', 'Field'], ['#unit', 'Unit']],
 'answerable': [{'Erdgas': {'means': 'ein Gas', 'spellings': ['Gas H']},
                 'Strom': {'spellings': ['Elektrizität']},
                 'out:unstated': {'means': 'these passages do not state '
                                           'it'}},
                {'GHD': ['Gewerbe'],
                 'out:unstated': ['not stated in these passages']}],
 'compute': ['The code did not run: boom. Answer now without a '
             'calculation, or correct the code.',
             'The code did not run: unknown. Answer now without a '
             'calculation, or correct the code.',
             'The code ran but printed nothing. Print every result with '
             'print(), or answer without a calculation.',
             'Output of the code:\n'
             '42\n'
             '\n'
             'Answer now with the tuple object. Calculated values carry '
             '"computed": true.'],
 'frame_pairs': {'answer_not_in_quote': ["scenario='target' does not stand "
                                         "in its quote 'im Jahr 2020 bei "
                                         '120 GWh im gesamten '
                                         "Stadtgebiet'. Write the wording "
                                         'of the document into '
                                         '"scenario_raw".'],
                 'missing': ['A pair lacked "scenario".'],
                 'no_quote': ['For scenario=\'target\', "scenario_quote" '
                              'was missing.'],
                 'not_a_year': ["year='Jahr 2020' does not stand in its "
                                "quote 'im Jahr 2020 bei 120 GWh im "
                                "gesamten Stadtgebiet'. Write the wording "
                                'of the document into "year_raw".'],
                 'not_an_option': ["'Stadtgebiet' is none of the keys of "
                                   '"scenarios". Choose exactly one of '
                                   'them, copied character for character, '
                                   'and write the word of the document '
                                   'into "scenario_raw".'],
                 'quote_not_in_source': ["The quote for scenario='target' "
                                         'stands in none of the passages '
                                         "shown: 'das steht nicht da'. "
                                         'Copy it character for character '
                                         'from "sources".']},
 'merge_field': {'answer_not_in_quote': ['Your "quote" does not contain '
                                         '2030. Quote the place where it '
                                         'really stands, or answer with '
                                         '"out:unstated".'],
                 'not_an_option': ['Your "value" \'Kohle\' is none of the '
                                   'entries of "options". Choose exactly '
                                   'one name from it, copied character for '
                                   'character, including one that starts '
                                   'with "out:". If none fits although the '
                                   'passage states the field, leave '
                                   '"value" out and give the wording in '
                                   '"value_raw".'],
                 'quote_not_in_source': ['Your "quote" stands in none of '
                                         'the sources shown. Copy a '
                                         'passage character for character '
                                         'from "sources" or from the '
                                         '"quote" of the row itself.'],
                 'quote_too_short': ['Your "quote" is too short to name a '
                                     'place (at least 8 characters). Quote '
                                     'the whole sentence or the whole line '
                                     'the answer stands in.'],
                 'wrong_type': ['Your "value" \'2020-2030\' is not a whole '
                                'number. Answer with a whole number, '
                                'exactly as the passage writes it.']},
 'reply_fault': {'cut_off': ['cut_off',
                             'Your answer was cut off after 512 tokens and '
                             'is therefore not a complete JSON object. '
                             'Answer more briefly: quote only the short '
                             'place where the field stands.'],
                 'cut_off_shorter': ['cut_off',
                                     'Your answer was cut off after 512 '
                                     'tokens and is therefore not a '
                                     'complete JSON object. Mach es kurz.'],
                 'empty': ['empty',
                           'Your answer was empty. Output ONLY the JSON '
                           'object, on ONE line, with no text before or '
                           'after it, no code fence, no <think> block and '
                           'no second object. Quotation marks INSIDE a '
                           'quote must be escaped as \\" — if that is '
                           'tedious, shorten the quote to a place without '
                           'quotation marks.'],
                 'key_not_a_list': ['missing_key',
                                    'In your answer "tuples" was not a '
                                    'list. Output ONLY the JSON object, on '
                                    'ONE line, with no text before or '
                                    'after it, no code fence, no <think> '
                                    'block and no second object. Quotation '
                                    'marks INSIDE a quote must be escaped '
                                    'as \\" — if that is tedious, shorten '
                                    'the quote to a place without '
                                    'quotation marks.'],
                 'missing_key': ['missing_key',
                                 'Your answer lacked "tuples". Output ONLY '
                                 'the JSON object, on ONE line, with no '
                                 'text before or after it, no code fence, '
                                 'no <think> block and no second object. '
                                 'Quotation marks INSIDE a quote must be '
                                 'escaped as \\" — if that is tedious, '
                                 'shorten the quote to a place without '
                                 'quotation marks.'],
                 'no_object': ['no_object',
                               'Your answer contained no JSON object at '
                               'all. Output ONLY the JSON object, on ONE '
                               'line, with no text before or after it, no '
                               'code fence, no <think> block and no second '
                               'object. Quotation marks INSIDE a quote '
                               'must be escaped as \\" — if that is '
                               'tedious, shorten the quote to a place '
                               'without quotation marks.'],
                 'not_an_object': ['not_an_object',
                                   'Your answer was a list structure and '
                                   'not a JSON object. Output ONLY the '
                                   'JSON object, on ONE line, with no text '
                                   'before or after it, no code fence, no '
                                   '<think> block and no second object. '
                                   'Quotation marks INSIDE a quote must be '
                                   'escaped as \\" — if that is tedious, '
                                   'shorten the quote to a place without '
                                   'quotation marks.'],
                 'outside_text': ['outside_text',
                                  'There was text beside the JSON object: '
                                  "'Hier:  fertig'. Output ONLY the JSON "
                                  'object, on ONE line, with no text '
                                  'before or after it, no code fence, no '
                                  '<think> block and no second object. '
                                  'Quotation marks INSIDE a quote must be '
                                  'escaped as \\" — if that is tedious, '
                                  'shorten the quote to a place without '
                                  'quotation marks.'],
                 'reasoning_only': ['reasoning_only',
                                    'You only thought and answered '
                                    'nothing: your reply was empty. Do not '
                                    'think ahead, output the result '
                                    'directly. Output ONLY the JSON '
                                    'object, on ONE line, with no text '
                                    'before or after it, no code fence, no '
                                    '<think> block and no second object. '
                                    'Quotation marks INSIDE a quote must '
                                    'be escaped as \\" — if that is '
                                    'tedious, shorten the quote to a place '
                                    'without quotation marks.'],
                 'syntax': ['syntax',
                            'Your JSON breaks at character 17 (Expecting '
                            'value), at this place: \'{"tuples": [1, 2,, '
                            "3]}'. Output ONLY the JSON object, on ONE "
                            'line, with no text before or after it, no '
                            'code fence, no <think> block and no second '
                            'object. Quotation marks INSIDE a quote must '
                            'be escaped as \\" — if that is tedious, '
                            'shorten the quote to a place without '
                            'quotation marks.'],
                 'wrong_shape': ['wrong_shape',
                                 'Your answer did not have the form that '
                                 'was asked for. Output ONLY the JSON '
                                 'object, on ONE line, with no text before '
                                 'or after it, no code fence, no <think> '
                                 'block and no second object. Quotation '
                                 'marks INSIDE a quote must be escaped as '
                                 '\\" — if that is tedious, shorten the '
                                 'quote to a place without quotation '
                                 'marks.']},
 'shape_rule': ' Output ONLY the JSON object, on ONE line, with no text '
               'before or after it, no code fence, no <think> block and no '
               'second object. Quotation marks INSIDE a quote must be '
               'escaped as \\" — if that is tedious, shorten the quote to '
               'a place without quotation marks.',
 'wrong_type': ['a whole number',
                'a whole number',
                'a whole number',
                'a piece of text',
                None]}

EXPECTED_OF = {"kwp": EXPECTED, "scenarios": EXPECTED_EN}
IMAGE_FOR = {"kwp": "Bild zu Q3:", "scenarios": "Image for Q3:"}
NOT_A_YEAR = {"kwp": "year='20x' ist keine ganze Jahreszahl. Gib das Jahr "
                     "vierstellig an.",
              "scenarios": "year='20x' is not a whole year. Give the year "
                           "with four digits."}


WITH_MEANING = fields.Slot(name="carrier", kind=fields.CHOICE, options=(
    fields.Option(label="Erdgas", uri="u1", synonyms=("Gas H",),
                  definition="ein Gas"),
    fields.Option(label="Strom", uri="u2", synonyms=("Elektrizität",)),
))
PLAIN = fields.Slot(name="sector", kind=fields.CHOICE, options=(
    fields.Option(label="GHD", uri="u3", synonyms=("Gewerbe",)),))
YEAR = fields.Slot(name="year", kind=fields.NUMBER)
SCENARIO = fields.Slot(name="scenario", kind=fields.CHOICE, options=(
    fields.Option(label="target", uri="t", synonyms=("Zielszenario",)),))
SOURCE = Source(owner_kind="section", owner_id=1,
                text="Der Verbrauch an Erdgas lag im Jahr 2020 bei 120 GWh "
                     "im gesamten Stadtgebiet.")
QUOTE = "im Jahr 2020 bei 120 GWh im gesamten Stadtgebiet"


@pytest.fixture(params=["kwp", "scenarios"])
def german(request, monkeypatch):
    """The two corpus profiles: kwp, whose sentences are German, and scenarios,
    whose sentences are English (the name is the fixture's from when both were
    German)."""
    monkeypatch.setenv("DOCPIPE_PROFILE", request.param)
    return request.param


def _reply(content, finish="stop", reasoning=None):
    return NS(finish_reason=finish, message=NS(
        content=content, reasoning_content=reasoning))


def test_the_closed_list_names_meaning_and_spellings_under_english_keys(
        german):
    assert [WITH_MEANING.answerable(), PLAIN.answerable()] == \
        EXPECTED_OF[german]["answerable"]
    # the order of the two keys is part of the request
    assert list(WITH_MEANING.answerable()["Erdgas"]) == [
        "means", "spellings"]


def test_a_reply_that_could_not_be_read_is_told_why_as_before(german):
    cases = {
        "cut_off": (_reply('{"tuples": [', "length"), {}),
        "cut_off_shorter": (_reply("", "length"),
                            {"shorter": "Mach es kurz."}),
        "reasoning_only": (_reply("", "stop", "ich denke"), {}),
        "empty": (_reply(""), {}),
        "no_object": (_reply("keine Ahnung"), {}),
        "syntax": (_reply('{"tuples": [1, 2,, 3]}'), {}),
        "outside_text": (_reply('Hier: {"tuples": []} fertig'), {}),
        "not_an_object": (_reply("[1, 2]"), {}),
        "missing_key": (_reply('{"other": 1}'), {"key": "tuples"}),
        "key_not_a_list": (_reply('{"tuples": 3}'), {"key": "tuples"}),
        "wrong_shape": (_reply('{"tuples": []}'), {}),
    }
    got = {name: list(runner._reply_fault(given, 512, **options))
           for name, (given, options) in cases.items()}
    assert got == EXPECTED_OF[german]["reply_fault"]
    assert runner._shape_rule() == EXPECTED_OF[german]["shape_rule"]


def test_a_calculation_is_answered_as_before(german):
    assert [runner._compute_reply({"ok": False, "error": "boom"}),
            runner._compute_reply({"ok": False}),
            runner._compute_reply({"ok": True, "stdout": "  "}),
            runner._compute_reply({"ok": True, "stdout": "42\n"})] == \
        EXPECTED_OF[german]["compute"]


def _field_reasons(slot, answers):
    rows = [Row(label=label, item_index=0,
                claim={"value": 120, "quote": "bei 120 GWh"})
            for label in answers]
    got = pipeline.merge_field(rows, [SOURCE], slot, {"answers": answers})
    return [failure["reason"] for failure in got.get("failed") or ()]


def test_a_coordinate_that_was_not_taken_is_told_why_as_before(german):
    assert [pipeline._wrong_type(NS(kind=fields.NUMBER), True),
            pipeline._wrong_type(NS(kind=fields.NUMBER), 2030.5),
            pipeline._wrong_type(NS(kind=fields.NUMBER), "x"),
            pipeline._wrong_type(NS(kind=fields.TEXT), 3),
            pipeline._wrong_type(NS(kind=fields.NUMBER), "2045.0")] == \
        EXPECTED_OF[german]["wrong_type"]
    assert {
        "not_an_option": _field_reasons(WITH_MEANING, {
            "R1": {"value": "Kohle", "quote": "Der Verbrauch an Erdgas"}}),
        "wrong_type": _field_reasons(YEAR, {
            "R1": {"value": "2020-2030",
                   "quote": "im Jahr 2020 bei 120 GWh"}}),
        "quote_not_in_source": _field_reasons(YEAR, {
            "R1": {"value": 2020, "quote": "steht nirgends in der Quelle"}}),
        "quote_too_short": _field_reasons(YEAR, {
            "R1": {"value": 2020, "quote": "2020"}}),
        "answer_not_in_quote": _field_reasons(YEAR, {
            "R1": {"value": 2030, "quote": "im Jahr 2020 bei 120 GWh"}}),
    } == EXPECTED_OF[german]["merge_field"]


def _frame_reasons(entry):
    rejected: list = []
    runner.frame_pairs({"pairs": [entry]}, [SCENARIO, YEAR], [SOURCE],
                       rejected)
    return [item["reason"] for item in rejected]


def test_a_pair_that_was_not_taken_is_told_why_as_before(german):
    good = {"scenario": "target", "scenario_raw": "gesamten Stadtgebiet",
            "scenario_quote": QUOTE, "scenario_source": "Q1"}
    assert {
        "missing": _frame_reasons({"scenario": ""}),
        "no_quote": _frame_reasons({"scenario": "target"}),
        "quote_not_in_source": _frame_reasons({
            "scenario": "target", "scenario_quote": "das steht nicht da"}),
        "answer_not_in_quote": _frame_reasons({
            "scenario": "target", "scenario_quote": QUOTE}),
        "not_an_option": _frame_reasons({
            "scenario": "Stadtgebiet", "scenario_quote": QUOTE}),
        "not_a_year": _frame_reasons({
            **good, "year": "Jahr 2020", "year_raw": "Jahr 2020",
            "year_quote": QUOTE}),
    } == EXPECTED_OF[german]["frame_pairs"]
    # the one refusal these pairs do not reach
    assert wording.say("frame_not_a_year", slot="year", given="20x") == (
        NOT_A_YEAR[german])


def test_the_two_core_questions_are_labelled_as_before(german):
    profile = load_profile(german)
    spec = load_spec(profile.component("extraction", "SPEC_PATH"))
    # the first target is the parameter's; the unit's follows where a spec
    # has a numeric parameter
    assert list(runner.anchor_targets(spec)[0][:2]) == \
        EXPECTED_OF[german]["anchor_labels"][0]
    assert wording.say("anchor_unit") == EXPECTED_OF[german]["anchor_labels"][1][1]
    assert wording.say("image_for", label="Q3") == IMAGE_FOR[german]


# -- the three tables against each other --------------------------------------

def _names(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


# A name the stage hands a phrase and a profile may use or leave out: one
# key for every closed frame coordinate or one per coordinate, and a
# correction that names that key by what was sent or by its own words.
MAY_LEAVE_OUT = {"frame_options": {"slot"},
                 "frame_not_an_option": {"options"}}


@pytest.mark.parametrize("name", ["kwp", "scenarios", "default"])
def test_every_profile_says_every_sentence_with_the_same_names(name):
    own = load_profile(name)._own("extraction", "PHRASES")
    assert set(own) == wording.REQUIRED
    german = load_profile("kwp")._own("extraction", "PHRASES")
    for key, text in own.items():
        assert isinstance(text, str) and text, key
        free = MAY_LEAVE_OUT.get(key, set())
        assert _names(text) - free == _names(german[key]) - free, key


# The two keys of an entry of a closed list are protocol and not prose: every
# profile sends the same two English words, and the prompts that name them
# name these.
ENGLISH_IN_EVERY_PROFILE = {"option_means", "option_spellings"}


def test_the_built_in_profile_says_it_in_english():
    english = load_profile("default")._own("extraction", "PHRASES")
    german = load_profile("kwp")._own("extraction", "PHRASES")
    same = [key for key in english if english[key] == german[key]]
    assert set(same) == ENGLISH_IN_EVERY_PROFILE, same
    umlauts = [key for key, text in english.items()
               if any(char in text for char in "äöüßÄÖÜ")]
    assert not umlauts, umlauts


def test_a_profile_that_lacks_a_sentence_is_told_which(monkeypatch):
    monkeypatch.setattr(wording, "_checked", {})
    half = Profile(name="kwp")          # stands alone: nothing to fall back on
    monkeypatch.setattr(
        Profile, "_own",
        lambda self, module, attr: {"empty": "x"}
        if (module, attr) == ("extraction", "PHRASES") else None)
    with pytest.raises(LookupError) as refused:
        wording.phrases(half)
    assert "shape_rule" in str(refused.value)
    assert "'empty'" not in str(refused.value)


def test_one_sentence_is_laid_over_the_extended_profile_s(tmp_path,
                                                          monkeypatch):
    home = tmp_path / "worded"
    home.mkdir()
    (home / "__init__.py").write_text("", encoding="utf-8")
    (home / "profile.py").write_text(
        "from docpipe.profile import Profile\n"
        "PROFILE = Profile(name='worded', extends='default')\n",
        encoding="utf-8")
    (home / "extraction.py").write_text(
        "PHRASES = {'empty': 'Nothing came back.'}\n", encoding="utf-8")
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))
    monkeypatch.setattr(wording, "_checked", {})
    got = wording.phrases(load_profile("worded"))
    base = load_profile("default")._own("extraction", "PHRASES")
    assert got["empty"] == "Nothing came back."
    assert {k: v for k, v in got.items() if k != "empty"} == \
        {k: v for k, v in base.items() if k != "empty"}


# -- where the frame request puts a closed list -------------------------------

REGION = fields.Slot(name="region", kind=fields.CHOICE, options=(
    fields.Option(label="north", uri="n", synonyms=("the North",)),))


def test_the_frame_request_names_its_list_as_before(german):
    """What the two German profiles send did not move: one key, and it is
    the one their frame prompts read."""
    payload = runner._frame_payload([SOURCE], [SCENARIO, YEAR])
    assert list(payload) == ["sources", "scenarios"]
    assert "target" in payload["scenarios"]
    # and two closed coordinates share that one list, as they always did
    both = runner._frame_payload([SOURCE], [SCENARIO, REGION, YEAR])
    assert list(both) == ["sources", "scenarios"]
    assert {"target", "north"} <= set(both["scenarios"])


def test_a_profile_that_names_the_coordinate_keeps_two_lists_apart(
        monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    payload = runner._frame_payload([SOURCE], [SCENARIO, REGION, YEAR])
    assert list(payload) == ["sources", "scenario_options", "region_options"]
    assert "target" in payload["scenario_options"]
    assert "north" not in payload["scenario_options"]
    assert "north" in payload["region_options"]
    assert "target" not in payload["region_options"]
    # the open coordinate has no list to choose from, under any name
    assert not [key for key in payload if key.startswith("year")]


def _frame_prompt(name) -> str:
    """The prompt as the request carries it: the profile's parts put into the
    core's frame template, not the profile's file."""
    return prompts.load("extraction/frame", load_profile(name)).text


def _refused_choice(slot) -> str:
    """The correction a pair gets that chose something off the list, as the
    stage itself words it."""
    rejected: list = []
    runner.frame_pairs(
        {"pairs": [{slot.name: "not on the list", f"{slot.name}_quote": QUOTE,
                    f"{slot.name}_raw": "Stadtgebiet",
                    f"{slot.name}_source": "Q1"}]},
        [slot], [SOURCE], rejected)
    return rejected[0]["reason"]


@pytest.mark.parametrize("german", ["kwp"], indirect=True)
def test_the_german_frame_prompts_read_the_list_where_the_request_puts_it(
        german):
    """The key is said in four places: by the request, twice by the prompt
    (where to choose from, and what to do about a correction), and by the
    correction itself. Each is the profile's, and each is held on its own:
    one that went stale alone would tell the model of a list that is not
    there."""
    key = wording.say("frame_options", slot="scenario")
    assert key in runner._frame_payload([SOURCE], [SCENARIO, YEAR])
    prompt = _frame_prompt(german)
    choose = [line for line in prompt.splitlines()
              if line.startswith("- `scenario`")]
    correct = [line for line in prompt.splitlines() if '"corrections"' in line]
    assert len(choose) == 1 and f'"{key}"' in choose[0]
    assert len(correct) == 1 and f'"{key}"' in correct[0]
    assert prompt.count(f'"{key}"') == 2
    assert f'"{key}"' in _refused_choice(SCENARIO)


@pytest.mark.parametrize("name", ["default", "scenarios"])
def test_the_english_frame_prompts_name_no_key_that_could_go_stale(
        name, monkeypatch):
    """The built-in profile is the one others extend, and scenarios is
    English like it. Their prompt says where to choose without a key of its
    own, and the correction is handed the key that was sent, for whichever
    coordinate."""
    monkeypatch.setenv("DOCPIPE_PROFILE", name)
    prompt = _frame_prompt(name)
    assert "_options" not in prompt and '"scenarios"' not in prompt
    assert "the list the request gives for `scenario`" in prompt
    for slot in (SCENARIO, REGION):
        key = wording.say("frame_options", slot=slot.name)
        assert key in runner._frame_payload([SOURCE], [slot])
        assert f'"{key}"' in _refused_choice(slot)


def test_a_profile_without_the_key_of_the_list_is_told(monkeypatch):
    monkeypatch.setattr(wording, "_checked", {})
    rest = {key: text for key, text
            in load_profile("kwp")._own("extraction", "PHRASES").items()
            if key != "frame_options"}
    monkeypatch.setattr(
        Profile, "_own",
        lambda self, module, attr: rest
        if (module, attr) == ("extraction", "PHRASES") else None)
    with pytest.raises(LookupError) as refused:
        wording.phrases(Profile(name="kwp"))
    assert "frame_options" in str(refused.value)


def test_a_project_words_the_key_of_the_list_itself(tmp_path, monkeypatch):
    home = tmp_path / "regional"
    home.mkdir()
    (home / "__init__.py").write_text("", encoding="utf-8")
    (home / "profile.py").write_text(
        "from docpipe.profile import Profile\n"
        "PROFILE = Profile(name='regional', extends='default')\n",
        encoding="utf-8")
    (home / "extraction.py").write_text(
        "PHRASES = {'frame_options': 'choices_for_{slot}'}\n",
        encoding="utf-8")
    monkeypatch.setenv("DOCPIPE_PROFILE_PATH", str(tmp_path))
    monkeypatch.setenv("DOCPIPE_PROFILE", "regional")
    monkeypatch.setattr(wording, "_checked", {})
    payload = runner._frame_payload([SOURCE], [SCENARIO, REGION])
    assert list(payload) == ["sources", "choices_for_scenario",
                             "choices_for_region"]
    # the one phrase moved all of it: the correction it inherits names the
    # key that was sent, and the prompt it inherits names none
    assert '"choices_for_region"' in _refused_choice(REGION)
    assert "_options" not in _refused_choice(REGION)
    assert "_options" not in prompts.load("extraction/frame").text


# -- how a corpus writes its numbers ------------------------------------------

def test_the_decimal_mark_is_the_profile_s_and_decides_what_digits_leave_open(
        monkeypatch):
    from docpipe.extraction import verify
    assert [load_profile(name).component("extraction", "DECIMAL_MARK")
            for name in ("kwp", "scenarios", "default")] == [",", ".", "."]
    read = verify.canonical_number
    # the same under both: several marks, or two kinds
    for mark in verify.MARKS:
        assert read("1.036.767,8", mark) == "1036767.8"
        assert read("1,036,767.8", mark) == "1036767.8"
        assert read("12,5", mark) == read("12.5", mark) == "12.5"
    # what only the corpus can say
    assert (read("3,251", ","), read("3,251", ".")) == ("3.251", "3251")
    assert (read("1.234", ","), read("1.234", ".")) == ("1234", "1.234")
    # read with the ambient profile's mark where none is given
    monkeypatch.setattr(verify, "_marks", {})
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    assert read("3,251") == "3251" and "3251" in verify.numbers_in(
        "a total of 3,251 employees")
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    assert read("3,251") == "3.251" and "3.251" in verify.numbers_in(
        "insgesamt 3,251 GWh")


def test_a_profile_that_names_no_mark_is_read_with_the_comma_and_a_wrong_one_is_refused(
        monkeypatch):
    from docpipe.extraction import verify
    monkeypatch.setattr(verify, "_marks", {})
    monkeypatch.setattr(Profile, "component", lambda self, module, attr: None)
    assert verify.decimal_mark() == ","
    monkeypatch.setattr(verify, "_marks", {})
    monkeypatch.setattr(Profile, "component", lambda self, module, attr: ";")
    with pytest.raises(ValueError, match="DECIMAL_MARK"):
        verify.decimal_mark()
