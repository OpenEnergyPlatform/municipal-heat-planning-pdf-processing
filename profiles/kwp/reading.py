"""
reading.py: What the refinement, visuals and page-transcription stages say to
the model when its reply was not the one JSON object that was asked for.

The instructions of these stages are English in this profile (only what the
model reads off a German page is German), so the sentences are too. See
docpipe/reading.py for what each name is filled with.

Author: Felix Vossel
"""

PHRASES = {
    # what is said back whatever went wrong: the shape that was asked for
    "shape_rule": (
        ' Output ONLY the JSON object, with no text before or after it, no '
        'code fence, no <think> block and no second object. Quotation marks '
        'and line breaks INSIDE a string must be escaped as \\" and \\n.'),
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
    "key_not_text": 'In your answer "{key}" was not a string.',
}
