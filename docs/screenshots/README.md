# Demo screenshots

This directory holds the demo screenshots referenced by
`Submission_and_Evaluation_Guidelines.md` § 18 and linked
from the repo README. The expected filenames are listed below;
capture them locally with the docker stack running
(`make up`) and drop them in here.

The screenshots are intentionally **not** committed by the
PR that introduced this directory — the operator captures them
on their own machine so the demo flow matches the actual
deployed UI.

## Expected filenames

| File | What it shows |
|---|---|
| `01-empty-state.png` | First load: sidebar with 3 example prompts, empty workspace hint, app bar with backend URL. |
| `02-chat-with-incident.png` | After a chat turn: assistant message card with intent + RAG-confidence + citation/trace count pills. The structured Incident card renders below the answer. |
| `03-workspace-panels.png` | The right-hand workspace column populated: incident summary card, editable draft card, citations cards, MCP trace timeline. |
| `04-confirmation-modal.png` | The approval modal showing the ticket draft + the full citations (the evidence chain) + the "What will happen" footer. |
| `05-ticket-created.png` | The success panel after the approver clicks "Approve & create" — `ticket_id` + audit block (`approved_by`, `request_id`). |

## How to capture

1. `make up` (docker compose up --build -d).
2. Wait ~30 seconds for the health checks to pass.
3. Open `http://localhost:5173` in a browser.
4. Walk the five states above, saving each capture as the
   matching `*.png`.
5. Replace these notes with the captures (or commit them
   alongside — they're gitignored only by `.gitignore` defaults,
   not by any explicit rule).

The brief's § 18 demo evidence ends here. For a 10-minute walk
video, record `screen` while running the demo and link it
from `README.md` (Story 9.2.3 — not implemented in this repo).

## Notes

* After the `feat(frontend): polished UI` PR lands, the app bar's
  title is centered. Re-capture `01-empty-state.png` to reflect
  the new layout if you want the screenshot to match the
  deployed UI.
