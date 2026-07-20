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

Download the newest supported filings for a ticker with the `sec download` command.
Supported forms are `10-K`, `10-Q`, and `8-K`.

```bash
uv run python -m financial_research_agent.sec download \
  --ticker AMD \
  --form 10-K \
  --latest 1 \
  --output data/sec
```

The downloader resolves the ticker to a CIK, fetches the SEC submissions JSON,
downloads each primary filing HTML, and writes a `metadata.json` beside every
filing in a deterministic, accession-specific folder such as:

```text
data/sec/AMD/10-K/2025-02-05/0000002488-26-000018/
```

## Parse 10-K and 10-Q sections

Parse an already-downloaded local filing without making a network request:

```bash
uv run python -m financial_research_agent.sec parse \
  --form 10-K \
  --filing data/sec/AMD/10-K/2025-02-05/0000002488-26-000018/AMD_10-K_2025-02-05_0000002488-26-000018.htm
```

This writes `sections.json` and `sections.md` beside the filing. The JSON records
each section's title, item identifier, readable text, start position, and character
count. In the download workflow, enable the optional `parse` input to include these
outputs for 10-K and 10-Q filings in the artifact.

## Analyze selected 10-K sections with an LLM

The v1 analyzer reads parser-produced `sections.json` and uses only Items 1, 1A,
7, and 7A. It writes auditable `analysis.json` and `analysis.md`; each conclusion
has a source item and short filing excerpt, and the Markdown separates filing facts
from LLM interpretation. It does not provide investment recommendations, target
prices, or valuations.

Select the provider explicitly. `mock` is deterministic and does not make a
network request. `openai` uses the official OpenAI Python SDK and requires an
API credential (never place the key in a command argument or file). `OPENAI_MODEL`
is optional and defaults to `gpt-4o-mini`; `--model` overrides it.

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY="your_api_key_here"
uv run python -m financial_research_agent.sec analyze \
  --sections data/sec/AMD/10-K/2025-02-05/0000002488-26-000018/sections.json \
  --output-dir data/sec/AMD/10-K/2025-02-05/0000002488-26-000018
```

The command prints the selected provider and model, never the API key. It never
falls back from `openai` to `mock`: set `LLM_PROVIDER=mock` explicitly for an
offline deterministic run.

### Real AMD smoke test

After parsing an AMD 10-K locally, run one live-provider smoke test against its
existing `sections.json`:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY="your_api_key_here"
uv run python scripts/openai_amd_smoke_test.py \
  --sections data/sec/AMD/10-K/<filing-id>/sections.json \
  --output-dir /tmp/amd-openai-smoke
```

This creates `/tmp/amd-openai-smoke/analysis.json` and
`/tmp/amd-openai-smoke/analysis.md`. The JSON includes `usage.model`,
`usage.input_tokens`, `usage.output_tokens`, and `usage.total_tokens` when the
provider reports them.

`--model` can select an OpenAI model and defaults to `gpt-4o-mini`. The existing
**SEC Filing Download** workflow has an `analyze` input. When enabled for a 10-K,
it requires the `OPENAI_API_KEY` repository secret, analyzes parsed outputs, and
uploads the raw HTML, parser outputs, and analysis outputs together.

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
5. Enter a ticker, form (`10-K`, `10-Q`, or `8-K`), and the number of newest
   matching filings to download in `latest`.
6. Download the `sec-filing-<ticker>-<form>` artifact from the completed workflow
   run to retrieve the filing HTML and metadata JSON.

## Tests

```bash
uv run python -m unittest discover -s tests
```
