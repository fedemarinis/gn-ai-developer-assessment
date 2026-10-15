"""Agent loop tests with a fake LLM (scripted tool calls) and the real API in-process."""

import json

import httpx
import openai
import pytest

from agent.agent import Agent, AgentError
from agent.config import REASONING_EFFORT
from agent.tests.conftest import FakeLLM, reply, tool_call
from ticket_api.main import store

INVALID_STATUS = "Invalid status 'PROGRESS'. Allowed values: OPEN, RESOLVED, CLOSED."


def make_agent(llm, backend, **kwargs) -> Agent:
    return Agent(llm, "test-deployment", backend, **kwargs)


def tool_results(request: dict) -> list[dict]:
    return [json.loads(m["content"]) for m in request["messages"] if m["role"] == "tool"]


def test_plain_answer_without_tools(backend):
    llm = FakeLLM(reply("Hello! How can I help?"))
    assert make_agent(llm, backend).ask("hi") == "Hello! How can I help?"
    request = llm.requests[0]
    assert request["model"] == "test-deployment"
    assert request["reasoning_effort"] == REASONING_EFFORT
    assert len(request["tools"]) == 5
    assert request["messages"][0]["role"] == "system"


def test_tool_call_result_is_fed_back_to_the_llm(backend):
    llm = FakeLLM(reply(tool_calls=[tool_call("create_ticket", title="Keyboard not working")]),
                  reply("Created ticket 4."))
    answer = make_agent(llm, backend).ask("Create a ticket about a keyboard not working.")
    assert answer == "Created ticket 4."
    assert store.get(4).title == "Keyboard not working"
    second = llm.requests[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "create_ticket"
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_1"
    assert json.loads(second[-1]["content"])["data"]["id"] == 4


def test_api_422_detail_reaches_the_llm_verbatim(backend):
    """GN scenario 4: the LLM receives the API's own list of allowed values."""
    llm = FakeLLM(reply(tool_calls=[tool_call("update_ticket", ticket_id=1, status="PROGRESS")]),
                  reply("PROGRESS is not valid. Allowed: OPEN, RESOLVED, CLOSED."))
    make_agent(llm, backend).ask("Update ticket 1 to have the status 'PROGRESS'.")
    assert tool_results(llm.requests[1]) == [{"ok": False, "status_code": 422, "detail": INVALID_STATUS}]
    assert store.get(1).status == "OPEN"


def test_api_404_detail_reaches_the_llm(backend):
    """GN scenario 6: the LLM receives the API's 404 message."""
    llm = FakeLLM(reply(tool_calls=[tool_call("update_ticket", ticket_id=999, status="CLOSED")]),
                  reply("Ticket 999 does not exist."))
    make_agent(llm, backend).ask("Update ticket 999 to 'CLOSED'.")
    assert tool_results(llm.requests[1]) == [
        {"ok": False, "status_code": 404, "detail": "Ticket with id 999 not found."}]


def test_multi_step_chaining_list_then_update(backend):
    """Chaining: find tickets first, then act on the result (several tool calls in one turn)."""
    llm = FakeLLM(
        reply(tool_calls=[tool_call("list_tickets", status="OPEN")]),
        reply(tool_calls=[tool_call("update_ticket", "call_a", ticket_id=1, status="CLOSED"),
                          tool_call("update_ticket", "call_b", ticket_id=2, status="CLOSED")]),
        reply("Closed tickets 1 and 2."),
    )
    seen = []
    agent = make_agent(llm, backend, on_tool_call=lambda name, args, result: seen.append((name, args)))
    assert agent.ask("Close all open tickets.") == "Closed tickets 1 and 2."
    assert [t.status for t in store.list()] == ["CLOSED", "CLOSED", "RESOLVED"]
    assert seen == [("list_tickets", {"status": "OPEN"}),
                    ("update_ticket", {"ticket_id": 1, "status": "CLOSED"}),
                    ("update_ticket", {"ticket_id": 2, "status": "CLOSED"})]
    assert [m["tool_call_id"] for m in llm.requests[2]["messages"] if m["role"] == "tool"] == [
        "call_1", "call_a", "call_b"]


def test_conversation_memory_and_reset(backend):
    llm = FakeLLM(reply("First."), reply("Second."), reply("After reset."))
    agent = make_agent(llm, backend)
    agent.ask("one")
    agent.ask("two")
    assert [m["content"] for m in llm.requests[1]["messages"] if m["role"] == "user"] == ["one", "two"]
    agent.reset()
    agent.ask("three")
    assert [m["content"] for m in llm.requests[2]["messages"] if m["role"] == "user"] == ["three"]


def test_invalid_tool_arguments_are_reported_to_the_llm(backend):
    bad = tool_call("get_ticket")
    bad.function.arguments = "{not json"
    llm = FakeLLM(reply(tool_calls=[bad]), reply("Sorry, let me retry."))
    make_agent(llm, backend).ask("Show ticket 1")
    [result] = tool_results(llm.requests[1])
    assert result["ok"] is False and result["detail"].startswith("Tool arguments were not valid JSON")


def test_stops_after_max_iterations(backend):
    endless = [reply(tool_calls=[tool_call("get_ticket", f"call_{i}", ticket_id=1)]) for i in range(3)]
    llm = FakeLLM(*endless)
    answer = make_agent(llm, backend, max_iterations=3).ask("loop forever")
    assert answer.startswith("I stopped after 3 steps")
    assert len(llm.requests) == 3


def test_llm_failure_raises_agent_error_and_keeps_history_clean(backend):
    request = httpx.Request("POST", "https://llm.test")
    llm = FakeLLM(reply(tool_calls=[tool_call("get_ticket", ticket_id=1)]),
                  openai.APIConnectionError(request=request))
    agent = make_agent(llm, backend)
    with pytest.raises(AgentError, match="Could not connect to the language model"):
        agent.ask("Show ticket 1")
    assert [m["role"] for m in agent.messages] == ["system"]  # the failed turn was undone


class _InterruptedBackend:
    """Raises once while a tool runs, like Ctrl+C or an unexpected crash in the middle of a turn."""

    name = "interrupted"

    def __init__(self, backend, error: BaseException) -> None:
        self._backend = backend
        self._error = error

    def tool_specs(self) -> list[dict]:
        return self._backend.tool_specs()

    def call(self, name: str, args: dict) -> str:
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        return self._backend.call(name, args)

    def close(self) -> None:
        self._backend.close()


@pytest.mark.parametrize("interruption", [RuntimeError("backend crashed"), KeyboardInterrupt()],
                         ids=["RuntimeError", "KeyboardInterrupt"])
def test_interrupted_turn_is_removed_from_history(backend, interruption):
    """A turn interrupted after the model requested a tool must not leave that request unanswered
    in the history: the chat API rejects every later request that contains it."""
    llm = FakeLLM(reply(tool_calls=[tool_call("get_ticket", ticket_id=1)]),
                  reply("Ticket 1 is OPEN."))
    agent = make_agent(llm, _InterruptedBackend(backend, interruption))
    with pytest.raises(type(interruption)):  # the CLI still receives the original exception
        agent.ask("Show ticket 1")
    assert [m["role"] for m in agent.messages] == ["system"]
    assert agent.ask("Show ticket 1 again.") == "Ticket 1 is OPEN."
    assert [m["role"] for m in llm.requests[1]["messages"]] == ["system", "user"]


@pytest.mark.parametrize("answer, deleted", [(None, True), (True, True), (False, False)],
                         ids=["no-confirmation", "approved", "declined"])
def test_delete_confirmation(backend, answer, deleted):
    """Without a callback deletions run as before; with one, only an approval reaches the backend."""
    asked = []

    def confirm(ticket_id):
        asked.append(ticket_id)
        return answer

    llm = FakeLLM(reply(tool_calls=[tool_call("delete_ticket", ticket_id=2)]), reply("Done."))
    make_agent(llm, backend, confirm_delete=confirm if answer is not None else None).ask("Delete ticket 2.")
    assert (store.get(2) is None) is deleted
    assert asked == ([] if answer is None else [2])
    if not deleted:
        assert tool_results(llm.requests[1]) == [
            {"ok": False, "status_code": None, "detail": "The user declined the deletion. The ticket was not deleted."}]


def test_authentication_error_message_points_to_the_key(backend):
    response = httpx.Response(401, request=httpx.Request("POST", "https://llm.test"))
    llm = FakeLLM(openai.AuthenticationError("unauthorized", response=response, body=None))
    with pytest.raises(AgentError, match="AZURE_OPENAI_API_KEY"):
        make_agent(llm, backend).ask("hi")
