"""
queries.py: Expands a profile's query templates into retrieval probes drawn
from the spec.

One broad question per parameter under-harvests. Retrieval ranks, a rank has a
cap, and the tenth-most-similar table wins over the eleventh for no reason a
corpus cares about. So the profile supplies query templates and the spec
supplies the material, a parameter's label and its axis vocabularies, and every
combination becomes its own retrieval probe. The templates live with the
profile because their wording is corpus language (German for kwp's plans); this
module only expands placeholders.

Placeholders:
    {label}        the parameter's label
    {axis:NAME}    one query per vocabulary entry of that axis, using the
                   entry's first (primary) corpus label

Author: Felix Vossel
"""
from __future__ import annotations

import re

from .spec import Parameter, SpecError

_AXIS = re.compile(r"\{axis:([a-z_]+)\}")


def expand(templates: list, parameter: Parameter) -> list:
    """Every template × every referenced vocabulary entry, order-stable."""
    out: list = []
    for template in templates:
        if not isinstance(template, str) or not template.strip():
            continue
        template = template.strip()
        axis_names = _AXIS.findall(template)
        if axis_names and not parameter.axes:
            # A parameter with no coordinates at all — a document's title, the
            # office that wrote it — cannot fan out along one. The template is
            # simply not about this parameter.
            continue
        for name in axis_names:
            axis = parameter.axes.get(name)
            if axis is None or axis.vocabulary is None:
                raise SpecError(
                    f"template {template!r} names axis {name!r}, which "
                    f"{parameter.uri} does not define as a vocabulary axis")
        base = template.replace("{label}", parameter.label)
        if not axis_names:
            out.append(base)
            continue
        # One query per entry of the first referenced axis; nested axis
        # products explode and add nothing a sweep round would not find.
        name = axis_names[0]
        for labels in parameter.axes[name].vocabulary.values():
            out.append(base.replace(f"{{axis:{name}}}", labels[0]))
    seen: set = set()
    unique = [q for q in out if not (q in seen or seen.add(q))]
    return unique
