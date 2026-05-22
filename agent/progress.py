"""Code-driven live progress panel for any A2A-served leaf agent.

Canonical, self-contained, drop-in. The Manager-side before_tool_callback
(costaff core) deterministically appends a real [PROGRESS_CONTEXT] block
(user_id / channel / session_id=task_<id>) into this agent's request, so
it arrives in llm_request.contents. This module turns that into the
user's single live Telegram panel WITHOUT any LLM involvement:

  before_model_callback : parse the block once → callback state
  before_tool_callback  : each real tool starts  → report_step "doing"
  after_tool_callback   : each real tool finishes → "done" / "failed"

It posts directly to the core report_step shim (no dependency on this
repo's tools/ package), so the SAME file works in every agent. Core's
panel_finalize (executor) flips the header to Done/Failed at task end,
and a core ticker animates the breathing dots between tool events.

Every callback is fail-safe: never raises, always returns None, so it
can never skip a model/tool call.
"""
import asyncio
import logging
import os
import re

import httpx

logger = logging.getLogger("progress")

_BASE = os.getenv(
    "COSTAFF_CORE_API_URL", "http://costaff-mcp-costaff:8081"
).rstrip("/")
_SECRET = os.getenv("MCP_SECRET_KEY", "").strip()
_TIMEOUT = float(os.getenv("COSTAFF_TOOL_HTTP_TIMEOUT", "30"))

_RE = {
    "user_id": re.compile(r"^\s*user_id\s*=\s*(.+?)\s*$", re.M),
    "channel": re.compile(r"^\s*channel\s*=\s*(.+?)\s*$", re.M),
    "session_id": re.compile(r"^\s*session_id\s*=\s*(.+?)\s*$", re.M),
}

# Plumbing the user should not see as work lines. An agent's real verbs
# are NOT in this set → each shows. send_message_now is handled
# specially (folded into the panel as a section), so it is NOT here.
_PLUMBING = {
    "add_task_comment",
    "move_to_shared",
    "list_data_files",
    "report_step",
}


def _txt(x) -> str:
    try:
        if x is None:
            return ""
        if isinstance(x, str):
            return x
        parts = getattr(x, "parts", None)
        if parts:
            return "\n".join((getattr(p, "text", "") or "") for p in parts)
        return str(x)
    except Exception:
        return ""


def _pc_from_state(tool_context):
    try:
        st = getattr(tool_context, "state", None)
        if st is None:
            return None
        return st.get("_pc")
    except Exception:
        return None


def _post_report(pc, step, status):
    headers = {"Authorization": f"Bearer {_SECRET}"} if _SECRET else {}
    try:
        httpx.post(
            f"{_BASE}/api/tool/report_step",
            json={
                "session_id": pc["session_id"],
                "step": step,
                "status": status,
                "agent": pc.get("agent") or "",
                "channel": pc["channel"],
                "user_id": pc["user_id"],
            },
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception:
        logger.info("[panel] report_step post failed", exc_info=True)


async def _report(pc, step, status):
    try:
        await asyncio.to_thread(_post_report, pc, step, status)
    except Exception:
        logger.info("[panel] report failed", exc_info=True)


# Sub-agents narrate progress via send_message_now (per their
# instruction, prefix "[Agent] ..."). While a panel is armed we fold
# that text into the panel as a section divider and SKIP the standalone
# send, so the user sees one self-updating message instead of N pings.
# The real task result is delivered separately by the executor (A2A
# response → dispatch_notification), not by send_message_now.
_SEND_TOOL = "send_message_now"
_SEND_SKIP_RESULT = "ok"


async def before_model_callback(callback_context, llm_request):
    """Parse the real PROGRESS_CONTEXT once → callback state."""
    try:
        st = getattr(callback_context, "state", None)
        if st is None or st.get("_pc"):
            return None
        contents = getattr(llm_request, "contents", None) or []
        ctext = "\n".join(_txt(c) for c in contents)
        if "[PROGRESS_CONTEXT]" not in ctext:
            return None
        g = {k: (rx.search(ctext).group(1).strip()
                 if rx.search(ctext) else None)
             for k, rx in _RE.items()}
        sid = g["session_id"]
        if not (sid and sid.startswith("task_")):
            return None
        st["_pc"] = {
            "session_id": sid,
            "channel": g["channel"] or "telegram",
            "user_id": g["user_id"] or "",
            "agent": getattr(callback_context, "agent_name", "") or "",
        }
        logger.info(
            f"[panel] armed → {sid} ch={g['channel']} "
            f"agent={st['_pc']['agent']}"
        )
    except Exception:
        logger.info("[panel] before_model failed", exc_info=True)
    return None


async def before_tool_callback(tool, args, tool_context):
    """Each real tool call → a panel line in 'doing'."""
    try:
        name = getattr(tool, "name", "") or ""
        pc = _pc_from_state(tool_context)
        if pc and not pc.get("agent"):
            pc["agent"] = getattr(tool_context, "agent_name", "") or ""

        if name == _SEND_TOOL:
            if not pc:
                return None  # no panel → let it send normally
            body = ""
            if isinstance(args, dict):
                body = (args.get("body") or args.get("message")
                        or args.get("text") or "")
            if body and body.strip():
                await _report(pc, body.strip(), "section")
            return _SEND_SKIP_RESULT  # truthy → skip the standalone send

        if name in _PLUMBING:
            return None
        if pc:
            await _report(pc, name, "doing")
    except Exception:
        logger.info("[panel] before_tool failed", exc_info=True)
    return None


async def after_tool_callback(tool, args, tool_context, tool_response):
    """Each real tool finish → flip its line to 'done' / 'failed'."""
    try:
        name = getattr(tool, "name", "") or ""
        if name in _PLUMBING or name == _SEND_TOOL:
            return None
        pc = _pc_from_state(tool_context)
        if not pc:
            return None
        txt = str(tool_response) if tool_response is not None else ""
        ok = "[ERROR]" not in txt and "Traceback" not in txt
        await _report(pc, name, "done" if ok else "failed")
    except Exception:
        logger.info("[panel] after_tool failed", exc_info=True)
    return None
