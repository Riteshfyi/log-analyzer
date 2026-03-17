"""
Pipeline agent — Sequential: search (with inline incremental analysis) -> visualize.

Pipeline: search_agent (includes map-reduce analysis) -> sequence_diagram_agent
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import SequentialAgent

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from search.agent import search_agent
from visualize.agent import sequence_diagram_agent

logging.info("Pipeline: all sub-agents imported successfully")

root_agent = SequentialAgent(
    name="pipeline",
    sub_agents=[search_agent, sequence_diagram_agent],
    description=(
        "Executes a full log analysis pipeline: "
        "exhaustive BFS search with inline incremental analysis -> "
        "PlantUML sequence diagram generation."
    ),
)
