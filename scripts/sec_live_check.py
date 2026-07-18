"""Run one live SEC integration check for AMD submissions JSON."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from financial_research_agent.sec_client import (
    SEC_DATA_BASE_URL,
    SecClientError,
    UrllibTransport,
    contact_email_from_env,
)

AMD_SUBMISSIONS_URL = f"{SEC_DATA_BASE_URL}/submissions/CIK0000002488.json"


def main() -> int:
    """Fetch the AMD submissions endpoint once and report non-secret diagnostics."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        transport = UrllibTransport(contact_email_from_env(), cache_dir=Path(temporary_directory))
        try:
            response = transport.get_response(AMD_SUBMISSIONS_URL)
        except SecClientError as exc:
            print("HTTP status code: unavailable")
            print("Content type: unavailable")
            print("Company name returned: unavailable")
            print("Valid JSON received: False")
            print(f"Failure reason: {exc}")
            return 1

    valid_json = False
    company_name = ""
    try:
        payload = json.loads(response.body.decode("utf-8"))
        valid_json = True
        company_name = payload.get("name", "")
    except json.JSONDecodeError:
        company_name = ""

    print(f"HTTP status code: {response.status}")
    print(f"Content type: {response.content_type}")
    print(f"Company name returned: {company_name}")
    print(f"Valid JSON received: {valid_json}")
    return 0 if response.status == 200 and valid_json else 1


if __name__ == "__main__":
    raise SystemExit(main())
