"""
Where the document says a missing detail at another place or points to it,
the model may fetch that place itself (owner decision 2026-11-12).

The promise: a question at a value's own place, of a field of the whole
document, of a name and of a cited work's detail may ask for pieces (the
rule `fetches` of its step), AND what the value's own place fetched comes
first in the search after it, before the pieces beside the value, AND what a
field of the whole document fetched comes first in its next request, AND a
name or a work's detail is asked again with the fetched pieces under
"passages" (as often as `fetch_rounds` says), its answer may name a line of
them and is checked as always, AND a question about a dimension may ask once
for the picture of a figure it shows and is asked again with it, its answer
still a shown line, AND the runner sends that picture beside the message and
tells the request about fetching only where its reply may fetch. Broken by
construction: the step's `fetches` empty, `fetch_rounds` 0, a figure without
a picture, a request whose reply may not fetch.
"""
import dataclasses
import json
from types import SimpleNamespace

from docpipe import rules
from docpipe.extraction import addressed, fields, flow, runner
from docpipe.extraction.addressed import Found, Names, Plan
from docpipe.extraction.pipeline import Source
from docpipe.profile import load_profile

from test_addressed import (CAPTION, ENERGY, FIGURE, Model, NUMBERS, SCENARIOS,
                            SPEC, TITLE, WORK_PLAN, NAMES_IN, plan_of,
                            reader_of, work_of_piece)


class Shaped(Model):
    """A Model that keeps the reply form each request was given."""

    def asks(self, check: bool = True):
        made = super().asks(check)
        self.shapes: list = []

        def keeping(kind, ask):
            def keep(payload, document_id, /, *, shape, example, **noted):
                self.shapes.append((kind, payload, shape, noted))
                return ask(payload, document_id, shape=shape,
                           example=example, **noted)
            return keep
        for kind in ("find", "docfield", "coord", "search", "names"):
            setattr(made, kind, keeping(kind, getattr(made, kind)))
        return made


def gets(shape) -> list:
    """The ways of fetching a reply form offers, [] where it offers none."""
    more = shape["json_schema"]["schema"]["properties"].get("more")
    return more["items"]["properties"]["get"]["enum"] if more else []


def first_block(payload) -> str:
    blocks = list((payload.get("passages") or {}).values())
    return " ".join(blocks[0]["lines"]) if blocks else ""


def address_of(payload, words: str) -> str:
    """The address the request shows a line holding *words* under."""
    for block in (payload.get("passages") or {}).values():
        for line in block["lines"]:
            if words in line:
                return line.split(" ", 1)[0]
    raise AssertionError(f"no shown line holds {words!r}")


# -- the value's own place ---------------------------------------------------

VALUE = Source("section", 2, "Die Stadt verbrauchte 300 MWh Erdgas, siehe "
                             "Anhang B.", {"document_id": 7, "page": 2})
FILLERS = [Source("section", 3 + i, f"Abschnitt {i}. Er nennt nichts.",
                  {"document_id": 7, "page": 3 + i}) for i in range(8)]
APPENDIX = Source("section", 30, "Anhang B: Alle Zahlen gelten für das "
                                 "Bilanzjahr 2019.",
                  {"document_id": 7, "page": 30})


def read_year():
    def search(payload, noted):
        if noted["coordinate"] != "year":
            return {"at": 0}
        for letter, block in payload["passages"].items():
            for line in block["lines"]:
                if "Bilanzjahr 2019" in line:
                    return {"at": line.split(" ", 1)[0], "words": "2019"}
        return {"at": 0}
    model = Shaped(
        find=lambda p, n: {"found": [{"at": "1", "words": "300"}]}
        if "300 MWh" in json.dumps(p, ensure_ascii=False) else {"found": []},
        coord=lambda p, n: {"at": 0, "more": [
            {"get": "search", "pattern": "Anhang B:"}]}
        if n["coordinate"] == "year" else {"at": 0},
        search=search)
    reads = reader_of(model)(plan_of(VALUE, *FILLERS, APPENDIX), [ENERGY])
    (claim,) = [c for r in reads for c in r.claims]
    asked = [(payload, shape) for kind, payload, shape, noted in model.shapes
             if kind == "search" and noted["coordinate"] == "year"]
    coord = [shape for kind, payload, shape, noted in model.shapes
             if kind == "coord" and noted["coordinate"] == "year"]
    return claim, model, asked, coord


