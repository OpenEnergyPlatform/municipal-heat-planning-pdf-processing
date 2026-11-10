"""A year is a number the profile takes for a year."""
from types import SimpleNamespace

import pytest

from docpipe import rules
from docpipe.extraction import pipeline


@pytest.fixture
def years():
    with rules.overlaid(year_range=[1900, 2100]):
        yield


NUMBER = SimpleNamespace(kind=pipeline.NUMBER)


@pytest.mark.parametrize("given", [2045, 2045.0, "2045", 1900, 2100])
def test_a_year_in_the_range_passes(years, given):
    assert pipeline._wrong_type(NUMBER, given) is None


@pytest.mark.parametrize("given", [169002, 169002.0, "169002", 1899, 2101])
def test_a_number_outside_the_range_is_refused(years, given):
    assert pipeline._wrong_type(NUMBER, given) is not None


def test_a_profile_without_a_range_takes_every_whole_number():
    with rules.overlaid(year_range=None):
        assert pipeline._wrong_type(NUMBER, 169002) is None
