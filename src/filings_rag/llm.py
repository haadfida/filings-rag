"""One place for Claude calls: structured JSON output, usage and cost, and refusal handling.

Model ids and prices come from the Claude API reference (cached 3 Nov 2026). Opus 5.5 always thinks,
so `effort` is the depth control and is always set explicitly (its default is "medium"). Sampling
parameters such as temperature are not accepted by these models, so variance is measured by repeat runs.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

# (input, output) US dollars per million tokens. Haiku's price is for prompts up to 100K tokens.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_READ_FRACTION = 0.05  # cache reads: $0.20 on Opus 5.5 against $4.00 input
DEFAULT_MODEL = "claude-opus-5-5"


def load_dotenv(path: Path) -> None:
    """Set variables from a KEY=value file without overriding the environment. No values are printed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def cost(self, model: str) -> float:
        inp, out = PRICES[model]
        return (
            self.input_tokens * inp
            + self.cache_write_tokens * inp * 1.25
            + self.cache_read_tokens * inp * CACHE_READ_FRACTION
            + self.output_tokens * out
        ) / 1_000_000

    def as_dict(self) -> dict:
        return dict(vars(self))


@dataclass
class Result:
    data: dict | None  # parsed JSON, or None when the model refused or was cut off
    stop_reason: str
    usage: Usage
    model: str
    latency_s: float
    request_id: str | None

    @property
    def cost(self) -> float:
        return self.usage.cost(self.model)


class LLM:
    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        self.client = client or anthropic.Anthropic(max_retries=4, timeout=600)

    def json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict,
        effort: str = "medium",
        max_tokens: int = 16000,
    ) -> Result:
        if model not in PRICES:
            raise ValueError(f"unknown model {model!r}; known: {', '.join(PRICES)}")
        start = time.perf_counter()
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        latency = time.perf_counter() - start
        u = response.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        data = None
        if response.stop_reason == "end_turn":
            text = next((b.text for b in response.content if b.type == "text"), None)
            if text is not None:
                data = json.loads(text)
        return Result(data, response.stop_reason, usage, model, latency, response._request_id)
