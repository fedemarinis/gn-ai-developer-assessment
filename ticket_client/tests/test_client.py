"""ticket_client tests: the real Part 1 app in-process (TestClient) plus simulated network failures."""

import httpx
import pytest
from fastapi.testclient import TestClient

from ticket_api.main import app, store
from ticket_client import TicketClient

INVALID_STATUS = "Invalid status 'PROGRESS'. Allowed values: OPEN, RESOLVED, CLOSED."


@pytest.fixture
def client():
    store.reset()  # Every test starts from the 3 seed tickets: ids 1 and 2 OPEN, id 3 RESOLVED.
    with TestClient(app) as http:
        yield TicketClient(http_client=http)


def test_health(client):
    assert client.health() == {"ok": True, "status_code": 200, "data": {"status": "ok"}}


def test_list_and_filter(client):
    everything = client.list_tickets()
    assert everything["ok"] and [t["id"] for t in everything["data"]] == [1, 2, 3]
    open_only = client.list_tickets(status="OPEN")
    assert [t["id"] for t in open_only["data"]] == [1, 2]


def test_invalid_filter_returns_api_detail(client):
    assert client.list_tickets(status="PROGRESS") == {
        "ok": False, "status_code": 422, "detail": INVALID_STATUS}


def test_get_ticket_and_404(client):
    assert client.get_ticket(1)["data"]["id"] == 1
    assert client.get_ticket(999) == {
        "ok": False, "status_code": 404, "detail": "Ticket with id 999 not found."}


def test_non_integer_id_gets_api_message(client):
    result = client.get_ticket("abc")
    assert result == {"ok": False, "status_code": 422,
                      "detail": "Ticket id must be an integer, got 'abc'."}


def test_create_sends_only_given_fields(client):
    result = client.create_ticket(title="Keyboard not working")
    assert result["ok"] and result["status_code"] == 201
    assert result["data"]["id"] == 4
    assert result["data"]["status"] == "OPEN"
    assert result["data"]["resolution"] is None


def test_update_invalid_status_returns_422_detail(client):
    assert client.update_ticket(1, status="PROGRESS") == {
        "ok": False, "status_code": 422, "detail": INVALID_STATUS}
    assert client.get_ticket(1)["data"]["status"] == "OPEN"  # a rejected update changes nothing


def test_update_resolved_with_resolution(client):
    result = client.update_ticket(1, status="RESOLVED", resolution="Replaced faulty cable")
    assert result["ok"] and result["status_code"] == 200
    assert result["data"]["status"] == "RESOLVED"
    assert result["data"]["resolution"] == "Replaced faulty cable"


def test_update_resolved_without_resolution_is_rule_error(client):
    assert client.update_ticket(1, status="RESOLVED") == {
        "ok": False, "status_code": 422,
        "detail": "A resolution note is required when setting status to RESOLVED."}


def test_update_unknown_ticket_returns_404(client):
    assert client.update_ticket(999, status="CLOSED") == {
        "ok": False, "status_code": 404, "detail": "Ticket with id 999 not found."}


def test_delete_returns_null_data_then_404(client):
    assert client.delete_ticket(2) == {"ok": True, "status_code": 204, "data": None}
    assert client.get_ticket(2)["status_code"] == 404


# --- Network failures (no API involved) -----------------------------------------

def _client_with(handler) -> TicketClient:
    # httpx.MockTransport answers each request with the given function instead of the network,
    # so failures such as timeouts can be simulated without a running server.
    http = httpx.Client(base_url="http://tickets.test", transport=httpx.MockTransport(handler))
    return TicketClient(base_url="http://tickets.test", http_client=http)


def test_connection_refused_is_reported_not_raised():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    assert _client_with(refuse).list_tickets() == {
        "ok": False, "status_code": None,
        "detail": "Ticket service unreachable at http://tickets.test: ConnectError."}


def test_timeout_is_reported_not_raised():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    result = _client_with(slow).get_ticket(1)
    assert result["ok"] is False and result["status_code"] is None
    assert "timed out" in result["detail"]


def test_non_json_server_error_becomes_short_detail():
    def broken(request):
        return httpx.Response(500, text="Internal Server Error")

    assert _client_with(broken).get_ticket(1) == {
        "ok": False, "status_code": 500,
        "detail": "HTTP 500 Internal Server Error: Internal Server Error"}
