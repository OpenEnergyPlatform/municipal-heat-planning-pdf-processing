"""The table check measures a transcription only against a PDF text that can
be read as the table (owner decision 2026-11-11): a coverage that falls short
goes unassessed only where less than a quarter of the transcription stands in
the PDF text AND less than half of that text's words occur in the rest of the
document. Everywhere else a short coverage fails the table.

Built on the shape of a real case: a scanned book whose OCR layer reads its
sideways tables upside down ("Ayjiqixayy" for "flexibility"). Each AND has a
case that breaks it by construction beside the one that keeps it."""
from docpipe.visuals import qa

LIMITS = dict(min_coverage=0.5, max_duplication=0.4, min_source_tokens=8,
              max_shared=0.25, min_known=0.5)

DOCUMENT = qa.words(
    "Flexibility options differ in efficiency: demand-based transmission and "
    "generation, storage, and more. Renewables such as solar, wind and hydro "
    "replace nuclear, coal, oil and gas. The district heating plan covers the "
    "households of eight towns.")

UPSIDE_DOWN = ("Ayjiqixayy ssa] Aoua!o!jja paseq-pueuap uoissiusuen pue "
               "uoneiauab dw! 0S0Z S'Z")
SIDEWAYS_TABLE = ("| Option | Flexibility | Efficiency gain (%) |\n"
                  "| --- | --- | --- |\n"
                  "| Demand-based transmission and generation | less | 2.5 |\n"
                  "| Storage | more | 1.0 |")


def test_upside_down_layer_is_no_measure():
    passed, metrics = qa.assess(SIDEWAYS_TABLE, UPSIDE_DOWN,
                                known_words=DOCUMENT, **LIMITS)
    assert metrics["source_unreadable"] is True
    assert metrics["coverage"] is None and metrics["coverage_assessed"] is False
    assert passed is True


def test_truncation_of_names_found_nowhere_else_still_fails():
    # Few known words, but the transcription stands in the PDF text.
    names = ("District Households Altenberg 1200 Birkenau 860 Crailsheim 2310 "
             "Dornstadt 540 Ebersbach 990 Friedrichshall 1470 Gaildorf 610 "
             "Heubach 780")
    truncated = ("| District | Households |\n| --- | --- |\n"
                 "| Altenberg | 1200 |\n| Birkenau | 860 |")
    passed, metrics = qa.assess(truncated, names, known_words=DOCUMENT,
                                **LIMITS)
    assert metrics["source_unreadable"] is False
    assert metrics["coverage"] < 0.5
    assert passed is False


def test_transcription_sharing_nothing_with_a_known_text_fails():
    # Nothing shared, but the PDF text is made of the document's own words.
    readable = ("Renewables 67 Solar 4 Wind 5 Hydro 15 Nuclear 30 Coal 160 "
                "Oil 190 Gas 139")
    other = "| Country | Year |\n| --- | --- |\n| Peru | 1999 |\n| Chile | 2004 |"
    passed, metrics = qa.assess(other, readable, known_words=DOCUMENT,
                                **LIMITS)
    assert metrics["source_unreadable"] is False
    assert metrics["coverage"] == 0
    assert passed is False


def test_without_the_documents_words_the_text_counts_as_readable():
    passed, metrics = qa.assess(SIDEWAYS_TABLE, UPSIDE_DOWN, **LIMITS)
    assert metrics["source_unreadable"] is False
    assert passed is False
