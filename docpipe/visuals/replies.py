"""
replies.py: The reply each vision request asks for, as a JSON schema.

The grammar of every request of this stage and of page transcription, on
every provider (see `docpipe.providers.grammar`). The prompts state the same
shapes in words; nothing here is a check beyond the one required key, which
`vision.call_vision` reads as text. The key is the single entry of `required`
in each schema.

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
