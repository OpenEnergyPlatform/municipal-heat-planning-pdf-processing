"""Pulling a profile's sources at upstream's current version.

No network: github.com, raw.githubusercontent.com and the OEKG endpoint are
replaced by dictionaries. What is tested is what the answers are turned into.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe import upstream                                    # noqa: E402

GH = "https://github.com"
RAW = "https://raw.githubusercontent.com"


@pytest.fixture
def web(monkeypatch):
    """{url: bytes} for downloads, {url: location} for redirects."""
    pages, redirects, asked = {}, {}, []

    def get(url, *, data=None, headers=None):
        asked.append((url, data, headers))
        if url not in pages:
            raise upstream.UpstreamError(f"{url}: HTTP 404", 404)
        if isinstance(pages[url], Exception):
            raise pages[url]
        return pages[url]

    monkeypatch.setattr(upstream, "_get", get)
    monkeypatch.setattr(upstream, "_location", lambda url: redirects.get(url))
    return pages, redirects, asked


def test_the_latest_release_is_read_off_the_redirect(web):
    _pages, redirects, _ = web
    redirects[f"{GH}/o/r/releases/latest"] = f"{GH}/o/r/releases/tag/v2.14.0"
    assert upstream.latest_release("o/r") == "v2.14.0"
    redirects[f"{GH}/o/r/releases/latest"] = f"{GH}/o/r/releases"
    assert upstream.latest_release("o/r") is None


def test_an_asset_is_stored_under_its_tag_and_not_fetched_twice(web, tmp_path):
    pages, redirects, asked = web
    redirects[f"{GH}/o/r/releases/latest"] = f"{GH}/o/r/releases/tag/v1"
    url = f"{GH}/o/r/releases/download/v1/closure.owl"
    pages[url] = b"<rdf/>"
    source = {"o": {"kind": "release_asset", "repo": "o/r",
                    "asset": "closure.owl"}}
    record = upstream.fetch(source, tmp_path)["o"]
    assert record["version"] == "v1"
    assert upstream.files(record, ".owl") == [tmp_path / "o" / "v1" / "closure.owl"]
    upstream.fetch(source, tmp_path)
    assert [a for a in asked if a[0] == url] == [(url, None, None)]


def test_a_repository_without_a_release_stops_unless_it_is_awaited(web, tmp_path):
    _pages, redirects, _ = web
    redirects[f"{GH}/o/m/releases/latest"] = f"{GH}/o/m/releases"
    source = {"kind": "release_asset", "repo": "o/m", "asset": "m.owl"}
    with pytest.raises(upstream.UpstreamError, match="has no release"):
        upstream.fetch({"m": source}, tmp_path)
    record = upstream.fetch({"m": {**source, "until_released": True}},
                            tmp_path)["m"]
    assert record["version"] is None and record["files"] == []
    assert "no release yet" in upstream.summary("m", record)


def test_a_release_without_the_named_asset_says_which_asset(web, tmp_path):
    _pages, redirects, _ = web
    redirects[f"{GH}/o/r/releases/latest"] = f"{GH}/o/r/releases/tag/v3"
    with pytest.raises(upstream.UpstreamError, match="no asset 'gone.owl'"):
        upstream.fetch({"o": {"kind": "release_asset", "repo": "o/r",
                              "asset": "gone.owl"}}, tmp_path)


def test_repo_files_name_what_changed_since_the_reviewed_commit(web, tmp_path):
    pages, _redirects, _ = web
    for ref, shapes in (("production", b"new shapes"), ("abc1234", b"old")):
        pages[f"{RAW}/o/k/{ref}/s/shapes.shacl.ttl"] = shapes
        pages[f"{RAW}/o/k/{ref}/s/mint.py"] = b"same"
    pages[f"{RAW}/o/k/production/s/added.yaml"] = b"x"
    source = {"kind": "repo_files", "repo": "o/k", "ref": "production",
              "reviewed": "abc1234",
              "files": ["s/shapes.shacl.ttl", "s/mint.py", "s/added.yaml"]}
    record = upstream.fetch({"k": source}, tmp_path)["k"]
    assert record["changed_since_reviewed"] == [
        "s/shapes.shacl.ttl", "s/added.yaml (new since abc1234)"]
    assert record["compare"] == f"{GH}/o/k/compare/abc1234...production"
    assert upstream.files(record, ".shacl.ttl") == [
        tmp_path / "k" / "head" / "production" / "s" / "shapes.shacl.ttl"]
    # The version is the bytes, so an unchanged head is an unchanged version.
    again = upstream.fetch({"k": source}, tmp_path)["k"]
    assert again["version"] == record["version"]
    pages[f"{RAW}/o/k/production/s/mint.py"] = b"edited"
    assert upstream.fetch({"k": source}, tmp_path)["k"]["version"] \
        != record["version"]


def test_a_failed_request_against_the_reviewed_commit_is_not_a_new_file(
        web, tmp_path):
    """Only a 404 means the file did not exist then. A server error is a
    refresh that failed, not drift."""
    pages, _redirects, _ = web
    pages[f"{RAW}/o/k/production/s/a.ttl"] = b"x"
    pages[f"{RAW}/o/k/abc1234/s/a.ttl"] = upstream.UpstreamError("HTTP 502", 502)
    source = {"kind": "repo_files", "repo": "o/k", "ref": "production",
              "reviewed": "abc1234", "files": ["s/a.ttl"]}
    with pytest.raises(upstream.UpstreamError, match="502"):
        upstream.fetch({"k": source}, tmp_path)


def test_a_transfer_cut_short_is_an_upstream_error(monkeypatch):
    import http.client

    class Cut:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"12345", 95)

    monkeypatch.setattr(upstream.urllib.request, "urlopen",
                        lambda request, timeout: Cut())
    with pytest.raises(upstream.UpstreamError, match="IncompleteRead"):
        upstream._get("https://example.org/closure.owl")


def test_a_live_query_needs_its_token_and_writes_it_nowhere(web, tmp_path,
                                                            monkeypatch):
    pages, _redirects, asked = web
    endpoint = "https://oekg.example/sparql/"
    result = {"results": {"bindings": [
        {"region": {"value": "r/Chad"}, "label": {"value": "Chad"}}]}}
    # The endpoint answers with a JSON string holding the JSON.
    pages[endpoint] = json.dumps(json.dumps(result)).encode()
    source = {"kind": "sparql", "endpoint": endpoint, "token_env": "T_TOKEN",
              "query": "SELECT ?region ?label WHERE {}"}
    monkeypatch.delenv("T_TOKEN", raising=False)
    with pytest.raises(upstream.UpstreamError, match="T_TOKEN is not set"):
        upstream.fetch({"regions": source}, tmp_path)
    monkeypatch.setenv("T_TOKEN", "secret-value")
    record = upstream.fetch({"regions": source}, tmp_path)["regions"]
    assert record["rows"] == 1
    rows = json.loads(upstream.files(record)[0].read_text(encoding="utf-8"))
    assert rows == [{"region": "r/Chad", "label": "Chad"}]
    assert asked[-1][2]["Authorization"] == "Token secret-value"
    lock = upstream.write_lock("p", {"regions": record}, tmp_path)
    for path in [lock, *tmp_path.rglob("*")]:
        if path.is_file():
            assert "secret-value" not in path.read_text(encoding="utf-8")


def test_the_lock_round_trips_and_an_unknown_kind_is_refused(tmp_path):
    assert upstream.load_lock("p", tmp_path) is None
    upstream.write_lock("p", {"o": {"kind": "release_asset", "version": "v1",
                                    "files": []}}, tmp_path)
    lock = upstream.load_lock("p", tmp_path)
    assert lock["sources"]["o"]["version"] == "v1" and lock["fetched_at"]
    with pytest.raises(upstream.UpstreamError, match="unknown kind"):
        upstream.fetch({"x": {"kind": "ftp"}}, tmp_path)


# ---------------------------------------------------------------------------
# What the profiles make of it
# ---------------------------------------------------------------------------

def test_regions_come_from_the_graph_and_keep_the_hand_spellings():
    from profiles.scenarios import vocabulary
    base = vocabulary.REGION_BASE
    rows = [{"region": base + "CaboVerde", "label": "Cabo Verde"},
            {"region": base + "CaboVerde", "label": "Republic of Cabo Verde"},
            {"region": base + "Chad", "label": "Chad "},
            {"region": base + "Chad", "label": "Chad"},
            {"region": base + "Atlantis"}]
    aliases = {base + "CaboVerde": ["Cabo Verde", "Cape Verde"],
               base + "Atlantis": ["Atlantis"],
               base + "Gone": ["Gone"]}
    assert vocabulary.merge_regions(rows, aliases) == {
        base + "Atlantis": ["Atlantis"],
        base + "CaboVerde": ["Cabo Verde", "Cape Verde",
                             "Republic of Cabo Verde"],
        base + "Chad": ["Chad"]}
    with pytest.raises(upstream.UpstreamError, match="has no label"):
        vocabulary.merge_regions([{"region": base + "Nowhere"}], aliases)
    with pytest.raises(upstream.UpstreamError, match="returned no region"):
        vocabulary.merge_regions([], aliases)


def test_the_checked_in_regions_are_what_a_refresh_writes_back():
    """Today's list, pulled again with nothing changed upstream, is the same
    file: the aliases carry every spelling it has."""
    from profiles.scenarios import vocabulary
    regions = json.loads(vocabulary.REGIONS_PATH.read_text(encoding="utf-8"))
    aliases = json.loads(vocabulary.ALIASES_PATH.read_text(encoding="utf-8"))
    rows = [{"region": iri, "label": label}
            for iri, labels in regions.items() for label in labels]
    assert vocabulary.merge_regions(rows, aliases) == regions


def test_kwp_refresh_builds_the_snapshot_from_what_it_pulled(tmp_path,
                                                             monkeypatch):
    from profiles.kwp import vocabulary
    closure = tmp_path / "oeo-closure.owl"
    closure.write_text("x")
    records = {
        "oeo": {"kind": "release_asset", "version": "v9.0.0",
                "files": [{"path": str(closure)}]},
        "mhpo": {"kind": "release_asset", "version": None, "files": [],
                 "note": "no release yet"},
        "mhpkg": {"kind": "repo_files", "version": "abc", "files": [
            {"path": str(tmp_path / "a.shacl.ttl")},
            {"path": str(tmp_path / "mint_slice.py")}]},
    }
    built = {}

    def build(closure_path, mhpo=None):
        built.update(closure=closure_path, mhpo=mhpo)
        return {"pin": {"oeo_version_iri": "x/releases/9.0.0/oeo.owl"},
                "sets": {}, "terms": {}, "disjoint": []}

    monkeypatch.setattr(vocabulary.upstream, "fetch", lambda s, c: records)
    monkeypatch.setattr(vocabulary, "build", build)
    monkeypatch.setattr(vocabulary, "VOCABULARY_PATH", tmp_path / "v.json")
    vocabulary.refresh(tmp_path)
    assert built == {"closure": closure, "mhpo": None}
    written = json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))
    assert written["pin"]["sources"] == {"oeo": "v9.0.0", "mhpo": None,
                                         "mhpkg": "abc"}
    assert vocabulary.shapes(tmp_path) == [tmp_path / "a.shacl.ttl"]


def test_kwp_names_its_sources_and_waits_for_an_mhpo_release():
    from profiles.kwp import vocabulary
    assert vocabulary.SOURCES["oeo"]["asset"] == "oeo-closure.owl"
    assert vocabulary.SOURCES["mhpo"]["until_released"] is True
    assert len(vocabulary.SOURCES["mhpkg"]["reviewed"]) == 40
    assert vocabulary.shapes(Path("/nonexistent")) == []


# ---------------------------------------------------------------------------
# The written graph against the shapes
# ---------------------------------------------------------------------------

SHAPES = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
ex:ThingShape a sh:NodeShape ; sh:targetClass ex:Thing ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""
POLICY = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
ex:OtherShape a sh:NodeShape ; sh:targetClass ex:Thing ;
    sh:property [ sh:path ex:size ; sh:maxCount 1 ] .
"""


