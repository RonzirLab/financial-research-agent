# Financial Research Agent

A small Python project that downloads the latest annual (10-K) and quarterly (10-Q)
SEC filings for an input ticker using SEC official JSON data endpoints. Downloads are
stored under `data/sec` by default.

## Setup

```bash
uv sync
```

## Usage

SEC requires a descriptive User-Agent for automated requests. Set `SEC_USER_AGENT_EMAIL` to a real contact email; the client sends `Financial Research Agent <your email>` as the User-Agent.

```bash
SEC_USER_AGENT_EMAIL="YOUR_EMAIL@example.com" uv run python -m financial_research_agent.cli AAPL
```

For example, to fetch AMD filings into the default `data/sec` folder:

```bash
SEC_USER_AGENT_EMAIL="YOUR_EMAIL@example.com" uv run python -m financial_research_agent.cli AMD
```

## Tests

```bash
uv run python -m unittest discover -s tests
```
