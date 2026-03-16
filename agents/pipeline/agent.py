"""
Pipeline agent — Sequential: search -> analyze -> visualize.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import SequentialAgent

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from search.agent import search_agent
from analyze.agent import analyze_agent
from visualize.agent import sequence_diagram_agent

logging.info("Pipeline: all sub-agents imported successfully")

root_agent = SequentialAgent(
    name="pipeline",
    sub_agents=[search_agent, analyze_agent, sequence_diagram_agent],
    description=(
        "Executes a full log analysis pipeline: "
        "exhaustive BFS search -> analysis (calling/contact-center routing) -> "
        "PlantUML sequence diagram generation."
    ),
)
