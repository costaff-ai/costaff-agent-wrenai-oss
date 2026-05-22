# CoStaff Agent — WrenAI GenBI

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-2.0-orange.svg)](https://github.com/google/adk-python)
[![Docker](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![A2A Protocol](https://img.shields.io/badge/A2A-protocol-violet.svg)](https://github.com/google/A2A)
[![costaff.agent.json](https://img.shields.io/badge/costaff-compatible-blue.svg)](https://github.com/costaff-ai/costaff)

[繁體中文](./README_zhtw.md) | **English**

**Natural-language → SQL specialist over a self-hosted [WrenAI](https://github.com/Canner/WrenAI) GenBI deployment.** Bound to one MDL (semantic model) per instance; the operator sets `WRENAI_BASE_URL`, `WRENAI_PROJECT_ID`, and `WRENAI_MDL_HASH` at deploy time.

---

## What it does

| Tool | Purpose |
|---|---|
| `wrenai_ask(question)` | Translate a natural-language question to SQL + reasoning + retrieved tables, using the configured MDL. |
| `wrenai_explain_result(question, sql, sql_data)` | Given a question, its SQL, and the executed rows, produce a natural-language answer. |
| `wrenai_make_chart(question, sql, sql_data)` | Given the same inputs, produce a Vega-Lite v5 chart spec. |
| `wrenai_add_sql_pair(question, sql)` | Store a verified (question, SQL) pair as a few-shot exemplar in WrenAI's qdrant index. |
| `wrenai_add_instruction(text, questions, is_default)` | Add a domain rule to WrenAI's knowledge base. |
| `wrenai_health()` | Probe `/health` + check `semantics-preparations` status for the configured MDL hash. |

## What it does NOT do (by design)

- **Execute SQL.** The agent generates SQL only; the caller (typically `database-agent`) executes it and passes rows back for `wrenai_explain_result` / `wrenai_make_chart`. Separating generation from execution keeps each agent's responsibility clean and avoids embedding a DB driver here.
- **Manage MDL prep.** The agent does NOT call `POST /v1/semantics-preparations` — the operator does that via wren-ui at deploy time. The agent only *checks* prep status via `wrenai_health`.
- **Switch MDL at runtime.** One agent instance serves one schema. Deploy another instance with different env values to target a different MDL.

---

## Architecture

```
CoStaff Manager
     │
     │  A2A Protocol (/.well-known/agent-card.json)
     ▼
WrenAI Agent (this)              ── httpx ──▶  wren-ai-service:5555
                                                 (self-hosted OSS WrenAI)
     │
     │  AgentTool dispatch
     ▼
database_agent                                  (executes the SQL)
```

For each end-to-end question the manager typically:

1. Calls `wrenai_ask` here to get SQL.
2. Calls `database_agent` to execute that SQL and return rows.
3. Calls `wrenai_explain_result` / `wrenai_make_chart` here with `(question, sql, rows)` to get the natural-language answer and / or chart spec.

---

## Quickstart

### Prerequisites

- A self-hosted WrenAI OSS deployment reachable from this agent's network (typical port: 5555).
- The MDL must already be prepared on the AI service via `POST /v1/semantics-preparations` (wren-ui does this when you deploy a project).
- A Google Gemini API key (default model `gemini-3.1-flash-lite-preview`) or a LiteLLM-compatible provider.

### Deploy via CoStaff CLI (recommended)

```bash
costaff agent add wrenai --github https://github.com/costaff-ai/costaff-agent-wrenai
# CLI prompts for: GOOGLE_API_KEY, WRENAI_BASE_URL, WRENAI_PROJECT_ID, WRENAI_MDL_HASH
```

### Standalone Docker Compose

```bash
git clone https://github.com/costaff-ai/costaff-agent-wrenai
cd costaff-agent-wrenai

cat > .env <<EOF
GOOGLE_API_KEY=...
WRENAI_BASE_URL=http://10.128.0.2:5555
WRENAI_PROJECT_ID=1
WRENAI_MDL_HASH=f91a37d52b86f0e302421d752955d7a41f7509d1
EOF

docker compose --env-file .env up -d --build
```

Agent listens on `http://localhost:8081`. A2A discovery endpoint: `/.well-known/agent-card.json`.

---

## Environment

| Var | Required | Default | Notes |
|---|---|---|---|
| `GOOGLE_API_KEY` | yes (gemini) | — | LLM key for the orchestrator |
| `WRENAI_BASE_URL` | yes | — | e.g. `http://10.128.0.2:5555` (internal IP) or `https://wren.example.com` |
| `WRENAI_PROJECT_ID` | yes | — | Integer-as-string from wren-ui's `project` table, e.g. `"1"` |
| `WRENAI_MDL_HASH` | yes | — | 40-char hex from wren-ui's `deploy_log.hash` |
| `WRENAI_TIMEOUT` | no | `30` | HTTP timeout per call (seconds) |
| `WRENAI_ASK_POLL_INTERVAL` | no | `2` | Poll cadence for async ask/answer/chart jobs |
| `WRENAI_ASK_POLL_TIMEOUT` | no | `120` | Max total wait for an async job |
| `COSTAFF_AGENT_MODEL_PROVIDER` | no | `gemini` | `gemini` or `litellm` |
| `WRENAI_AGENT_MODEL` | no | `gemini-3.1-flash-lite-preview` | LLM for the orchestrator (not WrenAI's own LLM) |

The LLM used by WrenAI itself for SQL generation is configured inside WrenAI's deployment, not here.

---

## Finding `WRENAI_PROJECT_ID` and `WRENAI_MDL_HASH`

On your WrenAI host, with `wren-ui` running:

```bash
# wren-ui uses sqlite at /app/data/db.sqlite3 inside the container
docker cp wrenai-wren-ui-1:/app/data/db.sqlite3 /tmp/wrenui.db
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/wrenui.db')
print('project_id:', c.execute('SELECT id FROM project LIMIT 1').fetchone()[0])
print('mdl_hash:  ', c.execute('SELECT hash FROM deploy_log WHERE status=\"SUCCESS\" ORDER BY created_at DESC LIMIT 1').fetchone()[0])
"
```

---

## Troubleshooting

- **`wrenai_ask` returns `type: "GENERAL"` with no SQL.** WrenAI's qdrant did not index the MDL for the configured hash. Re-deploy the project in wren-ui (which triggers `POST /v1/semantics-preparations` on the AI service), or call `wrenai_health` to confirm.
- **`wrenai_health` shows `semantics_status: "missing"`.** Same as above — prep has not run for this hash yet.
- **Network timeouts.** Confirm the firewall path between this agent's host and the WrenAI host allows TCP on the WrenAI port; if WrenAI is on another GCP VM, a single VPC firewall rule is usually enough.
- **`mcp_configurable: false` in manifest.** Intentional — this agent does not need any of the manager-core MCP tools beyond the 4 shared shims. The httpx-only design also sidesteps the ADK/anyio cancel-scope race seen on multi-MCP-session agents (see [project memory](https://github.com/costaff-ai/costaff)).

---

## License

[Apache 2.0](LICENSE)
