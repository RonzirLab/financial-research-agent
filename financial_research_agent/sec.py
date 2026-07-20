"""SEC filing downloader command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from financial_research_agent.sec_client import (
    DEFAULT_OUTPUT_DIR,
    SUPPORTED_FORMS,
    SecClient,
    SecClientError,
    contact_email_from_env,
)
from financial_research_agent.sec_parser import SUPPORTED_PARSER_FORMS, write_section_outputs
from financial_research_agent.llm_analyzer import analyze_sections_file
from financial_research_agent.llm_provider import provider_details, provider_from_env


def build_parser() -> argparse.ArgumentParser:
    """Build the SEC downloader argument parser."""
    parser = argparse.ArgumentParser(description="Download SEC filings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", description="Download the newest matching SEC filings.")
    download.add_argument("--ticker", required=True, help="Ticker symbol, for example AMD.")
    download.add_argument("--form", required=True, choices=SUPPORTED_FORMS, help="SEC form to download.")
    download.add_argument(
        "--latest",
        type=int,
        default=1,
        help="Number of newest matching filings to download.",
    )
    parse = subparsers.add_parser("parse", description="Parse a local 10-K or 10-Q filing into sections.")
    parse.add_argument("--filing", required=True, type=Path, help="Local SEC filing HTML file.")
    parse.add_argument("--form", required=True, choices=SUPPORTED_PARSER_FORMS, help="SEC filing form.")
    analyze = subparsers.add_parser("analyze", description="Analyze selected sections from a local 10-K sections.json.")
    analyze.add_argument("--sections", required=True, type=Path, help="Local sections.json produced by parse.")
    analyze.add_argument("--output-dir", required=True, type=Path, help="Directory for analysis.json and analysis.md.")
    analyze.add_argument("--model", help="OpenAI model; overrides OPENAI_MODEL and defaults to gpt-4o-mini.")
    download.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Root directory for downloaded filings. Defaults to data/sec.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the SEC downloader CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "download":
        try:
            contact_email_from_env()
            if args.latest < 1:
                parser.error("--latest must be at least 1.")
            paths = SecClient().download_latest_filings(
                args.ticker, args.form, args.output, limit=args.latest
            )
        except (ValueError, SecClientError) as exc:
            parser.error(str(exc))
        for path in paths:
            print(path)
            print(path.with_name("metadata.json"))
        return 0

    if args.command == "parse":
        try:
            json_path, markdown_path = write_section_outputs(args.filing, args.form)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(json_path)
        print(markdown_path)
        return 0

    if args.command == "analyze":
        try:
            provider = provider_from_env(args.model)
            provider_name, model = provider_details(provider)
            print(f"LLM provider: {provider_name}")
            if model:
                print(f"LLM model: {model}")
            json_path, markdown_path = analyze_sections_file(
                args.sections, args.output_dir, provider
            )
        except (OSError, RuntimeError, ValueError) as exc:
            parser.error(str(exc))
        print(json_path)
        print(markdown_path)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
