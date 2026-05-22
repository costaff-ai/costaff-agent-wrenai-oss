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
        if "error" in out:
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
        if "error" in out:
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
        if "error" in out:
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


# ---------------------------------------------------------- knowledge tools


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
    """Probe WrenAI: HTTP /health + semantic-prep status for the configured MDL.

    Returns:
        {
          "wren_ai_service": "ok" | error string,
          "mdl_hash": "<hash from env>",
          "semantics_status": "finished" | "in-progress" | "failed" | "missing",
          "ready_for_ask": bool,
          "notes": str
        }

    `ready_for_ask=True` means the agent can serve real ask requests.
    `False` means either the AI service is down OR the MDL has not been
    indexed into qdrant — in that case the user should redeploy the MDL
    through wren-ui (which triggers /v1/semantics-preparations on the
    AI service).
    """
    out: Dict[str, Any] = {
        "wren_ai_service": None,
        "mdl_hash": os.getenv("WRENAI_MDL_HASH", ""),
        "semantics_status": None,
        "ready_for_ask": False,
        "notes": "",
    }
    h = wai.health()
    out["wren_ai_service"] = h.get("status") or h.get("error") or "unknown"
    s = wai.semantics_status()
    # Distinguish our _get() transport error (added when status_code != 200)
    # from WrenAI's own "error" field on the status payload (always present,
    # null when prep succeeded). A WrenAI response always has "status";
    # transport failures don't.
    if "status" not in s:
        msg = str(s.get("error") or "unknown transport failure")
        out["semantics_status"] = "missing" if "404" in msg else f"error: {msg}"
    else:
        out["semantics_status"] = s.get("status") or "unknown"
    out["ready_for_ask"] = (
        out["wren_ai_service"] == "ok"
        and out["semantics_status"] == "finished"
    )
    if not out["ready_for_ask"]:
        out["notes"] = (
            "MDL not indexed for this hash. Re-deploy the MDL via wren-ui, "
            "or call /v1/semantics-preparations directly with the manifest. "
            "Ask requests will return type=GENERAL until prep is finished."
        )
    return out


# ---------------------------------------------------------------- loader


def load_wrenai_tools() -> list:
    return [
        wrenai_ask,
        wrenai_explain_result,
        wrenai_make_chart,
        wrenai_add_sql_pair,
        wrenai_add_instruction,
        wrenai_health,
    ]
