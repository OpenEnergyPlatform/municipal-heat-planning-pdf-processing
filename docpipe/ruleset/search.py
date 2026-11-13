"""
search.py: The search, the reranker, the calculation and marking in the PDF
(inference/, faiss_store.py, code_exec) and the providers' temperature.
"""
from .kit import ASKING, rule

# The steps that search: the search itself, the supply of chunks in the
# order the flow sets, and a field of the whole document.
SEARCHING = ("order", "search", "docfield")

RULES: tuple = (
    # -- flow: the model's temperature ---------------------------------
    # -- flow: the search -----------------------------------------------------
    rule("rerank_base_url", "flow", "Search", "text",
         "The address of the server whose reranker puts the passages of a "
         "search in order. Empty: the passages stay in the order of the "
         "vector search. A value of the machine: it is set at the start or in "
         "the project file, never in a file of the profile.",
         env="RERANK_BASE_URL", empty=True, machine=True,
         where="inference/rerank.py"),
    rule("rerank_api_key", "flow", "Search", "text",
         "The key the reranker's server expects. Set at the start only and "
         "never shown. Empty: a placeholder is sent.",
         env="RERANK_API_KEY", empty=True, secret=True, machine=True,
         where="inference/rerank.py"),
    rule("rerank_model", "flow", "Search", "text",
         "The name under which the reranker's server offers the model that "
         "puts the passages in order. Empty: the model the machine serves. "
         "A step may name another model among those the run knows, and its "
         "passages are then scored again by that model.",
         env="RERANK_MODEL", empty=True, machine=True, steps=SEARCHING,
         where="inference/rerank.py"),
    rule("rerank_pool", "flow", "Search", "whole",
         "How many passages of each kind (section, table, figure) the "
         "reranker is given: the best ones of the vector search. The rest "
         "follow in the order of the vector search, so a walk down the list "
         "still reaches every passage. A larger number reorders more and "
         "costs more requests to the reranker. Decided on 2026-11-09.",
         least=1, env="RERANK_POOL", decided="2026-11-09",
         steps=SEARCHING, where="inference/rerank.py (pool_of)"),
    rule("rerank_pool_by_kind", "flow", "Search", "map",
         "The number of passages of one kind the reranker is given, where it "
         "differs from the number for all kinds: its kind (section, table or "
         "figure) -> the number. 0 leaves that kind in the order of the "
         "vector search. Empty: every kind has the number above.",
         of="whole", empty=True, steps=SEARCHING,
         where="inference/rerank.py (pool_size)"),
    rule("rerank_chunk_pool", "flow", "Search", "whole",
         "How many passages of each kind the reranker of the pieces of a "
         "plan scores. The standard is so large that every piece is scored: "
         "it puts the pieces of a field in an order of its own and is not "
         "the search above, which keeps only the best.",
         least=1, steps=SEARCHING, where="inference/rerank.py (pool_of)"),
    rule("rerank_timeout_s", "flow", "Asking again and giving up", "number",
         "The seconds one request to the reranker waits for its answer. A "
         "larger number waits longer for a busy server before the request "
         "fails and is asked again.",
         least=1, steps=SEARCHING, where="inference/rerank.py (post)"),
    rule("embed_timeout_s", "flow", "Asking again and giving up", "number",
         "The seconds one request to the embedding server waits for its "
         "answer, the sentences of a search as well as the passages of the "
         "index. A larger number waits longer for a busy server before the "
         "request fails and is asked again.",
         least=1, steps=SEARCHING, where="embedding/api.py (ApiEmbedder)"),
    rule("rerank_truncate_tokens", "flow", "Search", "whole",
         "How many tokens of a passage and its sentence the reranker reads. "
         "-1: the model's own length, which the server cuts the pair to; "
         "no length of ours decides what it reads. A smaller number cuts "
         "long passages sooner.",
         least=-1, steps=SEARCHING, where="inference/rerank.py (scores)"),
    rule("rerank_with_images", "flow", "Search", "switch",
         "On: the reranker is given the picture of a figure together with its "
         "text, where the run attaches figures at all. Off: it reads only "
         "the text of a figure.",
         steps=SEARCHING,
         where="inference/rerank.py (scores), runner.py "
               "(make_search_reranker)"),
    rule("sentence_fusion", "flow", "Search", "choice",
         "How the scores one passage gets for several search sentences "
         "become one score, in the vector search and in the reranker. Max: "
         "the best of them, because a passage is relevant when one question "
         "matches it well, and adding a sentence can only move a passage up. "
         "Mean: their mean, which buries a good match among sentences that "
         "have nothing to do with it. Sum: their sum, which favours passages "
         "that match many sentences a little.",
         choices=("max", "mean", "sum"), steps=SEARCHING,
         where="inference/rerank.py (fused), inference/faiss_store.py"),
    rule("sentence_top", "flow", "Search", "whole",
         "A passage is a hit of the vector search only when it is among the "
         "best passages of at least one search sentence; this is how many. "
         "0: no limit, every passage can be a hit. A smaller number keeps "
         "out passages that no sentence ranks high.",
         least=0, steps=SEARCHING, where="inference/faiss_store.py "
         "(fuse_prepared)"),
    rule("search_full_ranking", "flow", "Search", "switch",
         "On: the vector search ranks every passage of the document for "
         "every sentence, so a later sentence can reach past everything the "
         "earlier ones took. Off: only the best passages of each sentence "
         "are kept, as many as the search asks for; a search that asks for "
         "all of them keeps the whole ranking anyway.",
         steps=SEARCHING, where="inference/faiss_store.py (fuse_prepared)"),
    rule("search_kinds", "flow", "Search", "texts",
         "The kinds of passage a search looks at: sections, tables and "
         "figures. Remove a kind to leave it out of every search. Decided "
         "on 2026-11-08 (pieces instead of passages).",
         choices=("section", "table", "figure"), decided="2026-11-08",
         steps=SEARCHING, where="inference/faiss_store.py (fuse_prepared)"),
    rule("search_with", "flow", "Search", "choice",
         "What a search of a dimension goes with. Phrase: a sentence the "
         "model writes as the plan would print the answer, in a request of "
         "its own, which is the standard. Question: the dimension's own "
         "question, with no request for a sentence. Name: the dimension's "
         "name, with no request. Decided on 2026-11-08 and 2026-11-09.",
         choices=("phrase", "question", "name"),
         decided="2026-11-08, 2026-11-09", steps=("phrase",),
         where="targets.py (search_sentence)"),
    rule("rerank_when", "flow", "Search", "choice",
         "When the reranker orders the chunks of a search for a dimension. "
         "Once: when the search starts, with the search sentence, which is "
         "the standard. Each round: also before every further request, "
         "over the chunks left, with the sentence of that round, which "
         "costs one request to the reranker for each. Decided on "
         "2026-11-09.", choices=("once", "each_round"),
         decided="2026-11-09", steps=("search",),
         where="engine.py (SearchSupply)"),
    rule("show_twice", "flow", "Search", "switch",
         "Off: no chunk is shown twice to one dimension. On: a chunk shown "
         "before may be shown a second time, where it stands beside the "
         "value, where the model fetches it or where the order reaches it, "
         "and never a third time. Decided on 2026-11-09.",
         decided="2026-11-09", steps=("search", "round", "if"),
         where="engine.py (SearchSupply), targets.py (over_hits)"),
    rule("fetched_count", "flow", "Search", "switch",
         "Off: chunks that the model fetched itself do not count against "
         "the most chunks a search shows, so a search may show more. On: "
         "they count, and the search ends once the fetched and the ordered "
         "chunks together reach that number. Decided on 2026-11-09.",
         decided="2026-11-09", steps=("search",),
         where="engine.py (SearchSupply)"),
    rule("conversation", "flow", "Asking again and giving up", "choice",
         "How the questions about the dimensions of one value are asked. "
         "None: each is a request of its own that shows the value and the "
         "question, which is the standard. Per value: the questions about "
         "one value go as one conversation, so that each shows the earlier "
         "questions about that value and how they were answered, a "
         "follow-up after the answer it follows, and the room for the "
         "answer counts all of it. Set it at the frame of the dimensions. "
         "Decided on 2026-11-08 and 2026-11-09.",
         choices=("none", "per_value"), decided="2026-11-08, 2026-11-09",
         steps=("each coordinate", "coord", "search", "work_coordinate"),
         where="addressed.py (_ask, _follow)"),
    rule("answer_with", "flow", "Asking again and giving up", "choice",
         "What an answer names a line of the document with. Address: the "
         "number of the line, which the request shows, which is the "
         "standard. Quote: the words of the line; the code finds the line "
         "among the lines shown, characters counted as the same by "
         "`same_characters` compared as the same, and an answer whose words "
         "stand in no shown line is refused as not in the source. Decided "
         "on 2026-11-08 and 2026-11-09.", choices=("address", "quote"),
         decided="2026-11-08, 2026-11-09",
         steps=("docfield", "find", "coord", "search", "work_coordinate",
                "works", "last_year", "quantity", "about"),
         where="addressed.py (resolve, the reply formats)"),
    rule("unit_searched", "flow", "Search", "switch",
         "Off: a unit that the value's own place does not settle is not "
         "searched; it is asked at the value's place only, as the spec's "
         "groups say. On: an open unit is searched like an open "
         "dimension, over the chunks of the document. Decided on "
         "2026-09-16.", decided="2026-09-16",
         steps=("each coordinate", "round", "if"),
         where="engine.py (facts, own_only)"),
    # -- flow: calculating ----------------------------------------------------
    rule("code_timeout_s", "flow", "Calculation", "number",
         "The seconds the run waits for one calculation of the sandbox. A "
         "larger number lets longer calculations finish; a smaller number "
         "gives up on a slow one sooner. Decided on 2026-11-03 (sandbox).",
         least=1, env="CODE_EXEC_TIMEOUT", decided="2026-11-03",
         steps=("compute",), where="inference/code_exec.py"),
    rule("code_resend", "flow", "Calculation", "whole",
         "How often a calculation is sent to the sandbox again when the "
         "sandbox failed (no answer, an error of the service), never when "
         "the code failed. 0: never. Where the sandbox still fails, the "
         "model is not told, the question ends without a row "
         "(sandbox_failed) and the log says so.",
         least=0, steps=("compute",), where="inference/code_exec.py"),
    # -- flow: marking in the PDF ---------------------------------------------
    rule("locate_min_score", "flow", "Locating in the PDF", "number",
         "How closely a quote has to match the words of a page of the PDF "
         "for its place to count as found, from 0 to 100. A higher number "
         "marks fewer places and fewer wrong ones; a lower number marks "
         "places a quote only half matches.",
         least=0, most=100, steps=("write",),
         where="inference/pdf_locate.py"),
    rule("locate_max_lines", "flow", "Locating in the PDF", "whole",
         "How many line rectangles a found place gets at most. A quote that "
         "runs over more lines is marked on the first of them only.",
         least=1, steps=("write",), where="inference/pdf_locate.py"),
    rule("locate_match", "flow", "Locating in the PDF", "choice",
         "How a quote is searched among the words of a page. Partial ratio: "
         "the stretch of the page that matches the quote best, allowing for "
         "ligatures, hyphenation and running heads that the extraction "
         "changed.",
         choices=("partial_ratio",), steps=("write",),
         where="inference/pdf_locate.py"),
)
