"""Client for SEC official data APIs and EDGAR filing downloads."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT_EMAIL_ENV = "SEC_USER_AGENT_EMAIL"
SEC_USER_AGENT_NAME_ENV = "SEC_USER_AGENT_NAME"
DEFAULT_OUTPUT_DIR = Path("data/sec")
DEFAULT_CACHE_DIR = DEFAULT_OUTPUT_DIR / "cache"
SUPPORTED_FORMS = ("10-K", "10-Q", "8-K")
RETRYABLE_STATUS_CODES = {403, 429}
MAX_REQUESTS_PER_SECOND = 2
REQUEST_INTERVAL_SECONDS = 1 / MAX_REQUESTS_PER_SECOND
MAX_RETRIES = 3
BODY_PREVIEW_BYTES = 500


class SecClientError(RuntimeError):
    """Raised when SEC data cannot be found or downloaded."""


class HttpTransport(Protocol):
    """Protocol for testable HTTP transports."""

    def get_json(self, url: str) -> Any:
        """Fetch JSON from a URL."""

    def get_bytes(self, url: str) -> bytes:
        """Fetch bytes from a URL."""


def build_sec_user_agent(contact_email: str, contact_name: str | None = None) -> str:
    """Build the SEC-compliant User-Agent from contact details."""
    normalized_email = contact_email.strip()
    if not normalized_email:
        raise ValueError(f"{SEC_USER_AGENT_EMAIL_ENV} must be set to a contact email.")
    normalized_name = (contact_name or os.getenv(SEC_USER_AGENT_NAME_ENV, "")).strip()
    if normalized_name:
        return f"Financial Research Agent {normalized_name} {normalized_email}"
    return f"Financial Research Agent {normalized_email}"


def contact_email_from_env() -> str:
    """Read the required SEC contact email from the environment."""
    contact_email = os.getenv(SEC_USER_AGENT_EMAIL_ENV)
    if not contact_email or not contact_email.strip():
        raise ValueError(
            f"{SEC_USER_AGENT_EMAIL_ENV} is required. Set it to a real contact email for SEC requests."
        )
    return contact_email.strip()


@dataclass(frozen=True)
class SecHttpResponse:
    """SEC HTTP response metadata and decoded body."""

    final_url: str
    status: int
    content_type: str
    body: bytes


class UrllibTransport:
    """HTTP transport backed by Python's standard library with SEC-friendly behavior."""

    def __init__(
        self,
        contact_email: str,
        *,
        timeout: float = 30.0,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout = timeout
        self._cache_dir = cache_dir
        self._sleeper = sleeper
        self._last_request_time = 0.0
        self._headers = {
            "User-Agent": build_sec_user_agent(contact_email),
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json,text/html",
        }

    def get_json(self, url: str) -> Any:
        return json.loads(self.get_bytes(url).decode("utf-8"))

    def get_bytes(self, url: str) -> bytes:
        return self.get_response(url).body

    def get_response(self, url: str) -> SecHttpResponse:
        cached_response = self._read_cache(url)
        if cached_response is not None:
            LOGGER.info("SEC cache hit url=%s status=CACHED body_preview=%r", url, _preview(cached_response))
            return SecHttpResponse(final_url=url, status=200, content_type="", body=cached_response)

        response = self._request_with_retries(url)
        self._write_cache(url, response.body)
        return response

    def _request_with_retries(self, url: str) -> SecHttpResponse:
        backoff_seconds = 1.0
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                self._sleeper(backoff_seconds)
                backoff_seconds *= 2

            self._rate_limit()
            request = Request(url, headers=self._headers)
            try:
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    raw_body = response.read()
                    body = _decode_response(raw_body, response.headers.get("Content-Encoding"))
                    status = getattr(response, "status", response.getcode())
                    content_type = response.headers.get("Content-Type", "")
                    LOGGER.info(
                        "SEC response url=%s status=%s body_preview=%r",
                        response.geturl(),
                        status,
                        _preview(body),
                    )
                    if _is_retryable_status(status):
                        last_error = SecClientError(f"SEC request returned retryable HTTP {status}: {url}")
                        if attempt < MAX_RETRIES:
                            continue
                    return SecHttpResponse(
                        final_url=response.geturl(),
                        status=status,
                        content_type=content_type,
                        body=body,
                    )
            except HTTPError as exc:
                raw_body = exc.read()
                body = _decode_response(raw_body, exc.headers.get("Content-Encoding"))
                LOGGER.warning(
                    "SEC response url=%s status=%s body_preview=%r",
                    exc.geturl(),
                    exc.code,
                    _preview(body),
                )
                last_error = SecClientError(f"SEC request failed with HTTP {exc.code}: {url}")
                if _is_retryable_status(exc.code) and attempt < MAX_RETRIES:
                    continue
                raise last_error from exc
            except URLError as exc:
                last_error = SecClientError(f"SEC request failed: {url}")
                raise last_error from exc

        raise SecClientError(f"SEC request failed after retries: {url}") from last_error

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        wait_time = REQUEST_INTERVAL_SECONDS - elapsed
        if wait_time > 0:
            self._sleeper(wait_time)
        self._last_request_time = time.monotonic()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.bin"

    def _read_cache(self, url: str) -> bytes | None:
        cache_path = self._cache_path(url)
        if not cache_path.exists():
            return None
        return cache_path.read_bytes()

    def _write_cache(self, url: str, body: bytes) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(url).write_bytes(body)


@dataclass(frozen=True)
class Filing:
    """Metadata needed to download a SEC filing document."""

    ticker: str
    cik: str
    form: str
    accession_number: str
    filing_date: str
    primary_document: str
    report_date: str
    company_name: str
    official_document_url: str | None = None

    @property
    def cik_without_leading_zeros(self) -> str:
        """Return the CIK formatted for EDGAR archive URLs."""
        return self.cik.lstrip("0") or "0"

    @property
    def accession_without_dashes(self) -> str:
        """Return the accession number formatted for EDGAR archive URLs."""
        return self.accession_number.replace("-", "")

    @property
    def constructed_download_url(self) -> str:
        """Build the EDGAR archive URL from CIK, accession number, and document."""
        return (
            f"{SEC_ARCHIVES_BASE_URL}/{self.cik_without_leading_zeros}/"
            f"{self.accession_without_dashes}/{self.primary_document}"
        )

    @property
    def download_url(self) -> str:
        """Return SEC-provided document URL when available, otherwise construct one."""
        return self.official_document_url or self.constructed_download_url

    @property
    def filename(self) -> str:
        suffix = Path(self.primary_document).suffix or ".txt"
        return (
            f"{self.ticker.upper()}_{self.form.replace('/', '-')}_"
            f"{self.filing_date}_{self.accession_number}{suffix}"
        )

    def metadata(self, downloaded_filename: str) -> dict[str, str]:
        """Return serializable filing download metadata."""
        return {
            "ticker": self.ticker,
            "cik": self.cik,
            "company_name": self.company_name,
            "form": self.form,
            "accession_number": self.accession_number,
            "filing_date": self.filing_date,
            "report_date": self.report_date,
            "source_url": self.download_url,
            "downloaded_filename": downloaded_filename,
        }


class SecClient:
    """Small SEC API client for finding and downloading SEC filings."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        transport: HttpTransport | None = None,
        cache_dir: Path = DEFAULT_CACHE_DIR,
    ) -> None:
        self._transport = transport or UrllibTransport(
            contact_email=contact_email_from_env(),
            timeout=timeout,
            cache_dir=cache_dir,
        )

    def get_company_for_ticker(self, ticker: str) -> dict[str, str]:
        """Return SEC company ticker metadata with a zero-padded CIK."""
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("Ticker cannot be blank.")

        companies: dict[str, dict[str, Any]] = self._transport.get_json(COMPANY_TICKERS_URL)
        for company in companies.values():
            if company.get("ticker", "").upper() == normalized:
                return {
                    "ticker": normalized,
                    "cik": str(company["cik_str"]).zfill(10),
                    "company_name": str(company.get("title", "")).strip(),
                }

        raise SecClientError(f"Ticker not found in SEC company tickers data: {ticker}")

    def get_cik_for_ticker(self, ticker: str) -> str:
        """Return the zero-padded CIK for a ticker using SEC's company tickers JSON."""
        return self.get_company_for_ticker(ticker)["cik"]

    def get_company_facts(self, ticker: str) -> dict[str, Any]:
        """Return SEC company facts for a ticker from the official XBRL companyfacts API."""
        cik = self.get_cik_for_ticker(ticker)
        return self._transport.get_json(f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json")

    def get_latest_filing(self, ticker: str, form: str) -> Filing:
        """Return metadata for the latest filing matching ``form`` for ``ticker``."""
        return self.get_filings(ticker, form, limit=1)[0]

    def get_filings(self, ticker: str, form: str, *, limit: int = 1) -> list[Filing]:
        """Return up to ``limit`` newest filings matching one supported form.

        SEC's submissions response is not relied on to be ordered; matching rows are
        explicitly sorted by filing date in descending order before being limited.
        """
        if form not in SUPPORTED_FORMS:
            raise ValueError(f"Unsupported form {form!r}; expected one of {SUPPORTED_FORMS}.")
        if limit < 1:
            raise ValueError("limit must be at least 1.")

        normalized_ticker = ticker.strip().upper()
        company = self.get_company_for_ticker(normalized_ticker)
        cik = company["cik"]
        submissions = self._transport.get_json(f"{SEC_DATA_BASE_URL}/submissions/CIK{cik}.json")
        filing_cik = str(submissions.get("cik", cik)).zfill(10)
        recent = submissions.get("filings", {}).get("recent", {})

        filings = [
            _filing_from_recent_row(recent, index, normalized_ticker, filing_cik, company["company_name"])
            for index, candidate_form in enumerate(recent.get("form", []))
            if candidate_form == form
        ]
        filings.sort(key=lambda filing: filing.filing_date, reverse=True)
        if not filings:
            raise SecClientError(f"No recent filings found for {ticker}: {form}.")
        return filings[:limit]

    def get_latest_filings(
        self,
        ticker: str,
        forms: tuple[str, ...] = SUPPORTED_FORMS,
    ) -> dict[str, Filing]:
        """Return latest filing metadata for each requested form using one submissions request."""
        unsupported_forms = tuple(form for form in forms if form not in SUPPORTED_FORMS)
        if unsupported_forms:
            raise ValueError(
                f"Unsupported forms {unsupported_forms!r}; expected forms from {SUPPORTED_FORMS}."
            )

        normalized_ticker = ticker.strip().upper()
        company = self.get_company_for_ticker(normalized_ticker)
        cik = company["cik"]
        submissions = self._transport.get_json(f"{SEC_DATA_BASE_URL}/submissions/CIK{cik}.json")
        filing_cik = str(submissions.get("cik", cik)).zfill(10)
        recent = submissions.get("filings", {}).get("recent", {})

        recent_forms = recent.get("form", [])

        filings_by_form: dict[str, list[Filing]] = {form: [] for form in forms}
        for index, candidate_form in enumerate(recent_forms):
            if candidate_form in filings_by_form:
                filings_by_form[candidate_form].append(
                    _filing_from_recent_row(
                        recent, index, normalized_ticker, filing_cik, company["company_name"]
                    )
                )

        filings = {
            form: max(candidates, key=lambda filing: filing.filing_date)
            for form, candidates in filings_by_form.items()
            if candidates
        }

        missing_forms = tuple(form for form in forms if form not in filings)
        if missing_forms:
            raise SecClientError(f"No recent filings found for {ticker}: {', '.join(missing_forms)}.")
        return filings

    def filing_output_dir(self, filing: Filing, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
        """Return the descriptive output directory for a filing."""
        return (
            output_dir
            / filing.ticker.upper()
            / filing.form
            / filing.filing_date
            / filing.accession_number
        )

    def download_filing(self, filing: Filing, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
        """Download a filing document and return the path written."""
        destination_dir = self.filing_output_dir(filing, output_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / filing.filename
        destination.write_bytes(self._transport.get_bytes(filing.download_url))
        metadata_path = destination.with_name("metadata.json")
        metadata_path.write_text(
            json.dumps(filing.metadata(destination.name), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def download_latest_filing(
        self,
        ticker: str,
        form: str,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
    ) -> Path:
        """Download the latest filing for one supported form."""
        return self.download_filing(self.get_latest_filing(ticker, form), output_dir)

    def download_latest_filings(
        self,
        ticker: str,
        form: str,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        *,
        limit: int = 1,
    ) -> list[Path]:
        """Download up to ``limit`` newest filings for one supported form."""
        return [
            self.download_filing(filing, output_dir)
            for filing in self.get_filings(ticker, form, limit=limit)
        ]

    def download_latest_annual_and_quarterly(
        self,
        ticker: str,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
    ) -> list[Path]:
        """Download the latest 10-K and 10-Q filings for ``ticker``."""
        filings = self.get_latest_filings(ticker)
        return [self.download_filing(filings[form], output_dir) for form in ("10-K", "10-Q")]


DIRECT_DOCUMENT_URL_FIELDS = (
    "primaryDocumentUrl",
    "primaryDocUrl",
    "documentUrl",
    "filingUrl",
)


def _get_recent_document_url(recent: dict[str, Any], index: int) -> str | None:
    """Return a directly usable SEC document URL from a recent filing row if present."""
    for field_name in DIRECT_DOCUMENT_URL_FIELDS:
        field_values = recent.get(field_name, [])
        if index < len(field_values):
            candidate = str(field_values[index]).strip()
            if candidate.startswith(("https://www.sec.gov/", "https://sec.gov/")):
                return candidate
    return None


def _filing_from_recent_row(
    recent: dict[str, Any],
    index: int,
    ticker: str,
    cik: str,
    company_name: str,
) -> Filing:
    """Build a filing from a row in SEC's column-oriented recent filings data."""
    report_dates = recent.get("reportDate", [])
    return Filing(
        ticker=ticker,
        cik=cik,
        form=recent["form"][index],
        accession_number=recent["accessionNumber"][index],
        filing_date=recent["filingDate"][index],
        primary_document=recent["primaryDocument"][index],
        report_date=report_dates[index] if index < len(report_dates) else "",
        company_name=company_name,
        official_document_url=_get_recent_document_url(recent, index),
    )


def _decode_response(body: bytes, content_encoding: str | None) -> bytes:
    if not content_encoding:
        return body
    normalized_encoding = content_encoding.lower()
    if "gzip" in normalized_encoding:
        return gzip.decompress(body)
    if "deflate" in normalized_encoding:
        return zlib.decompress(body)
    return body


def _is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUS_CODES or 500 <= status <= 599


def _preview(body: bytes) -> str:
    return body[:BODY_PREVIEW_BYTES].decode("utf-8", errors="replace")
