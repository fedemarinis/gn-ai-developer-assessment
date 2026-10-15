"""The tool-calling loop: plain synchronous code without an agent framework, at most 8 LLM calls per user message."""

import json
from collections.abc import Callable

import openai

from agent.backends import ToolBackend
from agent.config import REASONING_EFFORT
from agent.prompts import SYSTEM_PROMPT

MAX_ITERATIONS = 8

# Called after every tool call with (tool name, arguments, JSON result). Used by --verbose and the scenarios.
ToolObserver = Callable[[str, dict, str], None]

# Asked before delete_ticket runs, with the ticket id; returns True only if the deletion is allowed.
ConfirmDelete = Callable[[object], bool]


class AgentError(Exception):
    """The language model could not be reached or failed. The message is safe to show to the user."""


class Agent:
    def __init__(self, llm, deployment: str, backend: ToolBackend,
                 on_tool_call: ToolObserver | None = None, max_iterations: int = MAX_ITERATIONS,
                 confirm_delete: ConfirmDelete | None = None) -> None:
        self._llm = llm  # an AzureOpenAI client (or a fake one in tests)
        self._deployment = deployment
        self._backend = backend
        self.on_tool_call = on_tool_call
        self._max_iterations = max_iterations
        self._confirm_delete = confirm_delete  # None: deletions run without asking
        self.reset()

    def reset(self) -> None:
        """Forget the conversation (the CLI's /reset). Memory only lives for one session."""
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def ask(self, user_text: str) -> str:
        """Answer one user message, calling tools as often as the model needs (up to the limit)."""
        history_length = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        try:
            return self._run_loop()
        except openai.APIError as error:
            # Undo this turn so the history never ends with unanswered tool calls.
            del self.messages[history_length:]
            raise AgentError(_describe_llm_error(error)) from error
        except BaseException:
            # Same rollback for any other interruption (e.g. Ctrl+C); the exception is passed on unchanged.
            del self.messages[history_length:]
            raise

    def _run_loop(self) -> str:
        for _ in range(self._max_iterations):
            response = self._llm.chat.completions.create(
                model=self._deployment,
                messages=self.messages,
                tools=self._backend.tool_specs(),
                reasoning_effort=REASONING_EFFORT,
            )
            message = response.choices[0].message
            self.messages.append(_assistant_message(message))
            if not message.tool_calls:
                return message.content or "(The model returned an empty answer.)"
            for tool_call in message.tool_calls:
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": self._run_tool(tool_call.function.name, tool_call.function.arguments),
                })

        answer = (f"I stopped after {self._max_iterations} steps without finishing the request. "
                  "Please try again with a simpler or more specific request.")
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def _run_tool(self, name: str, raw_arguments: str) -> str:
        try:
            args = json.loads(raw_arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as error:
            args = {}
            result = json.dumps({"ok": False, "status_code": None,
                                 "detail": f"Tool arguments were not valid JSON: {error}"})
        else:
            # Checked here, not in a backend, so the confirmation applies to every backend.
            if name == "delete_ticket" and self._confirm_delete and not self._confirm_delete(args.get("ticket_id")):
                result = json.dumps({"ok": False, "status_code": None,
                                     "detail": "The user declined the deletion. The ticket was not deleted."})
            else:
                result = self._backend.call(name, args)  # expected failures come back as a result, not an exception
        if self.on_tool_call:
            self.on_tool_call(name, args, result)
        return result


def _assistant_message(message) -> dict:
    """Store only the fields the API needs back (not SDK extras such as `refusal`)."""
    stored = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        stored["tool_calls"] = [
            {"id": call.id, "type": "function",
             "function": {"name": call.function.name, "arguments": call.function.arguments}}
            for call in message.tool_calls
        ]
    return stored


def _describe_llm_error(error: openai.APIError) -> str:
    """Turn an SDK error into a short, actionable message; technical details are not shown to the user."""
    if isinstance(error, openai.APITimeoutError):
        return "The language model did not answer in time. Please try again."
    if isinstance(error, openai.APIConnectionError):
        return "Could not connect to the language model service. Check your network and try again."
    if isinstance(error, openai.AuthenticationError):
        return "The language model rejected the credentials. Check AZURE_OPENAI_API_KEY in your .env file."
    if isinstance(error, openai.RateLimitError):
        return "The language model is busy (rate limit). Please wait a moment and try again."
    if isinstance(error, openai.APIStatusError):
        return f"The language model service returned an error (HTTP {error.status_code}). Please try again."
    return "The language model service failed. Please try again."
