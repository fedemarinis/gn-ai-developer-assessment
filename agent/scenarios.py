"""Live demonstration of the 6 GN scenarios from Part 2 of the brief.

Needs the ticket API running and a real Azure OpenAI key. Run:
    python -m agent.scenarios [--backend direct|mcp]
Each scenario runs in a fresh conversation. The checks look at the API state and the tool calls,
not at the exact wording of the answer, which varies between runs.
A Markdown transcript is saved under agent/transcripts/.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent.agent import Agent, AgentError
from agent.backends import make_backend
from agent.config import ConfigError, load_config, make_llm_client
from ticket_client import TicketClient

TRANSCRIPT_DIR = Path(__file__).parent / "transcripts"


@dataclass
class Run:
    title: str
    prompt: str
    answer: str = ""
    calls: list[tuple[str, dict, dict]] = field(default_factory=list)  # (tool, args, result)
    checks: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(ok for _, ok in self.checks)

    def check(self, description: str, ok: bool) -> None:
        self.checks.append((description, bool(ok)))

    def calls_to(self, tool: str) -> list[tuple[dict, dict]]:
        return [(args, result) for name, args, result in self.calls if name == tool]


class ScenarioRunner:
    def __init__(self, agent: Agent, api: TicketClient) -> None:
        self.agent = agent
        self.api = api
        self.runs: list[Run] = []
        self._current: Run | None = None

    def record_tool_call(self, name: str, args: dict, result: str) -> None:
        self._current.calls.append((name, args, json.loads(result)))

    def ask(self, title: str, prompt: str) -> Run:
        run = Run(title, prompt)
        self._current = run
        self.agent.reset()  # every scenario starts a fresh conversation
        print(f"\n=== {title}\nYou: {prompt}")
        try:
            run.answer = self.agent.ask(prompt)
        except AgentError as error:
            run.answer = f"(LLM error: {error})"
        for name, args, result in run.calls:
            print(f"  [tool] {name}({json.dumps(args)}) -> {result.get('status_code')}")
        print(f"Agent: {run.answer}")
        self.runs.append(run)
        return run

    def tickets(self) -> dict[int, dict]:
        result = self.api.list_tickets()
        if not result["ok"]:
            raise RuntimeError(f"Could not read tickets for the checks: {result['detail']}")
        return {ticket["id"]: ticket for ticket in result["data"]}

    def run_all(self) -> None:
        before = self.tickets()

        # GN scenario 1: create a ticket
        run = self.ask("1. Create a ticket", "Create a new ticket about a keyboard not working.")
        after = self.tickets()
        new_ids = sorted(set(after) - set(before))
        run.check("exactly one new ticket was created", len(new_ids) == 1)
        valid_id = new_ids[0] if new_ids else min(after)
        created = after[valid_id]
        run.check("the new ticket is about a keyboard",
                  "keyboard" in (created["title"] + " " + created["description"]).lower())
        run.check("the new ticket is OPEN", created["status"] == "OPEN")
        run.check("the answer gives the new ticket ID", str(valid_id) in run.answer)

        # GN scenario 2: list open tickets
        run = self.ask("2. Retrieve all open tickets", "Retrieve all open tickets.")
        open_ids = [i for i, t in self.tickets().items() if t["status"] == "OPEN"]
        run.check("list_tickets was called with the status filter OPEN",
                  any(str(args.get("status", "")).upper() == "OPEN" and res["ok"]
                      for args, res in run.calls_to("list_tickets")))
        run.check(f"the answer names every open ticket {open_ids}",
                  all(str(i) in run.answer for i in open_ids))

        # GN scenario 3: get ticket details
        run = self.ask("3. Get ticket details", f"Get details for ticket {valid_id}.")
        run.check(f"get_ticket was called for ticket {valid_id} and succeeded",
                  any(args.get("ticket_id") == valid_id and res["ok"] for args, res in run.calls_to("get_ticket")))
        run.check("the answer shows the ticket ID", str(valid_id) in run.answer)

        # GN scenario 4: invalid status
        run = self.ask("4. Invalid status 'PROGRESS'",
                       f"Update ticket {valid_id} to have the status 'PROGRESS'.")
        run.check("the API was asked and answered 422",
                  any(res["status_code"] == 422 for _, res in run.calls_to("update_ticket")))
        run.check("the ticket status did not change", self.tickets()[valid_id]["status"] == "OPEN")
        run.check("the answer lists the valid values from the API (OPEN, RESOLVED, CLOSED)",
                  all(value in run.answer for value in ("OPEN", "RESOLVED", "CLOSED")))

        # GN scenario 5: resolve with a resolution note
        run = self.ask("5. Resolve with a resolution note",
                       f"Update ticket {valid_id} to be RESOLVED, adding 'Replaced faulty cable' as the resolution.")
        ticket = self.tickets()[valid_id]
        run.check("the ticket is now RESOLVED", ticket["status"] == "RESOLVED")
        run.check("the resolution is 'Replaced faulty cable'",
                  (ticket["resolution"] or "").strip().rstrip(".").lower() == "replaced faulty cable")

        # GN scenario 6: non-existent ticket
        before = self.tickets()
        missing_id = 999 if 999 not in before else max(before) + 1000
        run = self.ask("6. Non-existent ticket", f"Update ticket {missing_id} to 'CLOSED'.")
        run.check("the API answered 404 for the unknown ticket",
                  any(res["status_code"] == 404 for _, res in run.calls_to("update_ticket")))
        run.check("no ticket was created or changed", self.tickets() == before)
        run.check("the answer mentions the ticket ID", str(missing_id) in run.answer)


def write_transcript(runs: list[Run], path: Path, header: dict) -> None:
    lines = ["# Live run of the 6 GN scenarios", ""]
    lines += [f"- {key}: {value}" for key, value in header.items()]
    lines += [f"- Result: **{sum(r.passed for r in runs)}/{len(runs)} scenarios passed**", ""]
    for run in runs:
        lines += [f"## {run.title}: {'PASS' if run.passed else 'FAIL'}", "", f"**You:** {run.prompt}", ""]
        lines += ["Tool calls:", ""] if run.calls else ["Tool calls: none", ""]
        for name, args, result in run.calls:
            lines.append(f"- `{name}({json.dumps(args)})` → `{json.dumps(result)}`")
        lines += ["", "**Agent:**", ""] + [f"> {line}" for line in run.answer.splitlines()] + ["", "Checks:", ""]
        lines += [f"- {'PASS' if ok else 'FAIL'}: {description}" for description, ok in run.checks]
        lines.append("")
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent.scenarios", description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=["direct", "mcp"], default="direct")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    try:
        config = load_config()
    except ConfigError as error:
        print(f"Configuration error: {error}")
        return 1
    api = TicketClient(config.ticket_api_base_url)
    health = api.health()
    if not health["ok"]:
        print(f"{health['detail']} Start the ticket API first.")
        return 1

    backend = make_backend(args.backend, config.ticket_api_base_url)
    runner = ScenarioRunner(Agent(make_llm_client(config), config.deployment, backend), api)
    runner.agent.on_tool_call = runner.record_tool_call
    try:
        runner.run_all()
    finally:
        backend.close()
        api.close()

    path = TRANSCRIPT_DIR / f"scenarios_{args.backend}.md"
    write_transcript(runner.runs, path, {
        "Date (UTC)": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "Command": f"python -m agent.scenarios --backend {args.backend}",
        "Model deployment": config.deployment,
        "API version": config.api_version,
        "Tool backend": args.backend,
        "Ticket API": config.ticket_api_base_url,
    })
    passed = sum(run.passed for run in runner.runs)
    print(f"\n{passed}/{len(runner.runs)} scenarios passed. Transcript: {path}")
    for run in runner.runs:
        for description, ok in run.checks:
            if not ok:
                print(f"  FAIL [{run.title}]: {description}")
    return 0 if passed == len(runner.runs) else 1


if __name__ == "__main__":
    sys.exit(main())
