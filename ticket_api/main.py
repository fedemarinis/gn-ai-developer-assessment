"""Mock Ticketing API: the FastAPI app and its endpoints.

Run with:  python -m uvicorn ticket_api.main:app --reload

Every request passes three checks, in this order:
  1. Validation of the path, query and body by FastAPI/Pydantic -> 422
     (formatted by ticket_api.errors). The endpoint function does not run.
  2. Lookup of the ticket ID in the store                        -> 404
  3. The business rule (RESOLVED needs a resolution note)        -> 422
Because validation comes first, PATCH /tickets/999 with an invalid status
returns 422, not 404. Every 4xx response body is {"detail": "<one sentence>"}.
"""

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.exceptions import RequestValidationError

from ticket_api.errors import validation_error_handler
from ticket_api.models import BusinessRuleError, Ticket, TicketCreate, TicketStatus, TicketUpdate
from ticket_api.storage import TicketStore

app = FastAPI(
    title="Mock Ticketing API",
    description="Support tickets with CRUD, status filtering and readable 4xx errors.",
    version="1.0.0",
)
# Replaces FastAPI's default 422 body (a list of error objects) with one readable sentence.
app.add_exception_handler(RequestValidationError, validation_error_handler)

# Single in-memory store for this process (so the server must run with 1 worker).
store = TicketStore()


def _not_found(ticket_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Ticket with id {ticket_id} not found.")


def _rule_violation(error: BusinessRuleError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


# Liveness check, used by clients to see whether the API is running.
# (Endpoint docstrings would appear in the OpenAPI docs, so comments are used here.)
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(data: TicketCreate) -> Ticket:
    try:
        return store.create(data)
    except BusinessRuleError as error:
        raise _rule_violation(error)


@app.get("/tickets")
def list_tickets(status: TicketStatus | None = None) -> list[Ticket]:
    return store.list(status)


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int) -> Ticket:
    ticket = store.get(ticket_id)
    if ticket is None:
        raise _not_found(ticket_id)
    return ticket


@app.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, data: TicketUpdate) -> Ticket:
    # exclude_unset=True keeps only the fields present in the request body. An omitted
    # field stays unchanged, while an explicit {"resolution": null} clears the note.
    try:
        ticket = store.update(ticket_id, data.model_dump(exclude_unset=True))
    except BusinessRuleError as error:
        raise _rule_violation(error)
    if ticket is None:
        raise _not_found(ticket_id)
    return ticket


@app.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket(ticket_id: int) -> Response:
    if not store.delete(ticket_id):
        raise _not_found(ticket_id)
    # An explicit Response guarantees an empty body for 204 No Content.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
