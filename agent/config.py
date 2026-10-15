"""Configuration from environment variables (locally from a git-ignored `.env` file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import AzureOpenAI

REQUIRED_VARS = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
)
DEFAULT_TICKET_API_BASE_URL = "http://127.0.0.1:8000"

# Observed with the gpt-6-luna-c1 deployment and API version 2024-12-01-preview: function tools on
# /chat/completions are rejected unless reasoning is off (HTTP 400 "Function tools with reasoning_effort
# are not supported ..."). Other models or deployments may differ; check with python -m agent.smoke_test.
REASONING_EFFORT = "none"


class ConfigError(Exception):
    """A required setting is missing. The message names the variable, never its value."""


@dataclass(frozen=True)
class Config:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str
    ticket_api_base_url: str

    def __repr__(self) -> str:  # keep the key out of logs and tracebacks
        return f"Config(endpoint={self.endpoint!r}, deployment={self.deployment!r}, api_key='***')"


def load_config() -> Config:
    load_dotenv()  # does not override variables that are already set
    missing = [name for name in REQUIRED_VARS if not os.getenv(name, "").strip()]
    if missing:
        raise ConfigError(
            f"Missing environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the values."
        )
    return Config(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].strip(),
        api_key=os.environ["AZURE_OPENAI_API_KEY"].strip(),
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"].strip(),
        api_version=os.environ["AZURE_OPENAI_API_VERSION"].strip(),
        ticket_api_base_url=os.getenv("TICKET_API_BASE_URL", "").strip() or DEFAULT_TICKET_API_BASE_URL,
    )


def make_llm_client(config: Config) -> AzureOpenAI:
    # The SDK retries 429 / 5xx / connection errors itself (max_retries) with backoff.
    return AzureOpenAI(
        azure_endpoint=config.endpoint,
        api_key=config.api_key,
        api_version=config.api_version,
        timeout=60.0,
        max_retries=2,
    )
