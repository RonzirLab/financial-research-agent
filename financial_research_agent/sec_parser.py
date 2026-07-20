"""Offline section parser for SEC 10-K and 10-Q HTML filings."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

SUPPORTED_PARSER_FORMS = ("10-K", "10-Q")
_ITEM_RE = re.compile(r"^item\s+([0-9]+[a-z]?)\s*\.?\s*(.*)$", re.IGNORECASE)
_PART_RE = re.compile(r"^part\s+(i{1,3}|iv)\b", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_BLOCK_TAGS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "ix:header", "ix:hidden"}


@dataclass(frozen=True)
class FilingSection:
    """A readable SEC filing section."""

    title: str
    item_identifier: str
    text: str
    start_position: int
    character_count: int


@dataclass
class _Block:
    text: str
    has_link: bool


class _ReadableHtmlParser(HTMLParser):
    """Extract document-order text blocks while excluding non-readable markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._stack: list[tuple[str, bool]] = []
        self._text: list[str] = []
        self._skip_depth = 0
        self._has_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        style = dict(attrs).get("style", "") or ""
        hidden = tag in _SKIP_TAGS or "display:none" in style.replace(" ", "").lower()
        self._stack.append((tag, hidden))
        if hidden:
            self._skip_depth += 1
        if tag == "a" and not self._skip_depth:
            self._has_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS and not self._skip_depth:
            self._flush_block()
        if not self._stack:
            return
        opened_tag, hidden = self._stack.pop()
        if hidden:
            self._skip_depth -= 1
        if opened_tag == "body":
            self._flush_block()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._text.append(data)

    def _flush_block(self) -> None:
        text = _normalize_text("".join(self._text))
        if text:
            self.blocks.append(_Block(text, self._has_link))
        self._text = []
        self._has_link = False


def parse_filing_html(path: Path, form: str) -> list[FilingSection]:
    """Parse a local 10-K or 10-Q HTML filing into item-based sections."""
    if form not in SUPPORTED_PARSER_FORMS:
        raise ValueError(f"Unsupported filing form {form!r}; expected one of {SUPPORTED_PARSER_FORMS}.")
    parser = _ReadableHtmlParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.close()

    part: str | None = None
    starts: list[tuple[str, str, int]] = []
    readable_text = "\n\n".join(block.text for block in parser.blocks)
    cursor = 0
    for block in parser.blocks:
        position = cursor
        cursor += len(block.text) + 2
        if block.has_link or len(block.text) > 240:
            continue
        if form == "10-Q" and _PART_RE.match(block.text):
            part = _normalize_part(block.text)
            continue
        match = _ITEM_RE.match(block.text)
        if not match:
            continue
        if not match.group(2).strip():
            continue
        item = f"Item {match.group(1).upper()}"
        identifier = f"{part} {item}" if form == "10-Q" and part else item
        title = _normalize_text(f"{item}. {match.group(2)}").rstrip(".")
        starts.append((identifier, title, position))

    sections: list[FilingSection] = []
    for index, (identifier, title, start) in enumerate(starts):
        end = starts[index + 1][2] if index + 1 < len(starts) else len(readable_text)
        text = readable_text[start:end].strip()
        sections.append(FilingSection(title, identifier, text, start, len(text)))
    return sections


def write_section_outputs(filing_path: Path, form: str) -> tuple[Path, Path]:
    """Parse a local filing and write JSON and Markdown section outputs beside it."""
    sections = parse_filing_html(filing_path, form)
    json_path = filing_path.with_name("sections.json")
    markdown_path = filing_path.with_name("sections.md")
    json_path.write_text(json.dumps([asdict(section) for section in sections], indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(
        "\n\n".join(f"## {section.title}\n\n{section.text}" for section in sections) + "\n",
        encoding="utf-8",
    )
    return json_path, markdown_path


def _normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.replace("\xa0", " ")).strip()


def _normalize_part(value: str) -> str:
    match = _PART_RE.match(value)
    assert match is not None
    return f"Part {match.group(1).upper()}"
