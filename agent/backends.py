"""Tool backends. The agent loop only uses the ToolBackend interface, so the ticket API can be reached
either directly over HTTP (DirectBackend) or through the MCP server (agent/mcp_backend.py) without changing the loop."""

import json
from typing import Protocol

from ticket_client import TicketClient

# `status` is a plain string on purpose: no enum and no list of valid values.
# The LLM must ask the API, so invalid values are rejected by the API's 422 message,
# which lists the allowed values. The API stays the single source of truth.
_STATUS = {"type": "string", "description": "Ticket status, exactly as the user stated it."}
_TICKET_ID = {"type": "integer", "description": "The numeric ticket ID."}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SPECS = [
    _tool(
        "create_ticket",
        "Create a new support ticket. Returns the created ticket with its new ID.",
        {
            "title": {"type": "string", "description": "Short summary of the problem."},
            "description": {"type": "string", "description": "Longer description of the problem."},
            "status": _STATUS,
            "resolution": {"type": "string", "description": "How the problem was solved."},
        },
        ["title"],
    ),
    _tool(
        "list_tickets",
        "List support tickets. Optionally only those with a given status.",
        {"status": {**_STATUS, "description": "Only return tickets with this status. Omit to list all."}},
        [],
    ),
    _tool("get_ticket", "Get all details of one ticket by its ID.", {"ticket_id": _TICKET_ID}, ["ticket_id"]),
    _tool(
        "update_ticket",
        "Change one or more fields of an existing ticket. Only the fields you pass are changed.",
        {
            "ticket_id": _TICKET_ID,
            "title": {"type": "string", "description": "New title."},
            "description": {"type": "string", "description": "New description."},
            "status": {**_STATUS, "description": "New status, exactly as the user stated it."},
            "resolution": {"type": "string", "description": "Resolution note (how the problem was solved)."},
        },
        ["ticket_id"],
    ),
    _tool("delete_ticket", "Permanently delete a ticket by its ID.", {"ticket_id": _TICKET_ID}, ["ticket_id"]),
]


class ToolBackend(Protocol):
    """What the agent loop needs from a tool backend (any object with these members works)."""

    name: str

    def tool_specs(self) -> list[dict]: ...            # tools in OpenAI function-calling format
    # JSON {ok, status_code, data | detail}; expected failures come back as results
    def call(self, name: str, args: dict) -> str: ...
    def close(self) -> None: ...                       # release resources


class DirectBackend:
    """Calls the ticket API directly over HTTP through ticket_client."""

    name = "direct"

    def __init__(self, client: TicketClient) -> None:
        self._client = client
        self._handlers = {
            "create_ticket": client.create_ticket,
            "list_tickets": client.list_tickets,
            "get_ticket": client.get_ticket,
            "update_ticket": client.update_ticket,
            "delete_ticket": client.delete_ticket,
        }

    def tool_specs(self) -> list[dict]:
        return TOOL_SPECS

    def call(self, name: str, args: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            result = {"ok": False, "status_code": None, "detail": f"Unknown tool '{name}'."}
        else:
            try:
                result = handler(**args)
            except TypeError as error:  # missing or unexpected arguments from the LLM
                result = {"ok": False, "status_code": None, "detail": f"Invalid arguments for {name}: {error}"}
        return json.dumps(result)

    def close(self) -> None:
        self._client.close()


def make_backend(name: str, ticket_api_base_url: str) -> ToolBackend:
    """Build the backend chosen with --backend (used by the CLI and the scenario runner)."""
    if name == "direct":
        return DirectBackend(TicketClient(ticket_api_base_url))
    if name == "mcp":
        from agent.mcp_backend import McpBackend  # loads the MCP SDK only when this backend is chosen
        return McpBackend(ticket_api_base_url)
    raise ValueError(f"Unknown backend '{name}'.")
