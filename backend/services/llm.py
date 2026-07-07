from agno.agent import Agent
from agno.models.openai import OpenAIChat

from ..schemas import ApiConfig


OPENAI_COMPATIBLE_ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}


def create_agent(api_config: ApiConfig, instructions: str) -> Agent:
    return Agent(
        model=OpenAIChat(
            id=api_config.model,
            api_key=api_config.api_key,
            base_url=api_config.base_url or None,
            role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        ),
        instructions=[instructions],
        markdown=True,
    )


def run_agent(api_config: ApiConfig, instructions: str, prompt: str) -> str:
    agent = create_agent(api_config, instructions)
    response = agent.run(prompt)
    return str(getattr(response, "content", response)).strip()
