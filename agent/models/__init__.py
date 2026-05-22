"""Model selector: pick the LLM to use based on COSTAFF_AGENT_MODEL_PROVIDER.

Usage:
    from models import selected_model

Resolution rules:
    - COSTAFF_AGENT_MODEL_PROVIDER=litellm  → use the LiteLlm instance
                                              configured in litellm_model.py
    - anything else (default: 'gemini')     → use the Gemini model name
                                              from gemini_model.py
"""
import os

from .gemini_model import gemini_model

_provider = (os.getenv("COSTAFF_AGENT_MODEL_PROVIDER") or "gemini").lower()

if _provider == "litellm":
    from .litellm_model import litellm_model
    selected_model = litellm_model
else:
    selected_model = gemini_model
