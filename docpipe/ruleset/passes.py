"""
passes.py: The record of a run, its archive, the check before a run and the
passes after it (trace.py, stats.py, archive.py, preflight.py, topup*.py,
remap.py, recheck.py, review.py, survey.py). Every rule here is the run's: the
follow-up passes are switches of the call and no steps of the flow yet, so no
step has an own value of them. The one exception is `trace_requests`, which
each step that asks may set for itself.
"""
from .kit import ASKING, rule

# What a coordinate's state can be (`fields`): the choices of a rule that
# lists states.
STATES = ("read", "derived", "unstated", "unbacked", "exhausted",
          "unanswered", "out_of_slice")


def run_value(name: str):
    """The value of the rule *name* for the whole run, whatever step asks:
    for a rule no step sets, read where a step is running (the record of a
    request, the archive)."""
    from .. import rules
    return rules.current()[name]


RULES: tuple = (
    # -- flow: which documents a run reads --
    rule("documents", "flow", "Documents", "texts",
         "The documents a run reads, by their numbers. Empty: every current "
         "document is read. With numbers listed, only those are read and a "
         "number that is no current document is reported. The call "
         "switch that names a document sets this for one run.",
         empty=True, where="runner.py (select_documents)",
         title="Documents to read"),
    rule("skip_current", "flow", "Documents", "switch",
         "On: a document whose harvest is already there and whose stamp says "
         "it is current is skipped. Off: every document is read again, "
         "whatever its stamp says, and its earlier harvest is kept in the "
         "archive. The call switch that forces a reading sets this for one "
         "run.", where="runner.py (already_done)",
         title="Skip documents already read"),
    # -- flow: the record of a run (trace) --
    rule("trace_on", "flow", "Trace", "switch",
         "On: the run writes a record of every document, one line per event, "
         "so that a run can be counted and read back request by request "
         "afterwards; stages 4 and 5 write theirs in the document's folder. "
         "Off: nothing is recorded, and the statistics have nothing to count "
         "but the harvest.",
         env="EXTRACT_TRACE", env_flag=(False, True),
         where="trace.py",
         title="Write a record of every document"),
    rule("trace_compress", "flow", "Trace", "switch",
         "On: the record of a document is compressed to save space. Off: it "
         "is written as plain text, which is larger and can be read without "
         "a tool.", where="trace.py (_handle)",
         title="Compress the record"),
    rule("trace_time_places", "flow", "Trace", "whole",
         "How many decimal places the times of a request (when it was asked, "
         "sent and answered) are rounded to in the record. 3 is to the "
         "millisecond. A larger number records finer times and makes the "
         "record larger.", least=0, most=9, where="trace.py (_times)",
         title="Decimal places of times"),
    rule("trace_piece_min_chars", "flow", "Trace", "whole",
         "A text in the record that is longer than this is written once per "
         "document and referred to afterwards, so that a prompt or a passage "
         "that many requests share is not stored again and again. A smaller "
         "number saves more space and makes the record harder to read by "
         "eye.", least=1, where="trace.py (_ref)",
         title="Length for write-once texts"),
    rule("trace_vector_places", "flow", "Trace", "whole",
         "How many places of the vector search the record keeps for each "
         "kind of passage, each with its similarity, at every search. 0 "
         "keeps every place. A larger number shows further down the order "
         "and makes the record larger.",
         decided="2026-11-14", least=0,
         where="runner.py (trace_vector)",
         title="Search places kept per kind"),
    rule("trace_requests", "flow", "Trace", "switch",
         "On: the event that reports a request also records the request as "
         "it was sent and the answer or error that came back. Off: the "
         "event records only its own counts, and the request cannot be read "
         "back. A step that asks may set this for itself, so that one "
         "step's requests are recorded and another's are not.", decided="2026-11-05", steps=ASKING + ("each value",),
         where="trace.py (exchanged)",
         title="Record requests and answers"),
    rule("show_unparsable", "flow", "Trace", "whole",
         "How many replies that could not be read as the answer asked for "
         "the log shows in full during a run. Further ones are only "
         "counted. 0 shows none. A larger number fills the log with long "
         "replies.", least=0, env="EXTRACT_SHOW_UNPARSABLE",
         where="runner.py (reply log, _unparsable)",
         title="Unreadable replies shown in full"),
    # -- flow: the statistics after a run --
    rule("stats_not_asked_states", "flow", "Statistics", "texts",
         "The states of a coordinate that the statistics do not count as "
         "asked: the coordinates the spec decided and those a gate had "
         "already closed. Add a state to leave it out of the share of "
         "coordinates still open per document; remove one to count it as "
         "asked.", empty=True, choices=STATES,
         where="stats.py (from_harvest)",
         title="States not counted as asked"),
    rule("write_stats", "flow", "Statistics", "switch",
         "On: every run writes its statistics beside the harvest, with the "
         "open coordinates per axis and what each kind of request cost. Off: "
         "no statistics are written. A failure to write them never fails "
         "the run.", decided="2026-10-22",
         where="stats.py (write)",
         title="Write statistics for each run"),
    # -- flow: the archive --
    rule("archive_before_replace", "flow", "Archive", "switch",
         "On: before a run replaces or deletes a file of the harvest, a "
         "harvest, a stamp, a record or a working list, it keeps a copy of "
         "the file as it was, once per run and file, in a folder beside it. "
         "Off: files are replaced without a copy and cannot be got back.",
         decided="2026-10-22", where="archive.py (keep)",
         title="Keep a copy before replacing files"),
    # -- the check before a run --
    rule("shrug_words", "spec", "Check before a run", "texts",
         "Entries of a list that mean \"I do not know\". An entry with one of "
         "these words does not belong in a list of classes, because a "
         "coordinate nobody read is a state and no class, and the check "
         "before a run fails for it. Add a word in another language to catch "
         "it. Case does not matter.", empty=True,
         where="preflight.py (audit)",
         title="\"Don't know\" entries"),
    rule("preflight_severity", "flow", "Check before a run", "map",
         "What each check before a run does when it finds a problem, by the "
         "name of the check: fail stops the run, warn only reports it, off "
         "does not run the check. A check not named here fails. Most checks "
         "fail; those that report what the ontology or the sources say and "
         "no fault of the spec only warn.",
         of="text", empty=True, where="preflight.py (audit)",
         title="Consequence of a failed check"),
    rule("preflight_prompts", "prompts", "Check before a run", "texts",
         "Prompts the check before a run loads in addition to those the "
         "steps of the flow use, by their names. It loads every prompt the "
         "steps in effect ask with and fails where one is missing or empty; "
         "a prompt named here is held to the same.", empty=True,
         where="preflight.py (audit)",
         title="Extra prompts to check"),
    rule("preflight_skip_counts_ok", "flow", "Check before a run", "switch",
         "On: the check of the graph's shapes counts as passed where it "
         "cannot run (the profile names no shapes, the file is not there or "
         "a library is missing), and says it was skipped. Off: a check that "
         "cannot run is a warning.", where="preflight.py (shapes_verdict)",
         title="Skipped shape check counts passed"),
    # -- flow: reading again and appending --
    rule("reread_keep_states", "flow", "Reading again", "texts",
         "When a coordinate that was read is read again, these are the "
         "states of the new reading that replace the old one. With any other "
         "state the old reading comes back, so a coordinate read once is not "
         "lost to a worse one.", choices=STATES,
         where="topup.py (sweep_decide)",
         steps=("better",),
         title="States that replace a read result"),
    rule("reread_improves_states", "flow", "Reading again", "texts",
         "When a coordinate that was not read is read again, these are the "
         "states of the new reading that replace the old one. By default any "
         "answer does, including \"the document does not say it\", but not "
         "running out of budget.", choices=STATES,
         where="topup.py (sweep_decide)",
         steps=("better",),
         title="States that replace an unread result"),
    rule("document_poll_s", "flow", "Load and concurrency", "number",
         "How many seconds the pass that reads open coordinates waits "
         "before it looks again whether a document has finished, when it "
         "does not wait for room on the server.", least=0.1,
         where="passflow.py (_beside)",
         steps=("stored",),
         title="Seconds between document checks"),
    rule("document_poll_room_s", "flow", "Load and concurrency", "number",
         "How many seconds the pass that reads open coordinates waits "
         "before it looks again whether a document has finished and the "
         "server has room for the next, when it waits for room. Also the "
         "pause when no room is free and nothing of the pass is running.",
         least=0.1, where="passflow.py (_beside)",
         steps=("stored",),
         title="Seconds between document and room checks"),
    rule("reread_blocks_frame", "flow", "Reading again", "switch",
         "On: a document whose moved question belongs to the frame of its "
         "rows (the scenario and year a table stands under) is not read "
         "again coordinate by coordinate, because the frame decides how "
         "many passes the document gets and its rows may be other ones now. "
         "Off: such a coordinate is read again like any other.",
         where="topup.py (actionable)",
         steps=("movable",),
         title="A moved frame question blocks rereading"),
    rule("reread_blocks_dynamic_list", "flow", "Reading again", "switch",
         "On: a coordinate whose list of entries is made per document is "
         "not read again where that list cannot be made, because a wording "
         "would then stand where a class stood. Off: it is read again "
         "against an empty list.", where="topup.py (actionable)",
         steps=("movable",),
         title="A per-document list blocks rereading"),
    rule("reread_reopen_closed_rows", "flow", "Reading again", "switch",
         "On: after a moved gate, rows that had been left out of the slice "
         "and may now stay are asked the coordinates they never were asked. "
         "Off: they keep the state that says they left before the "
         "question.", where="topup.py (reopened_by_gate)",
         steps=("reopen_closed",),
         title="Reopen excluded rows"),
    rule("reread_order", "flow", "Reading again", "choice",
         "The order in which the moved coordinates of a document are read "
         "again. By the key of the stamp (alphabetical), or by the order of "
         "the parameters in the spec.", choices=("stamp_key", "spec_order"),
         where="topup.py (in_order)",
         steps=("movable",),
         title="Order of rereading"),
    rule("reread_refused_becomes_refusal", "flow", "Reading again", "choice",
         "What happens to a row that no longer passes the checks after one "
         "of its coordinates was read again. As a refusal: the row becomes "
         "a refusal with its reason, so the graph does not keep the reading "
         "the new one was asked to check. Keep the old: the row stays as it "
         "was and the coordinate counts as not settled.",
         choices=("refusal", "keep_old"), where="topup.py (sweep_decide)",
         steps=("better",),
         title="A row that fails after rereading"),
    rule("parameter_pass_blocks_on_derivation", "flow", "Reading again",
         "switch",
         "On: a document stays stale as a whole when a parameter added to "
         "the spec changes which parameter a stored row was assigned to, "
         "because those rows were decided under another assignment. Off: "
         "the new parameter is appended anyway.",
         where="topup_parameter.py (classify)",
         steps=("classify",),
         title="New field that moves stored rows"),
    rule("parameter_pass_all_or_nothing", "flow", "Reading again", "switch",
         "On: when a new parameter was not read completely (requests were "
         "lost or sources not reached), the pass writes neither the file nor "
         "the stamp and the document counts as failed. Off: what was read "
         "is appended and the stamp vouches for it.",
         where="passboxes.py (box_read_parameters, box_unread)",
         steps=("read_parameters", "unread"),
         title="New field: all or nothing"),
    rule("append_drop_repeats", "flow", "Reading again", "switch",
         "On: a row that equals a stored row in everything but where it was "
         "read and by whom is not appended again, in the passes that append "
         "a new parameter and the rest of the document. Off: it is appended.",
         where="topup_parameter.py (drop_stored_repeats)",
         steps=("replace",),
         title="Do not append repeated rows"),
    rule("rest_once_per_document", "flow", "Reading again", "switch",
         "On: a document the pass for the rest of a document has read to its "
         "end, as its stamp says, is never read by that pass again. Off: it "
         "is read again each time.", where="topup_rest.py (read_to_end)",
         steps=("unread",),
         title="Rest of a document only once"),
    rule("rest_without_trace", "flow", "Reading again", "choice",
         "What the pass for the rest of a document does with a document "
         "whose passages read earlier cannot be told, because it has neither "
         "a record nor a survey. Skip: it is skipped and counted. Read all: "
         "the whole document is read.", choices=("skip", "read_all"),
         where="passboxes.py (box_unread), topup_rest.py",
         steps=("unread",),
         title="Rest without a record"),
    rule("survey_fallback_order", "flow", "Reading again", "choice",
         "The order in which a pass over a stored harvest reads the "
         "passages of a field when no ranking of them was kept: in the "
         "order of the document, or the reverse.",
         choices=("document_order", "reverse_document_order"),
         where="survey.py (Found.passages_of)",
         title="Order without a kept ranking"),
    # -- flow: mapping the classes again --
    rule("remap_unlisted", "flow", "Mapping again", "choice",
         "What happens to a coordinate whose wording is in no list, neither "
         "the old nor the new. The class the model chose stays, or the "
         "class is emptied. Emptying loses a reading the spec did not "
         "foresee.", choices=("keep_model_class", "empty"),
         where="remap.py (remap_row)",
         steps=("remap",),
         title="Wording that is in no list"),
    rule("remap_overwrite_class", "flow", "Mapping again", "switch",
         "On: a class that is already there is replaced by the class the "
         "new list gives for the wording, a required axis included. Off: a "
         "class that is there stays and the coordinate counts as not "
         "settled.", where="remap.py (remap_row)",
         steps=("remap",),
         title="Replace an existing class"),
    rule("remap_refusals_block_stamp", "flow", "Mapping again", "switch",
         "On: a refusal that a grown list could turn into a row keeps the "
         "stamp of its axis as it was, so that the next run reads the "
         "document again; a refusal that cannot be attributed to an axis "
         "keeps all of them. Off: refusals never hold a stamp back.",
         where="remap.py (refused_spaces)",
         steps=("remap",),
         title="Keep the stamp for fixable refusals"),
    # -- flow: checking the quotes of a stored harvest --
    rule("recheck_clear_stamps", "flow", "Checking the quotes", "switch",
         "On: after the quotes of a harvest are checked again, its stamps "
         "are deleted (a copy is kept), so that the next run reads the "
         "documents again; a harvest rewritten by a rule it never saw is not "
         "the output its stamp names. Off: the stamps stay. The call switch "
         "that keeps the stamps sets this for one run.",
         where="passboxes.py (box_clear_stamps)",
         steps=("clear_stamps",),
         title="Delete stamps after rechecking quotes"),
    rule("recheck_keeps_derived", "flow", "Checking the quotes", "switch",
         "On: a coordinate the spec decided is not held to the rule that "
         "the answer stands in its quote, because no passage was ever "
         "claimed to carry it. Off: it is held to the rule like the others.",
         where="recheck.py (recheck_row)",
         steps=("recheck",),
         title="Exempt decided dimensions from check"),
    rule("recheck_drop_without_quote", "flow", "Checking the quotes", "switch",
         "On: a coordinate with no stored quote is dropped, because it was "
         "never checked and is no evidence. Off: it stays as it is.",
         decided="2026-09-13", where="recheck.py (recheck_row)",
         steps=("recheck",),
         title="Drop answers without a quote"),
    rule("recheck_dropped_state", "flow", "Checking the quotes", "choice",
         "The state a dropped coordinate falls to. Its value, wording and "
         "quote go with it. Unanswered: the request came back without it. "
         "Unbacked: it was answered and the passage does not carry it. "
         "Exhausted: the budget ended before it was settled.",
         choices=("unanswered", "unbacked", "exhausted"),
         where="recheck.py (recheck_row)",
         steps=("recheck",),
         title="State of a dropped answer"),
    # -- flow: the check of the filled nodes --
    rule("value_bounds", "flow", "Check of the nodes", "table",
         "The most a value of a field may be in the field's own unit, as the "
         "ontology defines the field, such as a share, which is a part of a "
         "whole and so at most 100 %. A value above it is read a second "
         "time and marked (condition:over_bound); nothing is taken away for "
         "it. Each row names a field by its address in the spec and the "
         "most. Empty: no bound is checked.",
         columns=("parameter", "at_most"), empty=True, decided="2026-11-17",
         steps=("check_value",),
         where="engine.py (Engine.conditions, check_row)",
         title="Upper limits of values per field"),
    rule("part_of_whole", "flow", "Check of the nodes", "map",
         "The entry of a dimension that names the whole its other entries "
         "are parts of, such as the total over all energy carriers. A part "
         "greater than its whole among the values of the document read so "
         "far, all other entries of the field the same, is read a second "
         "time and marked (condition:part_over_whole); nothing is taken away "
         "for it. Compared in the field's own unit. Empty: no part is "
         "compared with its whole.",
         empty=True, decided="2026-11-17", steps=("check_value",),
         where="engine.py (Engine.conditions, check_row)",
         title="Entry that names the whole"),
    # -- flow: the second reading --
    rule("review_axis_reasons", "flow", "Second reading", "texts",
         "The reasons in the trust of a row that name a coordinate. The "
         "second reading asks the value of a row and, besides it, each "
         "coordinate that one of these reasons names.", empty=True,
         where="review.py (disputed)",
         steps=("review",),
         title="Reasons that name a dimension"),
    rule("review_compare_places", "flow", "Second reading", "whole",
         "To how many decimal places a second number is rounded, after it "
         "is converted into the unit of the spec, before it is compared "
         "with the first. A smaller number tolerates larger rounding "
         "differences.", least=0, where="review.py (_value_agrees)",
         steps=("review",),
         title="Decimal places when comparing"),
    rule("review_once_per_row", "flow", "Second reading", "switch",
         "On: a row that already carries the mark of a second reading is "
         "not asked again, because the second answer would answer the same "
         "question. Off: it is asked again.",
         where="review.py (rows_to_review)",
         steps=("review",),
         title="Second reading once per row"),
    rule("review_fields_when_no_axis", "flow", "Second reading", "choice",
         "Which fields of a row the second reading asks when the reasons of "
         "the row name no coordinate. Only the value, or all of the "
         "fields.", choices=("value_only", "all_fields"),
         where="review.py (review_fields)",
         steps=("review",),
         title="Fields asked without a dimension"),
    rule("review_limit", "flow", "Second reading", "whole",
         "After how many values read again the second reading over all "
         "documents stops. 0 reads them all. The call switch that limits "
         "the review sets this for one run.", least=0,
         where="passboxes.py (box_review)",
         steps=("review",),
         title="Most values read a second time"),
    rule("review_shown_passages", "flow", "Second reading", "choice",
         "Which passages the second reading shows for a row: its own "
         "passage and the section above it, or its own passage alone. Both "
         "are a true part of what the first reading was shown, which makes "
         "the second reading a check of the first and no independent one.",
         choices=("own_and_section", "own_only"),
         where="runner.py (make_review_sources), review.py",
         steps=("review",),
         title="Chunks shown in the second reading"),
)
