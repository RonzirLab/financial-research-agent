"""Replaceable LLM clients for filing analysis."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_ITEM_RE = re.compile(r"### (Item (?:1A|1|7A|7))\n(.+?)(?=\n\n### Item |\Z)", re.DOTALL)
_AREAS = (
    "company_overview_and_business_model",
    "key_risks",
    "management_explanation_of_financial_performance",
    "important_operating_and_financial_drivers",
    "follow_up_research_questions",
)


@dataclass(frozen=True)
class LlmResponse:
    """Generated content and optional provider-reported usage metadata."""

    content: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LlmProvider(Protocol):
    """Generate a structured response from a prompt."""

    def generate(self, prompt: str) -> LlmResponse:
        """Return generated content and any available usage metadata."""


class OpenAIClient:
    """OpenAI implementation backed by the official OpenAI Python SDK."""

    provider_name = "openai"

    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai.")
        self.model = model or os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        self._client = OpenAI(api_key=api_key)

    def generate(self, prompt: str) -> LlmResponse:
        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Return only valid JSON. Do not give investment advice."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
        except Exception as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}") from exc
        if not content:
            raise RuntimeError("OpenAI API response did not contain assistant content.")
        usage = completion.usage
        return LlmResponse(
            content=content,
            model=completion.model or self.model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )


class MockLlmProvider:
    """Deterministic local provider for tests and offline CLI demonstrations."""

    provider_name = "mock"
    model = "mock-v1"

    def generate(self, prompt: str) -> LlmResponse:
        matches = {item: text for item, text in _ITEM_RE.findall(prompt)}
        if not matches:
            raise ValueError("Mock provider could not find filing sections in the prompt.")
        fallback_item = next(iter(matches))
        item_by_area = {
            "company_overview_and_business_model": "Item 1",
            "key_risks": "Item 1A",
            "management_explanation_of_financial_performance": "Item 7",
            "important_operating_and_financial_drivers": "Item 7",
            "follow_up_research_questions": "Item 7A",
        }
        result = {}
        for area in _AREAS:
            item = item_by_area[area] if item_by_area[area] in matches else fallback_item
            evidence = _short_excerpt(matches[item])
            entry = {"conclusion": f"Mock {area.replace('_', ' ')} conclusion.", "source_item": item, "evidence": evidence}
            result[area] = {"filing_facts": [entry], "llm_interpretation": [entry]}
        return LlmResponse(content=json.dumps(result), model=self.model)


def provider_from_env(model: str | None = None) -> LlmProvider:
    """Create only the provider explicitly selected through ``LLM_PROVIDER``."""
    provider = os.environ.get("LLM_PROVIDER")
    if provider == "mock":
        return MockLlmProvider()
    if provider == "openai":
        return OpenAIClient(model)
    raise ValueError("LLM_PROVIDER must be explicitly set to 'mock' or 'openai'.")


def provider_details(provider: LlmProvider) -> tuple[str, str | None]:
    """Return safe, printable provider and configured-model identifiers."""
    return getattr(provider, "provider_name", provider.__class__.__name__), getattr(provider, "model", None)


def _short_excerpt(text: str) -> str:
    normalized = " ".join(text.split())
    normalized = re.sub(r"^ITEM\s+\d+[A-Z]?\.\s*", "", normalized, flags=re.IGNORECASE)
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    for sentence in sentences[1:]:
        if len(sentence) > 40:
            return sentence[:500].strip()
    end = next((position + 1 for position, char in enumerate(normalized[:500]) if char in ".!?"), min(500, len(normalized)))
    return normalized[:end].strip()
