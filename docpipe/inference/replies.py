"""
replies.py: The reply each chat request asks for, as a JSON schema.

For an API that generates inside a schema (see `docpipe.providers`). The
prompts state the same shapes in words; nothing here is a check.

One request has no schema: the answer reformatted into a JSON shape the user
wrote into the task. That shape is the user's and only exists as prose.

Author: Felix Vossel
"""
TEXT = {"type": "string"}


def _only(name: str, **properties) -> tuple:
    required = [key for key, value in properties.items()
                if value.pop("_required", False)]
    return name, {"type": "object", "properties": properties,
                  "required": required, "additionalProperties": False}


CHOOSE = _only("choice_reply",
               answer={"type": ["string", "integer"], "_required": True})
PHRASE = _only("search_phrase_reply",
               phrase={"type": "string", "_required": True},
               repetition={"type": "boolean"})
CHUNK = _only("chunk_reply",
              found={"type": "boolean", "_required": True},
              answer=dict(TEXT), quote=dict(TEXT))
READOFF = _only("readoff_reply",
                reading={"type": "string", "_required": True},
                value={"type": ["number", "null"]},
                unit={"type": ["string", "null"]},
                confidence=dict(TEXT))
REVISE = _only("revised_answer_reply",
               answer={"type": "string", "_required": True})
COMPARE = _only("comparison_reply",
                comparison={"type": "string", "_required": True})

_SUPPORT = {"type": "object",
            "properties": {"index": {"type": "integer"},
                           "quote": TEXT,
                           "image": {"type": ["boolean", "null"]},
                           "reading": TEXT},
            "required": ["index"], "additionalProperties": False}


def answer(actions: bool = True) -> tuple:
    """The answer envelope, and with *actions* the two things the model may
    ask for instead: a calculation, or a crop it was only pointed at."""
    properties = {"found": {"type": "boolean"},
                  "complete": {"type": "boolean"},
                  "answer": TEXT,
                  "supports": {"type": "array", "items": _SUPPORT}}
    if actions:
        properties.update(action={"enum": ["python", "image"]},
                          code=dict(TEXT), id=dict(TEXT))
    return "answer_reply", {"type": "object", "properties": properties,
                            "additionalProperties": False}
