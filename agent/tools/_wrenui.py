"""Thin wren-ui GraphQL client.

wren-ui exposes a small set of mutations / queries at `/api/graphql`.
For the agent we only need `previewSql` — it accepts a SQL string,
runs it through wren-engine (which knows the project's MDL and the
underlying data source), and returns the executed rows as `columns`
+ `data` arrays. This is the same endpoint the wren-ui "Run" button
uses, so it's the most stable way to get rows for an arbitrary SQL.

Configuration via env:
    WRENAI_UI_GRAPHQL_URL   full URL ending in /api/graphql
    WRENAI_PROJECT_ID       integer-as-string passed as projectId
    WRENAI_TIMEOUT          HTTP timeout in seconds (default 30)
    WRENAI_EXEC_ROW_LIMIT   safety cap for previewSql limit (default 1000)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


_PREVIEW_MUTATION = (
    "mutation PreviewSql($d: PreviewSQLDataInput!) { previewSql(data: $d) }"
)


def _cfg() -> Dict[str, Any]:
    url = (os.getenv("WRENAI_UI_GRAPHQL_URL") or "").strip()
    if not url:
        raise ValueError(
            "WRENAI_UI_GRAPHQL_URL not set. Point it at the wren-ui graphql "
            "endpoint, e.g. http://10.128.0.2:13000/api/graphql"
        )
    return {
        "url": url,
        "project_id": os.getenv("WRENAI_PROJECT_ID", ""),
        "timeout": float(os.getenv("WRENAI_TIMEOUT", "30")),
        "row_cap": int(os.getenv("WRENAI_EXEC_ROW_LIMIT", "1000")),
    }


def preview_sql(sql: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """Execute `sql` against the configured project's MDL; return rows.

    Returns one of:
        {"columns": [{"name", "type"}], "rows": [[...], ...], "row_count": N}
        {"error": "..."}

    The row_count is capped by WRENAI_EXEC_ROW_LIMIT to keep the response
    small enough to feed into wrenai_explain_result / wrenai_make_chart
    without blowing out the LLM context window.
    """
    try:
        cfg = _cfg()
    except ValueError as e:
        return {"error": str(e)}

    cap = cfg["row_cap"]
    eff_limit = min(int(limit) if limit else cap, cap)

    body = {
        "query": _PREVIEW_MUTATION,
        "variables": {
            "d": {
                "projectId": cfg["project_id"] or None,
                "sql": sql,
                "limit": eff_limit,
            }
        },
    }
    try:
        r = httpx.post(
            cfg["url"], json=body, timeout=cfg["timeout"],
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        return {"error": f"network error reaching wren-ui graphql: {type(e).__name__}: {e}"}

    if r.status_code != 200:
        try:
            err = r.json()
        except Exception:
            err = r.text
        return {"error": f"wren-ui {r.status_code}: {err}"}

    try:
        payload = r.json()
    except Exception as e:
        return {"error": f"could not parse wren-ui response: {e}"}

    if payload.get("errors"):
        # Surface the first error message verbatim — wren-ui's GraphQL
        # errors are usually self-explanatory (syntax, missing column,
        # type mismatch).
        msg = payload["errors"][0].get("message", "unknown")
        return {"error": f"previewSql failed: {msg}"}

    out = (payload.get("data") or {}).get("previewSql") or {}
    cols = out.get("columns") or []
    rows = out.get("data") or []
    return {
        "columns": [{"name": c.get("name"), "type": c.get("type")} for c in cols],
        "rows": rows,
        "row_count": len(rows),
        "truncated_at": cap if len(rows) >= cap else None,
    }


def to_sql_data(executed: Dict[str, Any]) -> Dict[str, Any]:
    """Reshape `preview_sql` output into the `sql_data` payload that
    WrenAI's /v1/sql-answers and /v1/charts endpoints expect."""
    cols = [c["name"] for c in executed.get("columns", [])]
    return {
        "columns": cols,
        "data": executed.get("rows", []),
        "dtypes": {c["name"]: c.get("type") for c in executed.get("columns", [])},
    }
