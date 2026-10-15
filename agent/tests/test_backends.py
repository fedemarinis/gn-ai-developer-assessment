"""DirectBackend tests: the tool specs, and tool calls against the real API in-process."""

import json

from agent.backends import TOOL_SPECS
from agent.prompts import SYSTEM_PROMPT


def test_five_tools_one_per_endpoint(backend):
    names = [spec["function"]["name"] for spec in backend.tool_specs()]
    assert names == ["create_ticket", "list_tickets", "get_ticket", "update_ticket", "delete_ticket"]


def test_valid_statuses_are_not_hard_coded():
    # The allowed values must come from the API's 422 detail, never from the tool specs or the prompt.
    our_text = json.dumps(TOOL_SPECS) + SYSTEM_PROMPT
    for value in ("OPEN", "RESOLVED", "CLOSED", "enum"):
        assert value not in our_text


def test_list_with_filter(backend):
    result = json.loads(backend.call("list_tickets", {"status": "OPEN"}))
    assert [t["id"] for t in result["data"]] == [1, 2]


def test_null_arguments_are_not_sent(backend):
    # Models sometimes send null for optional fields. They must not reach the API as null.
    result = json.loads(backend.call("update_ticket", {"ticket_id": 1, "status": "CLOSED", "title": None}))
    assert result["ok"] is True and result["data"]["status"] == "CLOSED"


def test_delete(backend):
    assert json.loads(backend.call("delete_ticket", {"ticket_id": 2})) == {
        "ok": True, "status_code": 204, "data": None}


def test_unknown_tool_does_not_raise(backend):
    assert json.loads(backend.call("close_all", {})) == {
        "ok": False, "status_code": None, "detail": "Unknown tool 'close_all'."}


def test_bad_arguments_do_not_raise(backend):
    missing = json.loads(backend.call("get_ticket", {}))
    unexpected = json.loads(backend.call("get_ticket", {"ticket_id": 1, "priority": "high"}))
    for result in (missing, unexpected):
        assert result["ok"] is False and result["status_code"] is None
        assert result["detail"].startswith("Invalid arguments for get_ticket")
