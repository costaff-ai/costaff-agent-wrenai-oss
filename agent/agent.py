import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from google.adk.agents import LlmAgent

from instruction import build_instruction
from mcp_toolsets import load_all_mcp_toolsets
from models import selected_model
from skills import load_all_skills
from tools import load_costaff_api_tools, load_wrenai_tools
from sub_agents import load_all_sub_agents
from progress import (
    before_model_callback,
    before_tool_callback,
    after_tool_callback,
)

# No MCP toolsets — WrenAI HTTP API called directly via httpx
tools = list(load_all_mcp_toolsets())
tools.extend(load_wrenai_tools())
tools.extend(load_costaff_api_tools())
tools.append(load_all_skills())

sub_agents = load_all_sub_agents()

instruction = build_instruction()

wrenai_agent = LlmAgent(
    name="wrenai_agent",
    model=selected_model,
    description="GenBI specialist: natural language -> SQL via a self-hosted WrenAI MDL, plus answer/chart synthesis on supplied rows.",
    instruction=instruction,
    before_model_callback=before_model_callback,
    before_tool_callback=before_tool_callback,
    after_tool_callback=after_tool_callback,
    tools=tools,
    sub_agents=sub_agents,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
