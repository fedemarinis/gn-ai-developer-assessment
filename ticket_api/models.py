"""Ticket data models and the ticket business rule.

Defines the allowed statuses, the request bodies clients may send (create and
partial update), the ticket returned by the API, and the rule that a RESOLVED
ticket must carry a resolution note. Request validation is driven by these
models; the storage layer applies the business rule.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# The only status values a ticket can hold. (Docstrings on the models would appear in
# the OpenAPI schema, so the models below are described with comments instead.)
class TicketStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

    @classmethod
    def _missing_(cls, value):
        # Called by Enum when the exact value is not found: accept "open", " Resolved ", ...
        # Input is case-insensitive, but stored and returned values are always uppercase.
        if isinstance(value, str):
            return cls.__members__.get(value.strip().upper())
        return None


# Built from the enum so that error messages always list the current set of statuses.
ALLOWED_STATUSES = ", ".join(s.value for s in TicketStatus)
UPDATABLE_FIELDS = ("title", "description", "status", "resolution")

RESOLUTION_REQUIRED = "A resolution note is required when setting status to RESOLVED."


class BusinessRuleError(Exception):
    """A request that is well-formed but breaks a ticket rule (-> 422)."""


def check_resolution_rule(status: TicketStatus, resolution: str | None) -> None:
    """Enforce that a RESOLVED ticket always has a non-empty resolution note.

    Applied to the final state of a ticket (on create and after merging an
    update), so it also blocks clearing the note of an already resolved ticket.
    """
    if status == TicketStatus.RESOLVED and not (resolution and resolution.strip()):
        raise BusinessRuleError(RESOLUTION_REQUIRED)


class _Input(BaseModel):
    # Reject unknown fields (e.g. "state") instead of silently ignoring them; otherwise a
    # misspelled field would be dropped and the request would still report success.
    # Whitespace is trimmed so that a title of only spaces fails the min_length check.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# Body of POST /tickets. Only the title is required.
class TicketCreate(_Input):
    title: str = Field(min_length=1)
    description: str = ""
    status: TicketStatus = TicketStatus.OPEN
    resolution: str | None = None


class TicketUpdate(_Input):
    """PATCH body: every field is optional, only the fields sent are changed."""

    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: TicketStatus | None = None
    resolution: str | None = None

    @field_validator("title", "description", "status")
    @classmethod
    def not_null(cls, value):
        # Omitting these fields is fine; explicitly sending null is not.
        # Only `resolution` may be null (to clear it).
        if value is None:
            raise ValueError("may not be null")
        return value

    @model_validator(mode="after")
    def at_least_one_field(self):
        # model_fields_set holds only the fields present in the request body,
        # so an empty body {} is rejected even though every field is optional.
        if not self.model_fields_set:
            raise ValueError(
                f"Provide at least one field to update: {', '.join(UPDATABLE_FIELDS)}."
            )
        return self


# A stored ticket, exactly as returned by the API.
class Ticket(BaseModel):
    id: int
    title: str
    description: str
    created: datetime
    status: TicketStatus
    resolution: str | None
    updated: datetime | None
