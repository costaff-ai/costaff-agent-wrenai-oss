---
name: bi-question-answer
description: >
  Answer a natural-language business-intelligence question end-to-end with
  full SQL transparency: one wrenai_answer call runs ask -> execute -> explain
  and returns answer + SQL + rows. Use when asked to 查數據/查營收/數據分析/
  報表數字/統計/有多少筆/分布/趨勢, or any "what does the data say about X"
  question, optionally followed by 匯出/存檔 to CSV or JSON.
---
# NL BI Question -> Answer Playbook

## Steps
1. **One-shot answer** — `wrenai_answer(question="<verbatim user question>", with_chart=False)`.
   Do NOT decompose into ask/execute/explain yourself; the tool chains them and
   auto-retries the SQL once via sql-corrections if the engine rejects it.
2. **Check the result dict** — success means `error` is null and `answer` is
   non-empty. The dict also carries `sql`, `retrieved_tables`,
   `sql_generation_reasoning`, `columns`, `rows`, `row_count`.
3. **Report with SQL transparency** — return the `answer` string, then the
   `sql` in a fenced ```sql block, then `Row count: <row_count>`. If
   `sql_correction_applied` is true, say so and show `sql_before_correction`.
4. **Export when asked** — chain a save tool AFTER `wrenai_answer`, passing its
   `rows` field verbatim:
   - `wrenai_save_rows_as_csv(rows=<rows>, filename="<name>.csv")`
   - `wrenai_save_rows_as_json(rows=<rows>, filename="<name>.json")`
   - `wrenai_save_to_shared(filename, content)` for text (report / SQL string).
   Filenames must match `[A-Za-z0-9._-]+` — no slashes, no `..`. Report the
   returned `path` (under `/app/data/shared/costaff-agent-wrenai/`) in backticks.
5. **User doesn't know what to ask?** — call
   `wrenai_recommend_questions(max_questions=5, max_categories=3, language=...)`
   and present the suggested questions grouped by category.

## Gates & failure handling
- NEVER hand-write SQL and never invent rows, tables, or columns. Every SQL
  shown must come verbatim from a tool result; the MDL is the ground truth.
- If `wrenai_answer` returns an error mentioning `type=GENERAL` / "MDL is not
  indexed": call `wrenai_health()` ONCE. If `ready_for_ask=false`, return the
  health `notes` verbatim and stop — the operator must redeploy the MDL via
  wren-ui; do not retry the question.
- If `ready_for_ask=true` but the ask still classifies as GENERAL, the question
  is genuinely outside the schema — say so, list `retrieved_tables` if any,
  and stop. Do not fabricate an answer.
- If `error` starts with "explain failed" but rows are present, return the SQL
  and rows and state plainly that the natural-language summary step failed —
  do not paraphrase your own answer from the rows.
- Rows are capped (default 1000, `truncated_at` set when hit) — mention the cap
  whenever it triggered.
- Report engine/tool errors verbatim; never reword them into guesses.
