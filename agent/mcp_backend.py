"""Tool backend that reaches the ticket API through the MCP server in mcp_server/.

The server runs as a subprocess and both sides speak MCP over its stdin/stdout (the stdio transport).
The MCP client is asynchronous while the agent loop is synchronous, so the client lives in an anyio
blocking portal: an event loop in a background thread that the methods below hand their calls to.
"""

import json
import sys
from contextlib import ExitStack
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from mcp import Client, StdioServerParameters

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class McpBackend:
    """Discovers the tools with MCP tools/list and runs them with tools/call."""

    name = "mcp"

    def __init__(self, ticket_api_base_url: str) -> None:
        # The SDK passes only a minimal environment to the server, so no credentials reach it.
        server = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                       cwd=PROJECT_ROOT, env={"TICKET_API_BASE_URL": ticket_api_base_url})
        # If any step fails, the stack stops whatever was already started (server process, portal thread).
        with ExitStack() as stack:
            self._portal = stack.enter_context(start_blocking_portal())
            self._client = stack.enter_context(self._portal.wrap_async_context_manager(Client(server)))
            tools = self._portal.call(self._client.list_tools).tools
            self._resources = stack.pop_all()
        self._specs = [{"type": "function",
                        "function": {"name": tool.name, "description": tool.description,
                                     "parameters": tool.input_schema}}
                       for tool in tools]

    def tool_specs(self) -> list[dict]:
        return self._specs

    def call(self, name: str, args: dict) -> str:
        result = self._portal.call(self._client.call_tool, name, args)
        if result.structured_content is None:
            # Rejected by the MCP layer before reaching the API, e.g. an unknown tool or invalid arguments.
            return json.dumps({"ok": False, "status_code": None, "detail": result.content[0].text})
        return json.dumps(result.structured_content)

    def close(self) -> None:
        self._resources.close()