def test_the_question_at_the_value_s_place_may_fetch_what_a_line_points_to():
    claim, model, asked, coord = read_year()
    assert "search" in gets(coord[0])
    year = [(p, s) for p, s in asked
            if "Bilanzjahr" in json.dumps(p, ensure_ascii=False)]
    # the piece the line points to comes first, before the pieces beside it
    assert "Anhang B: Alle Zahlen" in first_block(asked[0][0])
    assert year and claim["year"] == 2019
    assert "Bilanzjahr 2019" in claim["year_quote"]
    # the failure by construction: the step may fetch nothing, so it is
    # offered nothing and the search starts with the pieces beside the value
    with rules.overlaid(fetches=[]):
        claim, model, asked, coord = read_year()
    assert gets(coord[0]) == []
    assert "Anhang B: Alle Zahlen" not in first_block(asked[0][0])


# -- a field of the whole document -------------------------------------------

def test_a_field_of_the_whole_document_shows_what_it_fetched_first_next():
    sector = SCENARIOS.by_uri["study_sector"]
    many = [Source("section", 10 + i, f"Abschnitt {i}. Er nennt nichts.",
                   {"document_id": 7, "page": 2 + i}) for i in range(12)]

    def asked():
        model = Shaped(docfield=lambda p, n: {
            "found": [], "more": [{"get": "search",
                                   "pattern": "Abschnitt 11"}]})
        numbers = dataclasses.replace(flow.default(), listed_field_factor=1)
        reader_of(model, spec=SCENARIOS, budget=4, numbers=numbers)(
            plan_of(TITLE, *many), [sector])
        return [(p, s) for kind, p, s, _n in model.shapes
                if kind == "docfield"]
    requests = asked()
    assert "search" in gets(requests[0][1])
    # the fetched piece comes first, beyond the budget of four
    assert len(requests) == 2
    assert "Abschnitt 11" in first_block(requests[1][0])
    # the failure by construction: nothing to fetch, one request
    with rules.overlaid(fetches=[]):
        requests = asked()
    assert len(requests) == 1 and gets(requests[0][1]) == []


# -- a name -------------------------------------------------------------------

NAMED = Source("table", 12, "Table 2: Scenarios\n| Scenario | 2050 |\n"
                            "| --- | --- |\n| KN2045 | 80 |",
               {"document_id": 7, "page": 2})
EXPLAINED = Source("section", 40, "KN2045 stands for the scenario "
                                  "Klimaneutral 2045 of this study.",
                   {"document_id": 7, "page": 9})


def name_kn2045():
    def names(payload, noted):
        if "passages" not in payload:
            return {"entry": "new",
                    "more": [{"get": "search", "pattern": "stands for"}]}
        return {"entry": 1}
    model = Shaped(names=names)
    reader = reader_of(model, spec=SCENARIOS)
    plan = plan_of(NAMED, *FILLERS, EXPLAINED)
    plan.names["scenario"] = Names("scenario")
    plan.names["scenario"].add("Klimaneutral 2045")
    passage = plan.passages[("table", 12)]
    line = next(one for one in passage.lines if "KN2045" in one.text)
    got = Found(lines=[(line, passage.source)], passage=passage,
                words="KN2045")
    picked = reader.name_of(plan, "scenario", "KN2045", got,
                            addressed.Counts())
    return picked, [(p, s) for kind, p, s, _n in model.shapes
                    if kind == "names"]


def test_a_name_is_asked_again_with_the_place_that_says_what_it_means():
    picked, asked = name_kn2045()
    assert len(asked) == 2 and "search" in gets(asked[0][1])
    assert "Klimaneutral 2045 of this study" in first_block(asked[1][0])
    assert picked == [("Klimaneutral 2045", 1)]
    # the failure by construction: asked once, the first answer stands
    with rules.overlaid(fetch_rounds=0):
        picked, asked = name_kn2045()
    assert len(asked) == 1 and picked == [("KN2045", 2)]


# -- a cited work's details --------------------------------------------------

REFERENCES = Source("section", 90, "References\nIRENA (2018). Global energy "
                                   "transformation: a roadmap to 2050. "
                                   "International Renewable Energy Agency, "
                                   "Abu Dhabi.",
                    {"document_id": 7, "page": 30,
                     "section_title": "References"})


def organisations():
    label = SCENARIOS.by_uri["scenario_label"]
    organisation = SCENARIOS.by_uri["study_organisation"]

    def coord(payload, noted):
        if "list" in payload:
            return {"entry": 0}
        if payload.get("work") == "IRENA 2018" \
                and noted["parameter"] == organisation.uri:
            if "passages" not in payload:
                return {"at": 0, "more": [{"get": "search",
                                           "pattern": "Energy Agency"}]}
            return {"at": address_of(payload, "Energy Agency"),
                    "words": "International Renewable Energy Agency"}
        return {"at": 0}
    model = Shaped(
        work=work_of_piece, coord=coord,
        find=lambda p, n: {"found": [{"at": at, "words": words}
                                     for at, words in NAMES_IN.get(
                                         n.get("owner"), ())]}
        if n.get("parameter") == label.uri else {"found": []})
    reader = reader_of(model, spec=SCENARIOS, works=SCENARIOS.works)
    reads = reader(plan_of(*WORK_PLAN, REFERENCES), [label])
    return [(claim, read.batch.items[0].source) for read in reads
            if read.batch.parameter is organisation for claim in read.claims]


