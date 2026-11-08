"""The example a request's prompt shows is that request's own reply (owner
decisions 2026-11-06): exactly the keys its schema asks, in the schema's
order, AND every coordinate read, never with the probe of an unstated one,
AND its printed wording wherever the grammar asks one, so beside every entry
of a list, the unit included, AND the prompt's {{example}} becomes that one
line, AND a prompt with that place but no example is not sent. Each promise
has a case that breaks it by construction beside the one that keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import combing, fields, reading, runner
from docpipe.extraction.pipeline import Source
from docpipe.extraction.spec import load as load_spec
from docpipe.prompts import Prompt

ROOT = Path(__file__).resolve().parent.parent


def spec_of(profile):
    return load_spec(json.loads((ROOT / "profiles" / profile
                                 / "extraction_spec.json").read_text(
        encoding="utf-8")))


KWP, SCENARIOS = spec_of("kwp"), spec_of("scenarios")
TABLE = Source(owner_kind="table", owner_id=7, provenance={},
               text="| Straße | Einfamilienhaus |\n|---|---|\n| Jahnstraße | 5 |")


def requests(spec):
    """(parameter, group, [slot]) of every reading request the spec makes:
    one coordinate in each (owner decision 2026-11-07), in the order of the
    spec's groups and of each group's coordinates."""
    out = []
    for parameter in spec.parameters:
        for group, slots in reading.groups_of(
                spec, reading.slots_of(spec, parameter)):
            for slot in reading.in_group_order(group, slots):
                out.append((parameter, group, [slot]))
    return out


def schema(shape):
    return shape["json_schema"]["schema"]


def one_of(entry):
    """A coordinate's schema in its one-answer form."""
    return entry["anyOf"][0] if "anyOf" in entry else entry


def keys_match(example: dict, properties: dict) -> bool:
    """The example names exactly the keys the schema does, in its order,
    the probe of an unstated entry and the last year of a span aside: an
    example shows one year read (`reading.span_rows`)."""
    return list(example) == [key for key in properties
                             if key not in ("probe", "until")]


ALL = requests(KWP) + requests(SCENARIOS)


def test_a_reading_example_has_exactly_its_requests_keys_in_order():
    assert ALL
    for parameter, group, slots in ALL:
        properties = schema(reading.text_response_format(slots))["properties"]
        example = reading.text_example(slots)
        assert keys_match(example, properties), (parameter.uri, group.name)
        for slot in slots:
            assert keys_match(example[slot.name],
                              one_of(properties[slot.name])["properties"]), \
                (parameter.uri, slot.name)


def test_one_fixed_example_misses_the_keys_of_other_requests():
    # The context example of 3a2e963 showed five coordinates where a request
    # asks another; with one coordinate to a request, the example of one
    # coordinate is not the reply of the next.
    heat_load = KWP.by_uri["heat_load"]
    asked = [slots[0] for parameter, group, slots in requests(KWP)
             if parameter is heat_load and group.name == "context"]
    assert len(asked) > 1
    fixed = reading.text_example([asked[0]])
    for other in asked[1:]:
        properties = schema(reading.text_response_format([other]))[
            "properties"]
        assert not keys_match(fixed, properties), other.name
        assert keys_match(reading.text_example([other]), properties)


def test_every_coordinate_of_an_example_is_read():
    for parameter, group, slots in ALL:
        for slot in slots:
            entry = reading.entry_example(slot)
            assert entry["value"] != fields.UNSTATED, slot.name
            assert "probe" not in entry, slot.name
            # The schema the request goes out with does take the probe.
            assert "probe" in one_of(reading.answer_schema(
                slot, probe=True))["properties"]


def test_an_entry_shows_its_printed_wording_where_the_grammar_asks_it():
    seen = set()
    for parameter, group, slots in ALL:
        for slot in slots:
            entry = reading.entry_example(slot)
            assert ("value_raw" in entry) == fields.wording_asked(slot), \
                slot.name
            seen.add((slot.name, "value_raw" in entry))
    assert ("unit", True) in seen          # a list: the unit included
    assert ("subject", False) in seen      # a wording is its own print


def test_a_year_is_shown_as_its_placeholder_and_never_as_a_year():
    # Owner decision 2026-11-07: "mach das Beispiel mit YYYY" -- the model
    # answered the example's year for a number under another year's column.
    for parameter, group, slots in ALL:
        for slot in slots:
            value = reading.entry_example(slot)["value"]
            number = not slot.is_closed and slot.kind == fields.NUMBER
            assert (value == fields.YEAR) == number, slot.name
            assert not isinstance(value, int), slot.name


