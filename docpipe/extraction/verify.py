"""
verify.py – No tuple enters the output on the model's word.

The extraction reply claims a value with a quote. Before anything is written,
every claim is checked against things the model does not control: the spec's
closed vocabularies, the source text the quote must literally sit in, and —
where a lookup is provided — the source PDF itself. A tuple that fails is
refused with a named reason, never repaired by guessing; a tuple that passes
carries a verification tier saying how far down the chain it was confirmed.

The tiers exist because the corpus text for tables is itself a model output
(the VLM's transcription). Matching a number against it is model-vs-model;
only the PDF lookup breaks that circle. Per project decision the tier does
not gate anything — everything is exported, the tier and the provenance make
each value checkable by a human.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .spec import Parameter

TIER_PDF = "pdf_verified"
TIER_SOURCE = "source_only"
TIER_READOFF = "readoff"

_WS = re.compile(r"\s+")
# A number as it appears in running text: digits with optional grouping and
# one decimal part, German or international.
_NUMBER = re.compile(r"\d(?:[\d.,   ]*\d)?")


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
    # The rightmost separator with 1-2 trailing digits is the decimal mark;
    # a separator followed by exactly 3 digits is grouping. Ambiguity like
    # '1.234' (one thousand or 1.234?) is resolved as grouping, which is how
    # these documents write it.
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    decimal_pos = max(last_dot, last_comma)
    if decimal_pos != -1 and len(s) - decimal_pos - 1 == 3 and \
            s.count(".") + s.count(",") == 1 and decimal_pos == min(
                p for p in (last_dot, last_comma) if p != -1):
        decimal_pos = -1                       # single grouping separator
    if decimal_pos != -1 and len(s) - decimal_pos - 1 != 3:
        integer = re.sub(r"[.,]", "", s[:decimal_pos])
        fraction = s[decimal_pos + 1:]
        if not fraction.isdigit():
            return None
        out = f"{integer}.{fraction}".rstrip("0").rstrip(".")
        return out or "0"
    return re.sub(r"[.,]", "", s)


def _numbers_in(text: str) -> set:
    return {canonical_number(m.group(0)) for m in _NUMBER.finditer(text or "")}


def quote_in(source: str, quote: str) -> bool:
    """Whitespace-collapsed literal containment — corrections.py semantics."""
    if not quote or not source:
        return False
    return _WS.sub(" ", quote).strip() in _WS.sub(" ", source)


@dataclass
class Verified:
    tuple: dict
    tier: str
    flags: list = field(default_factory=list)   # non-fatal findings


@dataclass
class Refusal:
    raw: dict
    reason: str


def verify_tuple(raw: dict, parameter: Parameter, source_text: str, *,
                 pdf_text: Optional[Callable[[], Optional[str]]] = None,
                 readoff: bool = False):
    """One claimed tuple against everything the model does not control.

    Returns Verified or Refusal. *pdf_text* is a lazy lookup for the native
    PDF text behind the source (bbox extraction) — lazy because opening the
    PDF is the expensive step and a tuple refused earlier never needs it.
    """
    if not isinstance(raw, dict):
        return Refusal(raw={}, reason="tuple is not an object")

    value = raw.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return Refusal(raw, "value is not a number")
    canonical = canonical_number(value)

    unit = raw.get("unit_raw")
    if unit not in parameter.units_accepted:
        return Refusal(raw, f"unit {unit!r} not in units_accepted "
                            f"({', '.join(parameter.units_accepted)})")

    flags: list = []
    resolved: dict = {}
    for name, axis in parameter.axes.items():
        given = raw.get(name)
        if axis.vocabulary is not None:
            if given is None:
                if axis.required:
                    return Refusal(raw, f"required axis {name!r} missing")
                resolved[name] = None
                continue
            if given in axis.vocabulary:           # already a URI
                resolved[name] = given
                continue
            uri = axis.label_to_uri().get(str(given).casefold())
            if uri is None:
                # Out-of-vocabulary is a mapping gap, not model misconduct:
                # the raw label stays on the tuple and the flag feeds the
                # vocabulary review. Refusing here would silently shrink the
                # harvest every time a plan words a label differently.
                if axis.required:
                    return Refusal(raw, f"axis {name!r}: {given!r} not in "
                                        f"vocabulary and axis is required")
                resolved[name] = None
                flags.append(f"unmapped:{name}:{given}")
            else:
                resolved[name] = uri
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
    if canonical not in _numbers_in(quote):
        return Refusal(raw, f"value {canonical} does not occur in the quote")

    tier = TIER_READOFF if readoff else TIER_SOURCE
    if not readoff and pdf_text is not None:
        native = pdf_text()
        if native and canonical in _numbers_in(native):
            tier = TIER_PDF
        # No native text (scan) or number absent: stays source_only. The
        # distinction between "scan" and "VLM transcribed a different digit"
        # is exactly what the tier reports to a human.

    out = dict(raw)
    out.update(resolved)
    out["value_target"] = round(
        float(value) * float(parameter.units_accepted[unit]), 6)
    out["parameter"] = parameter.uri
    return Verified(tuple=out, tier=tier, flags=flags)
