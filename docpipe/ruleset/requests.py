"""
requests.py: Asking the model: the request, its model, waiting and retrying,
the lanes of requests side by side (runner.py, throttle.py, scheduler.py,
llm_preflight.py, providers, settings.py).

Every value here stood in the code, or was read once at the start of the run
(owner, 2026-11-11: "alles soll anpassbar sein"). A request reads them where
it is sent, in the step that sends it, so each can have a value of its own at
a step.
"""
from .kit import ASKING, rule

_ASKS = ASKING + ("each value",)
_FLOW = "flow"
_MODEL = "Model and server"
_AGAIN = "Asking again and giving up"
_LOAD = "Load and concurrency"
_DOCS = "Documents"
_WINDOW = "Window and answer room"
_IMAGES = "Images"
_CHECK = "Check before the run"
_REVIEW = "Second reading"
_PDF = "Quote in the PDF"
_CALC = "Calculation"
_SEARCH = "Search"

RULES: tuple = (
    # -- model and server -----------------------------------------------------
    rule("llm_base_url", _FLOW, _MODEL, "text",
         "The address of the model server every request of the run goes "
         "to, such as http://localhost:8000/v1. It belongs to the machine "
         "and is set at the start or in the project file, never in a file "
         "of the repository. Empty: the run asks a server on this machine "
         "at port 8000.",
         empty=True, env="LLM_BASE_URL", machine=True,
         where="runner.py (llm_base_url)"),
    rule("llm_api_key", _FLOW, _MODEL, "text",
         "The key the run identifies itself to the model server with. It is "
         "a secret: it is set at the start only, never written to a file "
         "and never shown. Empty: a placeholder that servers which check no "
         "key accept.",
         empty=True, env="LLM_API_KEY", secret=True, machine=True,
         where="runner.py (llm_api_key)"),
    rule("gemini_api_key", _FLOW, _MODEL, "text",
         "The key the Gemini API is asked with where the run names none for "
         "its role. It is a secret: it is set at the start only, never "
         "written to a file and never shown. Empty: no key from here, and "
         "the next rule is tried.",
         empty=True, env="GEMINI_API_KEY", secret=True, machine=True,
         where="providers/gemini_api.py"),
    rule("google_api_key", _FLOW, _MODEL, "text",
         "The key the Gemini API is asked with where neither the run nor "
         "`gemini_api_key` names one. It is a secret: it is set at the "
         "start only, never written to a file and never shown. Empty: "
         "none, and a request to the Gemini API is refused for want of a "
         "key.",
         empty=True, env="GOOGLE_API_KEY", secret=True, machine=True,
         where="providers/gemini_api.py"),
    rule("gemini_timeout_s", _FLOW, _AGAIN, "number",
         "The seconds a request to the Gemini API waits for its answer "
         "where nothing gave it a time: an answer that never comes must "
         "not hold a thread for good.", least=1, steps=_ASKS,
         where="providers/gemini_api.py"),
    rule("gemini_embed_batch", _FLOW, _MODEL, "whole",
         "How many texts one embedding request to the Gemini API carries. "
         "A larger number needs fewer requests and makes each one larger.",
         least=1, where="providers/gemini_api.py"),
    rule("llm_provider", _FLOW, _MODEL, "choice",
         "Which API answers the requests of the run: a server of your own "
         "that speaks the OpenAI protocol, or the hosted OpenAI, Anthropic "
         "or Gemini API. A hosted API is asked inside a reply schema, waits "
         "when it says it is busy and has no queue to steer by.",
         choices=("openai-compatible", "openai", "anthropic", "gemini"),
         env="LLM_PROVIDER", machine=True,
         where="providers (provider)"),
    rule("model", _FLOW, _MODEL, "text",
         "The name of the model that answers a request, as the server "
         "offers it. Empty: the model the run was started with. A step "
         "that names a model asks that one, and the check before the run "
         "refuses a model the server does not offer. Models that share "
         "seats on one server take the seats of their own name.",
         empty=True, env="LLM_MODEL",
         steps=_ASKS + ("replace", "write"),
         where="runner.py (llm_model, ask_in_grammar)"),
    rule("thinking", _FLOW, _MODEL, "switch",
         "On: the model may think before it answers. Off: it answers at "
         "once, which keeps the reply short and complete, because a thinking "
         "block in front of the JSON can cut it off. A server of your own "
         "reads this switch; a hosted API ignores it.",
         env="LLM_ENABLE_THINKING", env_flag=(False, True), steps=_ASKS,
         where="llm_preflight.py (request_extras)"),
    rule("reasoning_effort", _FLOW, _MODEL, "text",
         "How much the model reasons, as the server names it, such as low, "
         "medium or high. Empty, off or none sends no effort at all. A "
         "server that refuses the effort refuses every request, so the "
         "check before the run asks it once. Both kinds of server read it.",
         empty=True, env="LLM_REASONING_EFFORT", steps=_ASKS,
         where="llm_preflight.py (request_extras)"),
    rule("tool_choice", _FLOW, _MODEL, "text",
         "The tool choice every request sends. none keeps an endpoint that "
         "carries tools of its own from handing a request to them. Empty "
         "or off sends none. A server of your own reads it; a hosted API "
         "ignores it. Decided on 2026-11-08.",
         empty=True, env="LLM_TOOL_CHOICE", decided="2026-11-08",
         steps=_ASKS, where="llm_preflight.py (request_extras)"),
    rule("request_options", _FLOW, _MODEL, "text",
         "A JSON object laid over the body of every request to a hosted "
         "model: what only that API takes. Empty: nothing is added. A "
         "server of your own ignores it.",
         empty=True, env="LLM_REQUEST_OPTIONS", steps=_ASKS,
         where="providers (request_options)"),
    rule("schema_grammar", _FLOW, _MODEL, "choice",
         "Whether the reply schema goes out as the grammar of the reply. "
         "auto: as each kind of request always did, which for the sentence "
         "of a search and the second reading means only on a hosted API. "
         "all: every request that asks for JSON sends it.",
         choices=("auto", "all"), env="LLM_SCHEMA", steps=_ASKS,
         where="providers (enforces_schema)"),
    rule("thinking_room_tokens", _FLOW, _MODEL, "whole",
         "The tokens a hosted model may think in, added to the answer room "
         "of each request. A larger number lets it think longer; too large "
         "a number is refused by some APIs. A server of your own ignores it.",
         least=0, env="LLM_THINKING_ROOM", steps=_ASKS,
         where="providers (adapters)"),
    rule("llm_models", _FLOW, _MODEL, "text",
         "Several model names on one endpoint that share the requests of "
         "the chat, separated by commas. Empty: the one model. It belongs "
         "to the machine.",
         empty=True, env="LLM_MODELS", machine=True,
         where="inference/pool.py"),
    rule("llm_slots_per_model", _FLOW, _MODEL, "whole",
         "How many requests each model of the list takes at once. It "
         "belongs to the machine.", least=1, env="LLM_SLOTS_PER_MODEL",
         machine=True, where="inference/pool.py"),
    rule("chat_look_ahead_s", _FLOW, _LOAD, "number",
         "How often, in seconds, a batch of the chat that is under way "
         "looks whether a place came free for its next request. A smaller "
         "number starts the next request sooner and looks more often.",
         least=0.001, where="inference/pool.py"),
    rule("model_window_tokens", _FLOW, _MODEL, "whole",
         "The tokens of the model server's window that a request is sized "
         "against while the server reports none. A server that reports its "
         "window is believed instead. A larger number lets requests grow; "
         "one the server refuses is lost.", least=1,
         env="EXTRACT_MAX_MODEL_LEN", where="runner.py (model_window)"),
    # -- answer room ----------------------------------------------------------
    rule("prompt_chars_per_token", _FLOW, _WINDOW, "number",
         "How many characters of a prompt count as one token where the "
         "model's own tokenizer does not count. A smaller number counts "
         "prompts larger and keeps requests inside the window; a larger "
         "number risks a request one token too long.", least=0.1,
         steps=_ASKS, where="runner.py (prompt_tokens)"),
    rule("message_overhead_tokens", _FLOW, _WINDOW, "whole",
         "The tokens each message of a request is counted with beyond its "
         "text, where the model's own tokenizer does not count.", least=0,
         steps=_ASKS, where="runner.py (prompt_tokens)"),
    rule("answer_margin_tokens", _FLOW, _WINDOW, "whole",
         "The tokens left free between the estimated request and the "
         "window of the model. A larger number is safer and leaves less "
         "room for the answer.", least=0, steps=_ASKS,
         where="runner.py (answer_room)"),
    rule("image_cache_crops", "prompts", _IMAGES, "whole",
         "How many scaled images stay in memory, so that a picture asked "
         "about for many fields is read from the file and scaled once. "
         "The oldest leave first. 0 keeps none.", least=0,
         steps=_ASKS, where="runner.py (_image_data_url)"),
    rule("image_format", "prompts", _IMAGES, "choice",
         "The format a table or figure image is sent in. png keeps thin "
         "rules and small digits sharp; jpeg is smaller and blurs them.",
         choices=("png", "jpeg"), steps=_ASKS,
         where="runner.py (_image_data_url)"),
    rule("image_token_side_px", "prompts", _IMAGES, "whole",
         "How many pixels of an image's side cost the model one token, "
         "which depends on the model: the size of an image is counted in "
         "squares of this side. It belongs to the machine's model.",
         least=1, steps=_ASKS, where="runner.py (image_tokens)"),
    rule("attach_images", "prompts", _IMAGES, "switch",
         "On: the image of a table or figure goes along with the requests "
         "that read it, so the model sees the picture as well as the text. "
         "Off: the requests carry text only.",
         env="EXTRACT_ATTACH_IMAGES", env_flag=(False, True),
         steps=("transcribe", "order", "search", "review", "each value"),
         where="runner.py (image_path_of)"),
    # -- waiting and asking again ---------------------------------------------
    rule("llm_timeout_s", _FLOW, _AGAIN, "number",
         "The seconds the first attempt of a request waits for its answer. "
         "A larger number gives a slow server more time and holds a thread "
         "longer. A repeated request waits as long as "
         "`repeat_timeout_s` says.", least=1, env="LLM_TIMEOUT",
         steps=_ASKS, where="runner.py (llm_timeout)"),
    rule("refusal_retry_most", _FLOW, _AGAIN, "whole",
         "How many times a request that the server refuses is asked, the "
         "first time included. A request refused to the end leaves its "
         "document unfinished, and a later run reads it again. Decided on "
         "2026-11-09.", least=1, decided="2026-11-09", steps=_ASKS,
         where="runner.py (Failures.failed, persistently)"),
    rule("server_failure_statuses", _FLOW, _AGAIN, "texts",
         "Which answers of the server count as its failure to do the work, "
         "which is asked again after a wait and not given up on: single "
         "statuses such as 429, ranges such as 500-599, and timeout for a "
         "request that got no answer in time. Every other status 400 to "
         "499 is the server refusing the request itself. Decided on "
         "2026-11-09.", decided="2026-11-09", steps=_ASKS,
         where="runner.py (unserved, refused)"),
    rule("server_retry_most", _FLOW, _AGAIN, "whole",
         "How often a request is asked again after the server's failure "
         "(a rate limit, a server error, a timeout, no connection). 0: "
         "without a limit, until the run halts, so that nothing is lost "
         "for a server that comes back. Any other error without a status "
         "is a fault in our own code, asked again as `other_errors_retry` "
         "says. Decided on 2026-11-09 and 2026-11-12.",
         least=0, decided="2026-11-09, 2026-11-12", steps=_ASKS,
         where="runner.py (Failures)"),
    rule("other_errors_retry", _FLOW, _AGAIN, "whole",
         "How often a request is asked again after an error that is neither "
         "the server's failure (no reply, a rate limit, a server error) nor "
         "a refusal: a fault in the code that sent it. 0: it is not asked "
         "again. A request not asked again leaves its document unfinished, "
         "the run goes on, a later run reads it again, and the log names "
         "the fault and where in the code it arose. This holds for a "
         "search, an embedding and a reranking too. Decided on 2026-11-12.",
         least=0, decided="2026-11-12", steps=_ASKS,
         where="runner.py (Failures, persistently)"),
    rule("unserved_unstamped", _FLOW, _AGAIN, "switch",
         "On: a document one of whose requests was never answered gets no "
         "stamp, so a later run reads it again. Off: it is stamped as read "
         "all the same. Decided on 2026-11-09.", decided="2026-11-09",
         steps=("write",), where="runner.py (not_happened)"),
    rule("search_retry_most", _FLOW, _AGAIN, "whole",
         "How often a search, an embedding or a reranking that the server "
         "failed (no reply, a rate limit, a server error) is asked again "
         "before its document fails. 0: without a limit, until it answers, "
         "and the plan's own order never stands in for a failed search. A "
         "fault in our own code is asked again as often as "
         "`other_errors_retry` says. Decided on 2026-11-09 and 2026-11-12.",
         least=0, decided="2026-11-09, 2026-11-12", steps=_ASKS,
         where="runner.py (persistently)"),
    rule("repair_replies", _FLOW, _AGAIN, "texts",
         "Which repairs a reply that is no JSON object gets before it is "
         "asked again: think (a think block is taken off), fences (code "
         "fences are taken off), cut_out (the one object that starts at "
         "the first brace is read out of the text around it), close (the "
         "brackets a reply stopped short of are closed; a reply cut off at "
         "its limit is never closed). Empty: no reply is repaired, and one "
         "that is not exactly the object asked for is asked again with its "
         "fault named. A repaired reply can stand in the harvest saying "
         "read with nothing under it; each one is noted in the request log "
         "with the repairs it went through. Decided on 2026-09-12.",
         choices=("think", "fences", "cut_out", "close"), empty=True,
         decided="2026-09-12", steps=_ASKS, where="runner.py (_loads_object)"),
    rule("cut_off", _FLOW, _AGAIN, "choice",
         "What a reply that was cut off at its limit gives. hole: nothing; "
         "the request is split where its work can be, and where it cannot "
         "it is a hole with its cause. rescue: the complete entries of the "
         "list the reply was cut off in are kept, the cut entry and what "
         "followed it are not, and the request is noted as cut off in the "
         "request log. A reply cut off in anything but a list has nothing "
         "to keep and is a hole. Decided on 2026-09-12.",
         choices=("hole", "rescue"), decided="2026-09-12", steps=_ASKS,
         where="runner.py (_ask_in_grammar)"),
    rule("retry_wait_growth", _FLOW, _AGAIN, "choice",
         "How fast the waits before asking again grow. by_cause: linearly "
         "after an answer that could not be read, doubling after the "
         "server's failure. linear: linearly after both. doubling: "
         "doubling after both.", choices=("by_cause", "linear", "doubling"),
         steps=_ASKS, where="runner.py (retry_wait)"),
    rule("fault_excerpt_chars", "prompts", "Questions asked again", "map",
         "How much of a broken answer the question asked again shows the "
         "model: the characters before the place where it broke, the "
         "characters after it, and the characters of text outside the "
         "object. Give all three. Decided on 2026-09-12.", of="whole",
         decided="2026-09-12", steps=_ASKS, where="runner.py (_reply_fault)"),
    rule("retry_shows_reply", _FLOW, _AGAIN, "switch",
         "On: a request asked again after an unreadable answer carries that "
         "answer and what was wrong with it. Off: it goes out unchanged, "
         "except for the temperature that rises with every attempt. "
         "Decided on 2026-09-12.", decided="2026-09-12", steps=_ASKS,
         where="runner.py (ask_in_grammar)"),
    rule("missing_key_asks_again", _FLOW, _AGAIN, "switch",
         "On: an answer that is valid JSON but lacks a key its schema "
         "requires is asked again, with the key named. Off: it is taken as "
         "it is, and the missing key reads as nothing found. "
         "Decided on 2026-09-12.", decided="2026-09-12", steps=_ASKS,
         where="runner.py (_lacking)"),
    rule("server_probe_timeout_s", _FLOW, _AGAIN, "number",
         "The seconds the health check waits for the model server to "
         "answer. Any answer below status 500 counts as the server being "
         "there. Decided on 2026-11-09.", least=1, decided="2026-11-09",
         where="runner.py (probe_server)"),
    rule("dead_server_ends_run", _FLOW, _AGAIN, "switch",
         "On: a server that has not answered for `server_dead_after_s` ends "
         "the run at once, and the documents in work stay unstamped. Off: "
         "the run goes on asking. Decided on 2026-11-09.",
         decided="2026-11-09", where="runner.py (server_dead)"),
    # -- concurrency ----------------------------------------------------------
    rule("limit_adaptive", _FLOW, _LOAD, "switch",
         "On: the number of requests open at once follows the load of the "
         "server, up where it has room and down where it is overloaded. "
         "Off: the number of threads alone bounds the requests. Decided "
         "on 2026-10-22.", env="EXTRACT_LIMIT_ADAPTIVE",
         env_flag=(False, True), decided="2026-10-22",
         where="runner.py (start_limit)"),
    rule("limit_start", _FLOW, _LOAD, "whole",
         "The requests open at once the run starts with, before the load "
         "of the server moves it. A hosted API starts at "
         "`limit_start_hosted`.",
         least=1, env="EXTRACT_LIMIT_START",
         where="throttle.py"),
    rule("limit_least", _FLOW, _LOAD, "whole",
         "The fewest requests open at once, which the limit never falls "
         "below.", least=1,
         env="EXTRACT_LIMIT_MIN",
         where="throttle.py"),
    rule("limit_most", _FLOW, _LOAD, "whole",
         "The most requests open at once, which the limit never rises "
         "above. It also sizes the threads that send requests.",
         least=1, env="EXTRACT_LIMIT_MAX",
         where="throttle.py"),
    rule("limit_step", _FLOW, _LOAD, "whole",
         "By how many requests the limit grows each time the server has "
         "room. Half of it is also how near the limit the open requests "
         "must be for the limit to count as used.", least=1,
         env="EXTRACT_LIMIT_STEP",
         where="throttle.py"),
    rule("limit_backoff", _FLOW, _LOAD, "number",
         "The share the limit falls to when the server is overloaded, such "
         "as 0.8 for a fifth less. It must be below 1, or the limit would "
         "never fall.", least=0.05, most=0.99, env="EXTRACT_LIMIT_BACKOFF",
         where="throttle.py"),
    rule("limit_poll_s", _FLOW, _LOAD, "number",
         "The seconds between two looks at the load of the server. With "
         "`limit_hold_samples` it makes the time the limit is held after "
         "a fall.", least=0.1, env="EXTRACT_LIMIT_POLL",
         where="throttle.py"),
    rule("limit_kv_grow", _FLOW, _LOAD, "number",
         "The share of the server's cache below which the limit may grow. "
         "It must not be above `limit_kv_high`.", least=0.0, most=1.0,
         env="EXTRACT_LIMIT_KV_GROW",
         where="throttle.py"),
    rule("limit_kv_high", _FLOW, _LOAD, "number",
         "The share of the server's cache at which the limit falls. A "
         "smaller number spares the server and slows the run.",
         least=0.0, most=1.0, env="EXTRACT_LIMIT_KV_HIGH",
         where="throttle.py"),
    rule("limit_token_time_s", _FLOW, _LOAD, "number",
         "The seconds per output token above which the limit falls, for a "
         "server shared with people who wait for answers. 0: the time per "
         "token never lowers the limit.", least=0.0,
         env="EXTRACT_LIMIT_TPOT_MAX",
         where="throttle.py"),
    rule("limit_waiting_samples", _FLOW, _LOAD, "whole",
         "How many looks in a row must find requests waiting at the server "
         "before the limit falls.", least=1,
         where="throttle.py"),
    rule("limit_hold_samples", _FLOW, _LOAD, "whole",
         "How many looks the limit is held after a fall, so that the "
         "server can drain before it is pushed again.", least=0,
         where="throttle.py"),
    rule("metrics_timeout_s", _FLOW, _LOAD, "number",
         "The seconds a look at the server's load waits for its answer.",
         least=0.1, where="throttle.py (Reader)"),
    rule("limit_start_hosted", _FLOW, _LOAD, "whole",
         "The requests open at once a hosted API starts with, which only "
         "its own refusals move. 0: `limit_least`.", least=0,
         where="throttle.py (start_hosted)"),
    rule("limit_grow_only_when_used", _FLOW, _LOAD, "switch",
         "On: the limit grows only while the open requests reach it, so a "
         "number that nothing uses does not grow. Off: it grows whenever "
         "the server has room.", where="throttle.py (Controller)"),
    rule("limit_down_on_preemption", _FLOW, _LOAD, "switch",
         "On: the limit falls when the server had to put requests aside to "
         "make room. Off: it does not.", where="throttle.py (Controller)"),
    rule("limit_without_metrics", _FLOW, _LOAD, "choice",
         "What the limit does for a server that shows no load. none: no "
         "limit, and the threads of the run bound the requests. fixed: a "
         "limit of `limit_start` that does not move.",
         choices=("none", "fixed"), where="throttle.py (start)"),
    rule("queue_order", _FLOW, _DOCS, "choice",
         "In which order the waiting requests are sent. oldest_document: "
         "the requests of the document that began first go first, so a "
         "document is finished before the next is far. arrival: in the "
         "order they were asked. newest_document: the newest document "
         "first. Requests that belong to no document always go first.",
         choices=("oldest_document", "arrival", "newest_document"),
         where="scheduler.py (Scheduler.rank)"),
    rule("parallel", _FLOW, _LOAD, "whole",
         "How many requests of this step may be open at once. 0: the step "
         "shares the limit that follows the load of the server with the "
         "other steps. A number: the step has a lane of its own with that "
         "limit, up or down from the shared one, and the other steps keep "
         "sharing theirs.", least=0, steps=_ASKS,
         where="scheduler.py (Scheduler)"),
    rule("compute_parallel", _FLOW, _LOAD, "whole",
         "How many calculation questions run at once over the whole run. "
         "A larger number asks more in parallel and is bounded by the "
         "limit of open requests.", least=1, env="EXTRACT_FIELD_PARALLEL",
         where="runner.py (make_computer)"),
    rule("phrase_parallel", _FLOW, _SEARCH, "whole",
         "How many search sentences of one document are written at the "
         "same time. 0: all of them. Decided on 2026-11-09.", least=0,
         decided="2026-11-09", steps=("sentences", "order", "phrase"),
         where="runner.py (document_anchor)"),
    rule("documents_in_flight", _FLOW, _LOAD, "whole",
         "The most documents read at the same time, which bounds the "
         "memory of the run. Decided on 2026-10-22.", least=1,
         env="EXTRACT_BATCH_DOCS", decided="2026-10-22",
         where="runner.py (main)"),
    rule("document_admission", _FLOW, _LOAD, "choice",
         "When a new document is let in. by_server_room: one at a time "
         "whenever fewer requests are open than the limit allows. "
         "ceiling_only: as many as `documents_in_flight` allows. Decided "
         "on 2026-10-22.", choices=("by_server_room", "ceiling_only"),
         decided="2026-10-22", where="runner.py (document_room)"),
    rule("fixed_limit_requests", _FLOW, _LOAD, "whole",
         "How many requests a probe keeps open at once, with a limit that "
         "does not move. 0: the number the caller gives.", least=0,
         where="runner.py (start_fixed_limit)"),
    rule("http_connections", _FLOW, _LOAD, "whole",
         "How many connections to the model server stay open. 0: as many "
         "as the most requests the limit allows. It belongs to the machine.",
         least=0, machine=True, where="runner.py (shared_http)"),
    rule("content_cache_owners", _FLOW, _LOAD, "whole",
         "How many sections, tables and figures one run keeps in memory; "
         "the oldest leave first. 0 keeps all.", least=0,
         env="EXTRACT_CONTENT_CACHE_OWNERS", where="runner.py"),
    rule("code_slots", _FLOW, _CALC, "whole",
         "How many code runs the sandbox takes at once for the whole run. "
         "A code run waiting for its turn waits on the sandbox otherwise. "
         "Decided on 2026-11-03.", least=1, env="CODE_EXEC_PARALLEL",
         decided="2026-11-03", steps=("compute",),
         where="runner.py (make_computer)"),
    rule("compute_extra_attempts", _FLOW, _CALC, "whole",
         "How many requests a calculation question may use beyond its "
         "unreadable answers and its code runs. Decided on 2026-11-03.",
         least=0, decided="2026-11-03", steps=("compute",),
         where="runner.py (make_computer)"),
    # -- documents and stamps -------------------------------------------------
    rule("current_versions_only", _FLOW, _DOCS, "switch",
         "On: only the current version of a plan is read. Off: every "
         "version in the catalogue is.", where="runner.py (_documents)"),
    rule("stamp_without_reply", _FLOW, _DOCS, "switch",
         "On: a document of which not one request was answered is stamped "
         "as read. Off: it gets no stamp, so a later run reads it again, "
         "which is what a dead server needs. Decided on 2026-11-09.",
         decided="2026-11-09", steps=("write",),
         where="runner.py (not_happened)"),
    rule("coarse_stamp_keys", _FLOW, "Reading a document again", "texts",
         "The stamp keys whose hash is compared where the stamp holds no "
         "finer key. The hash of the whole spec file moves with a comment "
         "or a changed indent and overrules every finer key, so it counts "
         "only where nothing finer is there. Empty: it is never compared. "
         "Decided on 2026-09-10.",
         empty=True, decided="2026-09-10", where="runner.py (stale)"),
    rule("search_to_end", _FLOW, _SEARCH, "switch",
         "On: every search shows every chunk of its document, so a "
         "dimension ends read or unstated and never as exhausted. A run "
         "that reads the open dimensions to the end switches it on. "
         "Decided on 2026-11-02.", decided="2026-11-02", steps=("order",),
         where="addressed.py (Reader.budget)"),
    rule("rest_starts_at_open_rows", _FLOW, _SEARCH, "switch",
         "On: the rest of a document is read from the section of the rows "
         "still open, with what was attached before it. Off: from the "
         "start of the document.", steps=("order",),
         where="runner.py (make_rest_of_document)"),
    # -- window of the server -------------------------------------------------
    rule("dynamic_list_tokens", _FLOW, _WINDOW, "whole",
         "The tokens a list built for one document may take in the window "
         "the server has to be started with.", least=0,
         where="runner.py (context_budget)"),
    rule("window_floor_tokens", _FLOW, _WINDOW, "whole",
         "The tokens every request is assumed to take at least, in the "
         "window the server has to be started with.", least=0,
         where="runner.py (context_budget)"),
    rule("window_extra_tokens", _FLOW, _WINDOW, "whole",
         "The tokens added for what is not counted, in the window the "
         "server has to be started with.", least=0,
         where="runner.py (context_budget)"),
    rule("window_words_per_token", _FLOW, _WINDOW, "number",
         "How many characters of text count as one token in the window the "
         "server has to be started with. A smaller number asks for a "
         "larger window.", least=0.1, where="runner.py (context_budget)"),
    rule("window_line_tokens", _FLOW, _WINDOW, "whole",
         "The tokens the longest line of a piece or heading is assumed to "
         "take, in the window the server has to be started with. A request "
         "shows `search_per_request` pieces of `piece_lines` lines and "
         "`headings` headings each; this is what one line of them costs. "
         "Today's value was measured on the plans: the chunk text of 5,333 "
         "tokens a request used to count, over the 90 lines of a request.",
         least=1, where="runner.py (context_budget)"),
    rule("window_tokens_per_image", _FLOW, _WINDOW, "whole",
         "The tokens one image counts for in the window the server has to "
         "be started with.", least=0, where="runner.py (context_budget)"),
    rule("batch_sources", _FLOW, _WINDOW, "whole",
         "How many chunks one request of the older batch way shares. It "
         "sizes the window the server has to be started with and the "
         "batches of the pass over stored values.", least=1,
         env="EXTRACT_BATCH_SOURCES", steps=("take_back",),
         where="runner.py, pipeline.py"),
    rule("batch_chars", _FLOW, _WINDOW, "whole",
         "How many characters of text one request of the older batch way "
         "carries at most, with `batch_sources`.", least=1,
         env="EXTRACT_BATCH_CHARS", steps=("take_back",),
         where="runner.py, pipeline.py"),
    # -- second reading and the quote in the PDF ------------------------------
    rule("review_parent_chars", _FLOW, _REVIEW, "whole",
         "How many characters of the section above a table go into the "
         "second reading of a value from that table.", least=0,
         env="EXTRACT_PARENT_CHARS", steps=("review",),
         where="runner.py (make_parents)"),
    rule("locate_quotes", _FLOW, _PDF, "switch",
         "On: the place of each quote in the PDF is found and written as "
         "rectangles, for highlighting. Off: no place is looked for, and "
         "the PDFs are not needed.", env="EXTRACT_LOCATE",
         env_flag=(False, True), steps=("write",),
         where="runner.py (make_locate)"),
    rule("locate_max_pages", _FLOW, _PDF, "whole",
         "On how many pages of a section a quote is looked for in the PDF "
         "before it is given up on. A section can run over a page break.",
         least=1, env="EXTRACT_LOCATE_MAX_PAGES", steps=("write",),
         where="runner.py (make_locate)"),
    rule("locate_cache_pages", _FLOW, _PDF, "whole",
         "How many pages with their words stay in memory for finding "
         "quotes, across documents.", least=1,
         env="EXTRACT_LOCATE_CACHE_PAGES", where="runner.py (make_locate)"),
    # -- the check before the run ---------------------------------------------
    rule("preflight_on", _FLOW, _CHECK, "switch",
         "On: the run asks the server before the first document whether it "
         "offers the model and whether its window is large enough. Off: "
         "it asks nothing and finds out hours in.",
         where="runner.py (main)"),
    rule("preflight_timeout_s", _FLOW, _CHECK, "number",
         "The seconds each question of the check before the run waits for "
         "the server.", least=1, where="llm_preflight.py"),
    rule("preflight_probe_timeout_s", _FLOW, _CHECK, "number",
         "The seconds each test request of the check before the run waits "
         "for the server.", least=1, where="llm_preflight.py"),
    rule("preflight_probe_tokens", _FLOW, _CHECK, "whole",
         "The longest answer of a test request of the check before the "
         "run. A hosted model that thinks may need more than a few.",
         least=1, where="llm_preflight.py"),
    rule("preflight_refusal_stops", _FLOW, _CHECK, "switch",
         "On: a server that refuses a test request (a status 400 to 499 "
         "but 429) stops the run before it starts. Off: the run asks "
         "anyway and meets the refusal at every request.",
         where="llm_preflight.py"),
    # -- hosted APIs ----------------------------------------------------------
    rule("rate_gate", _FLOW, _AGAIN, "switch",
         "On: when a hosted API says it is busy, every request to it waits "
         "behind one shared gate. Off: each request waits on its own.",
         where="providers/governor.py"),
    rule("rate_hold_start_s", _FLOW, _AGAIN, "number",
         "The seconds the gate of a hosted API stays closed after its "
         "first refusal that names no time. Each further round doubles it "
         "up to `rate_hold_most_s`.", least=0, where="providers/governor.py"),
    rule("rate_hold_most_s", _FLOW, _AGAIN, "number",
         "The longest the gate of a hosted API stays closed on its own "
         "doubling.", least=0, where="providers/governor.py"),
    rule("rate_hold_server_factor", _FLOW, _AGAIN, "number",
         "How many times `rate_hold_most_s` the gate may stay closed "
         "where the API itself names the time to wait.", least=0,
         where="providers/governor.py"),
    rule("rate_limited_statuses", _FLOW, _AGAIN, "texts",
         "The statuses of a hosted API that mean not now: they close the "
         "gate and make the run wait.", where="providers/governor.py"),
    rule("schema_optional_fields", _FLOW, _MODEL, "whole",
         "How many optional fields of a reply schema a hosted API that "
         "counts them takes; those over it are made required. A larger "
         "number keeps more fields optional.", least=0, steps=_ASKS,
         where="providers/anthropic_api.py"),
    rule("schema_optional_alternatives", _FLOW, _MODEL, "whole",
         "How many fields with alternatives of a reply schema a hosted API "
         "that counts them takes. A schema over it is refused.", least=0,
         steps=_ASKS, where="providers/anthropic_api.py"),
    rule("schema_dialect", _FLOW, _MODEL, "choice",
         "How a reply schema is written for a hosted API. by_provider: as "
         "that API takes it. all_required: every field required and "
         "nullable, which every API takes. optional: fields stay "
         "optional.", choices=("by_provider", "all_required", "optional"),
         steps=_ASKS, where="providers (adapters)"),
    rule("learn_no_temperature", _FLOW, _MODEL, "switch",
         "On: when a model refuses the temperature of a request, the "
         "request is sent again without it, and no later request to "
         "that model carries one. Off: a refused temperature is an "
         "error like any other refusal and is not worked around.",
         steps=_ASKS, where="providers/base.py"),
)
