from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from financial_research_agent.llm_analyzer import ANALYSIS_AREAS, analyze_sections_file
from financial_research_agent.llm_provider import LlmResponse


class MockLlmProvider:
    def generate(self, prompt: str) -> LlmResponse:
        self.prompt = prompt
        evidence = "We design and sell high-performance computing"
        entry = {"conclusion": "The company sells computing products.", "source_item": "Item 1", "evidence": evidence}
        return LlmResponse(
            content=json.dumps({area: {"filing_facts": [entry], "llm_interpretation": [entry]} for area in ANALYSIS_AREAS}),
            model="mock-test-model",
            input_tokens=123,
            output_tokens=45,
            total_tokens=168,
        )


class LlmAnalyzerTest(unittest.TestCase):
    def test_writes_auditable_json_and_markdown_with_mocked_provider(self) -> None:
        sections = [
            {"item_identifier": "Item 1", "text": "We design and sell high-performance computing products."},
            {"item_identifier": "Item 1A", "text": "Competition could adversely affect results."},
            {"item_identifier": "Item 7", "text": "Revenue increased due to demand."},
            {"item_identifier": "Item 7A", "text": "Foreign exchange rates create market risk."},
            {"item_identifier": "Item 8", "text": "This must not be sent to the provider."},
        ]
        provider = MockLlmProvider()
        with tempfile.TemporaryDirectory() as directory:
            sections_path = Path(directory) / "sections.json"
            sections_path.write_text(json.dumps(sections), encoding="utf-8")
            json_path, markdown_path = analyze_sections_file(sections_path, Path(directory) / "output", provider)
            result = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(result["analysis_version"], "v1")
        self.assertEqual(result["analyzed_source_items"], ["Item 1", "Item 1A", "Item 7", "Item 7A"])
        self.assertNotIn("Item 8", provider.prompt)
        self.assertIn("Facts stated in the filing", markdown)
        self.assertIn("LLM interpretation", markdown)
        self.assertEqual(result["usage"], {"model": "mock-test-model", "input_tokens": 123, "output_tokens": 45, "total_tokens": 168})

    def test_rejects_evidence_not_found_in_source_filing(self) -> None:
        class InvalidProvider:
            def generate(self, prompt: str) -> LlmResponse:
                entry = {"conclusion": "Claim", "source_item": "Item 1", "evidence": "invented evidence"}
                return LlmResponse(content=json.dumps({area: {"filing_facts": [entry], "llm_interpretation": []} for area in ANALYSIS_AREAS}))

        with tempfile.TemporaryDirectory() as directory:
            sections_path = Path(directory) / "sections.json"
            sections_path.write_text(json.dumps([{"item_identifier": "Item 1", "text": "Actual filing text."}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a verbatim excerpt"):
                analyze_sections_file(sections_path, Path(directory) / "output", InvalidProvider())
