"""File-based sub-agent auto-discovery.

How to add a sub-agent:
    1. Create a new .py file in this folder (e.g. search_agent.py).
    2. Define a module-level variable named `agent` (an LlmAgent instance).
    3. It is automatically included in the parent agent's sub_agents list —
       no registration in agent.py needed.

Example (sub_agents/search_agent.py):

    from google.adk.agents import LlmAgent

    agent = LlmAgent(
        name="search_agent",
        model="gemini-2.5-flash",
        description="...",
        instruction="...",
    )
"""
import importlib
import logging
import pkgutil
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def load_all_sub_agents() -> List:
    """Discover and import every <name>.py module in this folder.

    Each module must export a module-level `agent` variable. Modules
    without `agent` are skipped with a warning. Failures are logged but
    don't block the rest.
    """
    sub_agents = []
    pkg_dir = Path(__file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        full_name = f"sub_agents.{module_name}"
        try:
            module = importlib.import_module(full_name)
            if hasattr(module, "agent"):
                sub_agents.append(module.agent)
                logger.info(f"Loaded sub-agent from sub_agents/{module_name}.py")
            else:
                logger.warning(
                    f"sub_agents/{module_name}.py has no `agent` variable, skipping"
                )
        except Exception as e:
            logger.error(f"Failed to load sub-agent '{full_name}': {e}")
    return sub_agents
