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

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .spec import Parameter, fold_label, states_a_year

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
_SPACE_GROUPED = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?")


def canonical_number(raw) -> Optional[str]:
    """One spelling for a number, whatever locale wrote it.

    '1.036.767,8', '1,036,767.8' and '1036767.8' all become '1036767.8'.
    Digit-exact comparison then reduces to string equality — no float
    round-tripping, which matters for 9-digit kWh values.
    """
    if isinstance(raw, (int, float)):
        raw = f"{raw:.10f}".rstrip("0").rstrip(".") if isinstance(raw, float) else str(raw)
        return raw
    if not isinstance(raw, str):
        return None
    s = raw.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if not s or not re.fullmatch(r"[\d.,]+", s):
        return None
    # Mixed separator kinds are unambiguous: the rightmost kind is the
    # decimal mark ('1.234,567' is 1234.567). With one kind only, several
    # separators are all grouping, and a single one followed by exactly
    # 3 digits ('1.234') is grouping — how these documents write thousands.
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    decimal_pos = max(last_dot, last_comma)
    if decimal_pos != -1:
        mixed = last_dot != -1 and last_comma != -1
        tail = len(s) - decimal_pos - 1
        if not mixed and (s.count(s[decimal_pos]) > 1 or tail == 3):
            decimal_pos = -1
    if decimal_pos != -1:
        integer = re.sub(r"[.,]", "", s[:decimal_pos])
        fraction = s[decimal_pos + 1:]
        if not fraction.isdigit():
            return None
        out = f"{integer}.{fraction}".rstrip("0").rstrip(".")
        return out or "0"
    return re.sub(r"[.,]", "", s)


def numbers_in(text: str) -> set:
    found = {canonical_number(m.group(0)) for m in _NUMBER.finditer(text or "")}
    found.update(canonical_number(m.group(0))
                 for m in _SPACE_GROUPED.finditer(text or ""))
    return found


