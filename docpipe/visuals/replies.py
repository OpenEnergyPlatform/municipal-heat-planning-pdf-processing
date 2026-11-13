"""
replies.py: The reply each vision request asks for, as a JSON schema.

The grammar of every request of this stage and of page transcription, on
every provider (see `docpipe.providers.grammar`). The prompts state the same
shapes in words; nothing here is a check beyond the required keys, the first
of which `vision.call_vision` reads as text, or as a list where its schema is
an array. The first entry of `required` in each schema is that key.

Author: Felix Vossel
"""
TEXT = {"type": "string"}
CAPTION = {"type": ["string", "null"]}
# A table as its lines, one string each, which the code joins: the model
# never writes a line break inside a JSON string, where 43 of 1,656 tables of
# the scenarios rebuild of 2026-11-11 had come back on one line.
LINES = {"type": "array", "items": TEXT}

TABLE = ("table_reply", {
    "type": "object",
    "properties": {"rows": LINES, "caption": CAPTION},
    "required": ["rows"], "additionalProperties": False})

# A table that may continue the table before it (`continuation`): its
# transcription and whether it continues that table.
TABLE_CONTINUED = ("table_continued_reply", {
    "type": "object",
    "properties": {"rows": LINES, "caption": CAPTION,
                   "continues": {"type": "boolean"}},
    "required": ["rows", "continues"], "additionalProperties": False})

FIGURE = ("figure_reply", {
    "type": "object",
    "properties": {"description": TEXT, "caption": CAPTION},
    "required": ["description"], "additionalProperties": False})

PAGE = ("page_reply", {
    "type": "object",
    "properties": {"markdown": TEXT},
    "required": ["markdown"], "additionalProperties": False})
