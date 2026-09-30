# `03-workspace-panels.png` — what this screen tells you

This is the **third screen** in the demo flow. It is a close-up
of the **right-hand workspace column** after the operator has
asked the canonical question and the copilot has finished its
first round of investigation.

If you are explaining this app to a layman, this screen is the
**"the structured work area"** screen. Where the chat column
is a back-and-forth conversation, the workspace is the form-style
working surface where the copilot's findings are turned into a
ticket-to-be. The two columns update together, but this column
is where the **actionable output** lives.

This is the same moment as `02-chat-with-incident.png` — the
chat column is just scrolled off to the left so the operator
can focus on the workspace.

---

## What you see on the screen, top to bottom

### 1. 🛠 WORKSPACE (section header)

The label at the top of the right column. Same identity strip
as on the empty-state screen, but the workspace is no longer
empty — it now holds the structured incident, the editable
draft, and the start of the citations panel.

### 2. 📋 Incident summary card

A card titled **"Incident summary"** showing the structured
incident that the copilot assembled. It is the **canonical
view** of the incident — the same data that appeared in the
chat column's "Structured Incident" card on `02-chat-with-incident.png`,
but lifted into the workspace so the operator can refer to it
without scrolling the chat.

| Field | What it means |
|---|---|
| **Title** | The headline of the incident: *"Investigate recurring high-severity alarms on Boiler B-101 over the last 90 days — 4. Root cause hunt."* The dash joins the original question to the most relevant knowledge-base section. |
| **Severity** | A green pill marked **LOW**. The copilot's assessment of how urgent this is. Green = informational tier. |
| **Likely cause** | A short text block quoting the most relevant troubleshooting step from the cited knowledge-base document. The quoted text is the exact wording from the source. |
| **5. Returning** | A large section heading from the cited source document. The copilot surfaced it because the section itself is the answer to *"what should the operator do next?"* |
| **TKT-1042, TKT-1108, TKT-1231, TKT-1349, TKT-1410** | A row of ticket-id pills — the **top 5 past tickets** that look similar to this incident. The operator can spot-check them to see how similar problems were resolved before. |

The card is doing one job: **give the operator a stable,
form-style view of the incident** while the conversation
keeps moving in the chat column.

### 3. ✏️ Editable ticket draft card

The next card is the **"operator co-author"** stage. The copilot
has pre-filled a draft ticket from the structured incident, and
the operator can adjust any field before approving.

The card starts with a small instruction line:

> *"Pre-filled from the incident. Edit the fields, then click
> **Create ticket** below to open the approval modal."*

This is the operator's cue: **the draft is a starting point,
not a final answer**. The operator can tweak the wording, the
severity, the assignee, and the labels as needed.

#### The form fields, top to bottom

| Field | What it shows | What the operator can do |
|---|---|---|
| **Title** | Already pre-filled with the incident title. The text is truncated in the screenshot because the field is narrow, but the full title is in there. | Edit the wording. |
| **Severity** | A dropdown pre-selected to **"low"** (matching the green pill in the Incident summary card). The dropdown offers the four severity tiers: low, medium, high, critical. | Bump the severity up or down before approving. |
| **Body** | A multi-line text box pre-filled with the intent and findings from the chat. The text reads: *"Intent: Investigate recurring high-severity alarms on Boiler B-101 over the last 90 days. Findings: ..."* followed by the citations summary. | Edit, expand, or rewrite the body. |
| **Assignee** | An empty optional field with the placeholder *"(optional)"*. | Type the name of the person who should own the ticket. |
| **Labels (comma-separated)** | A text field pre-filled with the auto-generated labels: `severity:low, related:TKT-1042, related:TKT-1108, related:TKT-1231, related:TKT-1349, related:TKT-...` (the rest is truncated). | Add or remove labels. Each label is a tag the ticketing system will use to categorise the ticket. |

The pre-filled body and labels are doing a real job: **they
encode the copilot's reasoning into a ticket-shaped object
without forcing the operator to retype anything**. The severity
label pulls from the structured incident, the related-TKT
labels pull from the similar-tickets field, and the body
combines the intent and findings so the assignee has the
context without needing to scroll the chat.

### 4. 📚 Citations (5) card (just visible at the bottom)

The next card is starting to appear at the bottom of the frame —
the **"Citations"** panel, with the count "(5)" in the header
matching the 5 citations the copilot referenced.

This card is the **full version** of the citations list. On
`02-chat-with-incident.png`, the chat column showed the citations
as a compact inline list under the copilot reply. Here in the
workspace, each citation is rendered as its own card with
metadata — document name, section heading, page number, and
relevance score. The operator can read each one in detail
without leaving the workspace.

The MCP trace timeline (the vertical list of tool calls the
copilot made) would sit just below the citations, but it is
off-screen below the fold in this screenshot.

---

## Why this screen matters for the demo flow

This is the **"before the approval gate"** screen. Three things
are happening at once:

1. **The operator can see the incident at a glance** — the
   Incident summary card is the canonical view.
2. **The operator can co-author the ticket** — the Editable draft
   card is the form the operator edits.
3. **The operator can audit the evidence** — the Citations card
   (and the MCP trace below it) is the proof chain.

For a layman, the important takeaway is the **separation of
"review" and "act"**. The chat column is the *review* surface
(where the operator reads the copilot's reasoning). The
workspace column is the *act* surface (where the operator
shapes the next real-world action — the ticket). The two
columns talk to each other but they keep these two concerns
apart.

---

## What the editable draft is really telling the operator

The Editable ticket draft card is a small but important design
commitment. It is the system's way of saying:

* **The copilot's draft is a suggestion, not a final decision.**
  The operator is still the human in the loop.
* **The human's edits are preserved.** Whatever the operator
  types into the form is what eventually gets sent to the
  ticketing system.
* **The pre-fill is meaningful, not decorative.** The labels
  (`severity:low`, `related:TKT-…`) are the same labels the
  ticketing system would normally require the operator to add
  by hand.

So the form is the bridge between the **automated
investigation** and the **human decision** — and the operator
crosses the bridge only when they click **Create ticket** at
the bottom of the workspace column.

---

## Where this screen fits in the larger flow

This is the **"operator is reviewing the draft"** screen. It is
the third of five:

1. `01-empty-state.png` — operator opens the app.
2. `02-chat-with-incident.png` — operator asks, copilot answers.
3. `03-workspace-panels.png` — **this screen.** The operator
   focuses on the workspace, reads the incident summary, edits
   the draft, and (out of frame below) sees the citations and
   the tool-trace timeline.
4. `04-confirmation-modal.png` — operator clicks **Create
   ticket** and reviews the final approval modal.
5. `05-ticket-created.png` — ticket is live in the system.

So if you are demoing to a layman, you can describe this screen
as **"the moment the operator takes ownership of the draft —
edits it, audits the evidence, and gets ready to create the
ticket."**

---

## What a layman should take away

If you had to explain this screen in one sentence, it would be:

> *"The copilot has filled out a draft ticket from the
> investigation, and the operator can edit any field before
> giving final approval."*

The two cards in this screenshot are the two halves of the
handover: the **Incident summary** is what the copilot
believes, and the **Editable ticket draft** is what the
operator is about to commit to the world.
