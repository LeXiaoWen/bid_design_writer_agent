from agno.agent import Agent
from agno.agent import RunContentEvent
from agno.models.openai import OpenAIChat
from collections.abc import Callable
from typing import Optional

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


def run_agent(
    api_config: ApiConfig,
    instructions: str,
    prompt: str,
    on_delta: Optional[Callable[[str], None]] = None,
) -> str:
    agent = create_agent(api_config, instructions)
    if on_delta is not None:
        chunks: list[str] = []
        for event in agent.run(prompt, stream=True):
            if isinstance(event, RunContentEvent) and event.content:
                chunk = str(event.content)
                chunks.append(chunk)
                on_delta(chunk)
        return "".join(chunks).strip()
    response = agent.run(prompt)
    return str(getattr(response, "content", response)).strip()
