# End-to-End Fault-Tolerant GenAI Agent System

Solution to the GN Store Nord take-home assessment:

| Part | What | Where |
|---|---|---|
| 1 | Mock ticketing API (FastAPI, in-memory storage) | `ticket_api/` |
| 2 | GenAI agent with tool calling and a CLI (Azure OpenAI) | `agent/`, `ticket_client/` |
| Bonus | MCP server exposing the API as tools; the agent can use it | `mcp_server/`, `agent/mcp_backend.py` |
| 3 | PR review bot (Python script + GitHub Actions) | `pr_review/`, `.github/workflows/pr-review.yml` |
| 4 | Terraform skeleton for Azure App Service | `infra/` |
| 5 | Production design decision | [Part 5](#part-5-a-design-decision-to-change-for-production) |

Everything is written in Python 3.12. A second workflow, `.github/workflows/ci.yml`, runs the offline tests and the Terraform checks on every push to `main` and on every pull request.

## Architecture

```text
                 python -m agent [--backend direct|mcp]
 User ── CLI ──> Agent loop ───────────> Azure OpenAI (gpt-6-luna-c1)
                    │   tool calls
                    ▼
               ToolBackend
          ┌─────────┴───────────┐
   DirectBackend           McpBackend ──stdio──> MCP server (mcp_server/)
          │                                          │
          └──────────> ticket_client (HTTP) <────────┘
                              │
                              ▼
                Mock Ticketing API (ticket_api/, FastAPI)
```

- **API (Part 1):** CRUD endpoints for tickets with a status filter. Every 4xx response has the shape `{"detail": "<readable sentence>"}`.
- **Agent (Part 2):** a framework-free tool-calling loop on the Azure OpenAI SDK, with five tools (create, list with optional status filter, get, update, delete). The `status` tool parameter is a plain string with no list of valid values, so an invalid status reaches the API and the agent learns the valid options from the API's 422 message.
- **Fault tolerance:** API errors come back to the model as tool results (never exceptions). Connection errors and timeouts are reported clearly, and the CLI keeps running when the API is down or the LLM call fails. A turn is limited to 8 model calls, and an interrupted turn is removed from the conversation history.
- **MCP (bonus):** the same five tools, served with the official MCP Python SDK over stdio. The agent discovers them with `tools/list` and calls them with `tools/call`. Both backends use the same HTTP client, so they return identical results.

### API endpoints

| Method | Path | Success | Errors |
|---|---|---|---|
| `GET` | `/health` | 200 | |
| `POST` | `/tickets` | 201 + ticket | 422 |
| `GET` | `/tickets?status=OPEN` (filter optional) | 200 + list | 422 invalid status |
| `GET` | `/tickets/{id}` | 200 + ticket | 404 |
| `PATCH` | `/tickets/{id}` (only the fields sent change) | 200 + ticket | 404, 422 |
| `DELETE` | `/tickets/{id}` | 204 | 404 |

A ticket has `id`, `title`, `description`, `created`, `status` (`OPEN`, `RESOLVED`, `CLOSED`), `resolution` and the optional `updated` timestamp. Business rules:

- Unknown ID: 404 `Ticket with id 999 not found.`
- Invalid status: 422 `Invalid status 'PROGRESS'. Allowed values: OPEN, RESOLVED, CLOSED.`
- `RESOLVED` without a resolution note (optional rule, implemented): 422 `A resolution note is required when setting status to RESOLVED.`

The API starts with three dummy tickets: 1 and 2 `OPEN`, 3 `RESOLVED`. Data lives in memory and resets when the server restarts.

## Prerequisites

- **Python 3.12**
- **Git**
- **Terraform** 1.5 or newer (tested with 1.16.5), only for Part 4
- The Azure OpenAI values from the assessment brief, only for the agent, the scenarios and the PR review bot. The API, the tests and Terraform need no credentials.

## Installation

Run all commands from the repository root.

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

If PowerShell blocks `Activate.ps1`, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first (this affects the current window only).

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

All later commands assume the virtual environment is active, so `python` is the project's Python 3.12. Open every new terminal in the repository root and activate the environment there too.

## Configuration

Settings come from environment variables. Locally they are read from the git-ignored `.env` file created above. Open `.env` and replace `replace-with-your-key` with the API key from the brief.

| Variable | Used by | Value |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | agent, PR bot | `https://external-api.openai.azure.com/` |
| `AZURE_OPENAI_API_KEY` | agent, PR bot | key from the brief (never commit it) |
| `AZURE_OPENAI_DEPLOYMENT` | agent, PR bot | `gpt-6-luna-c1` |
| `AZURE_OPENAI_API_VERSION` | agent, PR bot | `2024-12-01-preview` |
| `TICKET_API_BASE_URL` | agent, MCP server | `http://127.0.0.1:8000` (default) |

The agent, the scenario runner and the PR bot dry run send requests to Azure OpenAI. Only dummy ticket data and this repository's own code are sent.

## Part 1: Run the ticketing API

```bash
python -m uvicorn ticket_api.main:app
```

The API listens on `http://127.0.0.1:8000`. Interactive documentation: `http://127.0.0.1:8000/docs`. Stop it with `Ctrl+C`.

Keep this terminal open: the agent, the MCP backend and the scenario runner all need the API running.

## Part 2: Run the agent (direct backend)

In a second terminal (virtual environment active, API running):

```bash
python -m agent
```

Type a request, for example `Retrieve all open tickets.` Commands: `/reset` clears the conversation, `/help`, `/exit`.

Options:

| Option | Effect |
|---|---|
| `--verbose` | Prints every tool call and the API result, so the orchestration is visible |
| `--backend direct` | Default: tools call the API over HTTP |
| `--backend mcp` | Tools go through the MCP server (see below) |
| `--confirm-deletes` | Asks `Delete ticket N? [y/N]` before every deletion. Only `y` or `yes` deletes; otherwise the ticket is kept and the agent is told that the user declined. Off by default |

Example: `python -m agent --verbose --confirm-deletes`

At start-up the CLI checks the API's `/health` endpoint and prints a warning if the API is not reachable. The CLI keeps running in that case.

## Bonus: Run the agent through MCP

With the API running:

```bash
python -m agent --backend mcp --verbose
```

The agent starts the MCP server (`mcp_server/server.py`) as a subprocess and talks to it over stdio. No separate server terminal is needed. All agent options work with both backends.

The server can also be started on its own for any MCP client (stdio transport):

```bash
python -m mcp_server.server
```

## The six GN scenarios

The scenario runner sends the six requests from the brief to the agent, each in a fresh conversation, and checks the API state afterwards (not the wording of the answer, which varies between runs). With the API running:

```bash
python -m agent.scenarios
python -m agent.scenarios --backend mcp
```

The command prints each scenario and ends with a summary such as `6/6 scenarios passed`. Exit code 0 means all six passed. Each run makes about 12 Azure OpenAI requests.

Recorded runs (both 6/6 passed):

- Direct backend: [`agent/transcripts/scenarios_direct.md`](agent/transcripts/scenarios_direct.md)
- MCP backend: [`agent/transcripts/scenarios_mcp.md`](agent/transcripts/scenarios_mcp.md)

Each transcript shows the request, every tool call with the API result, the agent's answer and the checks. Running the scenarios again **overwrites** the transcript for that backend.

| # | Request | What the transcript shows |
|---|---|---|
| 1 | Create a new ticket about a keyboard not working. | `create_ticket` → 201, new ID in the answer |
| 2 | Retrieve all open tickets. | `list_tickets` with `status=OPEN` |
| 3 | Get details for ticket [id]. | `get_ticket` → 200 |
| 4 | Update ticket [id] to have the status 'PROGRESS'. | API 422; the answer lists OPEN, RESOLVED, CLOSED from the API message |
| 5 | Update ticket [id] to be RESOLVED, adding 'Replaced faulty cable' as the resolution. | `update_ticket` with status and resolution → 200 |
| 6 | Update ticket [non-existent-id] to 'CLOSED'. | API 404; the answer says the ticket does not exist |

## Automated tests (offline)

```bash
python -m pytest -q
```

Expected result: `133 passed`. The tests need no API key, no `.env` file and no internet access: the API runs in-process, the LLM is replaced by a scripted fake, and GitHub calls are mocked. The MCP tests start the API on a free local port and the MCP server as a subprocess.

| Folder | Tests | Covers |
|---|---|---|
| `ticket_api/tests/` | 34 | CRUD, filtering, 404/422 messages, resolution rule |
| `ticket_client/tests/` | 14 | HTTP client results, timeouts, connection errors |
| `agent/tests/` | 30 | Tool loop, error relay, chaining, rollback, delete confirmation, CLI |
| `mcp_server/tests/` | 8 | MCP tools, error results, MCP backend parity with the direct backend |
| `pr_review/tests/` | 47 | Diff fetch, truncation, prompt, credential check, posting one comment |

The CI workflow (`.github/workflows/ci.yml`) runs the same tests on Ubuntu with Python 3.12, plus `terraform fmt -check` and `terraform validate`. It uses no secrets.

## Part 3: PR review bot

`pr_review/analyze_pr.py` fetches a pull request's diff through the GitHub API, sends it to Azure OpenAI for a summary and suggestions, and posts **one** comment on the PR. `.github/workflows/pr-review.yml` runs it on `pull_request` events of type `opened` and `synchronize`.

### Set up in GitHub

1. Push the repository to GitHub.
2. Add the repository secret in **Settings → Secrets and variables → Actions → New repository secret**:
   - Name: `AZURE_OPENAI_API_KEY`
   - Value: the key from the brief
3. Open a pull request from a branch of the same repository. The **PR review bot** workflow runs and posts one comment. Every new push to the PR posts a new comment.

No other secret is needed. The endpoint, deployment and API version are plain values in the workflow file, and the GitHub token is the built-in `GITHUB_TOKEN`, limited to `contents: read` and `pull-requests: write`.

> **Example PR:** _[placeholder: link to a pull request in this repository with the bot's comment]_

### Local dry run

A dry run reviews a diff file and prints the comment instead of posting it. It needs only the `AZURE_OPENAI_*` values in `.env`; no GitHub token is used. It makes one Azure OpenAI request. Using the sample diff included in the tests:

```bash
python pr_review/analyze_pr.py --dry-run --diff-file pr_review/tests/fixtures/sample.diff
```

To review your own changes, create the diff with `git diff --output=...` (on Windows PowerShell 5.1, `>` would write UTF-16, which the bot rejects). For example, from a feature branch:

```bash
git diff --output=change.diff main
python pr_review/analyze_pr.py --dry-run --diff-file change.diff
```

Exit codes: 0 = comment posted or printed, 1 = readable error (no partial comment), 2 = invalid options.

## Part 4: Terraform (Azure)

`infra/main.tf` defines three resources: a resource group, a Linux App Service plan (B1) and a Linux web app that runs the API with Python 3.12 and `python -m uvicorn ticket_api.main:app --host 0.0.0.0 --port 8000`. `variables.tf` has five variables with defaults (`project_name`, `location`, `sku_name`, `python_version`, `tags`); `outputs.tf` returns `api_url`, `resource_group_name` and `web_app_name`.

Validate (no Azure account needed, nothing is deployed):

```bash
cd infra
terraform fmt -check
terraform init
terraform validate
```

Expected: `terraform fmt -check` prints nothing (exit code 0), `terraform init` installs the `hashicorp/azurerm` provider (4.x, pinned in `.terraform.lock.hcl`), and `terraform validate` prints `Success! The configuration is valid.` Return to the repository root with `cd ..`.

A real deployment would additionally need an Azure login, the subscription ID in the `ARM_SUBSCRIPTION_ID` environment variable (required by the AzureRM v4 provider), a globally unique `project_name` (`terraform apply -var project_name=<unique-name>`), and a separate step that deploys the code to the web app.

## Limitations

- **In-memory storage:** data is lost on restart, and the API must run as a single process (one Uvicorn worker), because each process would hold its own copy.
- **No authentication** on the API or the MCP server. Both are meant for local use.
- **Swagger UI (`/docs`) shows FastAPI's default 422 schema** (a list of errors). The real 422 body is always `{"detail": "<string>"}`.
- **LLM output varies between runs.** The scenario runner therefore checks the API state and the tool calls, not the exact answer. The deployment rejects tool calls unless `reasoning_effort="none"` is sent, so the agent always sends it.
- **Conversation memory** lasts for one CLI session only (`/reset` clears it).
- **MCP** uses the local stdio transport: one server process per agent, no remote access.
- **PR bot:** pull requests from forks receive no repository secrets, so the bot cannot run for them; diffs longer than 20,000 characters are truncated (the comment says so); the review quality depends on the model. For a PR from a branch of the same repository, the workflow runs that branch's version of the bot with the secret, so only trusted collaborators should have write access.
- **Terraform** has only been validated, not planned or applied. The default web app name may already be taken in Azure, and state would be stored locally.

## Part 5: A design decision to change for production

One design decision I would change for production is the in-memory ticket storage. While it keeps the current solution simple and easy to test, all ticket data is lost when the application restarts, and multiple instances cannot share the same data. I would replace it with a persistent database such as PostgreSQL to ensure data durability and support scalability. This would introduce additional infrastructure and maintenance costs, but it would make the system more reliable and suitable for real-world use.

Additionally, as the agent grows in complexity, I would consider using frameworks such as LangChain to simplify tool orchestration, improve maintainability, and support more advanced workflows. For the current scope, however, using the Azure OpenAI SDK directly keeps the implementation simpler and avoids unnecessary dependencies.

## Project structure

```text
ticket_api/        Part 1: FastAPI app (main.py), models, in-memory storage, error handling, tests
ticket_client/     HTTP client for the API, shared by the agent and the MCP server, tests
agent/             Part 2: agent loop, tool backends, CLI, scenario runner, transcripts, tests
mcp_server/        Bonus: MCP server with the five ticket tools, tests
pr_review/         Part 3: analyze_pr.py, its own requirements.txt, tests and a sample diff
infra/             Part 4: main.tf, variables.tf, outputs.tf, provider lock file
.github/workflows/ pr-review.yml (Part 3 bot), ci.yml (tests + Terraform checks)
requirements.txt   Runtime dependencies (exact versions)
requirements-dev.txt  Runtime dependencies + pytest
.env.example       Template for the local .env file
```
