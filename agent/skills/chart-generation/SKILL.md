---
name: chart-generation
description: >
  Produce a Vega-Lite v5 chart spec for a data question, either in one shot
  (wrenai_answer with_chart=True) or from pre-executed rows
  (wrenai_make_chart). Use when asked to 畫圖/圖表/視覺化/長條圖/折線圖/
  圓餅圖/趨勢圖, "plot this", "chart the result", or any answer that should
  ship with a visualisation.
---
# Chart Generation Playbook

## Steps
1. **Pick the path**:
   - Fresh question, no rows yet -> `wrenai_answer(question="...",
     with_chart=True)`. One call returns `answer`, `sql`, `rows`, AND a
     `chart` object `{chart_type, vega_lite_spec, reasoning}`.
   - Caller already has (question, sql, rows) -> `wrenai_make_chart(question,
     sql, sql_data={"columns": [...], "data": [[...]]})`. Returns
     `{status, chart_type, vega_lite_spec, reasoning}`.
2. **Render the output** — return the `vega_lite_spec` as a fenced ```json
   block and state the `chart_type` on its own line so the frontend knows what
   to render. Include the natural-language `answer` (one-shot path) and the
   SQL in a fenced ```sql block for transparency.
3. **Table fallback** — if `chart_type == "table"`, WrenAI judged the data
   unsuitable for a chart. Say so, cite the tool's `reasoning`, and present
   the rows as a markdown table instead of forcing a chart.
4. **Persist when asked** — to save the spec, call
   `wrenai_save_to_shared(filename="<name>.json", content=<spec as JSON
   string>)`; to save the underlying data, `wrenai_save_rows_as_csv(rows,
   filename="<name>.csv")`. Filenames match `[A-Za-z0-9._-]+`, no slashes.

## Gates & failure handling
- Never invent `sql_data` — `wrenai_make_chart` requires real pre-executed
  rows. If the caller has none, run the one-shot path or state what is
  missing; do not synthesise sample rows.
- Never draft a Vega-Lite spec yourself. The spec must come verbatim from
  `wrenai_make_chart` or the `chart` field of `wrenai_answer`. If the chart
  step failed (`error` contains "chart failed"), return the answer + rows and
  report the chart failure verbatim — a missing chart is not a missing answer.
- Do not retry a failed chart call more than once; repeated chart failures
  point at the rows' shape, not transient flakiness — report and stop.
- Do not edit or "improve" the returned spec (colors, titles, encodings) —
  pass it through unchanged so the frontend renders what WrenAI produced.
