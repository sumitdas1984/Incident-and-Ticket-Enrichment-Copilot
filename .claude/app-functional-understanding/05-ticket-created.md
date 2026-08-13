# `05-ticket-created.png` — what this screen tells you

This is the **last screen** in the demo flow. It is the small
"success" panel that appears after the operator has clicked the
final **Approve & create** button on the previous screen
(`04-confirmation-modal.png`). It is the proof that the ticket
actually exists in the ticketing system.

If you are explaining this app to a non-technical person, this
screen is the **"we're done"** landing page. It answers three
questions in one glance:

1. **Did the ticket get created?** — Yes.
2. **Who pressed the button?** — The operator (the human).
3. **Can someone trace this back later?** — Yes, every detail
   is recorded.

---

## What you see on the screen, top to bottom

### 1. The green success banner

A green box with a ✅ checkmark and the words **"Ticket created"**.

This is the visual confirmation that the write happened. It is
the same kind of green confirmation you see when an online form
finishes submitting ("Thanks, your order is placed"). No green
banner = no ticket created.

### 2. The fact table — three rows

Underneath the banner is a small three-row table of
**what just happened**:

| Row | What it means in plain English |
|---|---|
| **Ticket id** | The unique reference number of the new ticket inside the ticketing system. Think of it like a confirmation number or order ID — `TKT-2002` here. Anyone with this id can look up the ticket later. |
| **Approved by** | The name of the person who clicked "Approve & create". This is the human accountability row. It is always a person — the system never approves its own writes. |
| **Request id** | A long random string (the green code `d9cf7…419b`). This is the technical trace id that ties this exact submit click to the log entries elsewhere in the system. If two people create tickets at the same time, the request ids keep their records from getting mixed up. |

### 3. The audit note at the bottom

A bordered note at the bottom says:

> *The audit row is appended to the ticket-mock's
> `GET /tickets/audit` log.*

This is the system telling you **"this event is now part of
the permanent record"**. The audit log is a chronologically
ordered list of every ticket write that has ever happened,
with the ticket id, the approver, the request id, and a
timestamp. It is the same idea as a bank statement or a
medical record — once a row is appended, it cannot be quietly
removed.

---

## How this fits in the bigger picture

The whole app is a journey through five screens. This is the
fifth and final one. The previous four were:

1. `01-empty-state.png` — the operator opens the app, sees the
   empty chat and the suggested prompts.
2. `02-chat-with-incident.png` — the operator asks a question;
   the copilot investigates, drafts a structured incident, and
   shows the editable ticket draft on the right.
3. `03-workspace-panels.png` — the workspace is fully populated
   with the citation cards and the tool-trace timeline.
4. `04-confirmation-modal.png` — the operator reviews the
   ticket one last time and clicks **Approve & create**.
5. `05-ticket-created.png` — **this screen.** The ticket is
   live in the system.

So if you are demoing to a layman, you can describe this screen
as the **"receipt"** for the ticket creation. It is the moment
the plan became a real record.

---

## Why this screen matters for the app's design

There are a few design commitments that this screen makes
visible:

* **No silent writes.** The operator is always shown the
  outcome. The system never creates a ticket in the background
  without telling the user.
* **Human accountability.** The "Approved by" row is non-empty
  on purpose. It is the trail back to the person who made the
  decision.
* **A trace id flows from the chat to the ticket.** The same
  request id that was generated at the start of the chat is
  the one tied to the ticket write. If a reviewer wants to
  retrace the full investigation — the planner steps, the
  citations, the draft edits, the approval — they can follow
  that single id.
* **An audit log is the system of record.** The note at the
  bottom points the user to the audit log. This is what makes
  the action reviewable later — important for any tool that
  is allowed to act on behalf of a human in an operational
  environment.

---

## What a layman should take away

If you had to explain this screen in one sentence, it would be:

> *"This is the confirmation that the ticket was created, who
> approved it, and how to find it again later."*

The green banner is the visual "yes". The three rows are the
trail. The audit note is the promise that the trail is permanent.
