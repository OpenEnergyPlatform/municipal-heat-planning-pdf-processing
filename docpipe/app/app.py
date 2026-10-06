"""
app.py: The chat over a docpipe corpus and the page on which harvested
values are reviewed. The only module of the package that imports Streamlit.

What the corpus is about comes from the profile: its catalog supplies the
labels, the filters and the detail shown for a selected document, and its
`inference.UI` every word on these pages. A question goes to one document,
to several (each asked by itself, then compared) or to the whole corpus.
Where a harvest is configured, the numbers it holds for a question are
shown first, as they were read and checked, and the answer from the
documents follows.

The graph route is not offered while no corpus graph exists, and
`docpipe.inference.kg_route` stays in the core for the day it does.

Run:
    docpipe --profile kwp chat --server.address 0.0.0.0 --server.port 8501

Author: Felix Vossel
"""
from __future__ import annotations

import itertools
import json
import logging
import mimetypes
import os
import sys
from pathlib import Path

# A pdf.js viewer behind PDF_VIEWER_PREFIX is served as ES modules; some Python
# installs don't map .mjs → a JS MIME type, and browsers refuse to execute
# modules served as octet-stream.
mimetypes.add_type("text/javascript", ".mjs")

# `streamlit run` executes this file as a top-level script (no package
# context), so relative imports would fail. Installed, the package is found
# anyway; from a checkout the directory that holds `docpipe/` is put on the
# path.
_PACKAGE_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

import streamlit as st

from docpipe import prompts
from docpipe.app import config, pdf_link
from docpipe.extraction import gold, trust
from docpipe.extraction.verify import canonical_number
from docpipe.inference import (
    answer, catalog, chunker, compare, faiss_store, kg_route, lexical,
    llm_client, query_cache, replies, request_log, values_route, wording,
)
from docpipe.inference import db
from docpipe.profile import load_profile
from docpipe.serve.values import Values

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# The profile whose words and prompts the pages use: the configured one, or
# the one the package brings itself.
WORDS_PROFILE = config.PROFILE or load_profile("default")
# The words of the pages, filled in by main().
T: dict = {}
# Streamlit refuses two widgets of one identity in a run, and two citations of
# one document are two download buttons of the same label: each takes a key.
_downloads = itertools.count()


# ---------------------------------------------------------------------------
# Cached resources. The embedding model is deliberately NOT among them: whether
# it stays loaded is the backend's business, and on a card that also serves this
# app the answer is no.
# ---------------------------------------------------------------------------
@st.cache_resource
def get_index():
    """Returns (faiss_index, id_to_pos) — loaded once, held in RAM."""
    return faiss_store.load_global_index(config.INDEX_PATH)


@st.cache_resource
def get_db():
    return db.connect_readonly(config.DB_PATH)


@st.cache_resource
def get_scopes():
    """The search scopes this index holds vectors of, in the fixed order."""
    return db.available_scopes(get_db())


@st.cache_resource
def get_index_notice():
    """The profile's sentence for an index built with another model than the
    one that embeds the questions, or None."""
    return db.index_model_notice(get_db(), config.EMBEDDING_MODEL,
                                 T["index_model_differs"])


@st.cache_resource
def get_cache():
    return query_cache.connect(config.QUERY_CACHE_PATH)


@st.cache_resource
def get_request_log():
    return request_log.connect(config.REQUEST_LOG_PATH)


@st.cache_resource
def get_catalog():
    """The profile's catalog, or the generic one if no profile is configured."""
    return catalog.load_catalog(config.PROFILE)


@st.cache_resource
def get_graph():
    """The graph `--serialize` wrote, and the trust lines above its nodes."""
    return kg_route.load_graph(config.KG_TTL_PATH)


@st.cache_resource
def get_kg_hooks():
    """What the profile contributes to the graph route; None without a graph."""
    return kg_route.hooks(config.PROFILE)


@st.cache_resource
def get_lexical():
    """The word index beside the vectors, or None: missing, stale, or
    turned off. `lexical.connect` says which in the log."""
    return lexical.connect(config.DB_PATH) if config.LEXICAL else None


@st.cache_resource
def get_values():
    """(value store, harvest rows by document) of the configured harvest,
    or (None, {}) where none is configured."""
    if config.HARVEST_DIR is None or not config.HARVEST_DIR.is_dir():
        return None, {}
    spec = None
    path = WORDS_PROFILE.component("extraction", "SPEC_PATH")
    if path is not None:
        from docpipe.extraction.spec import load as load_spec
        spec = load_spec(path)
    rows = gold.harvest(config.HARVEST_DIR)
    store = Values(rows, spec=spec,
                   transcribed=trust.transcribed_documents(config.DB_PATH))
    return store, rows


@st.cache_resource
def get_coordinate_prompt():
    return prompts.load(values_route.COORDINATE_PROMPT_ID, WORDS_PROFILE)


