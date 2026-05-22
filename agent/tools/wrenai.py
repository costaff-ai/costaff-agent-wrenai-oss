"""WrenAI GenBI tools exposed to the LlmAgent.

Each tool returns a primitive dict; failures come back as
{"error": "..."} rather than raised so the LLM can read and recover.

Bound to one WRENAI_MDL_HASH per agent deployment. The agent does NOT
execute SQL — `wrenai_explain_result` and `wrenai_make_chart` require
the caller to supply pre-executed rows in `sql_data` (typically
obtained via the database-agent).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from . import _wrenai as wai
from . import _wrenui as wui

logger = logging.getLogger(__name__)


# ---------------------------------------------------------- ask + helpers


def wrenai_ask(
    question: str,
    histories: Optional[List[Dict[str, str]]] = None,
) -> dict:
    """Translate a natural-language question into SQL against the configured MDL.

    The agent's MDL (semantic model + project_id) is fixed at deployment
    time via WRENAI_MDL_HASH / WRENAI_PROJECT_ID; one agent serves one
    schema. To target a different schema, deploy another instance with
    different env values.

    Args:
        question: The question, in any natural language. WrenAI rephrases
            internally before generating SQL.
        histories: Optional list of prior turns to provide conversational
            context. Each entry shaped {"question": "...", "sql": "..."}
            (matches WrenAI's AskHistory schema).

    Returns a dict with:
      - status: "finished" | "failed" | "stopped"
      - type: "TEXT_TO_SQL" (success) | "GENERAL" (no schema match, fallback chat) | "MISLEADING_QUERY"
      - rephrased_question: WrenAI's normalised version of the question
      - sql_generation_reasoning: step-by-step plan WrenAI used
      - retrieved_tables: tables WrenAI considered relevant from the MDL
      - response: list of `{"sql": "...", "type": "llm" | ...}` candidates;
                  the first item is the primary suggestion
      - error: only set when status == "failed"

    If type == "GENERAL" (no SQL was generated), the MDL likely is not
    prepped in qdrant for this mdl_hash — run `wrenai_health` to confirm,
    or re-deploy the MDL via wren-ui.
    """
    try:
        out = wai.ask_full(question, histories=histories)
        if out.get("error"):
            return out
        # Slim down the response — the manager doesn't need internal trace_id etc.
        return {
            "status": out.get("status"),
            "type": out.get("type"),
            "rephrased_question": out.get("rephrased_question"),
            "intent_reasoning": out.get("intent_reasoning"),
            "sql_generation_reasoning": out.get("sql_generation_reasoning"),
            "retrieved_tables": out.get("retrieved_tables") or [],
            "response": out.get("response") or [],
            "invalid_sql": out.get("invalid_sql"),
            "error": out.get("error"),
            "query_id": out.get("query_id"),
        }
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_ask failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def wrenai_explain_result(
    question: str,
    sql: str,
    sql_data: Dict[str, Any],
    custom_instruction: Optional[str] = None,
) -> dict:
    """Turn (question, sql, executed rows) into a natural-language answer.

    Use this AFTER `wrenai_ask` produced SQL AND the caller has executed
    it against the data source (e.g. database-agent). This is the
    explanatory step — WrenAI summarises the rows in the user's
    preferred language and ties them back to the question.

    Args:
        question: The original (or rephrased) user question.
        sql: The SQL string returned by `wrenai_ask`.
        sql_data: The execution result, shaped roughly
            {"columns": ["col_a", ...], "data": [[v1, v2, ...], ...]}.
            WrenAI is lenient about exact key names; passing the raw
            cursor result usually works.
        custom_instruction: Optional one-shot tone / style hint for the
            answer (e.g. "Reply in formal Mandarin and round numbers to 1 decimal").

    Returns {"status", "num_rows_used", "answer", ...} on success, or
    {"error": "..."} on failure.
    """
    try:
        out = wai.sql_answer_full(question, sql, sql_data, custom_instruction)
        if out.get("error"):
            return out
        return {
            "status": out.get("status"),
            "num_rows_used": out.get("num_rows_used"),
            "answer": out.get("answer"),
            "error": out.get("error"),
            "query_id": out.get("query_id"),
        }
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_explain_result failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def wrenai_make_chart(
    question: str,
    sql: str,
    sql_data: Dict[str, Any],
) -> dict:
    """Generate a Vega-Lite chart spec for (question, sql, executed rows).

    Same input contract as `wrenai_explain_result`: caller must supply
    pre-executed rows in `sql_data`. Output is a Vega-Lite v5 JSON
    spec the frontend can render directly.

    Returns {"status", "chart_type", "vega_lite_spec", "reasoning", ...}
    or {"error": "..."}. If `chart_type == "table"`, WrenAI decided the
    data is best shown as a table rather than a chart.
    """
    try:
        out = wai.chart_full(question, sql, sql_data)
        if out.get("error"):
            return out
        return {
            "status": out.get("status"),
            "chart_type": out.get("chart_type"),
            "reasoning": out.get("reasoning"),
            "vega_lite_spec": out.get("vega_lite_spec") or out.get("chart_schema"),
            "error": out.get("error"),
            "query_id": out.get("query_id"),
        }
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_make_chart failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------- execute + one-shot


def wrenai_execute_sql(sql: str, limit: Optional[int] = None) -> dict:
    """Execute SQL via wren-ui's previewSql GraphQL mutation.

    This runs the SQL through wren-engine against the project's
    underlying data source (DuckDB in the sample / your configured
    warehouse otherwise) and returns the rows directly. Use this
    AFTER `wrenai_ask` produced a SQL string, when the caller wants
    rows back without involving a separate database agent.

    Args:
        sql: The SQL to execute. Should be from `wrenai_ask` — do not
            hand-craft SQL; let WrenAI produce it.
        limit: Optional row cap. Hard-capped by WRENAI_EXEC_ROW_LIMIT
            (default 1000) to protect downstream LLM context.

    Returns:
        On success: {"columns": [{"name", "type"}], "rows": [[...]],
                     "row_count": N, "truncated_at": int | None}
        On failure: {"error": "..."}
    """
    try:
        out = wui.preview_sql(sql, limit=limit)
        return out
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_execute_sql failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def wrenai_answer(question: str, with_chart: bool = False) -> dict:
    """High-level one-shot: ask + execute + explain (+ optional chart).

    The "human prompt" path — call this when the caller wants a final
    natural-language answer to a data question without orchestrating
    ask / execute / explain steps separately. Internally runs:

      1. wrenai_ask(question)          -> SQL + reasoning
      2. wrenai_execute_sql(sql)       -> rows via wren-ui
      3. wrenai_explain_result(...)    -> natural-language answer
      4. (optional) wrenai_make_chart  -> Vega-Lite spec

    Args:
        question: The user's natural-language question.
        with_chart: If True, also build a Vega-Lite chart spec.

    Returns:
        {
          "question": str,
          "sql": str,
          "retrieved_tables": [...],
          "sql_generation_reasoning": str,
          "row_count": int,
          "columns": [...],
          "rows": [[...]],         # capped by WRENAI_EXEC_ROW_LIMIT
          "answer": str,           # natural-language answer
          "chart": {...} | None,   # Vega-Lite if with_chart=True
          "error": str | None,     # only set when a step failed
        }
    """
    out: Dict[str, Any] = {"question": question}
    # Step 1: ask
    asked = wrenai_ask(question)
    if asked.get("error") or asked.get("status") != "finished":
        out["error"] = f"ask failed: {asked.get('error') or asked.get('status')}"
        return out
    if asked.get("type") != "TEXT_TO_SQL":
        out["error"] = (
            f"ask returned type={asked.get('type')!r} — likely the MDL is "
            f"not indexed for this question. intent_reasoning="
            f"{asked.get('intent_reasoning')}"
        )
        return out
    candidates = asked.get("response") or []
    if not candidates or not candidates[0].get("sql"):
        out["error"] = "ask produced no SQL"
        return out
    sql = candidates[0]["sql"]
    out["sql"] = sql
    out["retrieved_tables"] = asked.get("retrieved_tables") or []
    out["sql_generation_reasoning"] = asked.get("sql_generation_reasoning")

    # Step 2: execute. If the engine rejects the SQL, give WrenAI ONE shot
    # at fixing it (via /v1/sql-corrections) and retry. Single retry only —
    # repeated correction loops are usually a sign the MDL is wrong, not
    # the SQL.
    executed = wui.preview_sql(sql)
    if "error" in executed:
        corr = wai.sql_correction_full([{"sql": sql, "error": str(executed["error"])}])
        corrected_sql = None
        if not corr.get("error"):
            resp = corr.get("response") or corr.get("sqls") or []
            if isinstance(resp, list) and resp and isinstance(resp[0], dict):
                corrected_sql = resp[0].get("sql") or resp[0].get("corrected_sql")
        if corrected_sql and corrected_sql.strip() != sql.strip():
            retried = wui.preview_sql(corrected_sql)
            if "error" not in retried:
                out["sql_correction_applied"] = True
                out["sql_before_correction"] = sql
                sql = corrected_sql
                out["sql"] = sql
                executed = retried
        if "error" in executed:
            out["error"] = f"execute failed (after correction attempt): {executed['error']}"
            return out
    out["columns"] = executed["columns"]
    out["rows"] = executed["rows"]
    out["row_count"] = executed["row_count"]

    # Step 3: explain
    sql_data = wui.to_sql_data(executed)
    explained = wai.sql_answer_full(question, sql, sql_data)
    # WrenAI status payloads always carry "error": null on success, so
    # discriminate on the *value* not just key presence.
    if explained.get("error"):
        # Explain failed but we still have rows — return what we have.
        out["answer"] = None
        out["error"] = f"explain failed: {explained['error']}"
    else:
        out["answer"] = explained.get("answer")

    # Step 4 (optional): chart
    if with_chart:
        charted = wai.chart_full(question, sql, sql_data)
        if charted.get("error"):
            out["chart"] = None
            # Don't overwrite a prior error from explain — append.
            chart_err = f"chart failed: {charted['error']}"
            out["error"] = (out.get("error") + "; " + chart_err) if out.get("error") else chart_err
        else:
            out["chart"] = {
                "chart_type": charted.get("chart_type"),
                "vega_lite_spec": charted.get("vega_lite_spec") or charted.get("chart_schema"),
                "reasoning": charted.get("reasoning"),
            }

    return out


# ---------------------------------------------------------- knowledge tools


def wrenai_recommend_questions(
    max_questions: int = 5,
    max_categories: int = 3,
    language: Optional[str] = None,
) -> dict:
    """Ask WrenAI to suggest natural-language questions worth asking of this MDL.

    Onboarding helper: given the deployed semantic model, WrenAI looks
    at the tables / columns / relationships and proposes example
    questions a non-technical user could plausibly ask. Useful as the
    first call when a new analyst opens the dashboard — they pick a
    suggested question and immediately get an answer via `wrenai_answer`.

    Args:
        max_questions: cap on the total suggestions returned (default 5).
        max_categories: group the suggestions into this many topic
            buckets (e.g. "revenue", "customers", "shipping"). Default 3.
        language: target language for the suggested questions, e.g.
            "English", "Traditional Chinese". Defaults to whatever
            WrenAI's project-level default is.

    Returns:
        {
          "status": "finished" | "failed",
          "questions": [
             {"question": str, "category": str, "sql": str | None,
              "explanation": str | None}, ...
          ],
          "error": str | None,
        }
    """
    try:
        out = wai.question_recommendation_full(
            max_questions=max_questions,
            max_categories=max_categories,
            language=language,
        )
        if out.get("error"):
            return out
        return {
            "status": out.get("status"),
            "questions": (
                (out.get("response") or {}).get("questions")
                or out.get("questions")
                or []
            ),
            "error": out.get("error"),
            "event_id": out.get("event_id"),
        }
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_recommend_questions failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def wrenai_correct_sql(sql: str, error_message: str) -> dict:
    """Repair broken SQL using WrenAI's correction endpoint.

    Use when a SQL produced by `wrenai_ask` (or hand-written) fails
    against the engine and the engine returned a concrete error message
    (e.g. "column orders.unknown_col does not exist", "syntax error
    near LIMIT"). WrenAI reads the schema + original SQL + error and
    proposes a corrected SQL.

    Use this as a retry path BEFORE giving up on a user's question.
    Typical chain:
      1. `wrenai_ask(question)` -> SQL
      2. `wrenai_execute_sql(sql)` -> error
      3. `wrenai_correct_sql(sql, error)` -> fixed SQL
      4. `wrenai_execute_sql(fixed_sql)` -> rows

    `wrenai_answer` already wires this in as an automatic retry — call
    this tool directly only when you want the corrected SQL string
    without running it.

    Args:
        sql: The original (failing) SQL.
        error_message: The engine's error message verbatim.

    Returns:
        {
          "status": "finished" | "failed",
          "corrected_sql": str | None,
          "reasoning": str | None,
          "error": str | None,
        }
    """
    try:
        out = wai.sql_correction_full([{"sql": sql, "error": error_message}])
        if out.get("error"):
            return out
        # The correction result can shape into a few variants across versions.
        # Look for the first corrected SQL candidate.
        corrected = None
        reasoning = None
        resp = out.get("response") or out.get("sqls") or []
        if isinstance(resp, list) and resp:
            first = resp[0]
            if isinstance(first, dict):
                corrected = first.get("sql") or first.get("corrected_sql")
                reasoning = first.get("reasoning") or first.get("explanation")
        if corrected is None:
            corrected = out.get("corrected_sql")
        return {
            "status": out.get("status"),
            "corrected_sql": corrected,
            "reasoning": reasoning,
            "error": out.get("error"),
            "query_id": out.get("query_id"),
        }
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_correct_sql failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def wrenai_add_sql_pair(question: str, sql: str) -> dict:
    """Store a (natural-language question, SQL) pair as a few-shot exemplar.

    WrenAI uses indexed sql_pairs as in-context examples for future asks
    against the same project. Use sparingly — only add pairs where the
    SQL is verified to be correct AND the question phrasing is one a
    user would realistically ask. Bad pairs poison the index.

    Args:
        question: Natural-language question (1 sentence ideally).
        sql: Verified-correct SQL for the configured MDL.

    Returns the WrenAI response (typically {"event_id": "..."}) or
    {"error": "..."}.
    """
    try:
        return wai.add_sql_pair(question, sql)
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_add_sql_pair failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def wrenai_add_instruction(
    text: str,
    questions: Optional[List[str]] = None,
    is_default: bool = False,
) -> dict:
    """Add a free-form instruction to WrenAI's knowledge base.

    Use to teach WrenAI domain conventions ("revenue is always
    in TWD, not USD"; "exclude rows where status='deleted'"; "join
    orders.customer_id to customers.id"). Indexed against the listed
    `questions` — when a future ask matches one of them, this
    instruction is injected into the SQL-generation prompt.

    Args:
        text: The instruction text (1-2 paragraphs at most).
        questions: List of natural-language questions this instruction
            should apply to. If empty AND is_default=True, applies to
            all questions for the project.
        is_default: If True, applies globally regardless of question
            match. Use cautiously — global instructions affect every ask.

    Returns the WrenAI response or {"error": "..."}.
    """
    try:
        return wai.add_instruction(text, questions=questions, is_default=is_default)
    except Exception as e:
        logger.warning(f"[wrenai] wrenai_add_instruction failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


# -------------------------------------------------------------------- health


def wrenai_health() -> dict:
    """Probe WrenAI: HTTP /health + a real smoke ask against the configured MDL.

    Returns:
        {
          "wren_ai_service": "ok" | error string,
          "mdl_hash": "<hash from env>",
          "semantics_status": "finished" | "in-progress" | "failed" |
                              "unknown_but_ask_works" | "missing",
          "ask_smoke_test": "passed" | "failed: ..." | "skipped",
          "ready_for_ask": bool,
          "notes": str
        }

    `ready_for_ask=True` is grounded on **the real ask path working**,
    not on `/v1/semantics-preparations` alone — that endpoint returns
    `status=failed, error="<id> is not found"` for MDLs prepped through
    other paths (e.g. wren-ui direct deploy) even when ask works fine,
    which caused false-positive "MDL broken" reports 2026-05-22.
    """
    out: Dict[str, Any] = {
        "wren_ai_service": None,
        "mdl_hash": os.getenv("WRENAI_MDL_HASH", ""),
        "semantics_status": None,
        "ask_smoke_test": "skipped",
        "ready_for_ask": False,
        "notes": "",
    }
    h = wai.health()
    out["wren_ai_service"] = h.get("status") or h.get("error") or "unknown"

    s = wai.semantics_status()
    if "status" not in s:
        msg = str(s.get("error") or "unknown transport failure")
        out["semantics_status"] = "missing" if "404" in msg else f"error: {msg}"
    else:
        prep_status = s.get("status") or "unknown"
        prep_err_msg = ""
        if isinstance(s.get("error"), dict):
            prep_err_msg = str(s["error"].get("message") or "")
        # `status=failed` with "is not found" message = prep record absent on
        # AI service's tracker, but the MDL itself may still be indexed via
        # wren-ui's deploy path. Don't trust this status alone.
        if prep_status == "failed" and "not found" in prep_err_msg.lower():
            out["semantics_status"] = "unknown_but_likely_ok"
        else:
            out["semantics_status"] = prep_status

    # Smoke test — verify ask can REACH wrenai and return a terminal result.
    # We do NOT require type=TEXT_TO_SQL because generic smoke questions
    # ("show one row") get classified as GENERAL even on perfectly healthy
    # MDLs; conflating that with "MDL broken" produces the false-negative
    # the older code emitted. Real evidence of brokenness:
    #   - smoke ask raises (network / 500 / timeout)
    #   - smoke ask returns status=failed
    # Anything that arrives at a terminal `finished` state = the service
    # is responsive, regardless of intent classification.
    if out["wren_ai_service"] == "ok":
        try:
            ping = wai.ask_full("count rows in the largest table")
            pstatus = ping.get("status")
            ptype = ping.get("type")
            if pstatus == "finished":
                if ptype == "TEXT_TO_SQL":
                    out["ask_smoke_test"] = "passed"
                else:
                    out["ask_smoke_test"] = (
                        f"inconclusive: type={ptype} (smoke question may be too generic — "
                        "service is responsive)"
                    )
            else:
                out["ask_smoke_test"] = (
                    f"failed: status={pstatus} error={ping.get('error')}"
                )
        except Exception as e:
            out["ask_smoke_test"] = f"failed: {type(e).__name__}: {e}"

    # ready_for_ask = no strong evidence of brokenness. "passed" and
    # "inconclusive" both count as healthy; only network/timeout failure
    # or a non-ok service marks it false.
    ai_ok = out["wren_ai_service"] == "ok"
    smoke = out["ask_smoke_test"]
    smoke_ok = smoke == "passed" or smoke.startswith("inconclusive")
    out["ready_for_ask"] = ai_ok and smoke_ok

    if not out["ready_for_ask"]:
        if not ai_ok:
            out["notes"] = (
                "wren-ai-service /health is not 'ok'. The service is down or "
                "unreachable from this container."
            )
        else:
            out["notes"] = (
                f"AI service /health is ok but the smoke ask failed at the "
                f"transport / status level: {smoke}. The MDL may not be "
                f"reachable for THIS hash even though the service itself is up — "
                f"redeploy the MDL via wren-ui."
            )
    elif smoke.startswith("inconclusive"):
        out["notes"] = (
            "Service responsive and ask reaches a terminal state. The smoke "
            "question itself was classified as non-data — try a specific data "
            "question (mention a table or metric) for a stronger signal."
        )
    return out


# ---------------------------------------------------------------- loader


def load_wrenai_tools() -> list:
    return [
        wrenai_answer,                 # high-level one-shot — prefer this
        wrenai_ask,
        wrenai_execute_sql,
        wrenai_explain_result,
        wrenai_make_chart,
        wrenai_correct_sql,            # SQL repair via /v1/sql-corrections
        wrenai_recommend_questions,    # onboarding: "what could I ask?"
        wrenai_add_sql_pair,
        wrenai_add_instruction,
        wrenai_health,
    ]
