import logging
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import SequentialAgent

# Load environment variables from agents/.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from chat.agent import chat_agent
from router.agent import query_router


root_agent = SequentialAgent(
    name="root_agent",
    sub_agents=[query_router, chat_agent],
    description=(
        "Root orchestrator: routes queries through the search pipeline "
        "and chat agent in sequence."
    ),
)
