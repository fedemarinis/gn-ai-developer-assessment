"""In-memory ticket storage (a dict keyed by ID), safe to use from several threads.

Data lives in the memory of one process: it is lost on restart, and the server
must run with a single worker so that every request sees the same tickets.
"""

import threading
from datetime import datetime, timezone

from ticket_api.models import Ticket, TicketCreate, TicketStatus, check_resolution_rule

# Fictional demo tickets, so the list is not empty after start-up. No personal data:
# ticket content may be passed to the LLM used by the agent.
SEED_TICKETS = [
    TicketCreate(
        title="Printer on floor 2 is jamming",
        description="The shared printer jams on every second page.",
    ),
    TicketCreate(
        title="VPN disconnects every few minutes",
        description="The VPN client drops the connection about every 5 minutes.",
    ),
    TicketCreate(
        title="Monitor flickering",
        description="The external monitor flickers when the laptop is docked.",
        status=TicketStatus.RESOLVED,
        resolution="Replaced the docking station cable.",
    ),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TicketStore:
    """FastAPI runs normal endpoints in a thread pool, so every operation that reads
    or changes the dict (including the full read-check-write of an update) holds a lock."""

    def __init__(self, seed: bool = True) -> None:
        self._lock = threading.Lock()
        self.reset(seed)

    def reset(self, seed: bool = True) -> None:
        with self._lock:
            self._tickets: dict[int, Ticket] = {}
            self._next_id = 1
        if seed:
            for data in SEED_TICKETS:
                self.create(data)

    def list(self, status: TicketStatus | None = None) -> list[Ticket]:
        # Copy the tickets under the lock; filtering the copy needs no lock.
        with self._lock:
            tickets = list(self._tickets.values())
        if status is not None:
            tickets = [t for t in tickets if t.status == status]
        return tickets

    def get(self, ticket_id: int) -> Ticket | None:
        with self._lock:
            return self._tickets.get(ticket_id)

    def create(self, data: TicketCreate) -> Ticket:
        check_resolution_rule(data.status, data.resolution)
        with self._lock:
            ticket = Ticket(
                # IDs are never reused, even after a delete, so a remembered ID
                # can never point to a different ticket later.
                id=self._next_id,
                created=_now(),
                updated=None,
                **data.model_dump(),
            )
            self._tickets[ticket.id] = ticket
            self._next_id += 1
            return ticket

    def update(self, ticket_id: int, changes: dict) -> Ticket | None:
        """Apply `changes` (only the fields the client sent). Returns None if the ID
        is unknown. Raises BusinessRuleError if the result would break a rule."""
        with self._lock:
            current = self._tickets.get(ticket_id)
            if current is None:
                return None
            # Build a new version and check the rule on it before saving, so a rejected
            # update leaves the stored ticket untouched. model_copy does not re-validate;
            # `changes` was already validated as a TicketUpdate.
            updated = current.model_copy(update={**changes, "updated": _now()})
            check_resolution_rule(updated.status, updated.resolution)
            self._tickets[ticket_id] = updated
            return updated

    def delete(self, ticket_id: int) -> bool:
        with self._lock:
            return self._tickets.pop(ticket_id, None) is not None
