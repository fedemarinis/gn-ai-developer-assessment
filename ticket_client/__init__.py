"""HTTP client for the Mock Ticketing API, used by the agent
(its direct tool backend, start-up health check and scenario runner) and by the MCP server."""

from ticket_client.client import TicketClient

__all__ = ["TicketClient"]
