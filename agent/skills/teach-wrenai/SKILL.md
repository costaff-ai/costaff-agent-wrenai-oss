---
name: teach-wrenai
description: >
  Improve future SQL generation by curating WrenAI's knowledge base: store
  verified question-SQL exemplars (wrenai_add_sql_pair), add domain rules
  (wrenai_add_instruction), suggest starter questions
  (wrenai_recommend_questions), and probe readiness (wrenai_health). Use when
  asked to 記住這個查詢/教 WrenAI/新增規則/業務邏輯/推薦問題/可以問什麼/
  健康檢查, "remember this as a good example", or "teach WrenAI that X means Y".
---
# Teach WrenAI Playbook

## Steps
1. **Store a verified exemplar** — `wrenai_add_sql_pair(question="<one
   natural sentence>", sql="<verified SQL>")`. Only after the SQL has been
   confirmed correct: it ran via `wrenai_execute_sql` (or `wrenai_answer`)
   without error AND the caller explicitly says to remember it. Return the
   `event_id` so the operator can track indexing.
2. **Add a domain rule** — `wrenai_add_instruction(text="<1-2 paragraph
   rule>", questions=["<trigger question>", ...], is_default=False)`.
   Examples: "revenue is always in TWD", "join orders.customer_id to
   customers.id". List concrete `questions` the rule should fire on; set
   `is_default=True` ONLY when the caller explicitly wants a global rule for
   every ask. Return the `event_id`.
3. **Onboard a new analyst** — `wrenai_recommend_questions(max_questions=5,
   max_categories=3, language="Traditional Chinese")` (match the user's
   language). Present `questions` grouped by `category`; each can be fed
   straight into `wrenai_answer`.
4. **Health probe** — `wrenai_health()` when asked "is WrenAI working" or
   after a suspicious GENERAL response. Report `wren_ai_service`,
   `semantics_status`, `ask_smoke_test`, `ready_for_ask`, and `notes`
   verbatim — no summarising away of the notes.

## Gates & failure handling
- Bad pairs poison the index: NEVER call `wrenai_add_sql_pair` on unverified
  or engine-rejected SQL, and never auto-add pairs after every ask. Explicit
  caller intent + verified execution are both required.
- `is_default=True` instructions affect EVERY future ask on this project —
  confirm the caller really wants a global rule before setting it; default to
  `is_default=False` with targeted `questions`.
- This agent is bound to ONE MDL (`WRENAI_PROJECT_ID` / `WRENAI_MDL_HASH`)
  fixed at deploy time — knowledge added here applies only to that project,
  and the MDL cannot be switched at runtime; say so if asked.
- Do not call `wrenai_health()` on every request — only on explicit ask or
  after a suspicious GENERAL/failed response. If `ready_for_ask=false`, the
  fix is operator-side (redeploy MDL via wren-ui); do not attempt re-prep.
- If a knowledge tool returns `{"error": ...}`, report it verbatim with no
  retry — indexing failures need operator attention, not loops.
