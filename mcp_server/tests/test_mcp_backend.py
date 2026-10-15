"""McpBackend tests over the real stdio transport: the agent's backend starts the MCP server as a subprocess,
which calls the real API over HTTP. The API runs in a background thread of this process."""

import json
import threading
import time

import pytest
import uvicorn

from agent.agent import Agent
from agent.backends import TOOL_SPECS, DirectBackend
from agent.mcp_backend import McpBackend
from agent.tests.conftest import FakeLLM, reply, tool_call
from ticket_api.main import app, store
from ticket_client import TicketClient


@pytest.fixture(scope="module")
def api_url():
    """The API on a free local port, reachable from the MCP server subprocess."""
    api = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=api.run, daemon=True)
    thread.start()
    while not api.started:
        assert thread.is_alive(), "the API server failed to start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{api.servers[0].sockets[0].getsockname()[1]}"
    api.should_exit = True
    thread.join()


@pytest.fixture(scope="module")
def mcp_backend(api_url):
    backend = McpBackend(api_url)  # one server subprocess for the whole module
    yield backend
    backend.close()


@pytest.fixture(autouse=True)
def seed_tickets():
    store.reset()  # ids 1 and 2 OPEN, id 3 RESOLVED


def test_results_match_the_direct_backend(api_url, mcp_backend):
    assert [spec["function"]["name"] for spec in mcp_backend.tool_specs()] == [
        spec["function"]["name"] for spec in TOOL_SPECS]
    direct = DirectBackend(TicketClient(api_url))
    for name, args in [("list_tickets", {"status": "OPEN"}), ("get_ticket", {"ticket_id": 1}),
                       ("update_ticket", {"ticket_id": 1, "status": "PROGRESS"})]:
        assert mcp_backend.call(name, args) == direct.call(name, args)
    direct.close()


def test_mcp_layer_errors_become_tool_results(mcp_backend):
    assert json.loads(mcp_backend.call("close_all", {})) == {
        "ok": False, "status_code": None, "detail": "Unknown tool: close_all"}


def test_delete_confirmation_applies_to_the_mcp_backend(mcp_backend):
    answers = [False, True]
    llm = FakeLLM(reply(tool_calls=[tool_call("delete_ticket", ticket_id=2)]), reply("Not deleted."),
                  reply(tool_calls=[tool_call("delete_ticket", ticket_id=2)]), reply("Deleted."))
    agent = Agent(llm, "test-deployment", mcp_backend, confirm_delete=lambda ticket_id: answers.pop(0))
    agent.ask("Delete ticket 2.")
    assert store.get(2) is not None
    agent.ask("Yes, delete ticket 2.")
    assert store.get(2) is None
    assert json.loads(llm.requests[3]["messages"][-1]["content"]) == {"ok": True, "status_code": 204, "data": None}


def test_interrupted_turn_leaves_the_mcp_session_usable(mcp_backend):
    def interrupt_once(name, args, result):
        agent.on_tool_call = None
        raise KeyboardInterrupt

    llm = FakeLLM(reply(tool_calls=[tool_call("get_ticket", ticket_id=1)]),
                  reply(tool_calls=[tool_call("get_ticket", ticket_id=1)]), reply("Ticket 1 is OPEN."))
    agent = Agent(llm, "test-deployment", mcp_backend, on_tool_call=interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        agent.ask("Show ticket 1")
    assert [m["role"] for m in agent.messages] == ["system"]
    assert agent.ask("Show ticket 1 again.") == "Ticket 1 is OPEN."
    assert json.loads(llm.requests[2]["messages"][-1]["content"])["data"]["id"] == 1
