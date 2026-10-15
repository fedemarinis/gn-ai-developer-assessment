"""HTTP client for the Mock Ticketing API (Part 1 of the brief).

Each method converts the expected outcomes (success, an API error, a network failure) into one
consistent result dict, so the agent's tools can pass it straight to the language model:
    {"ok": True,  "status_code": 200,  "data": <ticket | list of tickets | None for 204>}
    {"ok": False, "status_code": 404,  "detail": "<the API's detail message, verbatim>"}
    {"ok": False, "status_code": None, "detail": "Ticket service unreachable at <url>: <reason>"}
"""

from urllib.parse import quote

import httpx

DEFAULT_TIMEOUT_SECONDS = 10.0


class TicketClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # Tests inject FastAPI's TestClient (an httpx.Client) to call the API in-process.
        self.base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def health(self) -> dict:
        return self._request("GET", "/health")

    def list_tickets(self, status: str | None = None) -> dict:
        params = {"status": status} if status is not None else None
        return self._request("GET", "/tickets", params=params)

    def get_ticket(self, ticket_id: int) -> dict:
        return self._request("GET", _ticket_path(ticket_id))

    def create_ticket(
        self,
        title: str,
        description: str | None = None,
        status: str | None = None,
        resolution: str | None = None,
    ) -> dict:
        body = _drop_none(title=title, description=description, status=status, resolution=resolution)
        return self._request("POST", "/tickets", json=body)

    def update_ticket(
        self,
        ticket_id: int,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        resolution: str | None = None,
    ) -> dict:
        # Only fields that were given are sent, so the API changes only those (PATCH).
        body = _drop_none(title=title, description=description, status=status, resolution=resolution)
        return self._request("PATCH", _ticket_path(ticket_id), json=body)

    def delete_ticket(self, ticket_id: int) -> dict:
        return self._request("DELETE", _ticket_path(ticket_id))

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Send one request and convert the expected outcomes into the result dict."""
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            return _unreachable(self.base_url, "the request timed out")
        except httpx.HTTPError as error:  # connection refused, DNS failure, ...
            return _unreachable(self.base_url, type(error).__name__)

        if response.is_success:
            if response.status_code == 204 or not response.content:
                return {"ok": True, "status_code": response.status_code, "data": None}
            try:
                return {"ok": True, "status_code": response.status_code, "data": response.json()}
            except ValueError:
                return {"ok": False, "status_code": response.status_code,
                        "detail": "The ticket service returned a response that is not valid JSON."}
        return {"ok": False, "status_code": response.status_code, "detail": _error_detail(response)}


def _ticket_path(ticket_id) -> str:
    # The id is passed through as given, so a non-integer id gets the API's own 422 message.
    # quote() stops characters such as "/" from changing the URL path.
    return f"/tickets/{quote(str(ticket_id), safe='')}"


def _drop_none(**fields) -> dict:
    return {name: value for name, value in fields.items() if value is not None}


def _unreachable(base_url: str, reason: str) -> dict:
    return {"ok": False, "status_code": None,
            "detail": f"Ticket service unreachable at {base_url}: {reason}."}


def _error_detail(response: httpx.Response) -> str:
    """Return the API's error message. On 4xx the real body is {"detail": "<one string>"},
    even though the generated /openapi.json shows a list-shaped 422 schema.
    Anything else (e.g. a plain-text 500) is reported as short text."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, str) and detail:
        return detail
    text = response.text.strip()[:200]
    return f"HTTP {response.status_code} {response.reason_phrase}" + (f": {text}" if text else "")
