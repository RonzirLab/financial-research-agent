from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from financial_research_agent.sec_parser import parse_filing_html, write_section_outputs


AMD_10K_FIXTURE = Path(__file__).parent / "fixtures" / "amd-2025-10k.html"


class SecParserTest(unittest.TestCase):
    def test_parses_amd_10k_items_in_document_order_without_toc_entries(self) -> None:
        sections = parse_filing_html(AMD_10K_FIXTURE, "10-K")
        identifiers = [section.item_identifier for section in sections]

        self.assertIn("Item 1", identifiers)
        self.assertIn("Item 1A", identifiers)
        self.assertIn("Item 7", identifiers)
        self.assertEqual(identifiers.count("Item 1"), 1)
        self.assertEqual(
            [section.start_position for section in sections],
            sorted(section.start_position for section in sections),
        )
        item_7 = next(section for section in sections if section.item_identifier == "Item 7")
        self.assertIn("MANAGEMENT’S DISCUSSION", item_7.title)
        self.assertGreater(item_7.character_count, 1_000)

    def test_writes_json_and_markdown_outputs_for_amd_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            filing_path = Path(temporary_directory) / AMD_10K_FIXTURE.name
            filing_path.write_bytes(AMD_10K_FIXTURE.read_bytes())
            json_path, markdown_path = write_section_outputs(filing_path, "10-K")

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["item_identifier"], "Item 1")
            self.assertIn("start_position", payload[0])
            self.assertIn("character_count", payload[0])
            self.assertIn("## Item 1. BUSINESS", markdown_path.read_text(encoding="utf-8"))
