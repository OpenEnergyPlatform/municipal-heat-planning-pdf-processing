"""
wording.py: What the answer loop says around the prompts.

The prompts belong to the profile; so does everything the loop wraps around
them: the heading over the user's task, the labels inside the history block,
the sentence that tells the model to answer NOW. The core assembles those
pieces and does not write them: it cannot know whether the reader is holding a
German heat plan or an English scenario study.

A profile contributes them in `profiles/<name>/inference.py`. A profile that
extends another one writes only the pieces it words differently: its PHRASES
are laid over those of the profile it extends.

The words of the app's pages come the same way and from the same file: the
profile's `UI` table, which a person reads where a model reads PHRASES. That
includes the picker's labels, the tag after a document's name and the noun
for one. Both tables are checked for the entries the core asks for
(`REQUIRED`, `UI_REQUIRED`).

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from typing import Optional

from ..profile import ENV_VAR, Profile, active_profile, load_profile

log = logging.getLogger(__name__)

# Checked as a set at load time: a profile that forgets one should hear about
# it when the stage is imported, not three hours into a batch.
REQUIRED = frozenset({
    "task_heading", "history_heading", "history_task", "history_phrase",
    "history_answer",
    "code_heading", "exec_stdout", "exec_empty", "exec_failed",
    "exec_unknown", "exec_recover",
    "compute_heading", "compute_guide", "compute_guide_final",
    "image_heading", "image_uncaptioned", "image_unavailable",
    "image_guide", "image_guide_final", "image_part", "readoff_heading",
    "citation_quotes", "citation_page", "citation_page_unknown",
    "citation_section", "citation_table", "citation_figure",
    "readoff_value", "exec_none", "image_requested",
})


# The words of the app's pages: what a person reads and clicks, as
# opposed to PHRASES, which a model reads. Same rule, same check.
UI_REQUIRED = frozenset({
    "title_fallback", "page_chat", "page_review",
    "selection", "include_old", "no_documents",
    "no_match", "whole_corpus", "whole_corpus_help",
    "compare_help", "choose_one", "scopes",
    "scopes_help", "format", "format_prose",
    "stub_mode", "anchor", "image_upload",
    "image_mode", "image_and_text", "image_only",
    "chat_input", "choose_scope", "with_image",
    "preparing", "recheck", "all_examined",
    "no_hits", "nothing_backed", "no_answer_context",
    "statements_dropped", "replies_unreadable", "answer_unreadable",
    "computed_from", "run_label",
    "compare_dropped", "compare_note", "compare_too_few",
    "compare_failed", "column_document", "column_answer",
    "column_citations", "document_nothing", "show_evidence",
    "show_compute", "compute_no_output", "compute_error",
    "read_off", "open_pdf", "show_context",
    "show_page", "page_not_located", "page_no_file", "page_failed_library",
    "page_failed_open", "page_failed_range", "page_failed_draw",
    "download_pdf", "no_profile",
    "values_heading", "values_note", "values_more",
    "values_level", "index_model_differs",
    "review_heading", "review_intro", "review_no_harvest",
    "review_by", "review_by_missing", "review_progress",
    "review_none_open", "review_parameter_filter", "review_all_parameters",
    "review_value", "review_field", "review_open",
    "review_correct", "review_wrong", "review_expected",
    "review_note", "review_save", "review_skip",
    "review_nothing_decided", "review_saved", "review_missing_heading",
    "review_missing_intro", "review_missing_document", "review_missing_parameter",
    "review_missing_value", "review_missing_unit", "review_missing_quote",
    "review_missing_page", "review_missing_save", "review_missing_needs",
    "review_checked_heading", "review_checked_intro", "review_checked_save",
    "review_checked_all",
    # The picker's labels (docpipe/inference/catalog.py): the tag after a
    # document's name, and the noun for a profile that names none.
    "version_current", "version_old", "document_noun_fallback",
})


BUILT_IN = "default"
_said_fallback: list = []


def chat_profile(profile: Optional[Profile] = None) -> Profile:
    """The profile the answer loop reads from: the one given, else the one
    in force, else the built-in one.

    The chat starts on any corpus, and its pages already take their words
    from the built-in profile when none is named; its prompts and phrases
    follow, so the first question is answered in English instead of stopping.
    The fallback is here and not in `prompts.load` or `require_profile`: the
    stages that write a corpus keep their stop without a profile, because a
    forgotten flag there would start a real run on the wrong prompts. Said
    once per process, since the loop asks for a profile on every hit.
    """
    profile = profile or active_profile()
    if profile is not None:
        return profile
    profile = load_profile(BUILT_IN)
    if not _said_fallback:
        _said_fallback.append(profile.name)
        log.warning("chat: no profile is named, so the answer loop reads its "
                    "prompts and phrases from the built-in profile %r; name "
                    "another with --profile, `profile` in docpipe.toml or "
                    "$%s", profile.name, ENV_VAR)
    return profile


def _component(attr: str, profile: Optional[Profile] = None):
    return chat_profile(profile).require("inference", attr)


_checked: dict = {}


def phrases(profile: Optional[Profile] = None) -> dict:
    """The profile's labels and guides, complete.

    Cached: citation_label asks once per retrieval hit, and the completeness
    check has nothing new to say the second time.
    """
    profile = chat_profile(profile)
    key = profile.name
    if key in _checked:
        return _checked[key]
    nearest = _component("PHRASES", profile)
    got: dict = {}
    for layer in reversed(profile.layers("inference", "PHRASES")[1:]):
        got.update(layer)                   # those of the profiles it extends
    got.update(nearest)
    missing = sorted(REQUIRED - set(got))
    if missing:
        raise LookupError(f"inference.PHRASES is missing {missing}")
    _checked[key] = got
    return got


_ui_checked: dict = {}


def ui(profile: Optional[Profile] = None) -> dict:
    """The words of the app's pages and of the picker, complete. Without a
    profile they are those of the profile the package brings itself: the app
    starts on any corpus, and what it shows then is in English."""
    profile = profile or active_profile() or load_profile(BUILT_IN)
    if profile.name in _ui_checked:
        return _ui_checked[profile.name]
    got: dict = {}
    for layer in reversed(profile.layers("inference", "UI")):
        got.update(layer)
    missing = sorted(UI_REQUIRED - set(got))
    extra = sorted(set(got) - UI_REQUIRED)
    if missing or extra:
        raise LookupError(f"inference.UI of profile {profile.name!r} is "
                          f"missing {missing} and has {extra} no page uses")
    _ui_checked[profile.name] = got
    return got


def readoff(profile: Optional[Profile] = None) -> tuple:
    """(marker, note) for values the model read off a figure.

    The note is appended unless the answer already says so itself, and the
    marker is how that is recognised — both in the answer's own language.
    """
    return _component("READOFF_MARKER", profile), _component("READOFF_NOTE", profile)
