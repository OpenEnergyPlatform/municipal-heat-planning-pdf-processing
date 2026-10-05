"""
extraction.py – What the extraction stage says to the model outside its
prompts, in English.

A profile that extends this one and names an extraction spec of its own
(`SPEC_PATH`) gets these sentences with the prompts beside this file. See
docpipe/extraction/wording.py for what each name is filled with.

Author: Felix Vossel
"""

# How the documents write the decimal. It decides what the digits leave
# open: "3,251" is 3251 here, and "1.234" is 1.234.
DECIMAL_MARK = "."

# The language tag of the ontology's alternative labels that a vocabulary
# snapshot keeps for this profile, the words its spec is held against. This
# profile has no snapshot of its own; one that extends it and builds one reads
# the tag here.
ALT_LABEL_LANGUAGE = "en"


# What the preflight (`docpipe preflight`) holds this profile's prompts to,
# beyond the keys the stage reads by name: a wording the run depends on. The
# prompts are in the profile's language, so the passage is too. A profile
# that words a prompt of its own says its own passages.
# (what is checked, prompt, passage, True: has to be there, False: must not)
PROMPT_CHECKS = (
    ("field prompt asks one field", "extraction/field",
     "EXACTLY ONE field", True),
)

PHRASES = {
    # the closed list as a request shows it
    "option_means": 'means',
    "option_spellings": 'spellings',
    "unstated_means": 'these passages do not state it',
    "unstated_spelling": 'not stated in these passages',
    # why a coordinate's answer was not taken
    "kind_whole_number": 'a whole number',
    "kind_text": 'a piece of text',
    "not_an_option": (
        'Your "value" {given!r} is none of the entries of "options". '
        'Choose exactly one name from it, copied character for '
        'character, including one that starts with "out:". If none fits '
        'although the passage states the field, leave "value" out and '
        'give the wording in "value_raw".'),
    "wrong_type": (
        'Your "value" {given!r} is not {wrong}. Answer with {wrong}, '
        'exactly as the passage writes it.'),
    "quote_not_in_source": (
        'Your "quote" stands in none of the sources shown. Copy a '
        'passage character for character from "sources" or from the '
        '"quote" of the row itself.'),
    "quote_too_short": (
        'Your "quote" is too short to name a place (at least {minimum} '
        'characters). Quote the whole sentence or the whole line the '
        'answer stands in.'),
    "answer_not_in_quote": (
        'Your "quote" does not contain {answer!r}. Quote the place where '
        'it really stands, or answer with "{unstated}".'),
    # The key of the frame request that holds the entries of a closed frame
    # coordinate, one list per coordinate. The frame prompt of this profile
    # names no key of its own ("the list the request gives for ..."), and
    # the correction below is handed the key that was sent, so a profile
    # that words this one phrase differently has moved all of it.
    "frame_options": "{slot}_options",
    # why a pair of the document's frame was not taken
    "frame_missing": 'A pair lacked "{slot}".',
    "frame_no_quote": 'For {slot}={given!r}, "{slot}_quote" was missing.',
    "frame_quote_not_in_source": (
        'The quote for {slot}={given!r} stands in none of the passages '
        'shown: {quote!r}. Copy it character for character from '
        '"sources".'),
    "frame_answer_not_in_quote": (
        '{slot}={given!r} does not stand in its quote {quote!r}. Write '
        'the wording of the document into "{slot}_raw".'),
    "frame_not_an_option": (
        '{given!r} is none of the keys of "{options}". Choose exactly '
        'one of them, copied character for character, and write the word '
        'of the document into "{slot}_raw".'),
    "frame_not_a_year": (
        '{slot}={given!r} is not a whole year. Give the year with four '
        'digits.'),
    # a reply that could not be read
    "shape_rule": (
        ' Output ONLY the JSON object, on ONE line, with no text before '
        'or after it, no code fence, no <think> block and no second '
        'object. Quotation marks INSIDE a quote must be escaped as \\" — '
        'if that is tedious, shorten the quote to a place without '
        'quotation marks.'),
    "cut_off": (
        'Your answer was cut off after {limit} tokens and is therefore '
        'not a complete JSON object. '),
    "shorter": (
        'Answer more briefly: quote only the short place where the field '
        'stands.'),
    "shorter_frame": (
        'Answer with fewer pairs and quote only the short place where '
        'the scenario or the year stands.'),
    "shorter_rows": (
        'Answer with fewer tuples and quote only the short place where '
        'the value stands.'),
    "shorter_field": (
        'Put rows with the same answer together in "groups" and quote '
        'only the short place where the field stands.'),
    "shorter_review": (
        'Quote only the short place where the field stands, and leave '
        'out every field the two passages do not carry.'),
    "reasoning_only": (
        'You only thought and answered nothing: your reply was empty. Do '
        'not think ahead, output the result directly.'),
    "empty": 'Your answer was empty.',
    "no_object": 'Your answer contained no JSON object at all.',
    "syntax": (
        'Your JSON breaks at character {position} ({message}), at this '
        'place: {around!r}.'),
    "outside_text": 'There was text beside the JSON object: {extra!r}.',
    "not_an_object": (
        'Your answer was a {kind} structure and not a JSON object.'),
    "key_missing": 'Your answer lacked "{key}".',
    "key_not_a_list": 'In your answer "{key}" was not a list.',
    "wrong_shape": 'Your answer did not have the form that was asked for.',
    # what the model gets back after a calculation
    "code_failed": (
        'The code did not run: {error}. Answer now without a '
        'calculation, or correct the code.'),
    "code_error_unknown": 'unknown',
    "code_silent": (
        'The code ran but printed nothing. Print every result with '
        'print(), or answer without a calculation.'),
    "code_output": (
        'Output of the code:\n{output}\n\nAnswer now with the tuple '
        'object. Calculated values carry "computed": true.'),
    # labels inside a request
    "image_for": 'Image for {label}:',
    "anchor_parameter": 'Field',
    "anchor_unit": 'Unit',
}
