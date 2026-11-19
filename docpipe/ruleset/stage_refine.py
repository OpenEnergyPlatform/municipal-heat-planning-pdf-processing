"""
stage_refine.py: the rules of stage 4 (refinement), the decisions the stage
used to hold as fixed values in its code (owner request 2026-11-19, A1:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard"). Their
values stand in the default profile's rules.json; a profile that decides
otherwise says so in its own. The stage reads each where it decides, when it
runs (`rules.get`), so that a changed value is the next run's.

Author: Felix Vossel
"""
from .kit import rule

# The group of these rules on the tab "stages".
GROUP = "Stage 4: refinement"

# What every rule says last: a stored result is not redone by a change.
_AGAIN = (" A refined document is not redone by a change: it takes effect "
          "where stage 4 runs again over a document.")


def _r(name: str, kind: str, help: str, **more):
    return rule(name, "stages", GROUP, kind, help, **more)


RULES: tuple = (
    # -- the requests --
    _r("refine_max_attempts", "whole",
       "How many times a request of stage 4 (a window of sections, or the "
       "placing of cuts in a long section) is sent in all, the first time "
       "included, when the server fails or the reply is not the one object "
       "asked for. The sentence a table or figure gets in stage 6 is asked "
       "the same number of times. After the last attempt a window keeps its "
       "original text. A larger value gives the model more tries and costs "
       "more time on a bad window. A request the server refuses (4xx) is "
       "never repeated." + _AGAIN,
       least=1, most=20, where="refine.py (_call_llm, _make_splitter, "
       "_backoff), chunking/context.py (make_ask)",
       title="Attempts per refinement request"),
    _r("refine_window_sections", "whole",
       "How many sections are sent to the chat model in one request. A "
       "larger value gives the model more context to decide merges and "
       "removals and makes each request longer; a smaller one makes more, "
       "shorter requests. The served window must hold this many sections of "
       "the longest allowed size, which the check before a run counts. An "
       "unfinished run is only continued with the same value."
       + _AGAIN,
       least=1, most=20, env="REFINE_WINDOW_SIZE",
       where="refine.py (refine_sections), estimate.py, config.py "
       "(max_request_tokens)",
       title="Sections per refinement request"),
    _r("refine_return_corrections", "switch",
       "On: the model returns find-and-replace corrections that are checked "
       "against the original and applied, which saves reply tokens; the "
       "prompt of corrections is used. Off: the model returns every section "
       "whole. Switching marks every stored document stale, since the two "
       "modes use different prompts, so that it is redone with the option "
       "that redoes stale documents.",
       env="REFINE_RETURN_CORRECTIONS", env_flag=(False, True),
       where="refine.py (_call_llm), config.py, estimate.py",
       title="Model returns changes only"),
    _r("corrections_max_shrink", "number",
       "The largest share of a section that the corrections of the model "
       "may remove together. If they remove more, the model is doing "
       "something else than asked and the section is kept as it was. A "
       "larger value lets the model remove more text." + _AGAIN,
       least=0, most=1, where="corrections.py (apply_corrections)",
       title="Most text corrections may remove"),
    # -- the room of a request --
    _r("tokens_per_word", "number",
       "How many tokens one word is counted as when the size of a request "
       "or of its reply is estimated: for the room of the reply of a window "
       "request, the check of the served window before a run, and the "
       "estimate of a run. An over-estimate costs a little cache; an "
       "under-estimate cuts off replies. Takes effect with the next run.",
       least=0.5, most=10, where="config.py (reply_tokens, "
       "max_request_tokens), estimate.py",
       title="Tokens per word"),
    _r("reply_headroom", "number",
       "The factor by which the reply of a refined window is expected to "
       "exceed its input, since a refined sentence is rarely shorter. It "
       "sets the room of the reply of a window request. A smaller value "
       "cuts off more replies in the middle of a text; a larger one asks "
       "the server for more room. Takes effect with the next run.",
       least=1, most=5, where="config.py (reply_tokens), estimate.py",
       title="Reply room factor"),
    _r("reply_tokens_ceiling", "whole",
       "The most tokens a reply of a window request may be given, so that "
       "one runaway window cannot demand a context nobody has. The check "
       "before a run counts the server's window against it. Takes effect "
       "with the next run.",
       least=512, most=262144, env="REFINE_REPLY_CEILING",
       where="config.py (reply_tokens, largest_reply_tokens)",
       title="Largest reply room"),
    _r("refine_default_max_tokens", "whole",
       "The reply room of a request of stage 4 when the header of its "
       "prompt gives none. It is also the floor of the room of a window "
       "request. Takes effect with the next run.",
       least=256, most=262144, where="config.py (llm_max_tokens)",
       title="Default reply room"),
    _r("refine_default_temperature", "number",
       "The sampling temperature of a request of stage 4 when the header of "
       "its prompt gives none. A low value keeps the model close to the "
       "text. Takes effect with the next run.",
       least=0, most=2, where="config.py (llm_temperature)",
       title="Default temperature of refinement"),
    _r("split_default_max_tokens", "whole",
       "The reply room of the request that places cuts in a long section, "
       "when the header of its prompt gives none. Takes effect with the "
       "next run.",
       least=64, most=65536, where="split.py (split_max_tokens)",
       title="Default reply room of cutting"),
    _r("split_default_temperature", "number",
       "The sampling temperature of the request that places cuts in a long "
       "section, when the header of its prompt gives none. Takes effect "
       "with the next run.",
       least=0, most=2, where="split.py (split_temperature)",
       title="Default temperature of cutting"),
    # -- long sections --
    _r("split_long_sections", "switch",
       "On: a section longer than the longest allowed is cut into parts of "
       "about the target length, at readable boundaries, before the model "
       "reads it, and again after its merges. Off: sections are left as "
       "they are, and the embedding may drop the tail of a long one."
       + _AGAIN,
       where="refine.py (_hold_to_limit), split.py (split_oversized)",
       title="Cut long sections"),
    _r("section_max_words", "whole",
       "The most words a section may have after stage 4. A longer one is "
       "cut into parts; short sections are left alone, since a short piece "
       "is precise and a long one blurs. A larger value keeps more context "
       "together and makes bigger requests and vectors." + _AGAIN,
       least=100, most=20000, where="split.py (needs_split, cut_to_limit, "
       "split_oversized), refine.py (_hold_to_limit), config.py",
       title="Longest section"),
    _r("section_target_words", "whole",
       "The length in words a part of a cut section aims at. It is capped "
       "at half the longest allowed section. The request that places cuts "
       "names it to the model. A smaller value makes more, shorter parts."
       + _AGAIN,
       least=50, most=10000, where="split.py (_ask_range, _even_cuts, "
       "_enforce_max, cut_to_limit)",
       title="Target length of a part"),
    _r("split_min_part_words", "whole",
       "The fewest words a part of a cut section may have; a cut that "
       "would leave a shorter part is dropped, and a last part below it "
       "joins the one before where both fit. A larger value makes fewer "
       "parts." + _AGAIN,
       least=1, most=1000, where="split.py (_sanitize, _group)",
       title="Shortest part"),
    # -- headings --
    _r("clean_titles", "switch",
       "On: leading numbers of a heading are stripped after the model's "
       "pass and headings in capitals are written in normal case. Off: "
       "headings stay as the model returns them." + _AGAIN,
       where="refine.py (refine_sections, _normalize_title)",
       title="Clean headings"),
    _r("title_number_patterns", "texts",
       "Patterns, each tried at the start of a heading, that count as the "
       "number of a heading and are cut off together with the blank after "
       "it, again and again where numbers stand one behind the other. A "
       "four-digit year is not a number. A pattern that matches too much "
       "cuts real words; an empty list strips nothing. Only used where "
       "headings are cleaned." + _AGAIN,
       empty=True, where="refine.py (_normalize_title)",
       title="Patterns of heading numbers"),
    _r("title_shout_min_letters", "whole",
       "How many letters a heading in capitals must have for it to be "
       "written in normal case. Shorter ones are probably abbreviations "
       "and stay as they are. Only used where headings are cleaned."
       + _AGAIN,
       least=1, most=50, where="refine.py (_normalize_title)",
       title="Letters of a shouted heading"),
    _r("title_acronym_max_letters", "whole",
       "The most letters a word in capitals may have to be kept in "
       "capitals when a heading in capitals is written in normal case; a "
       "longer one is written in normal case. Only used where headings are "
       "cleaned." + _AGAIN,
       least=1, most=20, where="refine.py (_normalize_title)",
       title="Longest abbreviation"),
    # -- what the model may drop --
    _r("keep_sections_with_media", "switch",
       "On: the model may not remove a section that carries a table or a "
       "figure, because those have their own transcriptions. Off: the "
       "removal of the model stands, and the tables and figures go with "
       "it." + _AGAIN,
       where="refine.py (_apply_actions)",
       title="Keep sections with tables or figures"),
    _r("keep_opening_section", "switch",
       "On: the text before the first heading of the document is never "
       "removed, because the title may stand in it. Off: the model may "
       "remove it as a running head." + _AGAIN,
       where="refine.py (_apply_actions)",
       title="Keep text before the first heading"),
    _r("keep_front_matter", "switch",
       "On: sections that start on the first page or on the title page "
       "(title, authors, affiliations, journal line, dates) are never "
       "removed. Off: they can be removed like others." + _AGAIN,
       where="refine.py (_apply_actions)",
       title="Keep front matter"),
    _r("drop_cover_pages", "switch",
       "On: a section the model marks as a page that the publisher, a "
       "repository or the download put in front of the publication is "
       "dropped whole, with its heading and pictures, on the first page "
       "too. Off: the mark is ignored and the section stays." + _AGAIN,
       where="refine.py (_apply_actions)",
       title="Drop cover pages"),
    _r("fold_bare_headings", "switch",
       "On: a section that is a heading and nothing else is not dropped; "
       "its heading goes in front of the next section's text, so that a "
       "title set apart from the authors is not lost. Off: it is dropped "
       "as empty." + _AGAIN,
       where="refine.py (_fold_bare_headings)",
       title="Fold bare headings"),
)
