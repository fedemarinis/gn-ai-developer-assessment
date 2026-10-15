"""MCP server tests through an in-process MCP client: tool discovery and tool results,
against the real API in-process."""

import json

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from agent.backends import TOOL_SPECS
from mcp_server import server
from ticket_api.main import app, store
from ticket_client import TicketClient

pytestmark = pytest.mark.anyio

INVALID_STATUS = "Invalid status 'PROGRESS'. Allowed values: OPEN, RESOLVED, CLOSED."


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api(monkeypatch):
    """Point the server's ticket client at the in-process API, starting from the 3 seed tickets."""
    store.reset()
    with TestClient(app) as http:
        api_client = TicketClient(http_client=http)
        monkeypatch.setattr(server, "client", api_client)
        yield api_client


def _descriptions(schema: dict) -> dict:
    return {name: prop["description"] for name, prop in schema["properties"].items()}


async def test_tools_mirror_the_direct_backend_specs():
    async with Client(server.server) as client:
        tools = (await client.list_tools()).tools
    assert len(tools) == len(TOOL_SPECS) == 5
    for tool, spec in zip(tools, TOOL_SPECS):
        expected = spec["function"]
        assert (tool.name, tool.description) == (expected["name"], expected["description"])
        assert _descriptions(tool.input_schema) == _descriptions(expected["parameters"])
        assert tool.input_schema.get("required", []) == expected["parameters"]["required"]
        assert "enum" not in json.dumps(tool.input_schema)  # valid statuses come only from the API


@pytest.mark.parametrize("name, args, expected", [
    ("get_ticket", {"ticket_id": 1}, None),  # success: compared with the client's own result
    ("get_ticket", {"ticket_id": 999}, {"ok": False, "status_code": 404, "detail": "Ticket with id 999 not found."}),
    ("update_ticket", {"ticket_id": 1, "status": "PROGRESS"},
     {"ok": False, "status_code": 422, "detail": INVALID_STATUS}),
], ids=["success", "404", "422"])
async def test_tool_result_keeps_the_api_outcome(api, name, args, expected):
    expected = expected or api.get_ticket(**args)
    async with Client(server.server) as client:
        result = await client.call_tool(name, args)
    assert result.structured_content == expected
    assert json.loads(result.content[0].text) == expected
    assert result.is_error is not expected["ok"]
