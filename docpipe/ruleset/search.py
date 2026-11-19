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
         where="inference/rerank.py",
         title="Address of the reranker server"),
    rule("rerank_api_key", "flow", "Search", "text",
         "The key the reranker's server expects. Set at the start only and "
         "never shown. Empty: a placeholder is sent.",
         env="RERANK_API_KEY", empty=True, secret=True, machine=True,
         where="inference/rerank.py",
         title="Key of the reranker server"),
    rule("rerank_model", "flow", "Search", "text",
         "The name under which the reranker's server offers the model that "
         "puts the passages in order. Empty: the model the machine serves. "
         "A step may name another model among those the run knows, and its "
         "passages are then scored again by that model.",
         env="RERANK_MODEL", empty=True, machine=True, steps=SEARCHING,
         where="inference/rerank.py",
         title="Name of the reranker model"),
    rule("rerank_pool", "flow", "Search", "whole",
         "How many of the best passages of each kind (section, table, "
         "figure) of the vector search the reranker is given, besides those "
         "it draws at random from the places after them (rerank_drawn). The "
         "rest follow in the order of the vector search, so a walk down the "
         "list still reaches every passage. A larger number reorders more "
         "and costs more requests to the reranker.",
         least=1, env="RERANK_POOL", decided="2026-11-13",
         steps=SEARCHING, where="inference/rerank.py (pool_of)",
         title="Best chunks given to the reranker"),
    rule("rerank_drawn", "flow", "Search", "whole",
         "How many passages of each kind the reranker is given besides the "
         "best ones (rerank_pool), drawn at random from the places after "
         "them up to rerank_drawn_from. The draw is the same for the same "
         "document and search sentences, a new sentence draws anew. Where "
         "fewer places are left, all of them are given. 0: only the best.",
         least=0, env="RERANK_DRAWN", decided="2026-11-13",
         steps=SEARCHING, where="inference/rerank.py (pool_of)",
         title="Random chunks given to the reranker"),
    rule("rerank_drawn_from", "flow", "Search", "whole",
         "The last place of the vector search, within each kind, that the "
         "passages of rerank_drawn are drawn from.",
         least=0, env="RERANK_DRAWN_FROM", decided="2026-11-13",
         steps=SEARCHING, where="inference/rerank.py (pool_of)",
         title="Last place chunks are drawn from"),
    rule("rerank_pool_by_kind", "flow", "Search", "map",
         "The number of passages of one kind the reranker is given, where it "
         "differs from the number for all kinds: its kind (section, table or "
         "figure) -> the number. 0 leaves that kind in the order of the "
         "vector search. Empty: every kind has the number above.",
         of="whole", empty=True, steps=SEARCHING,
         where="inference/rerank.py (pool_size)",
         title="Reranker chunks by kind"),
    rule("rerank_chunk_pool", "flow", "Search", "whole",
         "How many passages of each kind the reranker of the pieces of a "
         "document scores. The standard is so large that every piece is "
         "scored: it puts the pieces of a field in an order of its own and "
         "is not the search above, which keeps only the best.",
         least=1, steps=SEARCHING, where="inference/rerank.py (pool_of)",
         title="Chunks scored for a document"),
    rule("embed_timeout_s", "flow", "Asking again and giving up", "number",
         "The seconds one request to the embedding server waits for its "
         "answer, the sentences of a search as well as the passages of the "
         "index. A larger number waits longer for a busy server before the "
         "request fails and is asked again.",
         least=1, steps=SEARCHING, where="embedding/api.py (ApiEmbedder)",
         title="Time limit of an embedding request"),
    rule("rerank_with_images", "flow", "Search", "switch",
         "On: the reranker is given the picture of a figure together with its "
         "text, where the run attaches figures at all. Off: it reads only "
         "the text of a figure.",
         steps=SEARCHING,
         where="inference/rerank.py (scores), runner.py "
               "(make_search_reranker)",
         title="Give the reranker the pictures"),
    rule("sentence_fusion", "flow", "Search", "choice",
         "How the scores one passage gets for several search sentences "
         "become one score, in the vector search and in the reranker. Max: "
         "the best of them, because a passage is relevant when one question "
         "matches it well, and adding a sentence can only move a passage up. "
         "Mean: their mean, which buries a good match among sentences that "
         "have nothing to do with it. Sum: their sum, which favours passages "
         "that match many sentences a little.",
         choices=("max", "mean", "sum"), steps=SEARCHING,
         where="inference/rerank.py (fused), inference/faiss_store.py",
         title="Combining the scores of several sentences"),
    rule("sentence_top", "flow", "Search", "whole",
         "A passage is a hit of the vector search only when it is among the "
         "best passages of at least one search sentence; this is how many. "
         "0: no limit, every passage can be a hit. A smaller number keeps "
         "out passages that no sentence ranks high.",
         least=0, steps=SEARCHING, where="inference/faiss_store.py "
         "(fuse_prepared)",
         title="Best places per sentence that count"),
    rule("search_full_ranking", "flow", "Search", "switch",
         "On: the vector search ranks every passage of the document for "
         "every sentence, so a later sentence can reach past everything the "
         "earlier ones took. Off: only the best passages of each sentence "
         "are kept, as many as the search asks for; a search that asks for "
         "all of them keeps the whole ranking anyway.",
         steps=SEARCHING, where="inference/faiss_store.py (fuse_prepared)",
         title="Rank every chunk for every sentence"),
    rule("search_kinds", "flow", "Search", "texts",
         "The kinds of passage a search looks at: sections, tables and "
         "figures. Remove a kind to leave it out of every search.",
         choices=("section", "table", "figure"), decided="2026-11-08",
         steps=SEARCHING, where="inference/faiss_store.py (fuse_prepared)",
         title="Kinds of chunk searched"),
    rule("search_with", "flow", "Search", "choice",
         "What a search of a dimension goes with. Phrase: a sentence the "
         "model writes as the document would print the answer, in a request "
         "of its own, which is the standard. Question: the dimension's own "
         "question, with no request for a sentence. Name: the dimension's "
         "name, with no request.",
         choices=("phrase", "question", "name"),
         decided="2026-11-08, 2026-11-09", steps=("phrase",),
         where="targets.py (search_sentence)",
         title="What a dimension search goes with"),
    rule("rerank_when", "flow", "Search", "choice",
         "When the reranker orders the chunks of a search for a dimension. "
         "Once: when the search starts, with the search sentence, which is "
         "the standard. Each round: also before every further request, "
         "over the chunks left, with the sentence of that round, which "
         "costs one request to the reranker for each.", choices=("once", "each_round"),
         decided="2026-11-09", steps=("search",),
         where="engine.py (SearchSupply)",
         title="When the reranker orders"),
    rule("show_twice", "flow", "Search", "switch",
         "Off: no chunk is shown twice to one dimension. On: a chunk shown "
         "before may be shown a second time, where it stands beside the "
         "value, where the model fetches it or where the order reaches it, "
         "and never a third time.",
         decided="2026-11-09", steps=("search", "round", "if"),
         where="engine.py (SearchSupply), targets.py (over_hits)",
         title="Show a chunk twice"),
    rule("fetched_count", "flow", "Search", "switch",
         "Off: chunks that the model fetched itself do not count against "
         "the most chunks a search shows, so a search may show more. On: "
         "they count, and the search ends once the fetched and the ordered "
         "chunks together reach that number.",
         decided="2026-11-09", steps=("search",),
         where="engine.py (SearchSupply)",
         title="Fetched chunks count toward the limit"),
    rule("conversation", "flow", "Asking again and giving up", "choice",
         "How the questions about the dimensions of one value are asked. "
         "None: each is a request of its own that shows the value and the "
         "question, which is the standard. Per value: the questions about "
         "one value go as one conversation, so that each shows the earlier "
         "questions about that value and how they were answered, a "
         "follow-up after the answer it follows, and the room for the "
         "answer counts all of it. Set it at the frame of the dimensions.",
         choices=("none", "per_value"), decided="2026-11-08, 2026-11-09",
         steps=("each coordinate", "coord", "search", "work_coordinate"),
         where="addressed.py (_ask, _follow)",
         title="How a value's questions are asked"),
    rule("answer_with", "flow", "Asking again and giving up", "choice",
         "What an answer names a line of the document with. Address: the "
         "number of the line, which the request shows, which is the "
         "standard. Quote: the words of the line; the code finds the line "
         "among the lines shown, characters counted as the same by "
         "`same_characters` compared as the same, and an answer whose words "
         "stand in no shown line is refused as not in the source.", choices=("address", "quote"),
         decided="2026-11-08, 2026-11-09",
         steps=("docfield", "find", "coord", "search", "work_coordinate",
                "works", "last_year", "quantity", "about"),
         where="addressed.py (resolve, the reply formats)",
         title="What an answer names lines with"),
    rule("reply_order", "flow", "Asking again and giving up", "choice",
         "In which order an answer writes its keys, which the form of the "
         "answer enforces. address_first: the line before its words, which "
         "is the standard. words_first: the words of the value first, then "
         "the line that prints them. The example a prompt shows follows the "
         "same order. The keys and the checks stay the same; the order can "
         "change what the model writes and is a setting to be measured.",
         choices=("address_first", "words_first"), decided="2026-11-17",
         steps=("docfield", "find", "coord", "search", "work_coordinate",
                "works", "last_year", "quantity", "about"),
         where="addressed.py (in_reply_order), runner.py (system_text)",
         title="Order of answer parts"),
    rule("example_place", "flow", "Asking again and giving up", "choice",
         "Where a request shows the example of its reply. prompt: in the "
         "system prompt, which is the standard; the example carries the "
         "request's own address, so two requests of a kind differ from that "
         "point on and the server's prefix cache serves only the part "
         "before it. message: the system prompt keeps its words and names "
         "the keys \"example\" and \"nothing\" instead, and the example "
         "stands under those keys at the end of the message; the whole "
         "system prompt is then the same for every request of a kind and "
         "step, and the server's prefix cache serves all of it. What "
         "changes: the example moves into the message; the keys and the "
         "checks stay the same.",
         choices=("prompt", "message"), decided="2026-11-17",
         steps=("docfield", "find", "coord", "search", "work_coordinate",
                "works", "last_year", "quantity", "about"),
         where="runner.py (system_text, example_keys, ask_in_grammar)",
         title="Where the example reply is shown"),
    rule("find_again_below", "flow", "Asking again and giving up", "whole",
         "A field the find step read piece by piece in a document is read "
         "a second time over the same pieces where the first pass found at "
         "least one value and fewer than this many; the finds of both "
         "passes are united, each backed by its own quote, and a value "
         "found twice at the same place counts once. A field that found "
         "nothing is not read again, the document most likely does not "
         "carry it. It costs about one more pass of find requests for each "
         "such field. 0: no second pass.", least=0,
         decided="2026-11-17", steps=("each piece",),
         where="engine.py (Engine.find_again)",
         title="Second pass after few finds"),
    rule("find_again_way", "flow", "Asking again and giving up", "choice",
         "How the second pass of a field's find step (`find_again_below`) "
         "asks. Generous (standard, the strict and the generous wording "
         "of RAME 2026): with a second wording of the prompt that asks for "
         "every value of the field the shown lines print, also where it is "
         "unsure; each value it names is checked like any other. Same: "
         "with the words of the first pass; the request is sent again and, "
         "at a temperature of 0, mostly answers the same. The first pass "
         "always asks in the standard way.",
         choices=("same", "generous"), decided="2026-11-17",
         steps=("find",), where="engine.py (Engine.find_again), "
                                "prompts find (way: find_again_way)",
         title="How the second pass asks"),
    rule("ask_untaken", "flow", "Asking again and giving up", "switch",
         "On: after the find steps of a document, each number of a table or "
         "figure that no field's question took (a cell of a table's row, or "
         "a number of a figure's line of numbers, other than a year) is "
         "asked which field of the list that reads numbers it is, or none; "
         "where a field is named, the number becomes a find of that field at "
         "that address and goes through the same coordinates and checks as "
         "every value. It costs one request for each such number, so a "
         "document with many cost and area tables has many; a profile "
         "without the prompt `assign` asks nothing. Off: nothing is asked, "
         "the numbers no question took stay unread.",
         decided="2026-11-17", steps=("assign",),
         where="targets.py (assigned), general.py (raw: untaken)",
         title="Ask about numbers no field took"),
    rule("unit_searched", "flow", "Search", "switch",
         "Off: a unit that the value's own place does not settle is not "
         "searched; it is asked at the value's place only, as the spec's "
         "groups say. On: an open unit is searched like an open "
         "dimension, over the chunks of the document.", decided="2026-09-16",
         steps=("each coordinate", "round", "if"),
         where="engine.py (facts, own_only)",
         title="Search for a unit"),
    # -- flow: calculating ----------------------------------------------------
    rule("code_timeout_s", "flow", "Calculation", "number",
         "The seconds the run waits for one calculation of the sandbox. A "
         "larger number lets longer calculations finish; a smaller number "
         "gives up on a slow one sooner.",
         least=1, env="CODE_EXEC_TIMEOUT", decided="2026-11-03",
         steps=("compute",), where="inference/code_exec.py",
         title="Time limit of one calculation"),
    rule("code_resend", "flow", "Calculation", "whole",
         "How often a calculation is sent to the sandbox again when the "
         "sandbox failed (no answer, an error of the service), never when "
         "the code failed. 0: never. Where the sandbox still fails, the "
         "model is not told, the question ends without a row "
         "(sandbox_failed) and the log says so.",
         least=0, steps=("compute",), where="inference/code_exec.py",
         title="Resends after a sandbox failure"),
    # -- flow: marking in the PDF ---------------------------------------------
    rule("locate_min_score", "flow", "Locating in the PDF", "number",
         "How closely a quote has to match the words of a page of the PDF "
         "for its place to count as found, from 0 to 100. A higher number "
         "marks fewer places and fewer wrong ones; a lower number marks "
         "places a quote only half matches.",
         least=0, most=100, steps=("write",),
         where="inference/pdf_locate.py",
         title="Least match for a found place"),
    rule("locate_max_lines", "flow", "Locating in the PDF", "whole",
         "How many line rectangles a found place gets at most. A quote that "
         "runs over more lines is marked on the first of them only.",
         least=1, steps=("write",), where="inference/pdf_locate.py",
         title="Most marked lines per place"),
    rule("locate_match", "flow", "Locating in the PDF", "choice",
         "How a quote is searched among the words of a page. Partial ratio: "
         "the stretch of the page that matches the quote best, allowing for "
         "ligatures, hyphenation and running heads that the extraction "
         "changed.",
         choices=("partial_ratio",), steps=("write",),
         where="inference/pdf_locate.py",
         title="How quotes are matched"),
)