def test_a_cited_work_s_detail_may_fetch_its_entry_in_the_references():
    (claim, source), = organisations()
    assert claim["value"] == "International Renewable Energy Agency"
    assert (source.owner_kind, source.owner_id) == ("section", 90)
    assert claim["work_state"] == fields.READ
    # the failure by construction: nothing fetched, nothing read
    with rules.overlaid(fetch_rounds=0):
        assert organisations() == []


# -- the picture of a figure --------------------------------------------------

def read_carrier(picture="fig5.png", again=False):
    def coord(payload, noted):
        if noted["coordinate"] != "carrier":
            return {"at": 0}
        if "image" in payload and not again:
            return {"found": [{"at": "2", "words": "Erdgas"}]}
        return {"found": [], "more": [{"get": "image"}]}
    model = Shaped(find=lambda p, n: {"found": [{"at": "2",
                                                  "words": "1.200"}]},
                   coord=coord, list=lambda p, n: {"entry": 1})
    plan = Plan(7, [FIGURE], {5: {"caption": CAPTION, "numbers": NUMBERS}}, 8)
    reader = reader_of(model, image_of=lambda source: picture
                       if source.owner_kind == "figure" else None)
    (claim,) = [c for r in reader(plan, [ENERGY]) for c in r.claims]
    return claim, [(p, s) for kind, p, s, noted in model.shapes
                   if kind == "coord" and noted["coordinate"] == "carrier"]


def test_a_coordinate_may_ask_once_for_the_picture_of_a_figure_it_shows():
    claim, asked = read_carrier()
    first, second = asked[:2]
    assert addressed.IMAGE in gets(first[1])
    assert second[0]["image"] == "passage"
    assert second[0][addressed.PICTURE] == "fig5.png"
    # one picture a request: the request with it may ask for none
    assert addressed.IMAGE not in gets(second[1])
    assert claim["carrier"] == "Erdgas"
    assert claim["carrier_state"] == fields.READ
    # each picture once: a reply that asks for it again is not asked again
    claim, asked = read_carrier(again=True)
    assert len([p for p, _s in asked if addressed.PICTURE in p]) == 1
    # the failure by construction: a figure without a picture offers none
    claim, asked = read_carrier(picture=None)
    assert addressed.IMAGE not in gets(asked[0][1])
    assert not [p for p, _s in asked if addressed.PICTURE in p]


# -- what the runner sends ----------------------------------------------------

def test_a_request_with_a_picture_sends_it_beside_its_message(monkeypatch,
                                                             tmp_path):
    from PIL import Image
    picture = tmp_path / "fig.png"
    Image.new("RGB", (8, 8), "white").save(picture)
    sent = []

    def create(**request):
        sent.append(request["messages"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                content='{"at": "2", "words": "Erdgas"}'))])
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(runner, "_client", lambda: client)
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)
    asks = runner.make_asks(load_profile("scenarios"))
    payload = {"value": {"words": "1.200", "at": "2"},
               "passage": {"lines": ["2 Erdgas: 1.200 MWh"]},
               "question": "Which energy carrier?"}
    example = {"at": "2", "words": "..."}
    asks.coord({**payload, "image": "passage",
                addressed.PICTURE: str(picture)}, 7,
               shape=addressed.coord_format(False, more=True), example=example)
    asks.coord(payload, 7, shape=addressed.coord_format(False, more=True,
                                                       image=True),
               example=example)
    asks.coord(payload, 7, shape=addressed.coord_format(False),
               example=example)
    with_picture, offered, plain = sent
    text, image = with_picture[-1]["content"]
    assert image["type"] == "image_url" and text["type"] == "text"
    assert addressed.PICTURE not in text["text"]
    assert "is attached" in with_picture[0]["content"]
    assert '"more"' in offered[0]["content"]
    assert "asks for the picture" in offered[0]["content"]
    # the failure by construction: a reply that may not fetch is told
    # nothing of it, and a request without a picture sends text alone
    assert '"more"' not in plain[0]["content"]
    assert isinstance(plain[-1]["content"], str)
