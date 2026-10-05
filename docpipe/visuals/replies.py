"""
replies.py: The reply each vision request asks for, as a JSON schema.

For an API that generates inside a schema (see `docpipe.providers`). The
prompts state the same shapes in words; nothing here is a check. The
plain-text rescue asks for no JSON and has no schema.

Author: Felix Vossel
"""
TEXT = {"type": "string"}
CAPTION = {"type": ["string", "null"]}

TABLE = ("table_reply", {
    "type": "object",
    "properties": {"markdown": TEXT, "caption": CAPTION},
    "required": ["markdown"], "additionalProperties": False})

FIGURE = ("figure_reply", {
    "type": "object",
    "properties": {"description": TEXT, "caption": CAPTION},
    "required": ["description"], "additionalProperties": False})

PAGE = ("page_reply", {
    "type": "object",
    "properties": {"markdown": TEXT},
    "required": ["markdown"], "additionalProperties": False})
