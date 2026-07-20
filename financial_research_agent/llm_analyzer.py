"""Analyze selected 10-K sections with a replaceable LLM provider."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from financial_research_agent.llm_provider import LlmProvider

ANALYZED_ITEMS = ("Item 1", "Item 1A", "Item 7", "Item 7A")
ANALYSIS_AREAS = (
    "company_overview_and_business_model",
    "key_risks",
    "management_explanation_of_financial_performance",
    "important_operating_and_financial_drivers",
    "follow_up_research_questions",
)
_SPACE_RE = re.compile(r"\s+")


def analyze_sections_file(sections_path: Path, output_dir: Path, provider: LlmProvider) -> tuple[Path, Path]:
    """Read sections JSON, generate validated analysis, and write JSON and Markdown."""
    sections = _load_target_sections(sections_path)
    result = analyze_sections(sections, provider)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "analysis.json"
    markdown_path = output_dir / "analysis.md"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_analysis_markdown(result), encoding="utf-8")
    return json_path, markdown_path


def analyze_sections(sections: dict[str, str], provider: LlmProvider) -> dict[str, Any]:
    """Ask a provider for analysis and validate its evidence against filing text."""
    response = provider.generate(_build_prompt(sections))
    try:
        result = json.loads(response.content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response was not valid JSON.") from exc
    _validate_analysis(result, sections)
    result["analysis_version"] = "v1"
    result["analyzed_source_items"] = list(sections)
    usage = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
    }
    if any(value is not None for value in usage.values()):
        result["usage"] = {key: value for key, value in usage.items() if value is not None}
    return result


def render_analysis_markdown(analysis: dict[str, Any]) -> str:
    """Render the machine-readable analysis in an auditable Markdown format."""
    lines = ["# 10-K LLM Analysis v1", "", "## Scope", ""]
    lines.append("Analyzed filing sections: " + ", ".join(analysis["analyzed_source_items"]) + ".")
    lines.append("")
    for area in ANALYSIS_AREAS:
        lines.extend([f"## {_heading(area)}", "", "### Facts stated in the filing", ""])
        for entry in analysis[area]["filing_facts"]:
            lines.append(_entry_markdown(entry, "fact"))
        lines.extend(["", "### LLM interpretation", ""])
        for entry in analysis[area]["llm_interpretation"]:
            lines.append(_entry_markdown(entry, "interpretation"))
        lines.append("")
    lines.extend(["## Investment-use limitation", "", "This analysis does not include a buy/sell recommendation, target price, or valuation.", ""])
    return "\n".join(lines)


def _load_target_sections(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read sections JSON at {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("sections.json must contain a list of sections.")
    sections = {entry.get("item_identifier"): entry.get("text") for entry in payload if isinstance(entry, dict)}
    selected = {item: sections[item] for item in ANALYZED_ITEMS if isinstance(sections.get(item), str) and sections[item].strip()}
    if not selected:
        raise ValueError("sections.json has none of the required 10-K sections: Item 1, Item 1A, Item 7, Item 7A.")
    return selected


def _build_prompt(sections: dict[str, str]) -> str:
    source = "\n\n".join(f"### {item}\n{text}" for item, text in sections.items())
    areas = ", ".join(ANALYSIS_AREAS)
    return f"""Analyze only the following 10-K filing sections. Do not use outside knowledge.

Return one JSON object with exactly these area keys: {areas}. Each area must have
`filing_facts` and `llm_interpretation` arrays. Every array entry must contain
`conclusion`, `source_item`, and `evidence`. `source_item` must be one supplied item.
`evidence` must be a short verbatim excerpt from that item. Facts are statements directly
made in the filing. Interpretations are clearly labeled in their separate array and must
be grounded by their evidence. Include practical questions in the follow-up area. Never
provide a buy/sell recommendation, target price, or valuation.

FILING SECTIONS:
{source}"""


def _validate_analysis(result: Any, sections: dict[str, str]) -> None:
    if not isinstance(result, dict):
        raise ValueError("LLM response must be a JSON object.")
    if set(result) != set(ANALYSIS_AREAS):
        raise ValueError("LLM response must contain exactly the five required analysis areas.")
    for area in ANALYSIS_AREAS:
        value = result[area]
        if not isinstance(value, dict) or set(value) != {"filing_facts", "llm_interpretation"}:
            raise ValueError(f"{area} must contain filing_facts and llm_interpretation arrays.")
        for label in ("filing_facts", "llm_interpretation"):
            entries = value[label]
            if not isinstance(entries, list):
                raise ValueError(f"{area}.{label} must be an array.")
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"conclusion", "source_item", "evidence"}:
                    raise ValueError(f"{area}.{label} entries need conclusion, source_item, and evidence.")
                item, evidence = entry["source_item"], entry["evidence"]
                if not isinstance(entry["conclusion"], str) or not entry["conclusion"].strip():
                    raise ValueError("Every analysis conclusion must be non-empty text.")
                if item not in sections:
                    raise ValueError(f"Evidence cites unavailable source item: {item!r}.")
                if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 500:
                    raise ValueError("Evidence must be a non-empty excerpt of 500 characters or fewer.")
                if _normalize(evidence) not in _normalize(sections[item]):
                    raise ValueError(f"Evidence for {item} is not a verbatim excerpt from the filing.")


def _entry_markdown(entry: dict[str, str], label: str) -> str:
    return f"- **{entry['conclusion']}** ({label}; source: {entry['source_item']})  \n  Evidence: “{entry['evidence']}”"


def _heading(value: str) -> str:
    return value.replace("_", " ").title()


def _normalize(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()
