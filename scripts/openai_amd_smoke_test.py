"""Run one real OpenAI analysis for a local AMD parser output.

This intentionally requires a local parser-produced sections.json and never
downloads filings or writes credentials.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from financial_research_agent.sec import main as sec_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one real OpenAI AMD 10-K analysis smoke test.")
    parser.add_argument("--sections", required=True, type=Path, help="AMD 10-K sections.json produced by the parser.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for analysis.json and analysis.md.")
    parser.add_argument("--model", help="Optional OpenAI model override.")
    args = parser.parse_args(argv)
    if os.environ.get("LLM_PROVIDER") != "openai":
        parser.error("Set LLM_PROVIDER=openai to run the real OpenAI smoke test.")
    command = ["analyze", "--sections", str(args.sections), "--output-dir", str(args.output_dir)]
    if args.model:
        command.extend(["--model", args.model])
    return sec_main(command)


if __name__ == "__main__":
    raise SystemExit(main())
