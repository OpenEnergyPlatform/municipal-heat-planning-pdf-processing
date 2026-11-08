"""A year is a number the profile takes for a year."""
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

import pytest

from docpipe.extraction import pipeline, runner


@dataclass
class Source:
    text: str
    owner_kind: str = "table"
    owner_id: int = 1
    image_path: Optional[str] = "crop.png"


class Years:
    def component(self, stage, name):
        return (1900, 2100) if name == "YEAR_RANGE" else None


@pytest.fixture
def years(monkeypatch):
    monkeypatch.setattr(pipeline, "active_profile", lambda: Years())


NUMBER = SimpleNamespace(kind=pipeline.NUMBER)


@pytest.mark.parametrize("given", [2045, 2045.0, "2045", 1900, 2100])
def test_a_year_in_the_range_passes(years, given):
    assert pipeline._wrong_type(NUMBER, given) is None


@pytest.mark.parametrize("given", [169002, 169002.0, "169002", 1899, 2101])
def test_a_number_outside_the_range_is_refused(years, given):
    assert pipeline._wrong_type(NUMBER, given) is not None


def test_a_profile_without_a_range_takes_every_whole_number(monkeypatch):
    monkeypatch.setattr(pipeline, "active_profile", lambda: None)
    assert pipeline._wrong_type(NUMBER, 169002) is None


def test_the_frame_refuses_a_zone_number_as_its_year(years):
    source = Source("| 169002 | Toddin | 113 |", "table")
    year = SimpleNamespace(name="year", kind=pipeline.NUMBER, options=())
    rejected = []
    pairs = runner.frame_pairs(
        {"pairs": [{"year": 169002, "year_quote": "| 169002 | Toddin | 113 |",
                    "year_source": "Q1"}]}, [year], [source], rejected)
    assert pairs == [] and len(rejected) == 1


def test_the_frame_takes_a_year_it_can_read(years):
    source = Source("Zieljahr 2045 im Szenario", "section")
    year = SimpleNamespace(name="year", kind=pipeline.NUMBER, options=())
    pairs = runner.frame_pairs(
        {"pairs": [{"year": 2045, "year_quote": "Zieljahr 2045 im Szenario",
                    "year_source": "Q1"}]}, [year], [source], [])
    assert [p["year"] for p in pairs] == [2045]


