# docpipe.app.app

`docpipe/app/app.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

app.py: The chat over a docpipe corpus and the page on which harvested
values are reviewed. The only module of the package that imports Streamlit.

What the corpus is about comes from the profile: its catalog supplies the
labels, the filters and the detail shown for a selected document, and its
`inference.UI` every word on these pages. A question goes to one document,
to several (each asked by itself, then compared) or to the whole corpus.
Where a harvest is configured, the numbers it holds for a question are
shown first, as they were read and checked, and the answer from the
documents follows.

The sidebar chooses where an answer comes from: the harvest first and
then the documents, the harvest alone, the graph `--serialize` wrote
alone (for one document, where the graph is there), or the documents
alone. A harvested value shows the page it was read on, as a citation
does.

Run:
    docpipe --profile kwp chat --server.address 0.0.0.0 --server.port 8501

Author: Felix Vossel

## Functions

### get_index

```python
@st.cache_resource
def get_index()
```

Returns (faiss_index, id_to_pos) — loaded once, held in RAM.

### get_db

```python
@st.cache_resource
def get_db()
```

### get_scopes

```python
@st.cache_resource
def get_scopes()
```

The search scopes this index holds vectors of, in the fixed order.

### get_index_notice

```python
@st.cache_resource
def get_index_notice()
```

The profile's sentence for an index built with another model than the
one that embeds the questions, or None.

### get_cache

```python
@st.cache_resource
def get_cache()
```

### get_request_log

```python
@st.cache_resource
def get_request_log()
```

### get_catalog

```python
@st.cache_resource
def get_catalog()
```

The profile's catalog, or the generic one if no profile is configured.

### get_graph

```python
@st.cache_resource
def get_graph()
```

The graph `--serialize` wrote, and the trust lines above its nodes.

### get_kg_hooks

```python
@st.cache_resource
def get_kg_hooks()
```

What the profile contributes to the graph route; None without a graph.

### get_lexical

```python
@st.cache_resource
def get_lexical()
```

The word index beside the vectors, or None: missing, stale, or
turned off. `lexical.connect` says which in the log.

### get_values

```python
@st.cache_resource
def get_values()
```

(value store, harvest rows by document) of the configured harvest,
or (None, {}) where none is configured.

### get_coordinate_prompt

```python
@st.cache_resource
def get_coordinate_prompt()
```

### get_documents

```python
@st.cache_resource
def get_documents() -> dict
```

{harvest name of a document: (id, file name)}. A harvest file is
named after its document's file without the ending.

### get_labels

```python
@st.cache_resource
def get_labels() -> dict
```

{document id: what the catalog calls it}, superseded ones included.

### resolve_image_path

```python
def resolve_image_path(stored_path: str | None) -> Path | None
```

Best-effort resolution of a Tables/Images `path` to an on-disk file.

### embed_query

```python
def embed_query(item: dict, cache_conn, cache_key: str)
```

Return the query vector, from cache or a fresh on-demand embed.

### run_turn

```python
def run_turn(task: str, image_bytes: bytes | None, image_only: bool,
             document_id: int | None, scopes: list[str], as_json: bool = False,
             history: list | None = None, corpus: answer.Corpus | None = None,
             progress=None)
```

One turn, with this app's resources and its spinners attached.
`document_id` None asks the whole corpus.

### run_comparison

```python
def run_comparison(task: str, documents: list, scopes: list[str],
                   as_json: bool = False, histories: dict | None = None)
```

The same question to every selected document, then one comparison.

No image: an uploaded picture is a query anchor for one document's index,
and the same crop searched across five plans anchors four of them to
whatever happens to look similar.

### run_kg_turn

```python
def run_kg_turn(task: str, document_id: int) -> dict
```

One question to the graph; `answer_from_graph` decides everything.

### run_values_turn

```python
def run_values_turn(task: str, document_id: int | None) -> dict | None
```

What the harvest holds for the question, or None: no harvest, or
the question names nothing it has. `document_id` None asks every
document's harvest.

### values_outcome

```python
def values_outcome(task: str, document_id: int | None) -> dict | None
```

The harvest's answer with its reason where it has none
(`values_route.REASONS`), or None: no harvest, or a document the
database does not know.

### run_values_answer

```python
def run_values_answer(task: str, got: dict, document_id: int | None,
                      history: list | None = None,
                      corpus: answer.Corpus | None = None,
                      progress=None) -> dict
```

The question answered from the passages the found values were read
from (`answer.answer_from_values`), and the values the answer stands on.

{"answer", "answer_text", "citations", "made", "dropped", "faults",
 "unread", "values", "shown", "total", "result"}: `values` are the used
ones, `shown` how many the answer was given, `total` how many matched.

### graph_offered

```python
def graph_offered() -> bool
```

Whether the graph route can answer: the profile contributes to it
and the graph `--serialize` wrote is where the app is told.

### harvest_offered

```python
def harvest_offered() -> bool
```

### route_words

```python
def route_words() -> dict
```

{route key: its label in the profile's words}.

### values_reason_words

```python
def values_reason_words() -> dict
```

{reason of values_route.REASONS: why the harvest holds nothing, in
the profile's words}.

### routes_offered

```python
def routes_offered(whole: bool) -> list
```

The answer routes the sidebar offers, by their UI key. The graph
answers for one plan, so not for the whole corpus.

### main

```python
def main() -> None
```

### chat_page

```python
def chat_page() -> None
```

### axis_names

```python
def axis_names() -> dict
```

{axis: its name in the profile's words}, `inference.AXIS_NAMES`; an
axis the profile does not name is shown by its key.

### reason_words

```python
def reason_words() -> dict
```

{reason family: why a value is not an A, in the profile's words}.
The families of `exhausted:<axis>` and its kin take the axis's name.

### review_page

```python
def review_page() -> None
```

[Back to the index](../README.md)
