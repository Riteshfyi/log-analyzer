"""
Root Agent v2 — Sequential pipeline: search (with inline incremental analysis)
then sequence diagram generation.

Pipeline: search_agent_v2 (includes map-reduce analysis) → sequence_diagram_agent

Run standalone:  adk web agents/root_agent_v2
"""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import SequentialAgent

# Load environment variables from agents/.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# ═══════════════════════════════════════════════════════════════════════════════
# Import sub-agents
# ═══════════════════════════════════════════════════════════════════════════════

from search_agent_v2.agent import search_agent
from visualAgent.agent import sequence_diagram_agent

logging.info("✓ root_agent_v2: All sub-agents imported successfully")

# ═══════════════════════════════════════════════════════════════════════════════
# Root Agent
# ═══════════════════════════════════════════════════════════════════════════════

root_agent = SequentialAgent(
    name="MicroserviceLogAnalyzerV2",
    sub_agents=[search_agent, sequence_diagram_agent],
    description=(
        "Executes a full log analysis pipeline: "
        "exhaustive BFS search with inline incremental analysis → "
        "PlantUML sequence diagram generation."
    ),
)
