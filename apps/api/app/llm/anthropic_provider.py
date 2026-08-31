"""Claude-backed provider.

Structured output is enforced with a tool schema derived from the Pydantic
model, so the model cannot answer with prose we would then have to parse.
"""

from __future__ import annotations

import json
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.llm.base import LLMProvider, LLMResult, LLMUnavailable, LLMUsage

M = TypeVar("M", bound=BaseModel)

SYSTEM_SUFFIX = """
You extract facts for a student's opportunity tracker. Rules you must follow:
- Only state what the supplied text supports. If a field is not stated, return null.
- Never invent experience, coursework, publications, deadlines or requirements.
- Keep REQUIRED and PREFERRED qualifications separate, exactly as worded.
- Every confidence you emit must reflect how directly the text supports the value.
"""


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        from anthropic import Anthropic

        settings = get_settings()
        self._client = Anthropic(api_key=api_key, timeout=settings.llm_timeout_seconds)
        self._model = model or settings.anthropic_model
        self._max_tokens = settings.llm_max_output_tokens

    @property
    def is_reasoning_capable(self) -> bool:
        return True

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
        tool_schema = schema.model_json_schema()
        tool_name = f"emit_{schema.__name__.lower()}"
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or self._max_tokens,
                temperature=temperature,
                system=system + SYSTEM_SUFFIX,
                tools=[
                    {
                        "name": tool_name,
                        "description": f"Return the structured result for {task}.",
                        "input_schema": tool_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # network, auth, rate limit
            raise LLMUnavailable(str(exc)) from exc

        block = next((b for b in message.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            raise LLMUnavailable("model returned no structured output")
        try:
            data = schema.model_validate(block.input)
        except ValidationError as exc:
            raise LLMUnavailable(f"structured output failed validation: {exc}") from exc

        return LLMResult(
            data=data,
            usage=LLMUsage(
                provider=self.name,
                model=self._model,
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
            raw=json.dumps(block.input)[:20000],
        )

    def complete_text(
        self, *, system: str, prompt: str, task: str, max_tokens: int | None = None
    ) -> str:
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or 1024,
                system=system + SYSTEM_SUFFIX,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise LLMUnavailable(str(exc)) from exc
        return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
