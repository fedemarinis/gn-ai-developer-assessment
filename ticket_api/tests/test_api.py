"""API tests for the Mock Ticketing API.

Requests go through FastAPI's in-process TestClient (no running server). Each test
starts from the same three seed tickets, and error tests assert the exact `detail`
text, because clients such as the agent rely on these messages.
"""

from ticket_api.storage import TicketStore

FIELDS = {"id", "title", "description", "created", "status", "resolution", "updated"}
INVALID_STATUS = "Invalid status 'PROGRESS'. Allowed values: OPEN, RESOLVED, CLOSED."
RESOLUTION_REQUIRED = "A resolution note is required when setting status to RESOLVED."


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Create --------------------------------------------------------------------

def test_create_ticket_with_defaults(client):
    response = client.post("/tickets", json={"title": "Keyboard not working"})
    assert response.status_code == 201
    ticket = response.json()
    assert set(ticket) == FIELDS
    assert ticket["id"] == 4
    assert ticket["status"] == "OPEN"
    assert ticket["description"] == ""
    assert ticket["resolution"] is None
    assert ticket["updated"] is None
    assert ticket["created"].endswith("Z")


def test_create_accepts_lowercase_status(client):
    response = client.post("/tickets", json={"title": "Mouse", "status": "closed"})
    assert response.status_code == 201
    assert response.json()["status"] == "CLOSED"