def test_a_comb_example_has_exactly_its_requests_keys_in_order():
    for parameter, group, slots in ALL:
        properties = schema(combing.comb_response_format(slots))["properties"]
        example = combing.comb_example(slots)
        assert keys_match(example, properties), (parameter.uri, group.name)
        assert list(example)[-1] == "more"
        for slot in slots:
            assert keys_match(example[slot.name],
                              one_of(properties[slot.name])["properties"])
    # Another coordinate is another request with another example.
    first, second = ALL[0][2], ALL[1][2]
    assert not keys_match(combing.comb_example(second), schema(
        combing.comb_response_format(first))["properties"])


@pytest.mark.parametrize("spec", [KWP, SCENARIOS], ids=["kwp", "scenarios"])
@pytest.mark.parametrize("drawn", [False, True])
def test_a_value_example_has_exactly_its_requests_keys_in_order(spec, drawn):
    for parameter in spec.parameters:
        whole = schema(reading.values_response_format(parameter, drawn))
        example = reading.values_example(parameter, drawn)
        # The answer lists the values and says whether it holds all of them
        # (owner decisions 2026-11-08).
        assert keys_match(example, whole["properties"]), parameter.uri
        assert example["incomplete"] is False
        entry = whole["properties"]["values"]["items"]
        # The example shows the printed form; the sentence read off an image
        # in place of a quote is the alternative of the "quote" it shows
        # (`values_example`).
        keys = {key: value for key, value in entry["properties"].items()
                if key != "reading"}
        [one] = example["values"]
        assert keys_match(one, keys), parameter.uri
        assert ("reading" in entry["properties"]) == drawn, parameter.uri
        assert isinstance(one["value"], float) == bool(
            parameter.is_numeric), parameter.uri


def test_a_value_example_shows_drawn_only_for_a_request_that_sends_an_image():
    numeric = next(p for p in KWP.parameters if p.is_numeric)
    assert reading.values_example(numeric, True)["values"][0]["drawn"] \
        is False
    assert "drawn" not in reading.values_example(numeric, False)["values"][0]
    # the failure by construction: an example without the image's key is not
    # the reply of a request that sends one
    entry = reading.value_entry_schema(numeric, True)["properties"]
    assert not keys_match(reading.values_example(numeric, False)["values"][0],
                          {k: v for k, v in entry.items() if k != "reading"})


def prompt(text):
    return Prompt(id="extraction/test", text=text, meta={}, sha256="",
                  path=Path("test.md"))


EXAMPLE = {"unit": {"value": "...", "value_raw": "...", "quote": "..."}}


def test_the_place_of_the_example_becomes_one_line_of_it():
    sent = runner.system_text(prompt("Antworte so:\n{{example}}\n* Regel"),
                              EXAMPLE)
    assert sent.splitlines()[1] == json.dumps(
        EXAMPLE, ensure_ascii=False, separators=(",", ":"))
    assert "{{" not in sent


def test_a_prompt_without_the_place_is_sent_as_it_is_written():
    text = "Antworte so:\n{\"unit\":{}}"
    assert runner.system_text(prompt(text), EXAMPLE) == text
    assert runner.system_text(SimpleNamespace(text="x"), None) == "x"


def test_a_prompt_with_the_place_and_no_example_is_not_sent():
    calls = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **request: calls.append(request))))
    with pytest.raises(KeyError):
        runner.ask_in_grammar(client, prompt("{{example}}"), [],
                              reading.text_response_format([]), 1, "read_text",
                              "unit")
    assert calls == []


def test_a_request_sends_its_own_example():
    sent = []

    def create(**request):
        sent.append(request["messages"][0]["content"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(
                content=json.dumps({"unit": {"value": "MWh"}})))])
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    slots = [slot for slot in reading.slots_of(
        KWP, KWP.by_uri["energy_consumption"]) if slot.name == "unit"]
    runner.ask_in_grammar(client, prompt("So:\n{{example}}"), [],
                          reading.text_response_format(slots), 1, "read_text",
                          "unit", example=reading.text_example(slots))
    shown = json.loads(sent[0].splitlines()[1])
    assert list(shown) == ["unit"]
    assert list(shown["unit"]) == ["value", "value_raw", "quote"]
