from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from financial_research_agent import sec_client as sec_module
from financial_research_agent.sec import main as sec_main
from financial_research_agent.sec_client import (
    COMPANY_TICKERS_URL,
    DEFAULT_CACHE_DIR,
    SEC_DATA_BASE_URL,
    SEC_USER_AGENT_EMAIL_ENV,
    SUPPORTED_FORMS,
    Filing,
    SecClient,
    SecClientError,
    UrllibTransport,
    build_sec_user_agent,
)


class FakeTransport:
    def __init__(
        self,
        json_by_url: dict[str, Any] | None = None,
        bytes_by_url: dict[str, bytes] | None = None,
    ) -> None:
        self.json_by_url = json_by_url or {}
        self.bytes_by_url = bytes_by_url or {}
        self.json_urls: list[str] = []
        self.bytes_urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.json_urls.append(url)
        return self.json_by_url[url]

    def get_bytes(self, url: str) -> bytes:
        self.bytes_urls.append(url)
        return self.bytes_by_url[url]


class FakeResponse:
    def __init__(self, url: str, body: bytes, status: int = 200) -> None:
        self._url = url
        self._body = body
        self.status = status
        self.headers: dict[str, str] = {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def getcode(self) -> int:
        return self.status


class SecClientTest(unittest.TestCase):
    def test_get_cik_for_ticker_zero_pads_and_matches_case_insensitively(self) -> None:
        transport = FakeTransport(
            {COMPANY_TICKERS_URL: {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}}
        )
        client = SecClient(transport=transport)

        self.assertEqual(client.get_cik_for_ticker("aapl"), "0000320193")
        self.assertEqual(transport.json_urls, [COMPANY_TICKERS_URL])

    def test_get_latest_filing_uses_sec_submissions_json(self) -> None:
        submissions_url = f"{SEC_DATA_BASE_URL}/submissions/CIK0000320193.json"
        transport = FakeTransport(
            {
                COMPANY_TICKERS_URL: {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}},
                submissions_url: {
                    "cik": 320193,
                    "filings": {
                        "recent": {
                            "form": ["8-K", "10-Q", "10-Q"],
                            "accessionNumber": [
                                "0000320193-26-000001",
                                "0000320193-26-000002",
                                "0000320193-25-000003",
                            ],
                            "filingDate": ["2026-01-01", "2026-05-01", "2025-10-31"],
                            "primaryDocument": ["a.htm", "aapl-20260501.htm", "old.htm"],
                            "reportDate": ["2025-12-31", "2026-03-31", "2025-09-30"],
                        }
                    }
                },
            }
        )
        client = SecClient(transport=transport)

        filing = client.get_latest_filing("AAPL", "10-Q")

        self.assertEqual(
            filing,
            Filing(
                ticker="AAPL",
                cik="0000320193",
                form="10-Q",
                accession_number="0000320193-26-000002",
                filing_date="2026-05-01",
                primary_document="aapl-20260501.htm",
                report_date="2026-03-31",
                company_name="Apple Inc.",
            ),
        )
        self.assertEqual(transport.json_urls, [COMPANY_TICKERS_URL, submissions_url])

    def test_get_company_facts_uses_official_xbrl_endpoint(self) -> None:
        company_facts_url = f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK0000320193.json"
        transport = FakeTransport(
            {
                COMPANY_TICKERS_URL: {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}},
                company_facts_url: {"cik": 320193, "entityName": "Apple Inc."},
            }
        )
        client = SecClient(transport=transport)

        self.assertEqual(client.get_company_facts("AAPL"), {"cik": 320193, "entityName": "Apple Inc."})
        self.assertEqual(transport.json_urls, [COMPANY_TICKERS_URL, company_facts_url])

    def test_sec_provided_document_url_is_preferred_when_present(self) -> None:
        submissions_url = f"{SEC_DATA_BASE_URL}/submissions/CIK0000320193.json"
        official_url = "https://www.sec.gov/ixviewer/doc/action?doc=/Archives/example/aapl.htm"
        transport = FakeTransport(
            {
                COMPANY_TICKERS_URL: {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}},
                submissions_url: {
                    "cik": 320193,
                    "filings": {
                        "recent": {
                            "form": ["10-K"],
                            "accessionNumber": ["0000320193-26-000123"],
                            "filingDate": ["2026-10-31"],
                            "reportDate": ["2026-09-26"],
                            "primaryDocument": ["aapl-20260926.htm"],
                            "primaryDocumentUrl": [official_url],
                        }
                    },
                },
            }
        )
        client = SecClient(transport=transport)

        filing = client.get_latest_filing("AAPL", "10-K")

        self.assertEqual(filing.official_document_url, official_url)
        self.assertEqual(filing.download_url, official_url)
        self.assertEqual(
            filing.constructed_download_url,
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/aapl-20260926.htm",
        )

    def test_download_url_strips_cik_zeros_and_accession_dashes(self) -> None:
        filing = Filing(
            ticker="AMD",
            cik="0000002488",
            form="10-K",
            accession_number="0000002488-26-000018",
            filing_date="2026-02-04",
            primary_document="amd-20251227.htm",
            report_date="2025-12-27",
            company_name="ADVANCED MICRO DEVICES INC",
        )

        self.assertEqual(filing.cik_without_leading_zeros, "2488")
        self.assertEqual(filing.accession_without_dashes, "000000248826000018")
        self.assertEqual(
            filing.download_url,
            "https://www.sec.gov/Archives/edgar/data/2488/000000248826000018/amd-20251227.htm",
        )

    def test_download_filing_writes_under_output_dir(self) -> None:
        filing = Filing(
            ticker="AAPL",
            cik="0000320193",
            form="10-K",
            accession_number="0000320193-25-000123",
            filing_date="2025-10-31",
            primary_document="aapl-20251031.htm",
            report_date="2025-09-27",
            company_name="Apple Inc.",
        )
        transport = FakeTransport(bytes_by_url={filing.download_url: b"filing contents"})
        client = SecClient(transport=transport)

        with self.subTest("tmp_path"):
            with tempfile.TemporaryDirectory() as temporary_directory:
                path = client.download_filing(filing, Path(temporary_directory))
                self.assertEqual(
                    path.parent,
                    Path(temporary_directory)
                    / "AAPL"
                    / "10-K"
                    / "2025-10-31"
                    / "0000320193-25-000123",
                )
                self.assertEqual(path.name, "AAPL_10-K_2025-10-31_0000320193-25-000123.htm")
                self.assertEqual(path.read_bytes(), b"filing contents")
                metadata = json.loads(path.with_name("metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["company_name"], "Apple Inc.")
                self.assertEqual(metadata["source_url"], filing.download_url)
        self.assertEqual(transport.bytes_urls, [filing.download_url])

    def test_amd_download_flow_builds_official_sec_resources(self) -> None:
        submissions_url = f"{SEC_DATA_BASE_URL}/submissions/CIK0000002488.json"
        transport = FakeTransport(
            {
                COMPANY_TICKERS_URL: {
                    "13": {
                        "ticker": "AMD",
                        "cik_str": 2488,
                        "title": "ADVANCED MICRO DEVICES INC",
                    }
                },
                submissions_url: {
                    "cik": 2488,
                    "filings": {
                        "recent": {
                            "form": ["8-K", "10-K", "10-Q"],
                            "accessionNumber": [
                                "0000002488-26-000010",
                                "0000002488-26-000018",
                                "0000002488-25-000108",
                            ],
                            "filingDate": ["2026-01-15", "2026-02-04", "2025-08-06"],
                            "primaryDocument": [
                                "amd-press-release.htm",
                                "amd-20251227.htm",
                                "amd-20250628.htm",
                            ],
                            "reportDate": ["2026-01-15", "2025-12-27", "2025-06-28"],
                        }
                    }
                },
            },
            bytes_by_url={
                (
                    "https://www.sec.gov/Archives/edgar/data/2488/"
                    "000000248826000018/amd-20251227.htm"
                ): b"AMD 10-K",
                (
                    "https://www.sec.gov/Archives/edgar/data/2488/"
                    "000000248825000108/amd-20250628.htm"
                ): b"AMD 10-Q",
            },
        )
        client = SecClient(transport=transport)

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = client.download_latest_annual_and_quarterly("AMD", Path(temporary_directory))
            names = [path.name for path in paths]
            contents = [path.read_bytes() for path in paths]

        self.assertEqual(
            names,
            [
                "AMD_10-K_2026-02-04_0000002488-26-000018.htm",
                "AMD_10-Q_2025-08-06_0000002488-25-000108.htm",
            ],
        )
        self.assertEqual(contents, [b"AMD 10-K", b"AMD 10-Q"])
        self.assertEqual(
            transport.json_urls,
            [COMPANY_TICKERS_URL, submissions_url],
        )
        self.assertEqual(
            transport.bytes_urls,
            [
                (
                    "https://www.sec.gov/Archives/edgar/data/2488/"
                    "000000248826000018/amd-20251227.htm"
                ),
                (
                    "https://www.sec.gov/Archives/edgar/data/2488/"
                    "000000248825000108/amd-20250628.htm"
                ),
            ],
        )

    def test_supported_forms_include_8k(self) -> None:
        self.assertEqual(SUPPORTED_FORMS, ("10-K", "10-Q", "8-K"))

    def test_download_latest_filings_sorts_and_downloads_one_filing(self) -> None:
        submissions_url = f"{SEC_DATA_BASE_URL}/submissions/CIK0000320193.json"
        older_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000003/older.htm"
        newer_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000002/newer.htm"
        transport = FakeTransport(
            {
                COMPANY_TICKERS_URL: {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}},
                submissions_url: {"cik": 320193, "filings": {"recent": {
                    "form": ["10-Q", "10-Q"],
                    "accessionNumber": ["0000320193-25-000003", "0000320193-26-000002"],
                    "filingDate": ["2025-10-31", "2026-05-01"],
                    "primaryDocument": ["older.htm", "newer.htm"],
                    "reportDate": ["2025-09-30", "2026-03-31"],
                }}},
            },
            bytes_by_url={older_url: b"older", newer_url: b"newer"},
        )
        client = SecClient(transport=transport)

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = client.download_latest_filings("AAPL", "10-Q", Path(temporary_directory), limit=1)
            self.assertEqual([path.read_bytes() for path in paths], [b"newer"])
            self.assertTrue(paths[0].with_name("metadata.json").exists())

        self.assertEqual(transport.bytes_urls, [newer_url])

    def test_download_latest_filings_downloads_multiple_without_metadata_overwrite(self) -> None:
        submissions_url = f"{SEC_DATA_BASE_URL}/submissions/CIK0000320193.json"
        first_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/first.htm"
        second_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000002/second.htm"
        transport = FakeTransport(
            {
                COMPANY_TICKERS_URL: {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}},
                submissions_url: {"cik": 320193, "filings": {"recent": {
                    "form": ["10-Q", "10-Q"],
                    "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                    "filingDate": ["2026-05-01", "2026-05-01"],
                    "primaryDocument": ["first.htm", "second.htm"],
                    "reportDate": ["2026-03-31", "2026-03-31"],
                }}},
            },
            bytes_by_url={first_url: b"first", second_url: b"second"},
        )
        client = SecClient(transport=transport)

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = client.download_latest_filings("AAPL", "10-Q", Path(temporary_directory), limit=2)
            self.assertEqual([path.read_bytes() for path in paths], [b"first", b"second"])
            self.assertNotEqual(paths[0].parent, paths[1].parent)
            self.assertEqual(
                [json.loads(path.with_name("metadata.json").read_text())["accession_number"] for path in paths],
                ["0000320193-26-000001", "0000320193-26-000002"],
            )

        self.assertEqual(transport.bytes_urls, [first_url, second_url])

    def test_sec_download_cli_uses_mocked_client_for_one_filing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            with patch.dict("os.environ", {SEC_USER_AGENT_EMAIL_ENV: "YOUR_EMAIL@example.com"}, clear=True):
                with patch("financial_research_agent.sec.SecClient") as client_class:
                    client_class.return_value.download_latest_filings.return_value = [
                        output / "AMD" / "10-K" / "2025-02-05" / "0001" / "amd.htm"
                    ]
                    exit_code = sec_main([
                        "download",
                        "--ticker",
                        "AMD",
                        "--form",
                        "10-K",
                        "--latest",
                        "1",
                        "--output",
                        str(output),
                    ])

        self.assertEqual(exit_code, 0)
        client_class.return_value.download_latest_filings.assert_called_once_with(
            "AMD", "10-K", output, limit=1
        )

    def test_sec_download_cli_uses_mocked_client_for_multiple_filings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            with patch.dict("os.environ", {SEC_USER_AGENT_EMAIL_ENV: "YOUR_EMAIL@example.com"}, clear=True):
                with patch("financial_research_agent.sec.SecClient") as client_class:
                    client_class.return_value.download_latest_filings.return_value = [
                        output / "AMD" / "8-K" / "2025-02-05" / "0001" / "first.htm",
                        output / "AMD" / "8-K" / "2025-02-04" / "0002" / "second.htm",
                    ]
                    exit_code = sec_main([
                        "download", "--ticker", "AMD", "--form", "8-K", "--latest", "2", "--output", str(output),
                    ])

        self.assertEqual(exit_code, 0)
        client_class.return_value.download_latest_filings.assert_called_once_with(
            "AMD", "8-K", output, limit=2
        )

    def test_missing_ticker_raises_domain_error(self) -> None:
        transport = FakeTransport(
            {COMPANY_TICKERS_URL: {"0": {"ticker": "MSFT", "cik_str": 789019}}}
        )
        client = SecClient(transport=transport)

        with self.assertRaisesRegex(SecClientError, "Ticker not found"):
            client.get_cik_for_ticker("AAPL")

    def test_sec_user_agent_email_environment_variable_is_required(self) -> None:
        with patch.dict("os.environ", {SEC_USER_AGENT_EMAIL_ENV: ""}, clear=True):
            with self.assertRaisesRegex(ValueError, SEC_USER_AGENT_EMAIL_ENV):
                SecClient()

    def test_user_agent_is_descriptive_and_uses_required_headers(self) -> None:
        requests = []

        def fake_urlopen(request, timeout: float):
            requests.append((request, timeout))
            return FakeResponse(request.full_url, b'{"ok": true}')

        with patch.dict("os.environ", {}, clear=True):
            expected_user_agent = build_sec_user_agent("YOUR_EMAIL@example.com")
            with tempfile.TemporaryDirectory() as temporary_directory:
                transport = UrllibTransport(
                    "YOUR_EMAIL@example.com",
                    cache_dir=Path(temporary_directory),
                    sleeper=lambda _seconds: None,
                )
                with patch.object(sec_module, "urlopen", side_effect=fake_urlopen):
                    self.assertEqual(
                        transport.get_json("https://data.sec.gov/test.json"), {"ok": True}
                    )

        self.assertEqual(len(requests), 1)
        headers = dict(requests[0][0].header_items())
        self.assertEqual(headers["User-agent"], expected_user_agent)
        self.assertEqual(headers["Accept-encoding"], "gzip, deflate")
        self.assertEqual(headers["Accept"], "application/json,text/html")

    def test_user_agent_can_include_contact_name_from_environment(self) -> None:
        with patch.dict("os.environ", {"SEC_USER_AGENT_NAME": "ron q"}, clear=True):
            self.assertEqual(
                build_sec_user_agent("YOUR_EMAIL@example.com"),
                "Financial Research Agent ron q YOUR_EMAIL@example.com",
            )

    def test_transport_caches_same_url_without_repeated_network_request(self) -> None:
        requests = []

        def fake_urlopen(request, timeout: float):
            requests.append(request.full_url)
            return FakeResponse(request.full_url, b"cached response")

        with tempfile.TemporaryDirectory() as temporary_directory:
            transport = UrllibTransport(
                "YOUR_EMAIL@example.com",
                cache_dir=Path(temporary_directory),
                sleeper=lambda _seconds: None,
            )
            with patch.object(sec_module, "urlopen", side_effect=fake_urlopen):
                self.assertEqual(transport.get_bytes("https://data.sec.gov/cache-test"), b"cached response")
                self.assertEqual(transport.get_bytes("https://data.sec.gov/cache-test"), b"cached response")

        self.assertEqual(requests, ["https://data.sec.gov/cache-test"])

    def test_transport_retries_retryable_http_status_with_backoff(self) -> None:
        sleeps: list[float] = []
        responses = [
            HTTPError(
                "https://data.sec.gov/retry-test",
                429,
                "Too Many Requests",
                hdrs={},
                fp=BytesIO(b"slow down"),
            ),
            FakeResponse("https://data.sec.gov/retry-test", b"success"),
        ]

        def fake_urlopen(request, timeout: float):
            response = responses.pop(0)
            if isinstance(response, HTTPError):
                raise response
            return response

        with tempfile.TemporaryDirectory() as temporary_directory:
            transport = UrllibTransport(
                "YOUR_EMAIL@example.com",
                cache_dir=Path(temporary_directory),
                sleeper=sleeps.append,
            )
            with patch.object(sec_module, "urlopen", side_effect=fake_urlopen):
                with self.assertLogs(sec_module.LOGGER, level="WARNING"):
                    self.assertEqual(transport.get_bytes("https://data.sec.gov/retry-test"), b"success")

        self.assertIn(1.0, sleeps)

    def test_transport_logs_url_status_and_body_preview(self) -> None:
        def fake_urlopen(request, timeout: float):
            return FakeResponse(request.full_url, b"body preview text")

        with tempfile.TemporaryDirectory() as temporary_directory:
            transport = UrllibTransport(
                "YOUR_EMAIL@example.com",
                cache_dir=Path(temporary_directory),
                sleeper=lambda _seconds: None,
            )
            with patch.object(sec_module, "urlopen", side_effect=fake_urlopen):
                with self.assertLogs(sec_module.LOGGER, level="INFO") as logs:
                    self.assertEqual(transport.get_bytes("https://data.sec.gov/log-test"), b"body preview text")

        log_output = "\n".join(logs.output)
        self.assertIn("url=https://data.sec.gov/log-test", log_output)
        self.assertIn("status=200", log_output)
        self.assertIn("body preview text", log_output)

    def test_default_cache_dir_is_under_data_sec(self) -> None:
        self.assertEqual(DEFAULT_CACHE_DIR, Path("data/sec/cache"))


if __name__ == "__main__":
    unittest.main()
