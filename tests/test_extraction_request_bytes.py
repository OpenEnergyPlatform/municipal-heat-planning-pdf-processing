"""The requests a normal harvest sends are the bytes they were.

A pass that appends one parameter to a stored harvest shares the harvest's
request code, and the code that plans and folds a document was lifted out of
`runner.main` to be shared. A key added, a key reordered or a quantity
filtered in a request changes what every model on every document reads, and
nothing would fail: the answers would only be other answers. So the rows
request body, the rows prompt and the rows reply grammar are held here against
a file captured from the code before the lift, for both profiles that have a
harvest.

The text in the file is made up for the test and belongs to no corpus. To
write the file again after a change somebody decided on:
`python tests/test_extraction_request_bytes.py write`.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden"
PROFILES = ("kwp", "scenarios")


def request_bodies(profile: str) -> dict:
    """What a harvest says about the rows request of a made-up batch, for the
    profile's own spec: the body as the harvester sends it, the grammar the
    reply is asked in, and the sha256 of the prompt the model reads."""
    os.environ["DOCPIPE_PROFILE"] = profile
    from docpipe import prompts
    from docpipe.extraction import replies, runner
    from docpipe.extraction.pipeline import Batch, Source, WorkItem
    from docpipe.extraction.spec import load as load_spec

    spec = load_spec(json.loads((ROOT / "profiles" / profile
                                 / "extraction_spec.json")
                                .read_text(encoding="utf-8")))
    text = "Tabelle 4: Zielszenario 2045\n| Erdgas | 17.000 | MWh/a |"
    batch = Batch(7, None, [
        WorkItem(7, None, Source("table", 5, text,
                                 {"title": "Tabelle 4",
                                  "section_title": "Szenarien", "page": 5})),
        WorkItem(7, None, Source("section", 9, "Das Basisjahr ist 2020.",
                                 {"title": "Einleitung", "page": 2}))])
    if profile == "kwp":
        batch.frame = {"scenario": "target", "scenario_raw": "Zielszenario",
                       "scenario_quote": "Zielszenario",
                       "scenario_source": ["table", 5], "year": 2045,
                       "year_quote": "2045", "year_source": ["table", 5]}
        batch.frame_index = 1
        batch.pairs = (batch.frame,)
        batch.bases = ({"axis": "year", "year": 2020,
                        "quote": "Das Basisjahr ist 2020.",
                        "source": ["section", 9], "index": 0},)
    batch.anchors = ("Der Endenergiebedarf 2045 im Zielszenario.",)
    batch.spec = spec
    prior = [{"parameter": spec.parameters[0].uri, "value": 12.5,
              "unit": "MWh/a", "quote": "| Fernwaerme | 12,5 | MWh/a |",
              "unit_quote": "MWh/a", "tier": "text_located",
              "provenance": {"document_id": 7}}]
    sent = json.dumps(runner._batch_payload(batch, prior,
                                            runner.spec_of(batch, spec)),
                      ensure_ascii=False, indent=2)
    unframed = Batch(7, None, list(batch.items))
    return {
        "rows_request": sent,
        "rows_request_unframed": json.dumps(
            runner._batch_payload(unframed, [], spec), ensure_ascii=False,
            indent=2),
        "rows_reply_grammar": replies.rows(sandbox=True),
        "rows_prompt_sha256": hashlib.sha256(
            prompts.load("extraction/rows").text.encode("utf-8")).hexdigest(),
    }


def _golden(profile: str) -> Path:
    return GOLDEN / f"extraction_requests_{profile}.json"


@pytest.mark.parametrize("profile", PROFILES)
def test_a_normal_harvest_request_is_byte_for_byte_what_it_was(profile,
                                                               monkeypatch):
    """The body, the grammar and the prompt of the rows request, captured
    before the lift. Any key added to it, reordered in it or filtered out of
    it moves the bytes and fails here."""
    monkeypatch.setenv("DOCPIPE_PROFILE", profile)
    held = json.loads(_golden(profile).read_text(encoding="utf-8"))
    now = request_bodies(profile)
    assert now["rows_request"] == held["rows_request"]
    assert now["rows_request_unframed"] == held["rows_request_unframed"]
    assert now["rows_reply_grammar"] == held["rows_reply_grammar"]
    assert now["rows_prompt_sha256"] == held["rows_prompt_sha256"]


def test_the_golden_file_can_fail(monkeypatch):
    """A comparison that cannot fail is decoration: one quantity less in the
    body is not the body the file holds."""
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")
    held = json.loads(_golden("kwp").read_text(encoding="utf-8"))
    body = json.loads(held["rows_request"])
    assert body["quantities"], "the body names the quantities it asks for"
    body["quantities"] = body["quantities"][:-1]
    assert json.dumps(body, ensure_ascii=False, indent=2) != held[
        "rows_request"]


if __name__ == "__main__":
    if sys.argv[1:] == ["write"]:
        sys.path.insert(0, str(ROOT))
        for name in PROFILES:
            _golden(name).write_text(
                json.dumps(request_bodies(name), ensure_ascii=False,
                           indent=1) + "\n", encoding="utf-8")
