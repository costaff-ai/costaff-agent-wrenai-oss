"""No MCP toolsets for the Calendar agent.

This agent uses google-api-python-client directly via native ADK
FunctionTool — there is no companion MCP server. The function is
kept for protocol parity with the template (agent.py imports it).
"""
from typing import List


def load_all_mcp_toolsets() -> List:
    return []
