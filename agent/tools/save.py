"""Save WrenAI outputs (rows, SQL, explanations) to the shared workspace.

Why this lives in the wrenai agent instead of going via manager-core
`move_to_shared`: WrenAI's outputs are in-memory JSON from the previous
tool call (rows from `wrenai_answer` / `wrenai_execute_sql`), not files
sitting in a private workspace. A single direct write is the right
shape — moving an intermediate copy would just add a step the LLM has
to chain correctly.

Path safety: filename must be a bare name matching [A-Za-z0-9._-]+, no
slashes, no `..`. All writes go under /app/data/shared/costaff-agent-wrenai/.

Why the folder is `costaff-agent-wrenai` and not the bare `wrenai`: it
matches the container-name prefix the Manager already uses when
prescribing downstream paths (e.g. business_analysis reads from
/app/data/shared/costaff-agent-wrenai/...). Keeping the name consistent
avoids the LLM having to chain a `mv` to bridge the gap.
"""
from __future__ import annotations

import csv as _csv
import io as _io
import json as _json
import re
from pathlib import Path
from typing import Any, Dict, List

_SHARED_ROOT = Path("/app/data/shared/costaff-agent-wrenai")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _write(filename: str, text: str, append: bool) -> dict:
    if not filename or not _SAFE_NAME.match(filename):
        return {"error": f"invalid filename {filename!r}: must match [A-Za-z0-9._-]+ (no slashes, no `..`)"}
    if text is None:
        return {"error": "content cannot be None"}
    try:
        _SHARED_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"error": f"could not create {_SHARED_ROOT}: {type(e).__name__}: {e}"}
    target = _SHARED_ROOT / filename
    mode = "a" if append else "w"
    try:
        with open(target, mode, encoding="utf-8") as f:
            f.write(text)
        return {
            "path": str(target),
            "bytes": target.stat().st_size,
            "appended": bool(append),
        }
    except OSError as e:
        return {"error": f"write failed: {type(e).__name__}: {e}"}


def wrenai_save_to_shared(filename: str, content: str, append: bool = False) -> dict:
    """Save text content to /app/data/shared/costaff-agent-wrenai/<filename>.

    Use after wrenai_answer / wrenai_execute_sql when the user wants
    the result persisted as a report, SQL file, or pre-formatted text.
    The caller passes the final string — no formatting is done here.

    Args:
        filename: bare filename matching [A-Za-z0-9._-]+. No directories.
        content: file body. Written as UTF-8.
        append: if True, append; default False (overwrite).

    Returns:
        {"path": "...", "bytes": N, "appended": bool} on success, or
        {"error": "..."} on bad filename / write failure.
    """
    return _write(filename, content, append)


def wrenai_save_rows_as_csv(rows: List[Dict[str, Any]], filename: str) -> dict:
    """Save query rows to /app/data/shared/costaff-agent-wrenai/<filename> as CSV.

    Uses csv.DictWriter so commas / quotes / newlines inside cells are
    handled correctly — do NOT hand-format CSV in the prompt. Columns
    are taken from the first row's keys; missing keys in later rows
    write empty strings.

    Args:
        rows: list of dicts (e.g. the `rows` field of wrenai_answer).
        filename: must end in `.csv` and match [A-Za-z0-9._-]+.

    Returns:
        {"path": ..., "bytes": ..., "row_count": N, "column_count": M}
        or {"error": ...}.
    """
    if not rows:
        return {"error": "rows is empty — nothing to save"}
    if not filename.lower().endswith(".csv"):
        return {"error": "filename must end in .csv"}
    cols = list(rows[0].keys())
    buf = _io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
    result = _write(filename, buf.getvalue(), append=False)
    if "error" not in result:
        result["row_count"] = len(rows)
        result["column_count"] = len(cols)
    return result


def wrenai_save_rows_as_json(rows: List[Dict[str, Any]], filename: str, indent: int = 2) -> dict:
    """Save query rows to /app/data/shared/costaff-agent-wrenai/<filename> as JSON.

    Args:
        rows: list of dicts.
        filename: must end in `.json` and match [A-Za-z0-9._-]+.
        indent: pretty-print indent (0 = compact one-liner).

    Returns:
        {"path": ..., "bytes": ..., "row_count": N} or {"error": ...}.
    """
    if not rows:
        return {"error": "rows is empty — nothing to save"}
    if not filename.lower().endswith(".json"):
        return {"error": "filename must end in .json"}
    text = _json.dumps(rows, indent=indent or None, ensure_ascii=False, default=str)
    result = _write(filename, text, append=False)
    if "error" not in result:
        result["row_count"] = len(rows)
    return result


def load_save_tools() -> list:
    """Return the 3 save tools as native ADK function tools."""
    return [wrenai_save_to_shared, wrenai_save_rows_as_csv, wrenai_save_rows_as_json]
