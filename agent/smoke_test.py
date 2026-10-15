"""Minimal Azure OpenAI tool-calling check (no ticket API needed).

Run:  python -m agent.smoke_test
Sends one request with one dummy tool and checks that the model asks to call it.
Prints the model's tool call, never the API key.
"""

import json
import sys

from agent.config import REASONING_EFFORT, ConfigError, load_config, make_llm_client

DEMO_TOOL = {
    "type": "function",
    "function": {
        "name": "get_ticket",
        "description": "Get one support ticket by its ID.",
        "parameters": {
            "type": "object",
            "properties": {"ticket_id": {"type": "integer", "description": "The ticket ID."}},
            "required": ["ticket_id"],
        },
    },
}


def main() -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"Configuration error: {error}")
        return 1
    client = make_llm_client(config)
    print(f"Endpoint: {config.endpoint} | deployment: {config.deployment} | api-version: {config.api_version}")
    response = client.chat.completions.create(
        model=config.deployment,
        messages=[{"role": "user", "content": "Show me ticket 7."}],
        tools=[DEMO_TOOL],
        reasoning_effort=REASONING_EFFORT,
    )
    message = response.choices[0].message
    print(f"finish_reason: {response.choices[0].finish_reason} | model: {response.model}")
    if not message.tool_calls:
        print(f"FAIL: no tool call. Model answered: {message.content!r}")
        return 1
    call = message.tool_calls[0]
    args = json.loads(call.function.arguments)
    print(f"Tool call: {call.function.name}({args})")
    ok = call.function.name == "get_ticket" and args.get("ticket_id") == 7
    print("OK: tool calling works." if ok else "FAIL: unexpected tool call.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
