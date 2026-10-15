"""Turn FastAPI's technical 422 error list into one readable `detail` sentence.

FastAPI's default 422 body is a list like
    [{"type": "enum", "loc": ["body", "status"], "msg": "...", "input": "PROGRESS"}]
This handler replaces it with
    {"detail": "Invalid status 'PROGRESS'. Allowed values: OPEN, RESOLVED, CLOSED."}
so that a person, or the agent that relays the message, can act on it directly.
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ticket_api.models import ALLOWED_STATUSES, UPDATABLE_FIELDS


def _describe(error: dict) -> str:
    """Turn one Pydantic error (type, location, input) into a readable sentence."""
    kind = error["type"]
    loc = error["loc"]
    field = loc[-1] if len(loc) > 1 else None
    value = error.get("input")
    # Messages from custom validators arrive as "Value error, <text>".
    msg = error["msg"].removeprefix("Value error, ")

    if kind == "json_invalid":
        return "Request body is not valid JSON."
    if field is None:  # problem with the body as a whole
        if kind == "missing":
            return "Request body is required."
        if kind in ("model_attributes_type", "dict_type"):
            return "Request body must be a JSON object."
        return msg
    if kind == "enum":
        return f"Invalid {field} '{value}'. Allowed values: {ALLOWED_STATUSES}."
    if kind == "missing":
        return f"Field '{field}' is required."
    if kind == "extra_forbidden":
        return f"Unknown field '{field}'. Allowed fields: {', '.join(UPDATABLE_FIELDS)}."
    if kind == "string_too_short":
        return f"Field '{field}' must not be empty."
    if kind == "int_parsing" and loc[0] == "path":
        return f"Ticket id must be an integer, got '{value}'."
    # Fallback for any other validation problem (e.g. a wrong type).
    return f"Invalid value for '{field}': {msg}."


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Several problems are joined into one string, so `detail` is always a single string.
    sentences = dict.fromkeys(_describe(e) for e in exc.errors())  # keeps order, drops duplicates
    return JSONResponse(status_code=422, content={"detail": " ".join(sentences)})
