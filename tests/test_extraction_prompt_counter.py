"""A request is sized with the served model's own tokenizer, not an estimate.

The estimate (characters / 2.62) ran short on tables of figures, where the
tokenizer gives every digit a token of its own: requests went out one token
over the window and were refused, and a refused request that carried a crop
broke the server's multimodal cache.

The tokenizer here is a real fast tokenizer built in memory, one token per
character, with a chat template that shows the thinking switch it is given.
"""
import pytest

from docpipe.extraction import runner

TEMPLATE = ("{% for m in messages %}<{{ m.role }}>{{ m.content }}{% endfor %}"
            "{% if add_generation_prompt %}<a>"
            "{% if not enable_thinking %}<t></t>{% endif %}{% endif %}")


def _tokenizer():
    from tokenizers import Regex, Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast
    chars = [chr(c) for c in range(32, 127)] + ["\n", "[UNK]"]
    core = Tokenizer(models.WordLevel({c: i for i, c in enumerate(chars)},
                                      unk_token="[UNK]"))
    core.pre_tokenizer = pre_tokenizers.Split(Regex("."), "isolated")
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=core,
                                        unk_token="[UNK]")
    tokenizer.chat_template = TEMPLATE
    return tokenizer


def _rendered(system, user):
    """What the template makes of one system and one user message, with
    thinking off as every request sends it."""
    return f"<system>{system}<user>{user}<a><t></t>"


@pytest.fixture
def counted(monkeypatch):
    counter = runner.PromptCounter(_tokenizer())
    monkeypatch.setattr(runner, "PROMPT_COUNTER", counter)
    monkeypatch.delenv("LLM_ENABLE_THINKING", raising=False)
    return counter


TABLE = "| 2030 | 1.234.567 | 89,1 |\n" * 40


def test_a_table_of_figures_is_counted_exactly(counted):
    """The estimate would have sent it short; the count is what the template
    and the tokenizer make of it, character for character here."""
    conversation = [{"role": "user", "content": TABLE}]
    exact = len(_rendered("S", TABLE))
    assert runner.prompt_tokens("S", conversation) == exact
    estimate = len("S" + TABLE) / runner.PROMPT_CHARS_PER_TOKEN
    assert estimate < exact, "the case the estimate got wrong"


def test_the_thinking_switch_every_request_carries_is_counted(counted,
                                                             monkeypatch):
    conversation = [{"role": "user", "content": "x"}]
    off = runner.prompt_tokens("", conversation)
    monkeypatch.setenv("LLM_ENABLE_THINKING", "1")
    assert runner.prompt_tokens("", conversation) == off - len("<t></t>")


def test_a_crop_counts_at_image_tokens_and_not_as_text(counted):
    text_only = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
    with_crop = [{"role": "user", "content": [
        {"type": "text", "text": "x"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                                                   + "A" * 5000}}]}]
    assert (runner.prompt_tokens("", with_crop)
            - runner.prompt_tokens("", text_only)) == runner.IMAGE_TOKENS


def test_text_parts_are_never_counted_short(counted):
    """Parts are joined with a newline the template may not add: one token
    high per part at most, never one low."""
    parts = [{"type": "text", "text": "ab"}, {"type": "text", "text": "cd"}]
    counted_parts = runner.prompt_tokens("", [{"role": "user",
                                               "content": parts}])
    joined = len(_rendered("", "abcd"))
    assert joined <= counted_parts <= joined + len(parts) - 1


def test_the_room_for_the_answer_follows_the_count(counted, monkeypatch):
    monkeypatch.setattr(runner, "MAX_MODEL_LEN", 2000)
    conversation = [{"role": "user", "content": TABLE}]
    room = runner.answer_room("S", conversation, 10_000)
    assert room == 2000 - runner.ANSWER_MARGIN - len(_rendered("S", TABLE))


def test_without_a_tokenizer_the_estimate_stays(monkeypatch):
    monkeypatch.setattr(runner, "PROMPT_COUNTER", None)
    conversation = [{"role": "user", "content": "x" * 262}]
    assert runner.prompt_tokens("", conversation) == int(
        262 / runner.PROMPT_CHARS_PER_TOKEN) + 16 * 2


def test_a_tokenizer_that_cannot_be_loaded_ends_the_run(monkeypatch):
    import transformers
    monkeypatch.setattr(runner, "PROMPT_COUNTER", None)
    monkeypatch.setattr(runner.providers, "replaying", lambda: False)
    monkeypatch.setattr(runner.providers, "hosted", lambda role: False)

    def missing(name, *a, **k):
        raise OSError(f"{name} is not in the cache")

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained",
                        missing)
    with pytest.raises(RuntimeError, match="tokenizer"):
        runner.start_counting("Qwen/Nirgends")
    assert runner.PROMPT_COUNTER is None


def test_the_run_counts_with_the_served_models_tokenizer(monkeypatch):
    import transformers
    monkeypatch.setattr(runner, "PROMPT_COUNTER", None)
    monkeypatch.setattr(runner.providers, "replaying", lambda: False)
    monkeypatch.setattr(runner.providers, "hosted", lambda role: False)
    asked = []

    def load(name, *a, **k):
        asked.append(name)
        return _tokenizer()

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", load)
    runner.start_counting("Qwen/Served")
    assert asked == ["Qwen/Served"]
    assert isinstance(runner.PROMPT_COUNTER, runner.PromptCounter)


@pytest.mark.parametrize("hosted,replaying", [(True, False), (False, True)])
def test_a_hosted_api_and_a_recorded_run_keep_the_estimate(hosted, replaying,
                                                          monkeypatch):
    import transformers
    monkeypatch.setattr(runner, "PROMPT_COUNTER", None)
    monkeypatch.setattr(runner.providers, "replaying", lambda: replaying)
    monkeypatch.setattr(runner.providers, "hosted", lambda role: hosted)

    def never(*a, **k):
        raise AssertionError("no tokenizer is loaded")

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", never)
    runner.start_counting("Qwen/Served")
    assert runner.PROMPT_COUNTER is None
