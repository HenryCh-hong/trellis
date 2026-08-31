"""Offline provider — MOCKED ADAPTER (no network, no model).

This is the default so the whole product runs end to end with no API key.
It answers structured requests from rule-based extractors in
``app.services.extractors`` and returns *empty/unknown* values for anything it
cannot derive from the text in front of it.

It never writes a plausible-sounding guess into a field: an unknown deadline
comes back as ``None`` with confidence 0, which the UI renders as "Unknown"
rather than a date.  Set ``ANTHROPIC_API_KEY`` to switch to the real provider.
"""

from __future__ import annotations

import time
from typing import Any, TypeVar

from pydantic import BaseModel

from app.llm.base import LLMProvider, LLMResult, LLMUnavailable, LLMUsage

M = TypeVar("M", bound=BaseModel)

# Registry of task -> callable(prompt_context) -> dict, filled by the agents
# that know how to do their job without a model.
DeterministicHandler = Any
_HANDLERS: dict[str, DeterministicHandler] = {}


def register(task: str):
    def deco(fn: DeterministicHandler) -> DeterministicHandler:
        _HANDLERS[task] = fn
        return fn

    return deco


class DeterministicProvider(LLMProvider):
    name = "deterministic"

    @property
    def is_reasoning_capable(self) -> bool:
        return False

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[M],
        task: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> LLMResult[M]:
        started = time.perf_counter()
        handler = _HANDLERS.get(task)
        if handler is None:
            raise LLMUnavailable(
                f"No deterministic handler registered for task {task!r}. "
                "Set ANTHROPIC_API_KEY to use the model-backed provider."
            )
        payload = handler(prompt)
        data = schema.model_validate(payload)
        return LLMResult(
            data=data,
            usage=LLMUsage(
                provider=self.name,
                model="rules",
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
