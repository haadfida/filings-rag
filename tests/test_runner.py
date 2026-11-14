from filings_rag.answer import SCHEMA as ANSWER_SCHEMA
from filings_rag.judge import SCHEMA as JUDGE_SCHEMA
from filings_rag.llm import Usage
from filings_rag.runner import _kappa


def test_cost_uses_per_million_prices():
    assert Usage(input_tokens=1_000_000, output_tokens=0).cost("claude-opus-5-5") == 4.0
    assert Usage(input_tokens=0, output_tokens=1_000_000).cost("claude-haiku-5-5") == 0.5


def test_kappa_perfect_and_chance():
    perfect = [{"human": lab, "label": lab} for lab in ("correct", "incorrect", "refusal") * 5]
    assert _kappa(perfect) == 1.0
    always_correct = [{"human": lab, "label": "correct"} for lab in ("correct", "incorrect", "refusal") * 5]
    assert _kappa(always_correct) == 0.0


def test_schemas_are_strict_objects():
    for schema in (ANSWER_SCHEMA, JUDGE_SCHEMA):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
