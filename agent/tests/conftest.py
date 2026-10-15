"""Shared fixtures: a fake LLM that replays scripted replies, and a DirectBackend on the real API in-process."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent.backends import DirectBackend
from ticket_api.main import app, store
from ticket_client import TicketClient


def tool_call(name: str, call_id: str = "call_1", **args) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def reply(content: str | None = None, tool_calls: list | None = None) -> SimpleNamespace:
    """One chat-completions response, shaped like the SDK object the agent reads."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeLLM:
    """Mimics `client.chat.completions.create`: returns scripted replies and records every request."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # Copy the message list: the agent keeps appending to the same list object.
        self.requests.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def backend():
    store.reset()  # Every test starts from the 3 seed tickets: ids 1 and 2 OPEN, id 3 RESOLVED.
    with TestClient(app) as http:
        yield DirectBackend(TicketClient(http_client=http))
