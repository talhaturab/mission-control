"""All settings in one place. Every value can be set by an environment variable of the same name."""

import os
import socket
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The model. OpenRouter speaks the OpenAI protocol, so the OpenAI client works with its URL.
    openrouter_api_key: str | None = None
    llm_model: str = "deepseek/deepseek-v4.1-flash"
    llm_base_url: str = "https://openrouter.ai/api/v1"

    # Where workers and the ticker send heartbeats and fetch jobs: the web process.
    hub_url: str = "http://localhost:8000"

    # MCP servers the agent may use, as name=url pairs. DeepWiki answers questions about repos.
    mcp_servers: str = "deepwiki=https://mcp.deepwiki.com/mcp"

    # How this process names itself on the dashboard. On ECS the task id is appended.
    task_name: str = os.environ.get("TASK_NAME", socket.gethostname())

    @property
    def llm_configured(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def mcp_server_map(self) -> dict[str, str]:
        pairs = [p.split("=", 1) for p in self.mcp_servers.split(",") if "=" in p]
        return {name.strip(): url.strip() for name, url in pairs}


def task_label(kind: str, task_name: str) -> str:
    """'worker' + 'abc123' -> 'worker-abc123'; 'worker' + 'worker-1' stays 'worker-1'."""
    return task_name if task_name.startswith(kind) else f"{kind}-{task_name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
