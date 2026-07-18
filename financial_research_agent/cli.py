"""Command-line interface for downloading SEC filings."""

from __future__ import annotations

import argparse
from pathlib import Path

from financial_research_agent.sec_client import DEFAULT_OUTPUT_DIR, SecClient, contact_email_from_env


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Download the latest 10-K and 10-Q SEC filings for a ticker."
    )
    parser.add_argument("ticker", help="Ticker symbol, for example AAPL.")
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for downloaded filings. Defaults to data/sec.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the SEC downloader CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        contact_email_from_env()
    except ValueError as exc:
        parser.error(str(exc))

    client = SecClient()
    paths = client.download_latest_annual_and_quarterly(args.ticker, args.output_dir)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
