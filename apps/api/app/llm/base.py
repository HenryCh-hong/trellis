"""LLM provider abstraction.

Two rules shape this interface:

1. Every call that can affect an application decision returns *structured,
   validated* output — never free text we parse hopefully.  ``complete_json``
   validates against a Pydantic model and raises rather than guessing.
2. Every extracted value carries its confidence and where it came from
   (``Evidenced``), so the UI can be honest about uncertainty (spec §20/§23).

Swapping providers is a settings change; no agent imports a vendor SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from app.models.enums import Certainty, ExtractionMethod

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


class Evidenced[T](BaseModel):
    """A value plus the reason we believe it."""

    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    method: ExtractionMethod = ExtractionMethod.HEURISTIC
    source_text: str | None = None
    source_url: str | None = None

    @property
    def certainty(self) -> Certainty:
        """Map confidence onto the four words the UI is allowed to say.

        Thresholds live here (not in components) so 'Verified' means the same
        thing on every screen.
        """
        if self.value is None:
            return Certainty.UNKNOWN
        if self.method in (ExtractionMethod.SOURCE, ExtractionMethod.USER):
            return Certainty.VERIFIED
        if self.confidence >= 0.85 and self.source_text:
            return Certainty.VERIFIED
        if self.confidence >= 0.6:
            return Certainty.LIKELY
        if self.confidence > 0.0:
            return Certainty.INFERRED
        return Certainty.UNKNOWN

    def as_field(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 3),
            "certainty": self.certainty.value,
            "method": self.method.value,
            "source_text": self.source_text,
            "source_url": self.source_url,
        }


def unknown(method: ExtractionMethod = ExtractionMethod.HEURISTIC) -> Evidenced[Any]:
    return Evidenced(value=None, confidence=0.0, method=method)


class LLMUsage(BaseModel):
    provider: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None


class LLMResult[M: BaseModel](BaseModel):
    data: M
    usage: LLMUsage
    raw: str | None = None


class LLMUnavailable(RuntimeError):
    """Raised when a provider cannot answer; callers must degrade, not invent."""


class LLMProvider(ABC):
    """Minimal surface: structured completion, and a cheap capability flag."""

    name: str = "base"

    @property
    @abstractmethod
    def is_reasoning_capable(self) -> bool:
        """False for the offline provider.

        Agents check this to decide whether to attempt a genuinely generative
        step (e.g. drafting prose) or to fall back to deterministic output.
        They must never *fabricate* to fill the gap.
        """

    @abstractmethod
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
        """Return an instance of ``schema`` or raise ``LLMUnavailable``."""

    def complete_text(self, *, system: str, prompt: str, task: str, max_tokens: int | None = None) -> str:
        raise LLMUnavailable(f"{self.name} does not support free-text completion")
