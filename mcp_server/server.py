"""MCP server that exposes the Mock Ticketing API as five tools, built with the official MCP Python SDK.

Each tool calls the API through ticket_client and returns its result {ok, status_code, data | detail},
the same result the agent's direct backend produces. API errors (for example 404 or 422) are marked as
MCP tool errors and keep the API's own detail message.

Run over stdio:  python -m mcp_server.server   (TICKET_API_BASE_URL defaults to http://127.0.0.1:8000)
"""

import json
import os
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from ticket_client import TicketClient

# WARNING keeps per-request log lines out of the agent's terminal, which shares this process's stderr.
server = MCPServer("tickets", log_level="WARNING")
client = TicketClient(os.environ.get("TICKET_API_BASE_URL", "http://127.0.0.1:8000"))

# The tool inputs mirror the agent's direct tool specs. `status` is a plain string with no list of valid
# values, so the API's 422 message tells the model which values exist. Optional fields also accept null,
# because models sometimes send null instead of leaving a field out.
TicketId = Annotated[int, Field(description="The numeric ticket ID.")]


def _result(result: dict) -> CallToolResult:
    """Return the client's result as structured content and as JSON text, flagged as an error unless ok."""
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))],
                          structured_content=result, is_error=not result["ok"])


@server.tool()
def create_ticket(
    title: Annotated[str, Field(description="Short summary of the problem.")],
    description: Annotated[str | None, Field(description="Longer description of the problem.")] = None,
    status: Annotated[str | None, Field(description="Ticket status, exactly as the user stated it.")] = None,
    resolution: Annotated[str | None, Field(description="How the problem was solved.")] = None,
) -> CallToolResult:
    """Create a new support ticket. Returns the created ticket with its new ID."""
    return _result(client.create_ticket(title, description, status, resolution))


@server.tool()
def list_tickets(
    status: Annotated[str | None, Field(description="Only return tickets with this status. Omit to list all.")] = None,
) -> CallToolResult:
    """List support tickets. Optionally only those with a given status."""
    return _result(client.list_tickets(status))


@server.tool()
def get_ticket(ticket_id: TicketId) -> CallToolResult:
    """Get all details of one ticket by its ID."""
    return _result(client.get_ticket(ticket_id))


@server.tool()
def update_ticket(
    ticket_id: TicketId,
    title: Annotated[str | None, Field(description="New title.")] = None,
    description: Annotated[str | None, Field(description="New description.")] = None,
    status: Annotated[str | None, Field(description="New status, exactly as the user stated it.")] = None,
    resolution: Annotated[str | None, Field(description="Resolution note (how the problem was solved).")] = None,
) -> CallToolResult:
    """Change one or more fields of an existing ticket. Only the fields you pass are changed."""
    return _result(client.update_ticket(ticket_id, title, description, status, resolution))


@server.tool()
def delete_ticket(ticket_id: TicketId) -> CallToolResult:
    """Permanently delete a ticket by its ID."""
    return _result(client.delete_ticket(ticket_id))


if __name__ == "__main__":
    server.run()  # stdio transport
