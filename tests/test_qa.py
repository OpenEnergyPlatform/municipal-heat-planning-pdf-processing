"""Tests for the table QA helpers (coverage, duplication, dedup, assess)."""
from docpipe.visuals import qa

_GOOD = "| Energieträger | Anteil |\n| --- | --- |\n| Erdgas | 45,2 |\n| Fernwärme | 23,1 |"


def test_salient_tokens_numbers_and_words():
    toks = qa.salient_tokens("Erdgas 45,2 % und 24 V")
    assert "erdgas" in toks and "45,2" in toks and "24" in toks
    assert "v" not in toks and "%" not in toks   # single letters / punctuation dropped


def test_coverage_full_and_partial():
    src = "Erdgas 45,2 Fernwärme 23,1 Wärmepumpe 12,8 Solar 5,0"
    assert qa.coverage(src, src, min_source_tokens=4) == 1.0
    # markdown missing half the numbers → coverage drops
    partial = "| Erdgas | 45,2 | Fernwärme | 23,1 |"
    assert qa.coverage(src, partial, min_source_tokens=4) < 0.8


def test_coverage_skipped_when_too_few_source_tokens():
    # image-only table: almost no text layer → cannot assess → 1.0
    assert qa.coverage("12", "completely unrelated text", min_source_tokens=8) == 1.0


def test_duplication():
    assert qa.duplication(_GOOD) == 0.0
    stutter = "| --- | --- |\n| a | 1 |\n| a | 1 |\n| a | 1 |\n| a | 1 |"
    assert qa.duplication(stutter) >= 0.7        # mostly repeated rows
    assert qa.duplication("| only | one |") == 0.0


def test_dedup_consecutive_rows():
    stutter = "| h | h |\n| --- | --- |\n| a | 1 |\n| a | 1 |\n| a | 1 |\n| b | 2 |"
    out = qa.dedup_consecutive_rows(stutter)
    assert out.count("| a | 1 |") == 1           # collapsed to one
    assert "| b | 2 |" in out                     # distinct row kept
    assert "| --- | --- |" in out                 # separator preserved


def test_dedup_keeps_non_consecutive_duplicates():
    # identical rows that are NOT adjacent are legitimate (e.g. repeated values)
    md = "| a | 1 |\n| b | 2 |\n| a | 1 |"
    assert qa.dedup_consecutive_rows(md) == md


def test_assess_pass_and_fail():
    ok, m = qa.assess(_GOOD, "Energieträger Anteil Erdgas 45,2 Fernwärme 23,1",
                      min_source_tokens=4)
    assert ok and m["has_rows"] and m["duplication"] == 0.0

    # no data rows → fail
    bad, _ = qa.assess("Sorry, I cannot read this table.", "")
    assert not bad

    # heavy duplication → fail
    dup = "| --- | --- |\n| a | 1 |\n| a | 1 |\n| a | 1 |\n| a | 1 |"
    failed, mm = qa.assess(dup, "", max_duplication=0.4)
    assert not failed and mm["duplication"] > 0.4
