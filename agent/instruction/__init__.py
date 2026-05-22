"""Auto-load system.md and provide a build_instruction() helper."""
import os
from pathlib import Path

_SYSTEM_PATH = Path(__file__).parent / "system.md"

if _SYSTEM_PATH.exists():
    instruction_content = _SYSTEM_PATH.read_text(encoding="utf-8")
else:
    instruction_content = "You are a helpful AI assistant."


def build_instruction() -> str:
    workspace_dir = os.getenv("WORKSPACE_DIR", "/app/data/costaff-agent-wrenai")
    preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "English")
    mdl_hash = os.getenv("WRENAI_MDL_HASH", "<unset>")
    project_id = os.getenv("WRENAI_PROJECT_ID", "<unset>")
    return (
        instruction_content
        .replace("{WORKSPACE_DIR}", workspace_dir)
        .replace("{user_id}", "shared")
        .replace("{PREFERRED_LANGUAGE}", preferred_lang)
        .replace("{WRENAI_MDL_HASH}", mdl_hash)
        .replace("{WRENAI_PROJECT_ID}", project_id)
    )
