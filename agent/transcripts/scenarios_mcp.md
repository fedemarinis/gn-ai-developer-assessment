# Live run of the 6 GN scenarios

- Date (UTC): 2026-10-15 15:16
- Equivalent command: python -m agent.scenarios --backend mcp
- Recording note: the unchanged scenario runner was invoked through a temporary external wrapper that disabled automatic SDK retries, counted Azure OpenAI requests, and started and stopped a fresh local ticket API.
- Model deployment: gpt-6-luna-c1
- API version: 2024-12-01-preview
- Tool backend: mcp
- Ticket API: http://127.0.0.1:8010
- Result: **6/6 scenarios passed**

## 1. Create a ticket: PASS

**You:** Create a new ticket about a keyboard not working.

Tool calls:

- `create_ticket({"title": "Keyboard not working"})` → `{"ok": true, "status_code": 201, "data": {"id": 4, "title": "Keyboard not working", "description": "", "created": "2026-10-15T15:15:47.911961Z", "status": "OPEN", "resolution": null, "updated": null}}`

**Agent:**

> Created ticket **#4** — Keyboard not working (status: OPEN).

Checks:

- PASS: exactly one new ticket was created
- PASS: the new ticket is about a keyboard
- PASS: the new ticket is OPEN
- PASS: the answer gives the new ticket ID

## 2. Retrieve all open tickets: PASS

**You:** Retrieve all open tickets.

Tool calls:

- `list_tickets({"status": "open"})` → `{"ok": true, "status_code": 200, "data": [{"id": 1, "title": "Printer on floor 2 is jamming", "description": "The shared printer jams on every second page.", "created": "2026-10-15T15:15:43.903388Z", "status": "OPEN", "resolution": null, "updated": null}, {"id": 2, "title": "VPN disconnects every few minutes", "description": "The VPN client drops the connection about every 5 minutes.", "created": "2026-10-15T15:15:43.903388Z", "status": "OPEN", "resolution": null, "updated": null}, {"id": 4, "title": "Keyboard not working", "description": "", "created": "2026-10-15T15:15:47.911961Z", "status": "OPEN", "resolution": null, "updated": null}]}`

**Agent:**

> - **ID 1** — Printer on floor 2 is jamming — Status: OPEN — Resolution: none
> - **ID 2** — VPN disconnects every few minutes — Status: OPEN — Resolution: none
> - **ID 4** — Keyboard not working — Status: OPEN — Resolution: none

Checks:

- PASS: list_tickets was called with the status filter OPEN
- PASS: the answer names every open ticket [1, 2, 4]

## 3. Get ticket details: PASS

**You:** Get details for ticket 4.

Tool calls:

- `get_ticket({"ticket_id": 4})` → `{"ok": true, "status_code": 200, "data": {"id": 4, "title": "Keyboard not working", "description": "", "created": "2026-10-15T15:15:47.911961Z", "status": "OPEN", "resolution": null, "updated": null}}`

**Agent:**

> - **ID:** 4
> - **Title:** Keyboard not working
> - **Status:** OPEN
> - **Resolution:** None

Checks:

- PASS: get_ticket was called for ticket 4 and succeeded
- PASS: the answer shows the ticket ID

## 4. Invalid status 'PROGRESS': PASS

**You:** Update ticket 4 to have the status 'PROGRESS'.

Tool calls:

- `update_ticket({"ticket_id": 4, "status": "PROGRESS"})` → `{"ok": false, "status_code": 422, "detail": "Invalid status 'PROGRESS'. Allowed values: OPEN, RESOLVED, CLOSED."}`

**Agent:**

> Ticket 4 wasn’t updated: `PROGRESS` is invalid. Allowed statuses are `OPEN`, `RESOLVED`, and `CLOSED`. Which status would you like?

Checks:

- PASS: the API was asked and answered 422
- PASS: the ticket status did not change
- PASS: the answer lists the valid values from the API (OPEN, RESOLVED, CLOSED)

## 5. Resolve with a resolution note: PASS

**You:** Update ticket 4 to be RESOLVED, adding 'Replaced faulty cable' as the resolution.

Tool calls:

- `update_ticket({"ticket_id": 4, "status": "RESOLVED", "resolution": "Replaced faulty cable"})` → `{"ok": true, "status_code": 200, "data": {"id": 4, "title": "Keyboard not working", "description": "", "created": "2026-10-15T15:15:47.911961Z", "status": "RESOLVED", "resolution": "Replaced faulty cable", "updated": "2026-10-15T15:15:58.336912Z"}}`

**Agent:**

> Updated ticket **4** — Keyboard not working  
> - Status: RESOLVED  
> - Resolution: Replaced faulty cable

Checks:

- PASS: the ticket is now RESOLVED
- PASS: the resolution is 'Replaced faulty cable'

## 6. Non-existent ticket: PASS

**You:** Update ticket 999 to 'CLOSED'.

Tool calls:

- `update_ticket({"ticket_id": 999, "status": "CLOSED"})` → `{"ok": false, "status_code": 404, "detail": "Ticket with id 999 not found."}`

**Agent:**

> Ticket 999 does not exist, so I couldn’t update its status. Please check the ticket ID and try again.

Checks:

- PASS: the API answered 404 for the unknown ticket
- PASS: no ticket was created or changed
- PASS: the answer mentions the ticket ID
