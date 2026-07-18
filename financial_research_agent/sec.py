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


def build_parser() -> argparse.ArgumentParser:
    """Build the SEC downloader argument parser."""
    parser = argparse.ArgumentParser(description="Download SEC filings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", description="Download the newest matching SEC filing.")
    download.add_argument("--ticker", required=True, help="Ticker symbol, for example AMD.")
    download.add_argument("--form", required=True, choices=SUPPORTED_FORMS, help="SEC form to download.")
    download.add_argument(
        "--latest",
        type=int,
        default=1,
        help="Number of newest matching filings to download. Currently only 1 is supported.",
    )
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
        if args.latest != 1:
            parser.error("--latest currently supports only 1.")
        try:
            contact_email_from_env()
            path = SecClient().download_latest_filing(args.ticker, args.form, args.output)
        except (ValueError, SecClientError) as exc:
            parser.error(str(exc))
        print(path)
        print(path.with_name("metadata.json"))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
