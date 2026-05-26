# CoStaff Agent — WrenAI GenBI

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-2.0-orange.svg)](https://github.com/google/adk-python)
[![Docker](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![A2A Protocol](https://img.shields.io/badge/A2A-protocol-violet.svg)](https://github.com/google/A2A)

**繁體中文** | [English](./README.md)

**自然語言 → SQL 專家**，介接自架的 [WrenAI](https://github.com/Canner/WrenAI) GenBI 服務。一個 agent 實例綁定一個 MDL（語意模型），在部署時透過 env 變數設定 `WRENAI_BASE_URL` / `WRENAI_PROJECT_ID` / `WRENAI_MDL_HASH`。

---

## 它做什麼

| 工具 | 用途 |
|---|---|
| **`wrenai_answer(question, with_chart?)`** | **一鍵端到端。** 內部跑 ask → 透過 wren-ui GraphQL 執行 → 自然語言回答（+ 選擇性圖表）。引擎拒絕 SQL 時會自動透過 `/v1/sql-corrections` 重試一次。任何「回答我的資料問題」需求都優先用這個。 |
| `wrenai_ask(question)` | 只產 SQL，不執行。 |
| `wrenai_execute_sql(sql, limit?)` | 透過 wren-ui 的 `previewSql` GraphQL mutation 執行 SQL，回傳列。 |
| `wrenai_explain_result(question, sql, sql_data)` | 給定 (問題, SQL, 列) 三元組，產生自然語言回答。 |
| `wrenai_make_chart(question, sql, sql_data)` | 同樣三元組 → Vega-Lite v5 圖表規格。 |
| `wrenai_correct_sql(question, sql, error)` | 透過 `/v1/sql-corrections` 修復失敗的 SQL。 |
| `wrenai_recommend_questions()` | 上手用 ——「我可以問這個 MDL 什麼問題？」 |
| `wrenai_add_sql_pair(question, sql)` | 把驗證過的 (問題, SQL) 對寫入 WrenAI 的 qdrant 索引當 few-shot 範例。 |
| `wrenai_add_instruction(text, questions, is_default)` | 把領域規則加入 WrenAI knowledge base。 |
| `wrenai_health()` | 探測 `/health` 與設定的 MDL hash 的 `semantics-preparations` 狀態。 |
| `wrenai_save_rows_as_csv(rows, filename)` | 把查詢結果落地成 `/app/data/shared/costaff-agent-wrenai/<filename>.csv`。 |
| `wrenai_save_rows_as_json(rows, filename, indent?)` | 同上，但是 JSON。 |
| `wrenai_save_to_shared(filename, content, append?)` | 寫任意文字內容到共享 workspace。 |

## 它不做什麼（刻意設計）

- **不連線任意外部資料庫。** SQL 執行只走 wren-ui 的 `previewSql`，打在 project 設定的 MDL 之上 —— 要操作 WrenAI 之外的原始 DB，請用 `database-agent`。
- **不管 MDL prep。** Agent 不會打 `POST /v1/semantics-preparations` —— 那是 operator 在 wren-ui 部署時做的。Agent 只透過 `wrenai_health` 檢查狀態。
- **不能 runtime 切換 MDL。** 一個 agent 實例服務一個 schema。要另一個 schema，部署另一個實例，給不同 env。
- **不回傳無上限的結果集。** 列數會被 `WRENAI_EXEC_ROW_LIMIT`（預設 1000）截斷，保護下游 LLM context。

---

## 架構

```
CoStaff Manager
     │
     │  A2A Protocol (/.well-known/agent-card.json)
     ▼
WrenAI Agent (本 repo)  ── httpx ──▶  wren-ai-service:5555    (ask / corrections / charts / KB 寫入)
                        └─ GraphQL ─▶  wren-ui:3000/api/graphql  (previewSql → 對 project DB 執行)
```

**自給自足 —— caller 不需要在鏈中額外掛一個 database agent。** SQL 執行委派給 wren-ui 的 `previewSql` GraphQL mutation，由它去打 project 設定的資料來源。

end-to-end 一個資料問題，manager 通常只要呼叫 **`wrenai_answer(question)`** —— 內部會跑 ask → execute → explain（+ 選擇性 chart），引擎拒絕 SQL 時自動透過 `/v1/sql-corrections` 重試一次。

需要更細控制時，可以拆開呼叫底層工具：

1. `wrenai_ask(question)` → SQL。
2. `wrenai_execute_sql(sql)` → 列（透過 wren-ui）。
3. `wrenai_explain_result(question, sql, rows)` 與 / 或 `wrenai_make_chart(question, sql, rows)`。
4. 失敗時：`wrenai_correct_sql(question, sql, error)` → 修好的 SQL → 重新執行。

---

## 快速開始

### 前置需求

- 自架的 WrenAI OSS（agent 網路上要連得到，預設 port 5555）。
- MDL 已經在 AI service 上 prep 過（wren-ui 部署 project 時會自動觸發 `POST /v1/semantics-preparations`）。
- Google Gemini API key（預設 model `gemini-3.1-flash-lite`），或 LiteLLM 相容 provider。

### 透過 CoStaff CLI（建議）

```bash
costaff agent add wrenai --github https://github.com/costaff-ai/costaff-agent-wrenai-oss
# CLI 會提示輸入：GOOGLE_API_KEY, WRENAI_BASE_URL, WRENAI_UI_GRAPHQL_URL,
#                WRENAI_PROJECT_ID, WRENAI_MDL_HASH
```

### 獨立 Docker Compose

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

Agent 監聽 `http://localhost:8081`。A2A 探索端點 `/.well-known/agent-card.json`。

---

## 環境變數

| 變數 | 必填 | 預設 | 說明 |
|---|---|---|---|
| `GOOGLE_API_KEY` | 是（gemini） | — | Orchestrator 的 LLM key |
| `WRENAI_BASE_URL` | 是 | — | wren-ai-service URL，例如 `http://10.128.0.2:5555` |
| `WRENAI_UI_GRAPHQL_URL` | 是 | — | wren-ui 的 GraphQL URL（SQL 執行用），例如 `http://10.128.0.2:13000/api/graphql` |
| `WRENAI_PROJECT_ID` | 是 | — | wren-ui `project` 表的整數 id，如 `"1"` |
| `WRENAI_MDL_HASH` | 是 | — | wren-ui `deploy_log.hash` 的 40 字元 hex |
| `WRENAI_TIMEOUT` | 否 | `30` | 單次 HTTP timeout（秒） |
| `WRENAI_ASK_POLL_INTERVAL` | 否 | `2` | 非同步 job 的 poll 間隔 |
| `WRENAI_ASK_POLL_TIMEOUT` | 否 | `120` | 非同步 job 的最大總等待時間 |
| `WRENAI_EXEC_ROW_LIMIT` | 否 | `1000` | `wrenai_execute_sql` 回傳列數上限 |
| `COSTAFF_AGENT_MODEL_PROVIDER` | 否 | `gemini` | `gemini` 或 `litellm` |
| `WRENAI_AGENT_MODEL` | 否 | `gemini-3.1-flash-lite` | Orchestrator 用的 LLM（不是 WrenAI 自己內部的 LLM） |

WrenAI 自己產 SQL 時用的 LLM 是在 WrenAI 部署裡設定的，不在這裡。

---

## 找出 `WRENAI_PROJECT_ID` 與 `WRENAI_MDL_HASH`

在 WrenAI host 上、wren-ui 容器在跑時：

```bash
docker cp wrenai-wren-ui-1:/app/data/db.sqlite3 /tmp/wrenui.db
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/wrenui.db')
print('project_id:', c.execute('SELECT id FROM project LIMIT 1').fetchone()[0])
print('mdl_hash:  ', c.execute('SELECT hash FROM deploy_log WHERE status=\"SUCCESS\" ORDER BY created_at DESC LIMIT 1').fetchone()[0])
"
```

---

## 疑難排解

- **`wrenai_ask` 回 `type: "GENERAL"` 沒 SQL：** WrenAI 的 qdrant 還沒為這個 hash 索引 MDL。到 wren-ui 重新部署該 project（會觸發 `POST /v1/semantics-preparations`），或呼叫 `wrenai_health` 確認。
- **`wrenai_health` 顯示 `semantics_status: "missing"`：** 同上 —— 該 hash 還沒 prep。
- **網路 timeout：** 確認 agent 主機到 WrenAI 主機的 firewall 開了 WrenAI 的 port；若 WrenAI 在另一台 GCP VM，通常一條 VPC 防火牆規則就夠。
- **`mcp_configurable: false`：** 刻意設計 —— 本 agent 除了 4 個 manager-core 共用 shim 之外不需要任何 MCP 工具。純 httpx 設計也避開了多 MCP session 在 ADK/anyio 上的 cancel-scope race。

---

## License

[Apache 2.0](LICENSE)
