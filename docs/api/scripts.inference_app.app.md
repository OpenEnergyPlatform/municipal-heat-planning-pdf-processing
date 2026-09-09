# scripts.inference_app.app

`scripts/inference_app/app.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

app.py: Streamlit RAG chat over a docpipe corpus, the only module in this
package that imports Streamlit.

What the corpus is about comes from the profile: its catalog supplies the
labels, the filters and the detail shown for a selected document. With a
graph configured (`INFERENCE_KG_TTL_PATH`, the file `--serialize` wrote) a
question goes to the graph first, and to the documents only when the graph
states why it has no answer.

Run:
    DOCPIPE_PROFILE=kwp streamlit run scripts/inference_app/app.py \
        --server.address 0.0.0.0 --server.port 8501

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
             document_id: int, scopes: list[str], as_json: bool = False,
             history: list | None = None)
```

One turn, with this app's resources and its spinners attached.

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

### main

```python
def main() -> None
```

[Back to the index](../README.md)