def test_the_graph_is_reported_against_every_shapes_file(tmp_path):
    """Both files count. pyshacl given two `-s` flags uses only the last."""
    pytest.importorskip("pyshacl")
    from docpipe.extraction import serialize
    shapes = [tmp_path / "a.shacl.ttl", tmp_path / "b.shacl.ttl"]
    shapes[0].write_text(SHAPES, encoding="utf-8")
    shapes[1].write_text(POLICY, encoding="utf-8")
    ttl = tmp_path / "graph.ttl"
    ttl.write_text("@prefix ex: <http://example.org/> .\n"
                   "<http://example.org/thing/1> a ex:Thing ; ex:size 1, 2 .\n",
                   encoding="utf-8")
    report = serialize.validate(ttl, shapes)
    assert report["conforms"] is False and report["violations"] == 2
    assert {c[0][0] for c in report["counts"]} == {"MinCount", "MaxCount"}
    assert (tmp_path / "graph.ttl.shacl.txt").is_file()
    assert ttl.is_file()
    ttl.write_text("@prefix ex: <http://example.org/> .\n"
                   "<http://example.org/thing/1> a ex:Thing ; ex:name 'x' .\n",
                   encoding="utf-8")
    assert serialize.validate(ttl, shapes)["conforms"] is True
    # A violation on a blank node has no collection segment to count by.
    ttl.write_text("@prefix ex: <http://example.org/> .\n[] a ex:Thing .\n",
                   encoding="utf-8")
    report = serialize.validate(ttl, shapes)
    assert report["violations"] == 1 and report["counts"][0][0][2] == "?"
