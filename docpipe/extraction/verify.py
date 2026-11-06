"""
verify.py: Checks a claimed tuple against the spec and the source text before
it is written to the harvest.

An extraction reply states a value and cites the passage that supports it.
Before anything is written, the claim is checked against what the model does
not control: the spec's closed vocabularies, and the source text the quote has
to sit in verbatim.

A claim that passes carries an evidence tier stating how well it is backed.
`TIER_TEXT` applies when the quote sits in the document's refined section text
and the passage was located in the source PDF; the value can then be shown
highlighted on its page, the strongest evidence available. `TIER_VISUAL`
applies when the quote sits in a table transcription, a caption, or a figure
description, or the model read it off the image itself; the evidence is then
the page and that image. A `TIER_VISUAL` claim cannot be confirmed
automatically, because the transcription is itself a model output, so checking
the claim against it would compare one model output to another; confirmation is
left to a person who looks at the picture. A claim backed by neither tier is
refused: it is recorded with a reason and never reaches the output.

Values are not only numbers. An ontology asks for categories and for plain
statements as often as for numbers, and each is evidenced the same way, by the
passage it stands in. Only the comparison between a value and its quote
differs: digits for a number, text for anything else.

Author: Felix Vossel
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from ..profile import ENV_VAR, active_profile
from .fields import DERIVED, READ, UNBACKED
from .spec import Parameter, fold_label

TIER_TEXT = "text_located"
TIER_VISUAL = "visual_source"

# The owner kinds whose text is the document's own prose. Everything else is
# a model's reading of a picture.
TEXT_KINDS = ("section",)

_WS = re.compile(r"\s+")
# A number as it appears in running text: digits with optional grouping and
# one decimal part, German or international. Whitespace never joins two
# numbers into one token ('2020 45.000' is two numbers); space-grouped forms
# ('45 000') are collected separately.
_NUMBER = re.compile(r"\d(?:[\d.,]*\d)?")
# DD.MM.YYYY and MM.YYYY: the year at the end of a German date.
_DATED_YEAR = re.compile(r"(?<![\d.,])(?:\d{1,2}\.){1,2}((?:19|20)\d{2})(?!\d|[.,]\d)")
_SPACE_GROUPED = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?")


# The signs of a negative number, as a PDF prints them and a model retypes them.
_MINUS = ("-", "–", "−")
# A number with its sign in front. After a letter, a digit or a separator the
# dash joins two things ("KWP-2030", "2020-2030") and is no sign.
_SIGNED = re.compile(
    rf"(?<![\w.,])[{''.join(_MINUS)}]\s?"
    rf"({_SPACE_GROUPED.pattern}|{_NUMBER.pattern})")


MARKS = (",", ".")
_marks: dict = {}


def decimal_mark() -> str:
    """How the documents of the ambient profile write the decimal: "," or
    ".". The profile says it (`extraction.py: DECIMAL_MARK`); one that does
    not is read with the comma, as every corpus was before this was asked.

    It decides only what the digits leave open. '1.036.767,8' reads the same
    under both. '3,251' is 3.251 where the comma is the decimal mark and
    3251 where the point is, and no rule about digits can tell which.
    """
    name = os.environ.get(ENV_VAR)
    if name not in _marks:
        profile = active_profile()
        mark = profile.component("extraction", "DECIMAL_MARK") \
            if profile is not None else None
        if mark is not None and mark not in MARKS:
            raise ValueError(f"extraction.DECIMAL_MARK of profile {name!r} "
                             f"is {mark!r}; it is one of {MARKS}")
        _marks[name] = mark or ","
    return _marks[name]


def canonical_number(raw, decimal: Optional[str] = None) -> Optional[str]:
    """One spelling for a number, whatever locale wrote it.

    '1.036.767,8', '1,036,767.8' and '1036767.8' all become '1036767.8'.
    Digit-exact comparison then reduces to string equality — no float
    round-tripping, which matters for 9-digit kWh values.

    *decimal* is the mark the documents write the decimal with; without it,
    the ambient profile's (`decimal_mark`).
    """
    if isinstance(raw, float):
        # Fifteen significant digits, what a double holds of any number
        # written: ten fixed places showed the binary noise of a large one,
        # 52678423.38 was 52678423.3800000027 and never in its quote.
        text = format(Decimal(format(raw, ".15g")), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(raw, int):
        return str(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if s[:1] in _MINUS:
        magnitude = canonical_number(s[1:], decimal)
        return ("-" + magnitude
                if magnitude and not magnitude.startswith("-") else None)
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    # Mixed separator kinds are unambiguous: the rightmost kind is the
    # decimal mark ('1.234,567' is 1234.567). With one kind only, several
    # separators are all grouping, and a single GROUPING mark followed by
    # exactly 3 digits is grouping: '1.234' where the comma is the decimal
    # mark, how those documents write thousands, and '1,234' where the point
    # is. A single decimal mark is the decimal mark whatever follows it:
    # with the comma '3,251 GWh' is 3.251, and read as 3251 it refused 51
    # correct values on corpus_m5.
    grouping = "." if (decimal or decimal_mark()) == "," else ","
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    decimal_pos = max(last_dot, last_comma)
    if decimal_pos != -1:
        mixed = last_dot != -1 and last_comma != -1
        tail = len(s) - decimal_pos - 1
        if not mixed and (s.count(s[decimal_pos]) > 1
                          or (tail == 3 and s[decimal_pos] == grouping)):
            decimal_pos = -1
    if decimal_pos != -1:
        integer = re.sub(r"[.,]", "", s[:decimal_pos])
        fraction = s[decimal_pos + 1:]
        if not fraction.isdigit():
            return None
        out = f"{integer}.{fraction}".rstrip("0").rstrip(".")
        return out or "0"
    return re.sub(r"[.,]", "", s)


def numbers_in(text: str, decimal: Optional[str] = None) -> set:
    """The numbers *text* prints, each in `canonical_number`'s spelling.
    *decimal* is the mark the text writes the decimal with: the documents'
    by default."""
    found = {canonical_number(m.group(0), decimal)
             for m in _NUMBER.finditer(text or "")}
    found.update(canonical_number(m.group(0), decimal)
                 for m in _SPACE_GROUPED.finditer(text or ""))
    # The year of a dotted date. "Stand 09.12.2025" is one token to _NUMBER
    # and reads as the grouped number 09122025, so the 2025 it plainly prints
    # was not in the quote: 12 years on the corpus_m5 canary were dropped so.
    found.update(m.group(1) for m in _DATED_YEAR.finditer(text or ""))
    # A printed sign is part of the number: "-1.155" holds -1155, and a table
    # of savings lost all its values while the sign stayed outside this set.
    # The magnitude stays in too: the dash of "2020 - 2030" may be no sign.
    found.update("-" + canonical_number(m.group(1), decimal)
                 for m in _SIGNED.finditer(text or ""))
    return found


# A table transcription breaks a long cell label with <br>: "holzige<br>
# Festbrennstoffe". It is a line break like the whitespace collapsed here,
# and read as text it kept "holzige Festbrennstoffe" out of its own quote:
# on Kassel six carriers stayed open and three value pairs collided.
_BR = re.compile(r"<br\s*/?>", re.I)
# Bold in a transcribed table is markup of the transcription too: on
# Rendsburg a measure sheet printed "**Bedarf Bestand**<br>122,3 GWh" and its
# quote "Bedarf Bestand 122,3 GWh" was refused twice. `flat` drops the `**`.


# Quotation marks and dashes a PDF prints and a model retypes. The model is
# shown the transcription and writes its quote from it, but the two go through
# different encoders, and a passage that says „Bestand" against a quote that
# says "Bestand" is the same sentence twice under two code points.
_SAME = str.maketrans({
    "„": '"', "“": '"', "”": '"', "‟": '"',  # „ “ ” ‟
    "«": '"', "»": '"',                                # « »
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # ‘ ’ ‚ ‛
    "–": "-", "—": "-", "−": "-",                 # – — −
    " ": " ", " ": " ", " ": " ",                 # the thin spaces
    "­": "",                                                # the soft hyphen
})


def flat(text: str) -> str:
    """One shape for both sides of every comparison in this file.

    NFKC because a ligature and a decomposed umlaut are the same letters:
    `ﬁ` is `fi` and `u` plus a combining diaeresis is `ü`, and a quote that
    came out of the PDF one way and out of the model the other was read as
    two different sentences. This is not a check, it is the form both sides
    are brought into before the one check that exists runs.
    """
    same = unicodedata.normalize("NFKC", text or "").translate(_SAME)
    return _WS.sub(" ", _BR.sub(" ", same.replace("**", ""))).strip()


def quote_in(source: str, quote: str) -> bool:
    """Whitespace-collapsed literal containment — corrections.py semantics."""
    if not quote or not source:
        return False
    return flat(quote) in flat(source)


@dataclass
class Verified:
    tuple: dict
    tier: str
    flags: list = field(default_factory=list)   # non-fatal findings
    rects: Optional[list] = None                # highlight boxes, tier TEXT


@dataclass
class Refusal:
    raw: dict
    reason: str


def _check_value(raw: dict, parameter: Parameter, flags: list, *,
                 with_unit: bool = True):
    """The value itself: type, unit, vocabulary. Returns (resolved, refusal).
    Without *with_unit* not the unit, which a reading asks after the value."""
    value = raw.get("value")
    out: dict = {}

    if parameter.is_numeric:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None, Refusal(raw, "value is not a number")
        if not with_unit:
            return out, None
        # units_accepted is a closed list, so the unit is a choice: one entry,
        # read by the unit question with its own passage, and the document's
        # own spelling beside it. The spelling is evidence and is never
        # looked up -- a spelling table stood here once and let 3,324 tuples
        # of corpus_m5 carry an entry their wording contradicts.
        chosen = raw.get("unit")
        wording = raw.get("unit_raw")
        wording = (wording.strip() if isinstance(wording, str)
                   and wording.strip() else None)
        unit = chosen if isinstance(chosen, str) and chosen.strip() else None
        factor = parameter.unit_factor(unit)
        if factor is None:
            # No entry, or one this parameter does not list. The reason names
            # the wording the document wrote, because that is what a reader
            # of the refusals is after: which units the plans use that no
            # list holds.
            named = wording or raw.get("unit_seen") or unit
            return None, Refusal(raw, f"unit {named!r} not in units_accepted "
                                      f"({', '.join(parameter.units_accepted)})")
        if wording and wording != unit:
            out["unit_raw"] = wording
        out["unit"] = unit
        out["value_target"] = round(float(value) * float(factor), 6)
        return out, None

    wording = raw.get("value_raw")
    wording = wording.strip() if isinstance(wording, str) else ""
    if not isinstance(value, str) or not value.strip():
        # A category whose class list held nothing fitting. The model was told
        # to leave the class out rather than force one, so the wording alone is
        # the finding — the same rule an unmapped axis already follows, and the
        # only way the mapping gap is ever measurable.
        if parameter.value_type == "category" and wording:
            flags.append(f"unmapped:value:{wording}")
            return {"value": wording, "value_raw": wording, "value_uri": None}, None
        return None, Refusal(raw, f"a {parameter.value_type} parameter needs a "
                                  f"non-empty string value")
    if parameter.value_type == "category":
        uri = parameter.value_to_uri().get(fold_label(value.strip()))
        if uri is None:
            # An answer to a closed list that is none of its entries, never
            # read (owner, 2026-09-11). It was kept with a flag, and 2,234
            # tuples of one corpus run said "read" with no class at all. The
            # claim stays on the refusal, wording included; the no-class
            # answer above is how a value says the list lacks it.
            return None, Refusal(raw, f"value {value.strip()!r} not in "
                                      f"vocabulary")
        out["value_uri"] = uri
        if wording:
            out["value_raw"] = wording
            if fold_label(wording) not in parameter.value_to_uri():
                flags.append(f"mapped:value:{wording}->{uri}")
    return out, None


def computed_in_output(raw: dict, parameter: Parameter) -> bool:
    """Did the sandbox actually print this number?

    A computed value cannot stand in its quote — the document prints the
    inputs, not the result. What replaces the quote as the check on the value
    is the sandbox's own output: the number has to be in what the code printed.
    That is machine-checked, unlike a number the model works out in its head,
    which is exactly why the arithmetic goes to the sandbox at all. The quote
    is still required and still checked: it proves the inputs are in the
    document.
    """
    wanted = canonical_number(raw.get("value"))
    if wanted is None:
        return False
    # The output is read as Python prints, the point the decimal mark and no
    # grouping, whatever the plan writes: read as the plan, the "0.974" that
    # round(x, 3) printed was 974, and on one plan 17 of 26 shares were lost.
    for run in raw.get("compute") or ():
        if isinstance(run, dict) and wanted in numbers_in(
                run.get("stdout") or "", decimal="."):
            return True
    return False


def printed_rounding(value: float) -> float:
    """Half a unit of the last digit a number is written with: 116.1 stands
    for anything from 116.05 to 116.15, and 38892.0 for 38891.5 to 38892.5."""
    mantissa, _, exponent = repr(float(value)).lower().partition("e")
    decimals = len(mantissa.partition(".")[2].rstrip("0"))
    return 0.5 * 10.0 ** (int(exponent or 0) - decimals)


def computed_from_inputs(raw: dict) -> bool:
    """Is the number what the numbers it was worked out from make?

    The output proves the code printed the number, not that the code worked
    with the numbers the answer names: one summed a column of its table and
    printed 1,948 t/a beside inputs of 20,345 and 1,399. What the inputs make
    stands on the last run (`expected`, from the question: a share times its
    whole, the sum of the parts), and the number has to be it, to the rounding
    it is written with (owner decision 2026-11-03). A number the rows request
    worked out names no inputs and is held to its output alone.
    """
    runs = raw.get("compute") or ()
    last = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    if "inputs" not in last:
        return True
    value, expected = raw.get("value"), last.get("expected")
    if not all(isinstance(number, (int, float)) and not isinstance(number, bool)
               for number in (value, expected)):
        return False
    # Float noise: the code may add the parts in another order than the check.
    noise = 1e-9 * max(abs(value), abs(expected))
    return abs(value - expected) <= printed_rounding(value) + noise


def wording_of(raw: dict, parameter: Parameter):
    """The words a value's quote has to hold.

    For a category the tuple carries two things: the class the model mapped
    to and, in *_raw, how the document worded it. The evidence check is
    about the document, so it runs against the wording, never against the
    class name the mapping produced. Any other value is its own wording: a
    value_raw beside it vouches for nothing but itself (owner decision
    2026-11-04).
    """
    if parameter.value_type == "category":
        return raw.get("value_raw") or raw.get("value")
    return raw.get("value")


def value_in_quote(raw: dict, parameter: Parameter, quote: str) -> bool:
    """Is the claimed value actually in the passage it cites?"""
    if parameter.is_numeric:
        return canonical_number(raw.get("value")) in numbers_in(quote)
    wording = wording_of(raw, parameter)
    return flat(str(wording)).casefold() in flat(quote).casefold()


def number_outside_quote(claim: dict) -> bool:
    """A number the quote it stands under does not print. What
    `value_in_quote` refuses, asked before the parameter of a row is known."""
    value, quote = claim.get("value"), claim.get("quote")
    if (isinstance(value, bool) or not isinstance(quote, str)
            or claim.get("computed") is True):
        return False
    wanted = canonical_number(value)
    return wanted is not None and wanted not in numbers_in(quote)


# A passage shorter than this identifies nothing. "2030" sits in every plan
# a hundred times over, so it proves that the model can read a number and
# nothing about where it read THIS one. The value quote has been held to it
# since the first corpus run; the coordinate quotes were not, although
# field.md rule 3 promises the same, and three of Kassel's year readings were
# the bare year.
MIN_QUOTE_CHARS = 8

# Why the fold refuses a value's quote, said once for `verify_tuple` and for
# `value_refused`, which asks the same while the model can still answer.
QUOTE_TOO_SHORT = "quote missing or too short to identify anything"
QUOTE_NOT_FOUND = "quote not found in the source it cites"


def not_in_quote(raw: dict) -> str:
    """Why the fold refuses a value its quote does not hold."""
    return f"value {raw.get('value')!r} does not occur in the quote"


def verify_tuple(raw: dict, parameter: Parameter, source_text: str, *,
                 owner_kind: str = "section",
                 locate: Optional[Callable[[str], Optional[list]]] = None):
    """One claimed tuple against everything the model does not control.

    Returns Verified or Refusal. *owner_kind* decides the tier: prose gets
    TIER_TEXT, a table or figure gets TIER_VISUAL. *locate* is a lazy lookup
    that maps the quote to highlight rectangles in the source PDF — lazy
    because opening the PDF is the expensive step and a claim refused earlier
    never needs it.

    A quote that does not stand in *source_text* is refused, and nothing
    rebuilds it from the source (owner decision 2026-11-05).
    """
    if not isinstance(raw, dict):
        return Refusal(raw={}, reason="tuple is not an object")

    flags: list = []
    value_fields, refusal = _check_value(raw, parameter, flags)
    if refusal is not None:
        return refusal

    resolved: dict = {}
    for name, axis in parameter.axes.items():
        given = raw.get(name)
        if axis.vocabulary is not None:
            wording = raw.get(f"{name}_raw")
            wording = wording.strip() if isinstance(wording, str) else None
            if given is None:
                if axis.required:
                    return Refusal(raw, f"required axis {name!r} missing")
                resolved[name] = None
                if wording:
                    # The model read a label here and found no class it fits.
                    # That is the single most useful line for vocabulary
                    # review, so it survives with its wording instead of
                    # collapsing into an indistinguishable null.
                    resolved[f"{name}_raw"] = wording
                    flags.append(f"unmapped:{name}:{wording}")
                continue
            if given in axis.vocabulary:           # already a URI
                uri = given
            else:
                uri = axis.label_to_uri().get(fold_label(given))
            if uri is None:
                # The model chooses the class from the list it was given, so
                # a value outside that list means it found nothing fitting
                # (or answered off-contract). Either way the harvest keeps
                # the finding: the wording stays on the tuple and the flag
                # feeds the vocabulary review, because refusing here would
                # silently shrink the yield on every unforeseen wording.
                if axis.required:
                    return Refusal(raw, f"axis {name!r}: {given!r} not in "
                                        f"vocabulary and axis is required")
                resolved[name] = None
                resolved[f"{name}_raw"] = wording or given
                flags.append(f"unmapped:{name}:{given}")
            else:
                resolved[name] = uri
                if wording:
                    # How the document said it, next to the class it was
                    # mapped to. A wording the spec does not list means the
                    # model made a judgement call, and those are flagged so
                    # a review sees every mapping the table did not decide.
                    resolved[f"{name}_raw"] = wording
                    if fold_label(wording) not in axis.label_to_uri():
                        flags.append(f"mapped:{name}:{wording}->{uri}")
        elif axis.type == "text" or axis.dynamic:
            # No list to check against, so nothing to refuse: the coordinate
            # is a wording. A dynamic axis lands here when the profile had no
            # list for this document — then the wording is all there is, and
            # dropping it would be worse than carrying it unresolved.
            if given is None:
                if axis.required:
                    return Refusal(raw, f"required axis {name!r} missing")
                resolved[name] = None
            else:
                text = str(given).strip()
                if not text:
                    if axis.required:
                        return Refusal(raw, f"required axis {name!r} is empty")
                    resolved[name] = None
                else:
                    resolved[name] = text
        elif axis.type == "int":
            if given is None:
                if axis.required:
                    return Refusal(raw, f"required axis {name!r} missing")
                resolved[name] = None
            else:
                try:
                    # int() truncates: int(2045.7) is 2045, and a year the
                    # model got wrong by seven tenths was written into the
                    # graph as a year it never read. An integer axis takes
                    # integers, and everything else is asked again.
                    if isinstance(given, bool):
                        raise ValueError(given)
                    if isinstance(given, float):
                        if not given.is_integer():
                            raise ValueError(given)
                        resolved[name] = int(given)
                    else:
                        resolved[name] = int(str(given).strip())
                except (TypeError, ValueError):
                    return Refusal(raw, f"axis {name!r}: {given!r} is not an integer")
        else:                                       # enum
            if given is None:
                resolved[name] = None
            elif given in (axis.enum or ()):
                resolved[name] = given
            else:
                return Refusal(raw, f"axis {name!r}: {given!r} not in enum "
                                    f"{list(axis.enum or ())}")

    quote = raw.get("quote")
    if not isinstance(quote, str) or len(quote) < MIN_QUOTE_CHARS:
        return Refusal(raw, QUOTE_TOO_SHORT)
    if not quote_in(source_text, quote):
        return Refusal(raw, QUOTE_NOT_FOUND)
    if not value_in_quote(raw, parameter, quote):
        # `is True`, not truthy: "computed" is a switch that decides WHICH
        # evidence check applies, and the string "nein" would have opened the
        # door it exists to keep shut.
        if raw.get("computed") is True and computed_in_output(raw, parameter):
            # The document prints the inputs and the sandbox printed the
            # result. Both halves of the evidence are on the tuple.
            if not computed_from_inputs(raw):
                return Refusal(raw, f"value {raw.get('value')!r} does not "
                                    f"follow from its inputs")
            flags.append("computed")
        else:
            return Refusal(raw, not_in_quote(raw))

    if (parameter.is_numeric and parameter.integrated
            and not parameter.names_period(value_fields.get("unit"))):
        # The entry the unit question chose says in the spec that it names no
        # period. The period is part of that reading, because a passage
        # saying "over the year" makes the model choose kWh/a, so a plain
        # entry says the passage stated none. An integral needs the period it
        # runs over, and a graph that writes a year beside a storage capacity
        # has invented it.
        #
        # Only for a parameter whose unit IS an amount over a span. A power
        # has no period to state, so this would fire on every row of it and
        # separate nothing -- and it is read off every flag distribution the
        # reports are built from.
        flags.append("period:unstated")

    rects = None
    if owner_kind in TEXT_KINDS:
        tier = TIER_TEXT
        if locate is not None:
            rects = locate(quote)
            if not rects:
                # The passage is in the document's own text but could not be
                # placed on the page — the reader gets the page, not the
                # highlight. Worth counting, not worth dropping a finding for.
                flags.append("not_located")
    else:
        tier = TIER_VISUAL

    out = dict(raw)
    out.update(resolved)
    # A coordinate whose answer did not survive resolution must not keep the
    # stamp that says it was read. It did: an empty axis came back as None
    # while `<name>_state` still said "read", which is a row that claims a
    # reading and shows no value -- 171 of them in corpus_m5. The evidence
    # goes with it, because evidence for nothing is what made it look sound.
    for name, settled in resolved.items():
        if settled is not None or out.get(f"{name}_state") not in (READ,
                                                                  DERIVED):
            continue
        out[f"{name}_state"] = UNBACKED
        for suffix in ("_quote", "_source", "_window", "_link_quote",
                       "_link_source", "_means"):
            out.pop(f"{name}{suffix}", None)
        flags.append(f"unbacked:{name}")
    out.update(value_fields)
    out["parameter"] = parameter.uri
    return Verified(tuple=out, tier=tier, flags=flags, rects=rects)


def value_refused(raw: dict, parameter: Parameter,
                  source_text: str) -> Optional[str]:
    """Why the fold would refuse a value read before its coordinates, or
    None: what `verify_tuple` checks of the value itself (its type, its
    entry of a closed list) and of its quote (long enough, standing in
    *source_text*, holding the value), in its words. Not the unit and not
    the axes, which a reading asks after the value and checks as it reads
    them (`pipeline.merge_field`). A reading asks it of each value while
    the model can still answer (`reading.round_failure`), and the walk down
    a search's list of what it read (`surveyed.sought_walk`), so both hold a
    value to the check the fold applies (owner decisions 2026-11-05)."""
    if not isinstance(raw, dict):
        return "tuple is not an object"
    _resolved, refusal = _check_value(raw, parameter, [], with_unit=False)
    if refusal is not None:
        return refusal.reason
    quote = raw.get("quote")
    if not isinstance(quote, str) or len(quote) < MIN_QUOTE_CHARS:
        return QUOTE_TOO_SHORT
    if not quote_in(source_text or "", quote):
        return QUOTE_NOT_FOUND
    if not value_in_quote(raw, parameter, quote):
        return not_in_quote(raw)
    return None
