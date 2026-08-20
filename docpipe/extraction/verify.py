"""
verify.py – No claim enters the output on the model's word.

The extraction reply states something and cites the passage it read it in.
Before anything is written, the claim is checked against what the model does
not control: the spec's closed vocabularies, and the source text the quote
must literally sit in. What survives carries an evidence tier saying how the
claim is backed:

  TIER_TEXT   The quote sits in the document's refined section text, and the
              passage was located in the source PDF, so the value can be
              shown highlighted on its page. The strongest evidence there is.
  TIER_VISUAL The quote sits in a table transcription, a caption, or a figure
              description, or the model read it off the image itself. The
              evidence is the page and that image. It cannot be confirmed
              automatically: the transcription is a model output too, so
              checking a claim against it would be model against model. A
              human confirms it by looking at the picture.
  (refusal)   The claim is backed by neither. It is recorded with a reason
              and never reaches the output.

Values are not only numbers. An ontology asks for categories and for plain
statements just as often, and those are evidenced the same way — by the
passage they stand in. What differs is only how a value is compared to its
quote: digits for a number, text for everything else.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .spec import Parameter

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


def _numbers_in(text: str) -> set:
    found = {canonical_number(m.group(0)) for m in _NUMBER.finditer(text or "")}
    found.update(canonical_number(m.group(0))
                 for m in _SPACE_GROUPED.finditer(text or ""))
    return found


def _flat(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def quote_in(source: str, quote: str) -> bool:
    """Whitespace-collapsed literal containment — corrections.py semantics."""
    if not quote or not source:
        return False
    return _flat(quote) in _flat(source)


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
        unit = raw.get("unit_raw")
        if unit not in parameter.units_accepted:
            return None, Refusal(raw, f"unit {unit!r} not in units_accepted "
                                      f"({', '.join(parameter.units_accepted)})")
        out["value_target"] = round(
            float(value) * float(parameter.units_accepted[unit]), 6)
        return out, None

    if not isinstance(value, str) or not value.strip():
        return None, Refusal(raw, f"a {parameter.value_type} parameter needs a "
                                  f"non-empty string value")
    if parameter.value_type == "category":
        uri = parameter.value_to_uri().get(value.strip().casefold())
        if uri is None:
            # The model was handed the closed class list and still found
            # nothing that fits. That is a mapping gap to review, not a
            # reason to drop the finding: the wording stays on the tuple.
            flags.append(f"unmapped:value:{value.strip()}")
        out["value_uri"] = uri
        wording = raw.get("value_raw")
        if isinstance(wording, str) and wording.strip():
            out["value_raw"] = wording.strip()
            if wording.strip().casefold() not in parameter.value_to_uri():
                flags.append(f"mapped:value:{wording.strip()}->{uri}")
    return out, None


def _value_in_quote(raw: dict, parameter: Parameter, quote: str) -> bool:
    """Is the claimed value actually in the passage it cites?"""
    if parameter.is_numeric:
        return canonical_number(raw.get("value")) in _numbers_in(quote)
    # For a category the tuple carries two things: the class the model mapped
    # to and, in *_raw, how the document worded it. The evidence check is
    # about the document, so it runs against the wording, never against the
    # class name the mapping produced.
    wording = raw.get("value_raw") or raw.get("value")
    return _flat(str(wording)).casefold() in _flat(quote).casefold()


def verify_tuple(raw: dict, parameter: Parameter, source_text: str, *,
                 owner_kind: str = "section",
                 locate: Optional[Callable[[str], Optional[list]]] = None):
    """One claimed tuple against everything the model does not control.

    Returns Verified or Refusal. *owner_kind* decides the tier: prose gets
    TIER_TEXT, a table or figure gets TIER_VISUAL. *locate* is a lazy lookup
    that maps the quote to highlight rectangles in the source PDF — lazy
    because opening the PDF is the expensive step and a claim refused earlier
    never needs it.
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
                uri = axis.label_to_uri().get(str(given).casefold())
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
                    if wording.casefold() not in axis.label_to_uri():
                        flags.append(f"mapped:{name}:{wording}->{uri}")
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
    if not isinstance(quote, str) or len(quote) < 8:
        return Refusal(raw, "quote missing or too short to identify anything")
    if not quote_in(source_text, quote):
        return Refusal(raw, "quote not found in the source it cites")
    if not _value_in_quote(raw, parameter, quote):
        return Refusal(raw, f"value {raw.get('value')!r} does not occur in the quote")

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
