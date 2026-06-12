---
name: sql-inspect-execute-correct
description: >
  Granular SQL workflow with strict loop discipline: generate SQL only
  (wrenai_ask), execute it (wrenai_execute_sql), repair on engine error
  (wrenai_correct_sql, single attempt), explain pre-executed rows
  (wrenai_explain_result). Use when asked to 產生SQL/給我SQL/執行SQL/
  修正SQL/解釋查詢結果, when the caller wants the SQL string without
  execution, or already has rows and only needs an explanation.
---
# SQL Inspect / Execute / Correct Playbook

## Steps
1. **SQL only** — `wrenai_ask(question="...", histories=None)`. The primary
   candidate is `response[0].sql`; also surface `sql_generation_reasoning` and
   `retrieved_tables`. Pass `histories=[{"question": "...", "sql": "..."}]`
   only when the caller supplies prior turns. If the caller wants just the
   SQL, return it in a fenced ```sql block and STOP — no execution.
2. **Execute** — `wrenai_execute_sql(sql=<response[0].sql>, limit=None)`.
   Success shape: `{"columns": [{"name","type"}], "rows": [[...]],
   "row_count": N, "truncated_at": int|None}`. The SQL must come from
   `wrenai_ask` (or be supplied verbatim by the caller) — never hand-crafted.
3. **Correct on engine error (ONCE)** — if step 2 returns `{"error": ...}`,
   call `wrenai_correct_sql(sql=<failing sql>, error_message=<engine error
   verbatim>)`, then re-run `wrenai_execute_sql` with `corrected_sql`.
   Maximum ONE correction round per question.
4. **Explain caller-supplied rows** — when the caller already has rows (from
   step 2 or another agent), call `wrenai_explain_result(question, sql,
   sql_data={"columns": [...], "data": [[...]]}, custom_instruction=None)`.
   Return its `answer` verbatim plus `(based on <num_rows_used> rows)`.
5. **Report** — always include the final SQL in a fenced ```sql block; if a
   correction was applied, show both the original and corrected SQL and the
   `reasoning` from `wrenai_correct_sql`.

## Gates & failure handling
- READ-ONLY discipline: this agent only previews/SELECTs via wren-ui's
  previewSql path. Refuse any request to INSERT/UPDATE/DELETE/DDL — that is
  outside WrenAI's capability; recommend `database_agent`.
- Do NOT loop corrections more than once. A second engine rejection usually
  means the MDL is wrong, not the SQL — report both errors verbatim and stop.
- If `wrenai_ask` returns `type` other than `TEXT_TO_SQL` (GENERAL /
  MISLEADING_QUERY) or empty `response`, report that no SQL was generated,
  include `intent_reasoning`, and stop — never fabricate SQL.
- Never invent `sql_data` for `wrenai_explain_result` — if the caller did not
  supply rows and you did not execute, state what is missing.
- `limit` is hard-capped by `WRENAI_EXEC_ROW_LIMIT` (default 1000); mention
  `truncated_at` when set.
- SQL passes through verbatim — never translated, reformatted, or "cleaned up".
