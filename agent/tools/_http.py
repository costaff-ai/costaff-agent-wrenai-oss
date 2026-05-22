"""Shared httpx caller for the plain-HTTP tool shims.

No MCP client, no anyio task group — a plain blocking httpx.post. This
is the whole point: it cannot trigger the ADK/anyio CancelScope
cross-task race because there is no cancel scope here at all.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_SECRET = os.getenv("MCP_SECRET_KEY", "").strip()
_TIMEOUT = float(os.getenv("COSTAFF_TOOL_HTTP_TIMEOUT", "120"))


def call_shim(base_url: str, tool: str, **kwargs) -> str:
    """POST kwargs to <base_url>/api/tool/<tool>; return the tool's string result."""
    headers = {}
    if _SECRET:
        headers["Authorization"] = f"Bearer {_SECRET}"
    url = f"{base_url.rstrip('/')}/api/tool/{tool}"
    try:
        resp = httpx.post(url, json=kwargs, headers=headers, timeout=_TIMEOUT)
    except Exception as e:
        logger.error(f"[tool-http] {tool} transport error: {e}")
        return f"[ERROR] could not reach tool shim ({tool}): {e}"
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:
            err = resp.text
        logger.warning(f"[tool-http] {tool} -> {resp.status_code}: {err}")
        return f"[ERROR] {tool} failed ({resp.status_code}): {err}"
    try:
        return resp.json().get("result", "")
    except Exception:
        return resp.text
