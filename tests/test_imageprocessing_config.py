"""Tests for the imageprocessing config (prompts, temperatures, atomic JSON)."""
import json

from docpipe.visuals import config as C


def test_system_prompts_single_braced_and_injection_hardened():
    for prompt in (C.table_system_prompt(), C.figure_system_prompt()):
        assert "{{" not in prompt and "}}" not in prompt   # never .format()-ed
        assert "untrusted document text" in prompt          # F23 hardening


def test_user_prompts_still_format_cleanly():
    out = C.table_user_prompt().format(
        section_title="T", page_number=1, existing_caption="(none)",
        section_content="ctx", caption_instruction="do X",
    )
    assert 'Section title: "T"' in out and "do X" in out


def test_table_uses_lower_temperature_than_figures():
    assert C.TABLE_VLM_TEMPERATURE == 0.1
    assert C.VLM_TEMPERATURE == 0.6


def test_dump_json_atomic(tmp_path):
    p = tmp_path / "o.json"
    C.dump_json_atomic({"a": 1}, p)
    assert json.loads(p.read_text(encoding="utf-8"))["a"] == 1
