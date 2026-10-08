"""
inference.py – What the answer loop says around the prompts, in English.

See docpipe/inference/wording.py for what each piece is used for. A profile
that extends this one writes only the pieces it words differently.

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

    # What the loop splices into a reading, a failed run and an image part.
    "readoff_value": "{reading} — value read off: {value} {unit}",
    "exec_none": "no result",
    "image_requested": "Requested image [{id}]: {title}",
}


# The words of the chat app's pages (docpipe/app/app.py) and of the picker's
# labels (docpipe/inference/catalog.py): what a person reads and clicks. Every
# key is used there, and `wording.UI_REQUIRED` lists them.
UI = {
    "title_fallback": "docpipe – search",
    "page_chat": "Search",
    "page_review": "Review values",
    "selection": "Selection",
    "include_old": "Include superseded versions",
    "no_documents": "No documents found in the database.",
    "no_match": "No document matches this filter.",
    "whole_corpus": "Search the whole corpus",
    "whole_corpus_help": ("The question goes to every current document at "
                          "once; each source names its document. The "
                          "verified values above it come from every "
                          "harvested document, older versions included."),
    "compare_help": ("Several selected: the same question goes to each "
                     "document by itself, then only the answers are "
                     "compared."),
    "choose_one": "Please choose at least one {noun}.",
    "scopes": "Search in",
    "scopes_help": ("Tables and figures are in the index twice: “image + "
                    "description” searches the embedded image with its "
                    "description, “description only” the caption and "
                    "description text without the image."),
    "format": "Answer format",
    "format_prose": "Prose",
    "stub_mode": "LLM_STUB_MODE is on – answers are placeholders.",
    "anchor": "🔎 Search anchor (embedding phrase): {phrase}",
    "image_upload": "Optional image for the query",
    "image_mode": "Use the image for retrieval as",
    "image_and_text": "Image + text",
    "image_only": "Image only",
    "chat_input": "Your question …",
    "choose_scope": "Please choose at least one place to search in.",
    "with_image": "_(with image)_",
    "preparing": "Preparing",
    "recheck": "🔁 Searching again – {n} sources already examined were skipped",
    "all_examined": "Every matching source has already been examined.",
    "no_hits": "No hits in the chosen places.",
    "nothing_backed": ("The examined sources hold nothing that backs an "
                       "answer to this question."),
    "no_answer_context": "(no backed answer found)",
    "statements_dropped": ("⚠️ {dropped} of {made} statement(s) removed: "
                           "their quote does not stand in the source they "
                           "cite."),
    "replies_unreadable": ("⚠️ {n} request(s) to the model could not be read "
                           "({causes}). What they would have said is missing "
                           "from this answer."),
    "answer_unreadable": ("The model's replies could not be read ({causes}). "
                          "Nothing can be said about what the sources "
                          "contain."),
    "computed_from": ("🧮 Calculated: code and output of run {n} under "
                      "“Show calculation”."),
    "run_label": "Run {n}",
    "compare_dropped": "Not asked (limit {limit}): {names}",
    "compare_note": ("⚖️ Comparison of the answers, without sources of its "
                     "own — the evidence stands with each answer."),
    "compare_too_few": "Too few backed answers for a comparison.",
    "compare_failed": ("The comparison could not be written; each "
                       "document's answer is below."),
    "column_document": "Document",
    "column_answer": "Answer",
    "column_citations": "Citations",
    "document_nothing": "Nothing in this document backs an answer.",
    "show_evidence": "Show evidence",
    "show_compute": "🧮 Show calculation ({n}×)",
    "compute_no_output": "(no output)",
    "compute_error": "Error: {error}",
    "read_off": ("📷 Read off the figure – an estimate, reading errors are "
                 "possible"),
    "open_pdf": "📄 Open page {page} in the PDF",
    "show_context": "Show context",
    "show_page": "Show page {page}",
    "page_not_located": ("The quote could not be located on this page, so "
                         "nothing is marked."),
    "page_no_file": ("{file} is not in the PDF folder of this server, so "
                     "its page cannot be shown."),
    "page_failed_library": ("Page {page} could not be shown: PyMuPDF is not "
                            "installed on this server."),
    "page_failed_open": "Page {page} could not be shown: the PDF does not open.",
    "page_failed_range": ("Page {page} could not be shown: the PDF has no such "
                          "page."),
    "page_failed_draw": "Page {page} could not be shown: it did not render.",
    "download_pdf": "Download the PDF",
    "no_profile": ("No profile is named, so the chat runs on the built-in "
                   "profile `default`: English prompts and wording that fit "
                   "any folder. To use another, start the chat with "
                   "`docpipe --profile <name> chat`, or set `profile = "
                   "\"<name>\"` in docpipe.toml or DOCPIPE_PROFILE."),
    "values_heading": "Backed values from the reading of the documents",
    "values_note": ("These numbers were read from the documents beforehand "
                    "and checked against their quote; they do not come from "
                    "the answer below."),
    "values_more": "{shown} of {total} values shown.",
    "values_level": "Level {level}",
    "index_model_differs": ("The index was built with {built}, questions are "
                            "embedded with {queried}: their vectors do not "
                            "compare, so what is found may be wrong."),
    "review_heading": "Review the values that were read",
    "review_intro": ("Decide for every value, field by field, whether the "
                     "document says that. The decisions are kept in a file "
                     "of their own and are what precision is counted "
                     "against."),
    "review_no_harvest": "No harvest is configured (INFERENCE_HARVEST_DIR).",
    "review_by": "Your name or initials",
    "review_by_missing": ("Please enter a name first: a decision without "
                          "one cannot be traced later."),
    "review_progress": "{open} values open.",
    "review_none_open": "No value is open for this selection.",
    "review_parameter_filter": "Parameter",
    "review_all_parameters": "All",
    "review_value": "Value",
    "review_field": "Field “{field}”: {content}",
    "review_open": "leave open",
    "review_correct": "correct",
    "review_wrong": "wrong",
    "review_expected": "What is right (optional)",
    "review_note": "Note (optional)",
    "review_save": "Save and continue",
    "review_skip": "Skip",
    "review_nothing_decided": "No field was decided.",
    "review_saved": "{n} decision(s) saved.",
    "review_missing_heading": "A value is missing",
    "review_missing_intro": (
        "The document states a value the harvest does not carry."),
    "review_missing_document": "Document",
    "review_missing_parameter": "Parameter",
    "review_missing_value": "Value",
    "review_missing_unit": "Unit (optional)",
    "review_missing_quote": "Wording in the document",
    "review_missing_page": "Page (optional)",
    "review_missing_save": "Add the missing value",
    "review_missing_needs": "Document, parameter and value are needed.",
    "review_checked_heading": "Document read whole",
    "review_checked_intro": (
        "Only for documents somebody read whole for a parameter can it be "
        "said what the harvest lacks."),
    "review_checked_save": "Record as read whole",
    "review_checked_all": "for every parameter",
    "version_current": "(current)",
    "version_old": "(old)",
    "document_noun_fallback": "document",
}
