from __future__ import annotations

import os
from unittest import mock
import unittest

from financial_research_agent.llm_provider import MockLlmProvider, provider_from_env


class LlmProviderTest(unittest.TestCase):
    def test_mock_provider_is_selected_explicitly_and_returns_json(self) -> None:
        prompt = """FILING SECTIONS:
### Item 1
Item 1 filing evidence.

### Item 1A
Item 1A filing evidence.
"""
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=False):
            provider = provider_from_env()
        self.assertIsInstance(provider, MockLlmProvider)
        self.assertIn('"source_item": "Item 1"', provider.generate(prompt).content)

    def test_provider_must_be_selected_explicitly(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "LLM_PROVIDER must be explicitly"):
                provider_from_env()

    def test_openai_provider_requires_api_key(self) -> None:
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "openai"}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY is required"):
                provider_from_env()