def flat(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


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


def _check_value(raw: dict, parameter: Parameter, flags: list):
    """The value itself: type, unit, vocabulary. Returns (resolved, refusal)."""
    value = raw.get("value")
    out: dict = {}

    if parameter.is_numeric:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None, Refusal(raw, "value is not a number")
        # units_accepted is a closed list, so the unit is a choice: the model
        # picks one and writes the document's own spelling beside it. The
        # spelling is evidence, never the thing looked up — mapping free text
        # onto a factor was a table of German spellings that never converged.
        chosen = raw.get("unit")
        wording = raw.get("unit_raw")
        unit = chosen if isinstance(chosen, str) and chosen.strip() else None
        if unit is None:
            # No choice made. The spelling is all there is, so it is looked up
            # and the tuple carries a flag saying the unit was not chosen.
            unit = wording
            if parameter.unit_factor(unit) is not None:
                flags.append(f"unit_not_chosen:{wording}")
        factor = parameter.unit_factor(unit)
        if factor is None:
            return None, Refusal(raw, f"unit {unit!r} not in units_accepted "
                                      f"({', '.join(parameter.units_accepted)})")
        if unit not in parameter.units_accepted:
            # A choice retyped slightly, or a spelling the list does not hold.
            # Worth a flag, not a refusal: a spelling that keeps turning up
            # belongs in the list, and the flag is how it gets noticed.
            flags.append(f"unit_spelling:{unit}")
        if isinstance(wording, str) and wording.strip() and wording != unit:
            out["unit_raw"] = wording.strip()
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
            # The model was handed the closed class list and still found
            # nothing that fits. That is a mapping gap to review, not a
            # reason to drop the finding: the wording stays on the tuple.
            flags.append(f"unmapped:value:{value.strip()}")
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
    for run in raw.get("compute") or ():
        if isinstance(run, dict) and wanted in numbers_in(run.get("stdout") or ""):
            return True
    return False


def value_in_quote(raw: dict, parameter: Parameter, quote: str) -> bool:
    """Is the claimed value actually in the passage it cites?"""
    if parameter.is_numeric:
        return canonical_number(raw.get("value")) in numbers_in(quote)
    # For a category the tuple carries two things: the class the model mapped
    # to and, in *_raw, how the document worded it. The evidence check is
    # about the document, so it runs against the wording, never against the
    # class name the mapping produced.
    wording = raw.get("value_raw") or raw.get("value")
    return flat(str(wording)).casefold() in flat(quote).casefold()


# A full stop, not a list separator. Figure descriptions separate items with
# semicolons and colons ("EWS: 41; EWK: 20"), and cutting the passage there
# leaves a fragment that proves nothing.
_TERMINATOR = re.compile(r"[.!?\n]")
# Below this a passage is not evidence. A table cell and a figure description
# are each one long sentence, so falling back to the plain window is right.
_MIN_PASSAGE = 40


def _occurrences(raw: dict, parameter: Parameter, source: str) -> list:
    """Every place in the source this value could be read, as (start, end)."""
    if parameter.is_numeric:
        wanted = canonical_number(raw.get("value"))
        if wanted is None:
            return []
        spans = [m.span() for m in _NUMBER.finditer(source)
                 if canonical_number(m.group(0)) == wanted]
        spans += [m.span() for m in _SPACE_GROUPED.finditer(source)
                  if canonical_number(m.group(0)) == wanted]
        return sorted(set(spans))
    wording = raw.get("value_raw") or raw.get("value")
    if not isinstance(wording, str) or len(wording.strip()) < 2:
        return []
    needle, hay = wording.strip().casefold(), source.casefold()
    spans, at = [], hay.find(needle)
    while at != -1:
        spans.append((at, at + len(needle)))
        at = hay.find(needle, at + 1)
    return spans


def _sentence_around(source: str, start: int, end: int, span: int = 320) -> str:
    """The passage the value stands in, cut at sentence ends where there are any.

    A cut that leaves less than _MIN_PASSAGE characters is no evidence, so the
    window is kept instead: a table cell is a whole "sentence" and a figure
    description is one long one.
    """
    lo, hi = max(0, start - span), min(len(source), end + span)
    cut_lo, cut_hi = lo, hi
    before = list(_TERMINATOR.finditer(source, lo, start))
    if before:
        cut_lo = before[-1].end()
    after = _TERMINATOR.search(source, end, hi)
    if after:
        cut_hi = after.end()
    passage = source[cut_lo:cut_hi].strip()
    return passage if len(passage) >= _MIN_PASSAGE else source[lo:hi].strip()


# A passage shorter than this identifies nothing. "2030" sits in every plan
# a hundred times over, so it proves that the model can read a number and
# nothing about where it read THIS one. The value quote has been held to it
# since the first corpus run; the coordinate quotes were not, although
# field.md rule 3 promises the same, and three of Kassel's year readings were
# the bare year.
MIN_QUOTE_CHARS = 8


def _repair_quote(raw: dict, parameter: Parameter, source: str) -> Optional[str]:
    """The passage the source itself gives for this value, or None.

    A model that abridges its quote — "...zeigen sukzessive sinkende Werte:
    79.499.951 kWh (2035)" for a sentence that also lists 2030 and 2040 — has
    stated something true and cited it wrongly. Refusing that loses the
    finding; taking the model's wording on trust loses the guarantee that the
    evidence is literally in the document. So the quote is rebuilt from the
    source, and only where the source leaves no choice: the value has to occur
    in it exactly once. Measured on the 16-document pilot, that is 303 of 377
    such refusals, against 8 where the value was not in the source at all.
    """
    spans = _occurrences(raw, parameter, source)
    if len(spans) != 1:
        return None
    passage = _sentence_around(source, *spans[0])
    return passage if len(passage) >= MIN_QUOTE_CHARS else None


def verify_tuple(raw: dict, parameter: Parameter, source_text: str, *,
                 owner_kind: str = "section",
                 locate: Optional[Callable[[str], Optional[list]]] = None,
                 repair_text: Optional[str] = None):
    """One claimed tuple against everything the model does not control.

    Returns Verified or Refusal. *owner_kind* decides the tier: prose gets
    TIER_TEXT, a table or figure gets TIER_VISUAL. *locate* is a lazy lookup
    that maps the quote to highlight rectangles in the source PDF — lazy
    because opening the PDF is the expensive step and a claim refused earlier
    never needs it.

    *repair_text* is what a missing quote is rebuilt from, when the heading
    prefixed into *source_text* is not part of it. The repair rests on the
    value occurring exactly once, and 1.9% of this corpus's table numbers
    also stand in their own caption.
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
                    resolved[name] = int(given)
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
        return Refusal(raw, "quote missing or too short to identify anything")
    if not quote_in(source_text, quote):
        repaired = _repair_quote(
            raw, parameter,
            repair_text if repair_text is not None else source_text)
        if repaired is None:
            return Refusal(raw, "quote not found in the source it cites")
        raw = dict(raw, quote=repaired)
        quote = repaired
        flags.append("quote_repaired")
    if not value_in_quote(raw, parameter, quote):
        if raw.get("computed") and computed_in_output(raw, parameter):
            # The document prints the inputs and the sandbox printed the
            # result. Both halves of the evidence are on the tuple.
            flags.append("computed")
        else:
            return Refusal(raw, f"value {raw.get('value')!r} does not occur "
                                f"in the quote")

    if (parameter.is_numeric and parameter.integrated
            and not states_a_year(raw.get("unit_raw")
                                  or raw.get("unit") or "")):
        # The unit is a plain amount, so what makes it a yearly one is the
        # passage or nothing. An integral needs the period it runs over, and
        # a graph that writes a year beside a storage capacity has invented
        # that period rather than read it.
        #
        # Only for a parameter whose unit IS an amount over a span. A power
        # has no period to state, so this would fire on every row of it and
        # separate nothing -- and it is read off every flag distribution the
        # reports are built from.
        flags.append("period:annual_in_quote" if states_a_year(quote)
                     else "period:unstated")

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
    out.update(value_fields)
    out["parameter"] = parameter.uri
    return Verified(tuple=out, tier=tier, flags=flags, rects=rects)
