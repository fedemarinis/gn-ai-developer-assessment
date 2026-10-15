"""CLI tests: commands, and the CLI keeps running when the LLM or the API fails."""

import httpx
import openai
import pytest

from agent.agent import Agent
from agent.cli import ask_delete_confirmation, check_api, run_repl
from agent.tests.conftest import FakeLLM, reply


def scripted_input(*lines):
    remaining = list(lines)

    def read_line(prompt: str) -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return read_line


def test_repl_survives_llm_failure_and_handles_commands(backend, capsys):
    failure = openai.APIConnectionError(request=httpx.Request("POST", "https://llm.test"))
    llm = FakeLLM(failure, reply("Hello again."))
    agent = Agent(llm, "test-deployment", backend)
    run_repl(agent, scripted_input("hi", "", "/reset", "hi again", "/exit"))
    out = capsys.readouterr().out
    assert "Sorry, I could not process that: Could not connect to the language model" in out
    assert "Conversation cleared." in out
    assert "Agent: Hello again." in out
    assert out.rstrip().endswith("Goodbye.")


def test_repl_survives_unexpected_error(backend, capsys):
    llm = FakeLLM(RuntimeError("boom"))
    run_repl(Agent(llm, "test-deployment", backend), scripted_input("hi"))  # then EOF
    out = capsys.readouterr().out
    assert "an unexpected error occurred (RuntimeError)" in out
    assert "Goodbye." in out


@pytest.mark.parametrize("typed, allowed", [("y", True), (" YES ", True), ("", False), ("n", False), ("ok", False)])
def test_delete_confirmation_needs_explicit_yes(monkeypatch, typed, allowed):
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or typed)
    assert ask_delete_confirmation(4) is allowed
    assert prompts == ["Delete ticket 4? [y/N] "]


def test_health_check_warns_when_api_is_down():
    message = check_api("http://127.0.0.1:9")
    assert message.startswith("WARNING: Ticket service unreachable at http://127.0.0.1:9")
