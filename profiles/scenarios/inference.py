"""
inference.py – What the answer loop says around the ar6 prompts.

English, like the publications and like the answers. See
docpipe/inference/wording.py for what each piece is used for.

Author: Felix Vossel
"""

READOFF_MARKER = "read off"
READOFF_NOTE = ("(Note: some values were read off from figures – estimates, "
                "reading errors possible.)")

PHRASES = {
    "task_heading": "User's task",
    "history_heading": ("Conversation so far (use it ONLY to resolve references in the "
                        "current task — pronouns, \"and …\", ellipses; NOT a source of "
                        "facts, evidence comes exclusively from the excerpts)"),
    "history_task": "Question",
    "history_phrase": "Search anchor",
    "history_answer": "Answer",

    "empty_reply": "Your reply was empty. Reply with valid JSON.",
    "parse_error": "Parse error: {error}. Reply with NOTHING BUT a valid JSON object.",

    "code_heading": "Code executed",
    "exec_stdout": "Execution result (stdout)",
    "exec_empty": "(no output)",
    "exec_failed": "Execution failed",
    "exec_unknown": "unknown error",
    "exec_recover": "Fix the code OR answer without computing.",

    "compute_heading": "Already executed",
    "compute_guide": ("Give the final answer in the prescribed JSON format — or, only "
                      "if truly necessary, another "
                      '{"action":"python","code":...}.'),
    "compute_guide_final": ("Give the final answer NOW, in the prescribed JSON format "
                            "(NO more action objects)."),

    "image_heading": "Requested figures (see images)",
    "image_uncaptioned": "no caption",
    "image_unavailable": "image unavailable",
    "image_guide": ("Read the value off the image and give the final answer — or, only "
                    'if truly necessary, another {"action":"image","id":"..."}.'),
    "image_guide_final": ("Give the final answer NOW, in the prescribed JSON format "
                          "(NO more action objects)."),
    "image_part": "Image for excerpt index={index}",

    "readoff_heading": "To read off (per the pre-check)",

    # The citation under the answer, which the model also reads as `source`.
    "citation_quotes": ("“", "”"),
    "citation_page": "page {page}",
    "citation_page_unknown": "page unknown",
    "citation_section": "Section",
    "citation_table": "Table",
    "citation_figure": "Figure",
}
