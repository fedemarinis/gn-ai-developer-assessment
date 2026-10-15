"""Interactive command-line chat with the ticket agent.

Run (with the ticket API running):  python -m agent [--verbose] [--confirm-deletes] [--backend direct|mcp]
"""

import argparse
import json
import sys
from collections.abc import Callable

from agent.agent import Agent, AgentError
from agent.backends import make_backend
from agent.config import ConfigError, load_config, make_llm_client
from ticket_client import TicketClient

HELP = "Commands: /reset (forget the conversation), /help, /exit. Anything else is sent to the agent."


def print_tool_call(name: str, args: dict, result: str) -> None:
    """--verbose: show each tool call and its result, so the orchestration is visible."""
    print(f"  [tool] {name}({json.dumps(args)})")
    print(f"  [tool] -> {result}")


def ask_delete_confirmation(ticket_id) -> bool:
    """--confirm-deletes: only an explicit "y" or "yes" allows the deletion."""
    return input(f"Delete ticket {ticket_id}? [y/N] ").strip().lower() in ("y", "yes")


def check_api(base_url: str) -> str:
    """Start-up health check. Only warns: the CLI also runs while the API is down."""
    client = TicketClient(base_url, timeout=3.0)
    result = client.health()
    client.close()
    if result["ok"]:
        return f"Ticket API reachable at {base_url}."
    return f"WARNING: {result['detail']} Start it first, or ticket requests will fail."


def run_repl(agent: Agent, read_line: Callable[[str], str] = input) -> None:
    """Chat loop. An error in one turn is reported and the session continues."""
    print(HELP)
    while True:
        try:
            text = read_line("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return
        if not text:
            continue
        command = text.lower()
        if command in ("/exit", "/quit"):
            print("Goodbye.")
            return
        if command == "/help":
            print(HELP)
            continue
        if command == "/reset":
            agent.reset()
            print("Conversation cleared.")
            continue
        try:
            answer = agent.ask(text)
        except AgentError as error:
            answer = f"Sorry, I could not process that: {error}"
        except KeyboardInterrupt:
            answer = "(Interrupted.)"
        except Exception as error:  # last line of defence: the CLI must keep running
            answer = f"Sorry, an unexpected error occurred ({type(error).__name__}). Please try again."
        print(f"\nAgent: {answer}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description="Chat with the support-ticket agent.")
    parser.add_argument("--backend", choices=["direct", "mcp"], default="direct",
                        help="How tools reach the ticket API (default: direct HTTP).")
    parser.add_argument("--verbose", action="store_true", help="Print every tool call and its result.")
    parser.add_argument("--confirm-deletes", action="store_true",
                        help="Ask for confirmation before a ticket is deleted (off by default).")
    args = parser.parse_args(argv)

    # Console output must never crash on characters the terminal cannot show.
    sys.stdout.reconfigure(errors="replace")

    try:
        config = load_config()
    except ConfigError as error:
        print(f"Configuration error: {error}")
        return 1

    print(check_api(config.ticket_api_base_url))
    backend = make_backend(args.backend, config.ticket_api_base_url)
    agent = Agent(make_llm_client(config), config.deployment, backend,
                  on_tool_call=print_tool_call if args.verbose else None,
                  confirm_delete=ask_delete_confirmation if args.confirm_deletes else None)
    print(f"Ticket agent ready (model: {config.deployment}, backend: {backend.name}).")
    try:
        run_repl(agent)
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
