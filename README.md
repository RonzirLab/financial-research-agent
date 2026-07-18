# Financial Research Agent

A small Python project that downloads SEC filings for an input ticker using SEC
official JSON data endpoints. Downloads are stored under `data/sec` by default.

## Setup

```bash
uv sync
```

## SEC User-Agent configuration

SEC requires a descriptive User-Agent for automated requests. Set both variables
locally or in GitHub Actions secrets before making live SEC requests:

```bash
export SEC_USER_AGENT_NAME="YOUR_NAME_OR_APP_NAME"
export SEC_USER_AGENT_EMAIL="YOUR_EMAIL@example.com"
```

Do not commit personal contact information or secrets to the repository.

## Usage

Download the newest supported filing for a ticker with the `sec download` command.
Supported forms are `10-K`, `10-Q`, and `8-K`.

```bash
uv run python -m financial_research_agent.sec download \
  --ticker AMD \
  --form 10-K \
  --latest 1 \
  --output data/sec
```

The downloader resolves the ticker to a CIK, fetches the SEC submissions JSON,
downloads the primary filing HTML, and writes `metadata.json` next to the filing in
a descriptive folder such as:

```text
data/sec/AMD/10-K/2025-02-05/
```

The older convenience CLI still downloads the latest annual and quarterly filings:

```bash
uv run python -m financial_research_agent.cli AMD
```

## Running the downloader from GitHub Actions in your browser

1. Add repository secrets named `SEC_USER_AGENT_NAME` and
   `SEC_USER_AGENT_EMAIL` in **Settings → Secrets and variables → Actions**.
2. Open the **Actions** tab in GitHub.
3. Select the **SEC Filing Download** workflow.
4. Choose **Run workflow**.
5. Enter a ticker, form (`10-K`, `10-Q`, or `8-K`), and `latest` value (`1`).
6. Download the `sec-filing-<ticker>-<form>` artifact from the completed workflow
   run to retrieve the filing HTML and metadata JSON.

## Tests

```bash
uv run python -m unittest discover -s tests
```