def test_create_requires_title(client):
    response = client.post("/tickets", json={"description": "no title"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Field 'title' is required."}


def test_create_rejects_blank_title(client):
    response = client.post("/tickets", json={"title": "   "})
    assert response.status_code == 422
    assert response.json() == {"detail": "Field 'title' must not be empty."}


def test_create_rejects_invalid_status(client):
    response = client.post("/tickets", json={"title": "x", "status": "PROGRESS"})
    assert response.status_code == 422
    assert response.json() == {"detail": INVALID_STATUS}


def test_create_resolved_requires_resolution(client):  # resolution rule on create
    response = client.post("/tickets", json={"title": "x", "status": "RESOLVED"})
    assert response.status_code == 422
    assert response.json() == {"detail": RESOLUTION_REQUIRED}


def test_create_resolved_with_resolution(client):
    response = client.post(
        "/tickets", json={"title": "x", "status": "RESOLVED", "resolution": "Fixed"}
    )
    assert response.status_code == 201
    assert response.json()["resolution"] == "Fixed"


def test_create_rejects_unknown_field(client):
    response = client.post("/tickets", json={"title": "x", "id": 99})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Unknown field 'id'. Allowed fields: title, description, status, resolution."
    }


# --- Retrieve and filter --------------------------------------------------------

def test_list_all_tickets(client):
    client.post("/tickets", json={"title": "Keyboard not working"})
    response = client.get("/tickets")
    assert response.status_code == 200
    tickets = response.json()
    assert [t["id"] for t in tickets] == [1, 2, 3, 4]
    assert all(set(t) == FIELDS for t in tickets)


def test_filter_by_status(client):
    response = client.get("/tickets", params={"status": "OPEN"})
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [1, 2]
    assert all(t["status"] == "OPEN" for t in response.json())


def test_filter_is_case_insensitive(client):
    response = client.get("/tickets", params={"status": "resolved"})
    assert [t["id"] for t in response.json()] == [3]


def test_filter_with_no_matches_returns_empty_list(client):
    response = client.get("/tickets", params={"status": "CLOSED"})
    assert response.status_code == 200
    assert response.json() == []


def test_filter_rejects_invalid_status(client):
    response = client.get("/tickets", params={"status": "PROGRESS"})
    assert response.status_code == 422
    assert response.json() == {"detail": INVALID_STATUS}


def test_get_ticket_by_id(client):
    response = client.get("/tickets/2")
    assert response.status_code == 200
    assert response.json()["id"] == 2
    assert response.json()["title"] == "VPN disconnects every few minutes"


def test_get_unknown_ticket_returns_404(client):
    response = client.get("/tickets/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket with id 999 not found."}


def test_non_integer_id_returns_422(client):
    response = client.get("/tickets/abc")
    assert response.status_code == 422
    assert response.json() == {"detail": "Ticket id must be an integer, got 'abc'."}


# --- Update (PATCH) -------------------------------------------------------------

def test_update_changes_persist_and_set_updated(client):
    response = client.patch("/tickets/1", json={"status": "CLOSED", "title": "Printer fixed"})
    assert response.status_code == 200
    ticket = response.json()
    assert ticket["status"] == "CLOSED"
    assert ticket["title"] == "Printer fixed"
    assert ticket["description"] == "The shared printer jams on every second page."
    assert ticket["updated"] is not None
    assert ticket["updated"] >= ticket["created"]
    assert client.get("/tickets/1").json() == ticket


def test_update_invalid_status_returns_422_listing_allowed_values(client):  # GN scenario 4
    response = client.patch("/tickets/1", json={"status": "PROGRESS"})
    assert response.status_code == 422
    assert response.json() == {"detail": INVALID_STATUS}
    assert client.get("/tickets/1").json()["status"] == "OPEN"


def test_update_unknown_ticket_returns_404(client):  # GN scenario 6
    response = client.patch("/tickets/999", json={"status": "CLOSED"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket with id 999 not found."}


def test_body_validation_happens_before_id_lookup(client):
    # Request validation runs before the ID lookup, so an invalid body gives 422
    # even when the ID is unknown.
    response = client.patch("/tickets/999", json={"status": "PROGRESS"})
    assert response.status_code == 422


def test_update_resolved_without_resolution_returns_422(client):
    response = client.patch("/tickets/1", json={"status": "RESOLVED"})
    assert response.status_code == 422
    assert response.json() == {"detail": RESOLUTION_REQUIRED}
    assert client.get("/tickets/1").json()["status"] == "OPEN"  # nothing changed


def test_update_resolved_with_resolution(client):  # GN scenario 5
    response = client.patch(
        "/tickets/1", json={"status": "RESOLVED", "resolution": "Replaced faulty cable"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"
    assert response.json()["resolution"] == "Replaced faulty cable"


def test_update_resolved_using_stored_resolution(client):
    client.patch("/tickets/1", json={"resolution": "Cleaned the rollers"})
    response = client.patch("/tickets/1", json={"status": "RESOLVED"})
    assert response.status_code == 200


def test_cannot_clear_resolution_of_resolved_ticket(client):
    for body in ({"resolution": None}, {"resolution": "  "}):
        response = client.patch("/tickets/3", json=body)
        assert response.status_code == 422
        assert response.json() == {"detail": RESOLUTION_REQUIRED}


def test_moving_away_from_resolved_keeps_resolution(client):
    response = client.patch("/tickets/3", json={"status": "closed"})
    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"
    assert response.json()["resolution"] == "Replaced the docking station cable."


def test_update_rejects_empty_body(client):
    response = client.patch("/tickets/1", json={})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Provide at least one field to update: title, description, status, resolution."
    }


def test_update_rejects_unknown_field(client):
    response = client.patch("/tickets/1", json={"state": "CLOSED"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Unknown field 'state'.")


def test_update_rejects_null_title(client):
    response = client.patch("/tickets/1", json={"title": None})
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid value for 'title': may not be null."}


def test_malformed_json_returns_422(client):
    response = client.patch(
        "/tickets/1", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Request body is not valid JSON."}


# --- Delete --------------------------------------------------------------------

def test_delete_ticket(client):
    response = client.delete("/tickets/2")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/tickets/2").status_code == 404


def test_delete_unknown_ticket_returns_404(client):
    response = client.delete("/tickets/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket with id 999 not found."}


def test_ids_are_not_reused_after_delete(client):
    client.delete("/tickets/3")
    response = client.post("/tickets", json={"title": "New"})
    assert response.json()["id"] == 4


# --- Storage: thread safety -----------------------------------------------------

def test_concurrent_creates_get_unique_ids():
    # FastAPI runs sync endpoints in a thread pool; concurrent creates must never
    # hand out the same ID.
    from concurrent.futures import ThreadPoolExecutor

    from ticket_api.models import TicketCreate

    store = TicketStore(seed=False)
    with ThreadPoolExecutor(max_workers=8) as pool:
        tickets = list(pool.map(lambda i: store.create(TicketCreate(title=f"t{i}")), range(200)))
    assert sorted(t.id for t in tickets) == list(range(1, 201))