@st.cache_resource
def get_documents() -> dict:
    """{harvest name of a document: (id, file name)}. A harvest file is
    named after its document's file without the ending."""
    return {Path(row["filename"]).stem: (row["id"], row["filename"])
            for row in get_db().execute(
                'SELECT "id", "filename" FROM "Documents"')}


@st.cache_resource
def get_labels() -> dict:
    """{document id: what the catalog calls it}, superseded ones included."""
    return {entry.id: entry.label for entry in get_catalog().entries(
        get_db(), include_superseded=True)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def resolve_image_path(stored_path: str | None) -> Path | None:
    """Best-effort resolution of a Tables/Images `path` to an on-disk file."""
    if not stored_path:
        return None
    candidates = [Path(stored_path), config.IMAGE_ROOT / stored_path]
    for c in candidates:
        if c.exists():
            return c
    return None


def embed_query(item: dict, cache_conn, cache_key: str):
    """Return the query vector, from cache or a fresh on-demand embed."""
    cached = query_cache.get(cache_conn, cache_key)
    if cached is not None:
        log.info("Query cache hit (%s)", cache_key[:12])
        return cached, True
    # Heavy backend imported lazily so a cache-hit turn never touches torch;
    # which backend that is (local model or an endpoint) is configuration.
    from docpipe.embedding import get_embedder
    vec = get_embedder().embed_one(item)
    query_cache.put(cache_conn, cache_key, vec)
    return vec, False


def _document_label(document_id) -> str | None:
    """What a source of a corpus-wide answer calls its document."""
    label = get_labels().get(document_id)
    if label:
        return label
    filename = db.document_filename(get_db(), document_id)
    return Path(filename).stem if filename else None


def _corpus(image_bytes: bytes | None = None) -> answer.Corpus:
    """This app's resources as the answer loop takes them."""
    with _spinner(T["preparing"]):
        index, id_to_pos = get_index()
    cache_conn = get_cache()

    def _embed(item):
        key = query_cache.make_key(
            "image" if item.get("image") and not item.get("text")
            else ("image+text" if item.get("image") else "text"),
            text=item.get("text"),
            image_bytes=image_bytes if item.get("image") else None,
        )
        return embed_query(item, cache_conn, key)

    return answer.Corpus(
        conn=get_db(), index=index, id_to_pos=id_to_pos, embed=_embed,
        resolve_image=resolve_image_path, log_conn=get_request_log(),
        lexical=get_lexical(), document_label=_document_label,
    )


def run_turn(task: str, image_bytes: bytes | None, image_only: bool,
             document_id: int | None, scopes: list[str], as_json: bool = False,
             history: list | None = None):
    """One turn, with this app's resources and its spinners attached.
    `document_id` None asks the whole corpus."""
    return answer.answer_question(
        task, _corpus(image_bytes), document_id, scopes,
        image_bytes=image_bytes, image_only=image_only, as_json=as_json,
        history=history, progress=_spinner,
    )


def run_comparison(task: str, documents: list, scopes: list[str],
                   as_json: bool = False, histories: dict | None = None):
    """The same question to every selected document, then one comparison.

    No image: an uploaded picture is a query anchor for one document's index,
    and the same crop searched across five plans anchors four of them to
    whatever happens to look similar.
    """
    return compare.compare_documents(
        task, _corpus(), documents, scopes, as_json=as_json,
        histories=histories, progress=_spinner,
    )


def run_kg_turn(task: str, document_id: int) -> dict:
    """One question to the graph; `answer_from_graph` decides everything."""
    graph, comments = get_graph()
    return kg_route.answer_from_graph(
        task, get_kg_hooks(), graph, comments, db_path=config.DB_PATH,
        document=db.document_filename(get_db(), document_id),
        ask=_ask_coordinate)


def _ask_coordinate(task: str, slot):
    """One closed question to the model, over the spec's own list."""
    return llm_client.choose(get_kg_hooks().prompt, task, slot.question,
                             slot.answerable() if slot.is_closed else {})


def run_values_turn(task: str, document_id: int | None) -> dict | None:
    """What the harvest holds for the question, or None: no harvest, or
    the question names nothing it has. `document_id` None asks every
    document's harvest."""
    store, _rows = get_values()
    if store is None:
        return None
    name = None
    if document_id is not None:
        filename = db.document_filename(get_db(), document_id)
        if not filename:
            return None
        name = Path(filename).stem
    got = values_route.answer_from_values(
        task, store, ask=_ask_value_coordinate, document=name,
        level=config.VALUES_LEVEL, limit=config.VALUES_LIMIT)
    return got if got["route"] == "values" else None


def _ask_value_coordinate(task: str, slot):
    return llm_client.choose(get_coordinate_prompt(), task, slot.question,
                             slot.answerable() if slot.is_closed else {})


def _spinner(label: str):
    """A labelled spinner with Streamlit's built-in live elapsed timer."""
    return st.spinner(f"{label} …", show_time=True)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def main() -> None:
    T.clear()
    T.update(wording.ui(WORDS_PROFILE))
    title = (config.PROFILE.display_title if config.PROFILE
             else T["title_fallback"])
    st.set_page_config(page_title=title, layout="wide")
    # Hide Streamlit's top-right "running man" status widget.
    st.markdown("<style>[data-testid='stStatusWidget']{display:none !important;}</style>",
                unsafe_allow_html=True)
    st.title(title)
    # No profile named: the pages and the answer loop both run on the
    # built-in profile (`wording.chat_profile`), and the page says so.
    if config.PROFILE is None:
        st.warning(T["no_profile"])

    # The review page is offered where there is something to review.
    if config.HARVEST_DIR is not None and config.GOLD_PATH is not None:
        with st.sidebar:
            page = st.radio("page", [T["page_chat"], T["page_review"]],
                            horizontal=True, label_visibility="collapsed")
        if page == T["page_review"]:
            review_page()
            return
    chat_page()


def chat_page() -> None:
    cat = get_catalog()
    conn = get_db()
    notice = get_index_notice()
    if notice:
        st.warning(notice)
    offered = get_scopes()

    # ---- Sidebar: document + scopes ----
    with st.sidebar:
        st.header(T["selection"])
        whole = st.checkbox(T["whole_corpus"], value=False,
                            help=T["whole_corpus_help"])
        by_id: dict = {}
        doc_ids: list = []
        if not whole:
            include_old = st.checkbox(T["include_old"], value=False)
            entries = cat.entries(conn, include_superseded=include_old)
            if not entries:
                st.error(T["no_documents"])
                st.stop()

            # Filters are whatever the profile declared and its catalog
            # filled; a facet no document carries a value for is not offered
            # at all.
            options = catalog.facet_options(entries, cat.facets)
            selections = {
                facet.field: st.multiselect(facet.label, options[facet.field],
                                            default=[])
                for facet in cat.facets if facet.field in options
            }
            entries = catalog.apply_filters(entries, selections)
            if not entries:
                st.warning(T["no_match"])
                st.stop()

            by_id = {e.id: e for e in entries}
            # Several selected = the same question to each, then a comparison
            # over the answers. Not a joint retrieval: the longest chapter
            # would take every slot in the top-k and the other documents
            # would look silent.
            doc_ids = st.multiselect(
                cat.document_noun, options=list(by_id),
                format_func=lambda i: by_id[i].label,
                default=list(by_id)[:1],
                max_selections=config.COMPARE_MAX_DOCUMENTS,
                help=T["compare_help"],
            )
            if not doc_ids:
                st.warning(T["choose_one"].format(noun=cat.document_noun))
                st.stop()
            if len(doc_ids) == 1:
                for heading, lines in by_id[doc_ids[0]].detail:
                    with st.expander(heading):
                        st.markdown("\n".join(f"- {line}" for line in lines))
        scopes = st.multiselect(
            T["scopes"], options=offered, default=offered,
            help=T["scopes_help"],
        )
        out_fmt = st.radio(T["format"], [T["format_prose"], "JSON"],
                           horizontal=True)
        as_json = out_fmt == "JSON"
        if config.LLM_STUB_MODE:
            st.info(T["stub_mode"])

    # ---- Reset chat when the selection changes ----
    comparing = len(doc_ids) > 1
    doc_id = None if whole else doc_ids[0]
    selected = ["corpus"] if whole else doc_ids
    if st.session_state.get("doc_ids") != selected:
        st.session_state["doc_ids"] = selected
        st.session_state["chat_history"] = []
        # Follow-up context resets with the selection, and it is kept per
        # document: a re-check has to search past what THAT document already
        # showed, not past what another one did.
        st.session_state["turns_by_doc"] = {}

    history = st.session_state.setdefault("chat_history", [])

    # ---- Render history ----
    for msg in history:
        with st.chat_message(msg["role"]):
            if msg.get("kg_values") is not None:
                _render_kg(msg["kg_values"])
                continue
            if msg.get("rows") is not None:
                _render_comparison(msg)
                continue
            if msg.get("values") is not None:
                _render_values(msg["values"])
            if msg["role"] == "assistant":
                _render_answer(msg["content"], msg.get("as_json", False))
                _render_dropped(msg.get("made"), msg.get("dropped"))
                _render_faults(msg.get("faults"))
            else:
                st.markdown(msg["content"])
            _render_notes(msg)
            _render_compute(msg.get("compute"))
            for cit in msg.get("citations", []):
                _render_citation(cit)

    # ---- Optional image upload + mode ----
    # The image and this toggle only change how the *query embedding* is formed;
    # the text task always drives the final question answering.
    uploaded = (None if comparing else
                st.file_uploader(T["image_upload"],
                                 type=["png", "jpg", "jpeg"]))
    image_only = False
    if uploaded is not None:
        image_only = st.radio(
            T["image_mode"],
            options=[T["image_and_text"], T["image_only"]], horizontal=True,
        ) == T["image_only"]

    # ---- Chat input (always required: it is the extraction task for the LLM) ----
    task = st.chat_input(T["chat_input"])
    if not task:
        return

    if not scopes:
        st.warning(T["choose_scope"])
        return

    image_bytes = uploaded.getvalue() if uploaded is not None else None

    # Echo the user turn
    user_text = task if uploaded is None else f"{task}  \n{T['with_image']}"
    history.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    by_doc = st.session_state.setdefault("turns_by_doc", {})

    if comparing:
        outcome = run_comparison(task, [(i, by_id[i].label) for i in doc_ids],
                                 scopes, as_json=as_json, histories=by_doc)
        with st.chat_message("assistant"):
            _render_comparison(outcome)
        history.append({"role": "assistant", "content": "", **outcome})
        for row in outcome["rows"]:
            _remember(by_doc, row["document_id"], task, row)
        return

    # The graph route is not offered: there is no corpus graph yet, and a
    # selector for a source that does not exist is a promise the app cannot
    # keep. `kg_route` stays in the core for the day the graph is there.
    route_note = None

    # What the harvest holds for the question comes first and stands for
    # itself: read and checked beforehand, not written by the answer below.
    # Not for a question that is only an image: it names nothing.
    values = None if image_only else run_values_turn(task, doc_id)

    result = run_turn(task, image_bytes, image_only, doc_id, scopes, as_json=as_json,
                      history=by_doc.get(doc_id, []))

    recheck_note = None
    if result.get("recheck"):
        recheck_note = T["recheck"].format(n=result["n_excluded"])

    # Compose assistant reply
    answered = result["answer"] is not None
    faults = list(result.get("faults") or [])
    unread = _unread_replies(result)
    told: list = []      # faults the reply says itself, and the page not twice
    if answered:
        reply = result["answer"]
    elif result["n_hits"] == 0:
        reply = (T["all_examined"]
                 if result.get("recheck") and result.get("n_excluded")
                 else T["no_hits"])
    elif unread:
        reply = T["answer_unreadable"].format(
            causes=llm_client.describe_faults(unread))
        told = unread
    else:
        reply = T["nothing_backed"]
    message = {
        "role": "assistant", "content": reply,
        "citations": result["citations"] if answered else [],
        "phrase": result.get("phrase"),
        "as_json": result["as_json"] if answered else False,
        "recheck_note": recheck_note, "route_note": route_note,
        "compute": result.get("compute", []), "values": values,
        "made": result.get("statements_made", 0),
        "dropped": result.get("statements_dropped", 0),
        "faults": [f for f in faults if f not in told],
    }
    with st.chat_message("assistant"):
        if values is not None:
            _render_values(values)
        _render_answer(reply, message["as_json"])
        _render_dropped(message["made"], message["dropped"])
        _render_faults(message["faults"])
        _render_notes(message)
        _render_compute(message["compute"])
        # Rendered directly (not inside an expander) so each citation can carry
        # its own page and context expanders without illegal nesting.
        for cit in message["citations"]:
            _render_citation(cit)
    history.append(message)

    _remember(by_doc, doc_id, task, result)


def _unread_replies(turn: dict) -> list:
    """The answer requests of a turn that stayed unreadable, where the turn
    made no statement at all: the model's replies could not be read, so the
    sources were not looked at, which is not the same as nothing standing in
    them. A turn that made statements has its answer, and says the rest in
    the faults under it."""
    if turn.get("statements_made"):
        return []
    return [f for f in turn.get("faults") or []
            if f["request"] == replies.ANSWER]


def _render_dropped(made, dropped) -> None:
    """How many of the statements the model made were removed because their
    quote does not stand in the source they cite, directly under the answer
    (also where every one of them was)."""
    if dropped:
        st.caption(T["statements_dropped"].format(dropped=dropped, made=made))


def _render_faults(faults) -> None:
    """The requests of the turn that stayed unreadable, with their causes: what
    they would have said is missing from the answer above."""
    if faults:
        st.warning(T["replies_unreadable"].format(
            n=len(faults), causes=llm_client.describe_faults(faults)))


def _render_notes(msg: dict) -> None:
    """The small lines under an answer: its search anchor and what kind of
    search it was."""
    if msg.get("phrase"):
        st.caption(T["anchor"].format(phrase=msg["phrase"]))
    if msg.get("recheck_note"):
        st.caption(msg["recheck_note"])
    if msg.get("route_note"):
        st.caption(msg["route_note"])


def _remember(by_doc: dict, document_id, task: str, result: dict) -> None:
    """Keep this turn as follow-up context for ITS document; no excerpts.

    Failed turns too: "schau noch einmal nach" is asked precisely AFTER a
    failure, and without the failed question in context the anchor is built
    from the literal follow-up words with no referent at all. The whole
    corpus is one conversation of its own, under the key None.
    """
    turns = by_doc.setdefault(document_id, [])
    turns.append({
        "task": task, "phrase": result.get("phrase"),
        "answer": result.get("answer_text") or result.get("answer")
                  or T["no_answer_context"],
        # (owner_kind, owner_id) of the sources the LLM read this turn — a
        # re-check searches past these instead of re-reading them. The flag
        # marks chain membership, so a second re-check excludes the whole chain.
        "examined": result.get("examined", []),
        "recheck": result.get("recheck", False),
    })
    by_doc[document_id] = turns[-5:]


def _render_values(got: dict) -> None:
    """The values the harvest holds for the question, each with its
    document, page, level and quote. Nothing here was written by a model
    in this turn."""
    st.markdown(f"**{T['values_heading']}**")
    st.caption(T["values_note"])
    for value, line in zip(got["values"],
                           values_route.as_passages(got["values"])):
        level = T["values_level"].format(level=value["level"])
        if value["reasons"]:
            level += " (" + ", ".join(value["reasons"]) + ")"
        st.markdown(f"**{line['text']}** · {line['where']} · {level}")
        if value.get("quote"):
            st.markdown("> " + str(value["quote"]).replace("\n", " "))
        _value_link(value["document"], value.get("page"), value.get("quote"))
    if got["total"] > len(got["values"]):
        st.caption(T["values_more"].format(shown=len(got["values"]),
                                           total=got["total"]))
    st.divider()


def _value_link(document: str, page, quote) -> None:
    """A button into the source PDF at a harvested value's page."""
    known = get_documents().get(document)
    if known is None or not page:
        return
    url = _pdf_url(known[1], page, quote)
    if url:
        st.link_button(T["open_pdf"].format(page=page), url)


def _render_comparison(outcome: dict) -> None:
    """The comparison, then every document's own answer and citations.

    The comparison first because it is what was asked for, and each answer in
    full underneath it because the comparison is the only part of this screen
    that no citation backs: it was written from the answers alone.
    """
    rows = outcome.get("rows") or []
    if outcome.get("dropped"):
        st.warning(T["compare_dropped"].format(
            limit=config.COMPARE_MAX_DOCUMENTS,
            names=", ".join(outcome["dropped"])))
    if outcome.get("comparison"):
        st.markdown(outcome["comparison"])
        st.caption(T["compare_note"])
    elif outcome.get("answered", 0) < 2:
        st.markdown(T["compare_too_few"])
    else:
        st.markdown(T["compare_failed"])
    _render_faults(outcome.get("faults"))
    st.dataframe(
        [{T["column_document"]: r["label"],
          T["column_answer"]: compare.summary(r),
          T["column_citations"]: r.get("n_findings", 0)} for r in rows],
        hide_index=True, use_container_width=True)
    for row in rows:
        st.subheader(row["label"])
        unread = []
        if row.get("answer") is None:
            unread = _unread_replies(row) if row.get("n_hits") else []
            if unread:
                # Not a document that holds nothing: its replies were not read.
                st.markdown(T["answer_unreadable"].format(
                    causes=llm_client.describe_faults(unread)))
            else:
                st.markdown(T["document_nothing"] if row.get("n_hits")
                            else T["no_hits"])
        else:
            _render_answer(row["answer"],
                           row.get("as_json", outcome.get("as_json", False)))
        _render_dropped(row.get("statements_made"),
                        row.get("statements_dropped"))
        _render_faults([f for f in row.get("faults") or [] if f not in unread])
        if row.get("phrase"):
            st.caption(T["anchor"].format(phrase=row["phrase"]))
        _render_compute(row.get("compute"))
        for cit in row.get("citations", []):
            _render_citation(cit)


def _render_kg(values: list) -> None:
    """The graph's values, each under the trust line the serializer wrote.

    The badge is the LAST comment line above the node and the evidence the
    rest, which is the order evidence_comment writes them in. A C is a
    warning because the profile's own word for it is a review request.
    """
    hooks = get_kg_hooks()
    for value in values:
        st.markdown(f"**{value['number']} {hooks.label(value['unit'])}** · "
                    f"{value['year']} · {hooks.label(value['quantity'])} · "
                    f"{hooks.label(value['aggregation'])}")
        # Carrier and sector come back under one predicate; the spec's own
        # lists say which is which, so the caption names the axis.
        about = [f"{axis or '?'}: " + ", ".join(hooks.label(iri) for iri in iris)
                 for axis, iris in kg_route.by_axis(
                     hooks.spec, hooks.axes, (value.get("abouts") or "").split())]
        st.caption("🏷 " + " · ".join([value["partLabel"]] + about))
        level = kg_route.trust_level(value["trust"], hooks.prose)
        if level == kg_route.LEVEL_C:
            st.warning(value["trust"])
        elif level == kg_route.LEVEL_B:
            st.caption(value["trust"])
        else:
            st.markdown(value["trust"])
        if value.get("evidence"):
            with st.expander(T["show_evidence"]):
                st.markdown("\n".join(f"- {line}" for line in value["evidence"]))


def _render_compute(compute: list | None) -> None:
    """Show the code the model ran in the sandbox + its output."""
    if not compute:
        return
    with st.expander(T["show_compute"].format(n=len(compute))):
        for number, step in enumerate(compute, start=1):
            st.caption(T["run_label"].format(n=number))
            st.code(step.get("code", ""), language="python")
            out = step.get("output") or {}
            if out.get("ok"):
                txt = (out.get("stdout") or "").strip() or T["compute_no_output"]
            else:
                txt = T["compute_error"].format(
                    error=out.get("error")
                    or (out.get("stderr") or "").strip() or "?")
            st.text(txt[:2000])


def _render_answer(answer: str, as_json: bool) -> None:
    """Render the assistant answer: pretty JSON (interactive, code fallback) or prose."""
    if as_json:
        try:
            st.json(json.loads(answer))
        except (ValueError, TypeError):
            st.code(answer, language="json")
    else:
        st.markdown(answer)


def _pdf_url(filename: str, page, quote=None, phrase=None, rects=None):
    """The link into a source PDF at *page*, boxing *quote* where it can be
    located there. None where no PDF area is configured."""
    prefix = config.PDF_URL_PREFIX
    if not prefix or not page:
        return None
    if quote and rects is None:
        # Per-line rects of the quote itself, so ONLY the cited passage is
        # boxed. Drawn by pdfjs_overlay.js.
        rects = pdf_link.best_quote_rects(config.PDF_ROOT / filename, page,
                                          quote)
        if not rects:
            pdf_phrase = pdf_link.best_search_phrase(
                config.PDF_ROOT / filename, page, quote)
            if pdf_phrase:
                phrase = pdf_phrase
    if config.PDF_VIEWER_PREFIX:      # a pdf.js viewer → highlight in every browser
        return pdf_link.pdf_viewer_url(config.PDF_VIEWER_PREFIX, prefix,
                                       filename, page, phrase, rects)
    # native browser viewer (no overlay; phrase only)
    return pdf_link.pdf_page_url(prefix, filename, page, phrase)


def _cited_page(cit: dict):
    """(filename, page, phrase, quote) of the page a citation stands on, or
    None where its document or its page is unknown.

    A section's quote is matched back onto the raw segments, which gives the
    exact page and a phrase. It is also the only quote that is a passage of
    the page: that of a table or a figure is a title or a reading, so *quote*
    is None there and the page is shown unmarked.
    """
    filename = db.document_filename(get_db(), cit.get("document_id"))
    if not filename:
        return None
    page = cit.get("page_number")
    phrase = None
    quote = cit.get("quote")
    located = cit.get("owner_kind") == "section" and quote \
        and cit.get("owner_id")
    if located:
        loc = pdf_link.locate_quote(
            quote, db.section_segments(get_db(), cit["owner_id"]))
        if loc:
            page, phrase = loc            # exact page (+ a fallback phrase)
    if not page:
        return None
    return filename, page, phrase, (quote if located else None)


@st.cache_data(show_spinner=False, max_entries=128)
def _page_image(path: str, stamp: int, page: int, quote):
    """(PNG, whether the quote was located) of one page of a PDF. *stamp* is
    the file's modification time: a PDF replaced on disk is drawn again and
    not remembered. A page that cannot be drawn raises, and is not cached."""
    rects = pdf_link.best_quote_rects(path, page, quote) if quote else None
    return pdf_link.render_page(path, page, rects), bool(rects)


@st.cache_data(show_spinner=False, max_entries=4)
def _pdf_bytes(path: str, stamp: int) -> bytes:
    """The PDF as it lies on disk, for the download; *stamp* as above."""
    return Path(path).read_bytes()


def _page_failure(page, why) -> str:
    """Why a page was not drawn, in the profile's words. The exception says it
    in English, and that goes to the log."""
    if why.reason == pdf_link.NOT_INSTALLED:
        return T["page_failed_library"].format(page=page)
    if why.reason == pdf_link.NOT_OPENED:
        return T["page_failed_open"].format(page=page)
    if why.reason == pdf_link.NO_SUCH_PAGE:
        return T["page_failed_range"].format(page=page)
    return T["page_failed_draw"].format(page=page)


def _show_page(filename: str, page, quote) -> None:
    """The cited page, drawn here from the PDF under PDF_ROOT with the quote
    marked, and the PDF to download. Where the page cannot be shown the
    expander says what is missing; where the quote cannot be located the page
    is shown without a mark and says so."""
    path = config.PDF_ROOT / filename
    with st.expander(T["show_page"].format(page=page)):
        if not path.is_file():
            # the folder is the server's own and goes to the log, not to a reader
            log.warning("%s is not in the PDF folder %s", filename,
                        config.PDF_ROOT)
            st.caption(T["page_no_file"].format(file=filename))
            return
        stamp = path.stat().st_mtime_ns
        try:
            image, located = _page_image(str(path), stamp, int(page), quote)
        except pdf_link.PageNotRendered as why:
            log.warning("page %s of %s was not drawn: %s", page, filename, why)
            st.caption(_page_failure(page, why))
        else:
            st.image(image)
            if quote and not located:
                st.caption(T["page_not_located"])
        st.download_button(T["download_pdf"],
                           data=_pdf_bytes(str(path), stamp),
                           file_name=Path(filename).name,
                           mime="application/pdf",
                           key=f"download_pdf:{next(_downloads)}")


def _render_citation(cit: dict) -> None:
    """Render one citation: source label, quote, its page, expandable
    context, image.

    Must NOT be called inside another st.expander (Streamlit forbids nesting the
    page and context expanders below).
    """
    label = chunker.citation_label(cit)
    number = f"[{cit['n']}] " if cit.get("n") else ""
    st.caption(f"{number}📄 {label}")
    quote = cit.get("quote")
    if quote:
        st.markdown("> " + str(quote).replace("\n", " "))
    if cit.get("visual"):
        st.caption(T["read_off"])
    if cit.get("computed"):
        st.caption(T["computed_from"].format(n=cit["run"]))
    where = _cited_page(cit)
    if where:
        filename, page, phrase, marked = where
        # None where no prefix is configured: nothing to link to
        url = _pdf_url(filename, page, marked, phrase)
        if url:
            st.link_button(T["open_pdf"].format(page=page), url)
        _show_page(filename, page, marked)
    context = (cit.get("text") or "").strip()
    if context:
        with st.expander(T["show_context"]):
            body = context
            if quote and str(quote) in body:
                body = body.replace(str(quote), f"**{quote}**", 1)
            st.markdown(body)
    img = resolve_image_path(cit.get("image_path"))
    if img is not None:
        st.image(str(img))


# ---------------------------------------------------------------------------
# The review page: a person decides, field by field, whether a harvested value
# is what the document says. The decisions are appended to the gold file
# (docpipe/extraction/gold.py); nothing here changes the harvest.
# ---------------------------------------------------------------------------
def _typed(text: str, like):
    """What was typed into a field, as the kind of thing the harvest holds
    there: a number where it holds a number. A number is read the way the
    harvest reads one off a page, with the decimal mark of the profile's
    documents: "1.234,5" is 1234.5 where they write a decimal comma."""
    text = (text or "").strip()
    if not text:
        return None
    if isinstance(like, (int, float)) and not isinstance(like, bool):
        sign, digits = 1, text
        if digits[:1] in ("-", "\u2212", "+"):
            sign, digits = (1 if digits[0] == "+" else -1), digits[1:].strip()
        mark = WORDS_PROFILE.component("extraction", "DECIMAL_MARK") or ","
        canonical = canonical_number(digits, mark)
        if canonical is None:
            return text
        number = sign * float(canonical)
        return int(number) if number.is_integer() and isinstance(like, int) \
            else number
    return text


def review_page() -> None:
    st.header(T["review_heading"])
    st.markdown(T["review_intro"])
    store, rows = get_values()
    if store is None:
        st.warning(T["review_no_harvest"])
        return
    name = st.text_input(T["review_by"],
                         value=st.session_state.get("review_by", ""))
    st.session_state["review_by"] = name.strip()
    by = st.session_state["review_by"]

    labels = {entry["parameter"]: entry["label"] or entry["parameter"]
              for entry in store.parameters()}
    every = T["review_all_parameters"]
    chosen = st.selectbox(T["review_parameter_filter"],
                          [every] + sorted(labels, key=lambda u: labels[u]),
                          format_func=lambda u: labels.get(u, u))
    held = gold.Gold.load(config.GOLD_PATH)
    queue = gold.queue(rows, held,
                       parameters=None if chosen == every else [chosen])
    skipped = st.session_state.setdefault("review_skipped", set())
    queue = [(document, row) for document, row in queue
             if gold.row_name(document, row) not in skipped]
    st.caption(T["review_progress"].format(open=len(queue)))

    if not queue:
        st.info(T["review_none_open"])
    else:
        _review_one(queue[0][0], queue[0][1], held, labels, by, skipped,
                    rows.get(queue[0][0]))
    st.divider()
    _review_missing(store, labels, by)
    st.divider()
    _review_checked(store, labels, by)


def _review_one(document: str, row: dict, held, labels: dict, by: str,
                skipped: set, beside=None) -> None:
    """One row and its open fields. *beside* are the rows of its document:
    a second row of the same quote and value is another row, with its own
    decisions and its own keys on the page."""
    key = gold.row_name(document, row)
    st.subheader(f"{labels.get(row.get('parameter'), row.get('parameter'))}"
                 f" · {document}")
    number = row.get("value")
    st.markdown(f"**{T['review_value']}: {number} {row.get('unit') or ''}**")
    if row.get("quote"):
        st.markdown("> " + str(row["quote"]).replace("\n", " "))
    page = (row.get("provenance") or {}).get("page")
    _value_link(document, page, row.get("quote"))

    choices = [T["review_open"], T["review_correct"], T["review_wrong"]]
    decided: dict = {}
    for field in gold.fields_of(row):
        already = held.verdict(document, row, field, beside)
        if already is not None:
            continue                    # decided before: not asked again
        picked = st.radio(
            T["review_field"].format(field=field, content=row.get(field)),
            choices, horizontal=True, key=f"{key}:{field}")
        if picked == T["review_correct"]:
            decided[field] = (gold.CORRECT, None)
        elif picked == T["review_wrong"]:
            expected = st.text_input(T["review_expected"],
                                     key=f"{key}:{field}:expected")
            decided[field] = (gold.WRONG, _typed(expected, row.get(field)))
    note = st.text_input(T["review_note"], key=f"{key}:note")
    save, skip = st.columns(2)
    if save.button(T["review_save"], key=f"{key}:save", type="primary"):
        if not by:
            st.error(T["review_by_missing"])
        elif not decided:
            st.warning(T["review_nothing_decided"])
        else:
            for field, (verdict, expected) in decided.items():
                gold.decide(config.GOLD_PATH, document, row, field, verdict,
                            expected=expected, by=by,
                            note=note.strip() or None)
            st.toast(T["review_saved"].format(n=len(decided)))
            st.rerun()
    if skip.button(T["review_skip"], key=f"{key}:skip"):
        skipped.add(key)
        st.rerun()


def _review_missing(store, labels: dict, by: str) -> None:
    st.subheader(T["review_missing_heading"])
    st.markdown(T["review_missing_intro"])
    documents = [entry["document"] for entry in store.documents()]
    if store.spec is not None:
        labels = {parameter.uri: parameter.label
                  for parameter in store.spec.parameters}
    document = st.selectbox(T["review_missing_document"], documents,
                            key="missing:document")
    parameter = st.selectbox(T["review_missing_parameter"],
                             sorted(labels, key=lambda u: labels[u]),
                             format_func=lambda u: labels.get(u, u),
                             key="missing:parameter")
    value = st.text_input(T["review_missing_value"], key="missing:value")
    unit = st.text_input(T["review_missing_unit"], key="missing:unit")
    quote = st.text_area(T["review_missing_quote"], key="missing:quote")
    page = st.text_input(T["review_missing_page"], key="missing:page")
    coordinates = {}
    described = store.spec.by_uri.get(parameter) if store.spec else None
    for axis in sorted((described.axes or {}) if described else {}):
        said = st.text_input(axis, key=f"missing:axis:{axis}")
        if said.strip():
            coordinates[axis] = _typed(said, 0)
    if st.button(T["review_missing_save"], key="missing:save"):
        if not by:
            st.error(T["review_by_missing"])
        elif not (document and parameter and value.strip()):
            st.warning(T["review_missing_needs"])
        else:
            gold.add_missing(
                config.GOLD_PATH, document, parameter, _typed(value, 0.0),
                unit=unit.strip() or None, quote=quote.strip() or None,
                coordinates=coordinates, page=_typed(page, 0), by=by)
            st.toast(T["review_saved"].format(n=1))
            # An empty form for the next value: one that stays filled in
            # invites a second press, and the same value twice.
            for filled in [name for name in st.session_state
                           if str(name).startswith("missing:")
                           and name not in ("missing:document",
                                            "missing:parameter")]:
                del st.session_state[filled]
            st.rerun()


def _review_checked(store, labels: dict, by: str) -> None:
    st.subheader(T["review_checked_heading"])
    st.markdown(T["review_checked_intro"])
    documents = [entry["document"] for entry in store.documents()]
    if store.spec is not None:
        labels = {parameter.uri: parameter.label
                  for parameter in store.spec.parameters}
    every = T["review_checked_all"]
    document = st.selectbox(T["review_missing_document"], documents,
                            key="checked:document")
    parameter = st.selectbox(T["review_missing_parameter"],
                             [every] + sorted(labels, key=lambda u: labels[u]),
                             format_func=lambda u: labels.get(u, u),
                             key="checked:parameter")
    if st.button(T["review_checked_save"], key="checked:save"):
        if not by:
            st.error(T["review_by_missing"])
        elif document:
            gold.mark_checked(config.GOLD_PATH, document,
                              None if parameter == every else parameter,
                              by=by)
            st.toast(T["review_saved"].format(n=1))


if __name__ == "__main__":
    main()
