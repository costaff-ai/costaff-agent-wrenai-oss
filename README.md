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
| **`wrenai_answer(question, with_chart?)`** | **One-shot end-to-end.** Runs ask → execute via wren-ui GraphQL → natural-language answer (+ optional chart). Auto-retries once via `/v1/sql-corrections` if the engine rejects the generated SQL. Prefer this for any "answer my data question" request. |
| `wrenai_ask(question)` | SQL generation only (no execution). |
| `wrenai_execute_sql(sql, limit?)` | Execute a SQL via wren-ui's `previewSql` GraphQL mutation and return rows. |
| `wrenai_explain_result(question, sql, sql_data)` | Given a (question, sql, rows) triple, produce a natural-language answer. |
| `wrenai_make_chart(question, sql, sql_data)` | Same triple → Vega-Lite v5 chart spec. |
| `wrenai_correct_sql(question, sql, error)` | Repair a failing SQL via `/v1/sql-corrections`. |
| `wrenai_recommend_questions()` | Onboarding helper — "what could I ask about this MDL?". |
| `wrenai_add_sql_pair(question, sql)` | Store a verified (question, SQL) pair as a few-shot exemplar in WrenAI's qdrant index. |
| `wrenai_add_instruction(text, questions, is_default)` | Add a domain rule to WrenAI's knowledge base. |
| `wrenai_health()` | Probe `/health` + check `semantics-preparations` status for the configured MDL hash. |
| `wrenai_save_rows_as_csv(rows, filename)` | Persist query rows to `/app/data/shared/costaff-agent-wrenai/<filename>.csv`. |
| `wrenai_save_rows_as_json(rows, filename, indent?)` | Same, as JSON. |
| `wrenai_save_to_shared(filename, content, append?)` | Write arbitrary text content to the shared workspace. |

## What it does NOT do (by design)

- **Connect to arbitrary external databases.** SQL execution goes through wren-ui's `previewSql` against the project's configured MDL — for raw DBs outside WrenAI, use `database-agent`.
- **Manage MDL prep.** The agent does NOT call `POST /v1/semantics-preparations` — the operator does that via wren-ui at deploy time. The agent only *checks* prep status via `wrenai_health`.
- **Switch MDL at runtime.** One agent instance serves one schema. Deploy another instance with different env values to target a different MDL.
- **Return unbounded result sets.** Rows are capped at `WRENAI_EXEC_ROW_LIMIT` (default 1000) to protect downstream LLM context.

---

## Architecture

```
CoStaff Manager
     │
     │  A2A Protocol (/.well-known/agent-card.json)
     ▼
WrenAI Agent (this)  ── httpx ──▶  wren-ai-service:5555    (ask / corrections / charts / KB writes)
                     └─ GraphQL ─▶  wren-ui:3000/api/graphql  (previewSql → execute against project DB)
```

**Self-contained — the caller does NOT need a separate database agent in the chain.** SQL execution is delegated to wren-ui's `previewSql` GraphQL mutation, which runs the query against the project's configured data source.

For an end-to-end data question, the manager normally just calls **`wrenai_answer(question)`** — it internally runs ask → execute → explain (+ optional chart), and auto-retries once via `/v1/sql-corrections` if the engine rejects the SQL.

For granular control the lower-level tools can be chained explicitly:

1. `wrenai_ask(question)` → SQL.
2. `wrenai_execute_sql(sql)` → rows (via wren-ui).
3. `wrenai_explain_result(question, sql, rows)` and/or `wrenai_make_chart(question, sql, rows)`.
4. On failure: `wrenai_correct_sql(question, sql, error)` → fixed SQL → re-execute.

---

## Quickstart

### Prerequisites

- A self-hosted WrenAI OSS deployment reachable from this agent's network (typical port: 5555).
- The MDL must already be prepared on the AI service via `POST /v1/semantics-preparations` (wren-ui does this when you deploy a project).
- A Google Gemini API key (default model `gemini-3.1-flash-lite`) or a LiteLLM-compatible provider.

### Deploy via CoStaff CLI (recommended)

```bash
costaff agent add wrenai --github https://github.com/costaff-ai/costaff-agent-wrenai-oss
# CLI prompts for: GOOGLE_API_KEY, WRENAI_BASE_URL, WRENAI_UI_GRAPHQL_URL,
#                  WRENAI_PROJECT_ID, WRENAI_MDL_HASH
```

### Standalone Docker Compose

```bash
git clone https://github.com/costaff-ai/costaff-agent-wrenai-oss
cd costaff-agent-wrenai-oss

cat > .env <<EOF
GOOGLE_API_KEY=...
WRENAI_BASE_URL=http://10.128.0.2:5555
WRENAI_UI_GRAPHQL_URL=http://10.128.0.2:13000/api/graphql
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
| `WRENAI_BASE_URL` | yes | — | wren-ai-service URL, e.g. `http://10.128.0.2:5555` |
| `WRENAI_UI_GRAPHQL_URL` | yes | — | wren-ui GraphQL URL for SQL execution, e.g. `http://10.128.0.2:13000/api/graphql` |
| `WRENAI_PROJECT_ID` | yes | — | Integer-as-string from wren-ui's `project` table, e.g. `"1"` |
| `WRENAI_MDL_HASH` | yes | — | 40-char hex from wren-ui's `deploy_log.hash` |
| `WRENAI_TIMEOUT` | no | `30` | HTTP timeout per call (seconds) |
| `WRENAI_ASK_POLL_INTERVAL` | no | `2` | Poll cadence for async ask/answer/chart jobs |
| `WRENAI_ASK_POLL_TIMEOUT` | no | `120` | Max total wait for an async job |
| `WRENAI_EXEC_ROW_LIMIT` | no | `1000` | Hard cap on rows returned from `wrenai_execute_sql` |
| `COSTAFF_AGENT_MODEL_PROVIDER` | no | `gemini` | `gemini` or `litellm` |
| `WRENAI_AGENT_MODEL` | no | `gemini-3.1-flash-lite` | LLM for the orchestrator (not WrenAI's own LLM) |

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
