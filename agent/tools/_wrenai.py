"""Low-level WrenAI httpx client.

Wraps the self-hosted `wren-ai-service` REST API (default port 5555). All
async-style endpoints follow the same pattern: POST kicks off a job and
returns `{"query_id": "..."}` (or `{"event_id": "..."}` for sync-prep
endpoints); a GET on `<base>/result` or status URL polls until the
status is in a terminal state.

Configuration via env:
    WRENAI_BASE_URL              http(s)://host:5555 — set at agent add time
    WRENAI_PROJECT_ID            integer-as-string, e.g. "1"
    WRENAI_MDL_HASH              40-char hex hash from wren-ui's deploy_log
    WRENAI_TIMEOUT               per-request HTTP timeout in seconds (default 30)
    WRENAI_ASK_POLL_INTERVAL     seconds between status polls (default 2)
    WRENAI_ASK_POLL_TIMEOUT      total seconds to wait before giving up (default 120)
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Iterable, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Terminal status values across WrenAI endpoints. Different endpoints use
# different vocabulary: /v1/asks ends in 'finished'; /v1/sql-answers ends in
# 'succeeded'; both can also end in 'failed' / 'stopped'. Charts use
# 'fetching' as a non-terminal mid-state. Union of every terminal token.
TERMINAL = {"finished", "succeeded", "failed", "stopped"}


def _cfg() -> Dict[str, Any]:
    base = (os.getenv("WRENAI_BASE_URL") or "").rstrip("/")
    if not base:
        raise ValueError(
            "WRENAI_BASE_URL not set. Point it at your wren-ai-service "
            "endpoint, e.g. http://10.128.0.2:5555"
        )
    return {
        "base": base,
        "project_id": os.getenv("WRENAI_PROJECT_ID", ""),
        "mdl_hash": os.getenv("WRENAI_MDL_HASH", ""),
        "timeout": float(os.getenv("WRENAI_TIMEOUT", "30")),
        "poll_interval": float(os.getenv("WRENAI_ASK_POLL_INTERVAL", "2")),
        "poll_timeout": float(os.getenv("WRENAI_ASK_POLL_TIMEOUT", "120")),
    }


def _post(path: str, body: dict, *, timeout: Optional[float] = None) -> dict:
    cfg = _cfg()
    url = f"{cfg['base']}{path}"
    try:
        r = httpx.post(url, json=body, timeout=timeout or cfg["timeout"])
    except Exception as e:
        return {"error": f"network error on POST {path}: {type(e).__name__}: {e}"}
    if r.status_code not in (200, 201):
        try:
            err = r.json()
        except Exception:
            err = r.text
        return {"error": f"WrenAI {r.status_code} on POST {path}: {err}"}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"could not parse JSON from POST {path}: {e}"}


def _get(path: str) -> dict:
    cfg = _cfg()
    url = f"{cfg['base']}{path}"
    try:
        r = httpx.get(url, timeout=cfg["timeout"])
    except Exception as e:
        return {"error": f"network error on GET {path}: {type(e).__name__}: {e}"}
    if r.status_code != 200:
        try:
            err = r.json()
        except Exception:
            err = r.text
        return {"error": f"WrenAI {r.status_code} on GET {path}: {err}"}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"could not parse JSON from GET {path}: {e}"}


def _read_sse_messages(path: str, *, timeout: Optional[float] = None) -> str:
    """Consume an SSE stream at `<base>/<path>` and return the concatenated
    'message' fields. WrenAI's /streaming endpoints emit chunks shaped:

        data: {"message": "<partial text>"}\\n\\n

    so a successful read returns the full natural-language string. Any
    non-data lines or JSON parse failures are silently skipped — partial
    payloads still yield whatever text was streamed before the error.
    """
    cfg = _cfg()
    url = f"{cfg['base']}{path}"
    parts: List[str] = []
    try:
        with httpx.stream("GET", url, timeout=timeout or cfg["timeout"]) as r:
            if r.status_code != 200:
                return ""
            buffer = ""
            for chunk in r.iter_text():
                buffer += chunk
                # Process complete SSE events (\n\n separated)
                while "\n\n" in buffer:
                    event, buffer = buffer.split("\n\n", 1)
                    for line in event.split("\n"):
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        body = line[5:].strip()
                        try:
                            d = json.loads(body)
                        except Exception:
                            continue
                        msg = d.get("message")
                        if isinstance(msg, str):
                            parts.append(msg)
    except Exception as e:
        logger.info(f"[wrenai] stream read on {path} ended early: {e}")
    return "".join(parts)


def _poll(result_path: str, *, expect_id_key: str = "query_id",
          job_id: Optional[str] = None) -> dict:
    """Poll <result_path> until status is terminal or poll_timeout elapses.

    Returns the final JSON body, or {"error": ...} on timeout / transport
    failure. The poll loop is tolerant of transient 404/500 in the first
    second (WrenAI sometimes lags between POST and the GET being ready).
    """
    cfg = _cfg()
    deadline = time.monotonic() + cfg["poll_timeout"]
    last: dict = {}
    while time.monotonic() < deadline:
        last = _get(result_path)
        status = (last.get("status") or "").lower()
        if status in TERMINAL:
            return last
        if "error" in last and status == "":
            # Transient network or 404 in the very first moments — keep trying.
            pass
        time.sleep(cfg["poll_interval"])
    return {
        "error": (
            f"WrenAI poll timeout after {cfg['poll_timeout']}s on {result_path} "
            f"(last status={last.get('status')!r}); "
            f"{expect_id_key}={job_id or '?'}"
        ),
        "last_body": last,
    }


# ---------------------------------------------------------------- /v1/asks


def ask_kickoff(query: str, *, histories: Optional[List[dict]] = None) -> dict:
    cfg = _cfg()
    body: Dict[str, Any] = {
        "query": query,
        "project_id": cfg["project_id"] or None,
        "mdl_hash": cfg["mdl_hash"] or None,
    }
    if histories:
        body["histories"] = histories
    return _post("/v1/asks", body)


def ask_result(query_id: str) -> dict:
    return _get(f"/v1/asks/{query_id}/result")


def ask_full(query: str, *, histories: Optional[List[dict]] = None) -> dict:
    """Convenience: POST + poll. Returns the final result dict."""
    started = ask_kickoff(query, histories=histories)
    if "error" in started:
        return started
    qid = started.get("query_id")
    if not qid:
        return {"error": f"ask kickoff returned no query_id: {started}"}
    final = _poll(f"/v1/asks/{qid}/result", job_id=qid)
    final.setdefault("query_id", qid)
    return final


# -------------------------------------------------------- /v1/sql-answers


def sql_answer_kickoff(query: str, sql: str, sql_data: dict,
                       custom_instruction: Optional[str] = None) -> dict:
    cfg = _cfg()
    body: Dict[str, Any] = {
        "query": query,
        "sql": sql,
        "sql_data": sql_data,
        "project_id": cfg["project_id"] or None,
    }
    if custom_instruction:
        body["custom_instruction"] = custom_instruction
    return _post("/v1/sql-answers", body)


def sql_answer_result(query_id: str) -> dict:
    return _get(f"/v1/sql-answers/{query_id}")


def sql_answer_full(query: str, sql: str, sql_data: dict,
                    custom_instruction: Optional[str] = None) -> dict:
    started = sql_answer_kickoff(query, sql, sql_data, custom_instruction)
    if "error" in started:
        return started
    qid = started.get("query_id")
    if not qid:
        return {"error": f"sql_answer kickoff returned no query_id: {started}"}
    final = _poll(f"/v1/sql-answers/{qid}", job_id=qid)
    final.setdefault("query_id", qid)
    # The status endpoint only reports state; the actual natural-language
    # answer streams from /streaming. Collect it once status is terminal.
    if final.get("status") == "succeeded" and not final.get("answer"):
        final["answer"] = _read_sse_messages(f"/v1/sql-answers/{qid}/streaming")
    return final


# -------------------------------------------------------------- /v1/charts


def chart_kickoff(query: str, sql: str, sql_data: dict) -> dict:
    cfg = _cfg()
    body: Dict[str, Any] = {
        "query": query,
        "sql": sql,
        "sql_data": sql_data,
        "project_id": cfg["project_id"] or None,
    }
    return _post("/v1/charts", body)


def chart_result(query_id: str) -> dict:
    return _get(f"/v1/charts/{query_id}")


def chart_full(query: str, sql: str, sql_data: dict) -> dict:
    started = chart_kickoff(query, sql, sql_data)
    if "error" in started:
        return started
    qid = started.get("query_id")
    if not qid:
        return {"error": f"chart kickoff returned no query_id: {started}"}
    final = _poll(f"/v1/charts/{qid}", job_id=qid)
    final.setdefault("query_id", qid)
    return final


# ------------------------------------------------------------ /v1/sql-pairs


def add_sql_pair(question: str, sql: str) -> dict:
    cfg = _cfg()
    body = {
        "project_id": cfg["project_id"] or None,
        "sql_pairs": [{"question": question, "sql": sql}],
    }
    return _post("/v1/sql-pairs", body)


# ----------------------------------------------------------- /v1/instructions


def add_instruction(text: str, *, questions: Optional[List[str]] = None,
                    is_default: bool = False) -> dict:
    cfg = _cfg()
    body = {
        "project_id": cfg["project_id"] or None,
        "instructions": [
            {
                "instruction": text,
                "questions": questions or [],
                "is_default": bool(is_default),
            }
        ],
    }
    return _post("/v1/instructions", body)


# -------------------------------------------------- semantics preparation


def semantics_status() -> dict:
    cfg = _cfg()
    mdl = cfg["mdl_hash"]
    if not mdl:
        return {"error": "WRENAI_MDL_HASH not set"}
    return _get(f"/v1/semantics-preparations/{mdl}/status")


def health() -> dict:
    return _get("/health")
