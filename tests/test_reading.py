"""The one JSON object a stage asked a model for, or why there is none.

Promised: a reply is read as exactly one JSON object with nothing stripped, cut
out, closed or salvaged (`test_only_the_one_object_is_read`) AND every reply
that is not that object is classified by the harvest's own causes
(`test_a_reply_is_classified_like_the_harvests`) AND the sentence for the retry
names the cause in the profile's words (`test_the_retry_names_the_cause`) AND a
unit that ends without a result carries one of a closed set of causes
(`test_a_hole_names_only_known_causes`).
"""
from types import SimpleNamespace as NS

import pytest

from docpipe import reading
from docpipe.extraction import runner


def _choice(content, finish="stop", reasoning=None):
    return NS(finish_reason=finish, message=NS(
        content=content, reasoning_content=reasoning))


# ---------------------------------------------------------------------------
# AND 1: exactly one object, nothing repaired
# ---------------------------------------------------------------------------

# The harvest's own cases (test_only_the_one_object_that_was_asked_for_is_read).
# Every one of the None cases was unwrapped, closed or cut out of its
# surroundings by the code these stages used to carry (a think strip, a fence
# strip, an outermost-braces search, a closing of the brackets), and gave a dict.
ONE_OBJECT = [
    ('{"a": 1}', {"a": 1}),
    ('  {"a": 1}\n', {"a": 1}),
    ('```json\n{"a": 1}\n```', None),
    ('<think>so</think>{"a": 1}', None),
    ('{"a": 1}{"b": 2}', None),
    ('{"a": 1}\nDas war die Antwort (siehe oben) {Ende}', None),
    ('Hier ist das Ergebnis: {"a": 1} fertig.', None),
    ('{"a": 1', None),
    ('{"a": "cut in the middle of a str', None),
    ("[1, 2]", None),
    ("gar kein json", None),
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("raw,expect", ONE_OBJECT)
def test_only_the_one_object_is_read(raw, expect):
    assert reading.loads_object(raw) == expect
    got, cause, _said = reading.read(_choice(raw))
    assert got == expect
    assert bool(cause) == (expect is None)


def test_it_reads_what_the_harvest_reads():
    """The two readers take the same object and refuse the same replies, so a
    stage and the harvest cannot disagree on what a reply is."""
    for raw, _expect in ONE_OBJECT:
        assert reading.loads_object(raw) == runner._loads_object(raw), raw


def test_a_reply_is_not_made_right_by_what_surrounds_it():
    """The case built to break it: an object wrapped in every way the old code
    took apart. A reader that strips or cuts out would return the dict."""
    wrapped = ['```\n{"sections": []}\n```', 'ok {"sections": []}',
               '{"sections": []} ok', '<think>x</think>\n{"sections": []}',
               '{"sections": []', '{"sections": [{"a": 1},']
    for raw in wrapped:
        got, cause, _said = reading.read(_choice(raw), key="sections")
        assert got is None and cause, raw


# ---------------------------------------------------------------------------
# AND 2: classified as the harvest classifies
# ---------------------------------------------------------------------------

CASES = {
    "cut_off": (_choice('{"tuples": [', "length"), {}),
    "cut_off_empty": (_choice("", "length"), {}),
    "reasoning_only": (_choice("", "stop", "ich denke"), {}),
    "reasoning_only_cut": (_choice("", "length", "ich denke"), {}),
    "empty": (_choice(""), {}),
    "blank": (_choice("  \n"), {}),
    "no_object": (_choice("keine Ahnung"), {}),
    "syntax": (_choice('{"tuples": [1, 2,, 3]}'), {}),
    "outside_text": (_choice('Hier: {"tuples": []} fertig'), {}),
    "fenced": (_choice('```json\n{"tuples": []}\n```'), {}),
    "two_objects": (_choice('{"tuples": []}{"tuples": []}'), {}),
    "not_an_object": (_choice("[1, 2]"), {}),
    "missing_key": (_choice('{"other": 1}'), {"key": "tuples"}),
    "key_not_a_list": (_choice('{"tuples": 3}'), {"key": "tuples"}),
    "a_cut_that_parses_keeps_its_shape_fault": (
        _choice('{"other": 1}', "length"), {"key": "tuples"}),
}


def _disagreements():
    """(case, reading's cause, the harvest's cause) wherever they differ."""
    found = []
    for name, (given, options) in CASES.items():
        _got, cause, _said = reading.read(given, **options)
        harvest, _correction = runner._reply_fault(given, 512, **options)
        if cause != harvest:
            found.append((name, cause, harvest))
    return found


def test_a_reply_is_classified_like_the_harvests():
    assert _disagreements() == []
    causes = {reading.read(given, **options)[1]
              for given, options in CASES.values()}
    # every cause the harvest can give for a reply that was not read
    assert causes == set(reading.CAUSES) - {"wrong_shape"}


def test_the_guard_against_drift_sees_a_cause_that_changed(monkeypatch):
    """A harvest that named one cause differently is found: the table above
    is no decoration."""
    real = runner._reply_fault

    def drifted(reply, limit, **options):
        cause, correction = real(reply, limit, **options)
        return ("syntax" if cause == "outside_text" else cause), correction

    monkeypatch.setattr(runner, "_reply_fault", drifted)
    # the three replies that carry an object and text beside it
    assert [name for name, *_ in _disagreements()] == [
        "outside_text", "fenced", "two_objects"]


def test_a_response_without_a_choice_is_an_empty_reply():
    response = NS(choices=[])
    assert reading.first(response) is None
    assert reading.first(NS(choices=[_choice("x")])).message.content == "x"
    assert reading.first(NS()) is None
    got, cause, said = reading.read(reading.first(response))
    assert (got, cause) == (None, "empty") and said


def test_the_key_has_to_be_of_the_type_asked_for():
    ok = _choice('{"markdown": "| a |"}')
    assert reading.read(ok, key="markdown", of=str)[0] == {"markdown": "| a |"}
    # absent, a list where text was asked for, nothing where text was asked for
    for raw in ('{"description": "x"}', '{"markdown": ["a"]}',
                '{"markdown": null}', '{"markdown": 3}'):
        got, cause, _said = reading.read(_choice(raw), key="markdown", of=str)
        assert (got, cause) == (None, "missing_key"), raw
    # an empty string is text: an answer, and the stage decides what it is worth
    assert reading.read(_choice('{"markdown": ""}'), key="markdown",
                        of=str)[0] == {"markdown": ""}
    # a list was asked for, text is none
    assert reading.read(_choice('{"sections": "x"}'), key="sections")[1] \
        == "missing_key"


def test_a_key_of_any_kind_still_has_to_be_there():
    """`of=object` asks for the key and not for its kind: an object with other
    keys only is no reply, whatever `.get` makes of the key that is not there
    (None, which is an instance of object)."""
    for raw in ('{"answer": "a"}', '{"answer": 3}', '{"answer": null}',
                '{"answer": []}'):
        got, cause, _said = reading.read(_choice(raw), key="answer",
                                         of=object)
        assert cause == "" and got is not None, raw
    for raw in ("{}", '{"other": 1}', '{"Answer": "a"}'):
        got, cause, said = reading.read(_choice(raw), key="answer", of=object)
        assert (got, cause) == (None, "missing_key"), raw
        assert 'lacked "answer"' in said, raw


def test_a_cut_reply_has_no_sentence_for_the_retry():
    """It is never asked again as it stands, so nothing is told to the model."""
    for given in (_choice('{"sections": [', "length"), _choice("", "length")):
        got, cause, said = reading.read(given, key="sections")
        assert (got, cause, said) == (None, "cut_off", "")


# ---------------------------------------------------------------------------
# AND 3: the sentence is the profile's, and names the cause
# ---------------------------------------------------------------------------

def test_the_retry_names_the_cause():
    said = {name: reading.read(given, key="tuples")[2]
            for name, (given, _options) in CASES.items()
            if reading.read(given, key="tuples")[1] not in ("cut_off",)}
    assert "text beside the JSON object" in said["outside_text"]
    assert "'Hier:  fertig'" in said["outside_text"]
    assert "breaks at character 17" in said["syntax"]
    assert "no JSON object" in said["no_object"]
    assert "list structure" in said["not_an_object"]
    assert 'lacked "tuples"' in said["missing_key"]
    assert '"tuples" was not a list' in said["key_not_a_list"]
    assert "only thought" in said["reasoning_only"]
    assert "was empty" in said["empty"]
    # every one carries the shape that was asked for
    rule = reading.say("shape_rule")
    assert rule.strip().startswith("Output ONLY the JSON object")
    assert all(text.endswith(rule) for text in said.values())
    # and the sentence of a string key says text, not list
    assert 'was not a string' in reading.read(
        _choice('{"markdown": 1}'), key="markdown", of=str)[2]


# ---------------------------------------------------------------------------
# AND 4: a hole has a cause from a closed set
# ---------------------------------------------------------------------------

# Written openly: a new cause has to be added here, or the test fails. The
# documentation lists the same set.
LISTED = {"cut_off", "reasoning_only", "empty", "no_object", "syntax",
          "outside_text", "not_an_object", "missing_key", "wrong_shape",
          "refused", "not_served", "error"}


def test_a_hole_names_only_known_causes():
    assert set(reading.HOLE_CAUSES) == LISTED
    assert len(reading.HOLE_CAUSES) == len(LISTED), "no cause twice"
    for cause in LISTED:
        assert reading.Hole(cause).cause == cause
    for typo in ("cutoff", "no usable reply", "", "Cut_off"):
        with pytest.raises(ValueError, match="no cause of a hole"):
            reading.Hole(typo)


def test_a_hole_is_a_value_that_cannot_be_changed():
    hole = reading.Hole("refused", "HTTP 400")
    assert hole == reading.Hole("refused", "HTTP 400")
    with pytest.raises(Exception):
        hole.cause = "error"


# ---------------------------------------------------------------------------
# A caller that has a profile where none is in force
# ---------------------------------------------------------------------------

def _speaker(name):
    """A stand-in for a profile whose every sentence is its own."""
    table = {key: f"{name}-{key}" for key in reading.REQUIRED}
    return NS(name=name, require=lambda module, attr: table,
              layers=lambda module, attr: [table])


def test_a_caller_with_a_profile_of_its_own_speaks_through_it(monkeypatch):
    """The chat answers on the built-in profile where none is named; the
    stages that write a corpus still stop. The block is the difference, and
    it is not a leak: outside it the reader is as it was."""
    monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    monkeypatch.setattr(reading, "_checked", {})
    broken = _choice("keine Ahnung")
    with pytest.raises(LookupError, match="needs a profile"):
        reading.read(broken)
    with reading.speaking(_speaker("chat")):
        got, cause, said = reading.read(broken)
        assert (got, cause) == (None, "no_object")
        assert said == "chat-no_object" + "chat-shape_rule"
        with reading.speaking(_speaker("inner")):         # the nearest wins
            assert reading.read(broken)[2].startswith("inner-")
        assert reading.read(broken)[2].startswith("chat-")
    with pytest.raises(LookupError, match="needs a profile"):
        reading.read(broken)


def test_a_profile_in_force_speaks_unless_a_block_names_another(monkeypatch):
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    monkeypatch.setattr(reading, "_checked", {})
    broken = _choice("keine Ahnung")
    assert reading.read(broken)[2].startswith("Your answer contained no JSON")
    with reading.speaking(_speaker("other")):
        assert reading.read(broken)[2].startswith("other-")
    assert reading.read(broken)[2].startswith("Your answer contained no JSON")
