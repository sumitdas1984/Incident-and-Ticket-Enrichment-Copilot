# `02-chat-with-incident.png` — what this screen tells you

This is the **second screen** in the demo flow. It is what the
chat looks like after the operator has posted the canonical
question — *"Investigate recurring high-severity alarms on Boiler
B-101 over the last 90 days…"* — and the copilot has finished
its first round of investigation.

If you are explaining this app to a layman, this screen is the
**"here is the answer"** screen. It shows three things working
together:

1. The **conversation** — the operator's question and the
   copilot's reply, in plain chat form.
2. The **structured incident** — a tidy, form-style summary of
   what the copilot found, with a severity badge and a list of
   related past tickets.
3. The **evidence breadcrumb** — a small recap of how much
   evidence the copilot used to answer.

---

## What you see on the screen, top to bottom

### 1. The user message card (YOU)

A blue-tinted card with the header **"YOU · 11:06:26"** and the
operator's full question:

> *"Investigate recurring high-severity alarms on Boiler B-101
> over the last 90 days. Identify likely contributing factors
> and retrieve the relevant troubleshooting procedure."*

This is the **"what the operator asked"** card. It is the left
half of a conversation turn — the input. The timestamp is there
so two operators chatting at the same time can keep their
turns straight.

The card mirrors what the operator typed into the chat input
field at the bottom of the previous screen. Nothing surprising
on this card — it is just the question, preserved verbatim.

### 2. The copilot message card (COPILOT)

A purple-tinted card with the header **"COPILOT · 11:06:26"** and
a row of four coloured pills:

| Pill | What it means in plain English |
|---|---|
| **INVESTIGATE RECURRING HIGH-SEVERITY ALARMS ON BOILER B-101 OVER THE LAST 90 DAYS** (blue) | The copilot has categorised the operator's question into a topic. It is the same intent the operator expressed, but reformulated into a single canonical label so the operator can see *"yes, the copilot understood me correctly."* |
| **RAG · LOW** (red) | The copilot's confidence in the document-based part of the answer is **low**. This is honesty the operator can act on — *"don't trust this answer without checking the citations."* |
| **📚 5 CITATIONS** (neutral) | The copilot referenced **5 document chunks** in the knowledge base to build the answer. |
| **🛠 3 STEPS** (neutral) | The copilot performed **3 tool steps** to gather the evidence (for example: look up the asset, fetch the alarms, search the knowledge base). |

#### The body of the reply

Below the pill row, the copilot has written:

* **Intent** — the same canonical reformulation as the pill
  above. Provided as text so the operator can read it as a
  sentence, not just a label.
* **Findings** — *"Returned 5 item(s)."* A short summary line.
* **Citations** — a list of the 5 chunks it used, each with its
  document name, section heading, and a numeric score. The score
  is how closely the document matched the question — higher is
  closer. The first citation (`compressor-surge-recovery`) is
  the top match at 0.13.

#### The "2 document chunks were dropped" note

A small line in the middle:

> *"Note: 2 document chunk(s) were dropped by the
> prompt-injection blocklist before retrieval."*

This is the copilot **telling the operator about its own safety
behaviour**. Some documents in the knowledge base contain
instructions that try to override the operator or the system
(a known attack pattern). The copilot detected them on the way
in and quietly dropped them, then kept going with the clean
ones. The operator can see this happened — nothing is hidden —
but the chat doesn't break.

#### The footer line

> *"Confidence: low | Trace steps: 4"*

Two pieces of context compressed into one line:

* **Confidence: low** — the same message as the red `RAG · LOW`
  pill, repeated in text form so it is visible even with colours
  off.
* **Trace steps: 4** — the copilot performed **4 steps** in
  total (the 3 evidence steps plus the final reasoning step
  that produced the answer).

### 3. The Structured Incident card (📋)

A separate card below the chat. This is the **"form-style
summary"** of what the copilot found. Where the chat card is a
free-form reply, this card is structured data — fields and
values, ready to be turned into a ticket.

| Field | What it means |
|---|---|
| **Title** | The headline of the incident: *"Investigate recurring high-severity alarms on Boiler B-101 over the last 90 days — 4. Root cause hunt."* It stitches the operator's question to the most relevant knowledge-base section. |
| **Severity** | A green pill marked **LOW**. The copilot's assessment of how urgent this is, based on the alarms it retrieved. Green = handled-once / informational tier. |
| **Likely cause** | A short text block quoting the most relevant troubleshooting step from the cited knowledge-base document. The text in quotes is the exact wording from the source. |
| **5. Returning** | A large section heading from the cited source document. The copilot has surfaced it because the section itself is the answer to "what should the operator do next?" |
| **TKT-1042, TKT-1108, TKT-1231, TKT-1349, TKT-1410** | A row of ticket-id pills. These are the **top 5 past tickets** that look similar to this incident. The copilot found them so the operator can see how similar problems were resolved before. |

The card is doing one job: **condensing the answer into a
ticket-shaped object**. The fields here are exactly the fields
a ticketing system would care about.

### 4. The Evidence card (🔎)

A small recap card at the bottom of the chat column:

* **📚 Citations: 5 referenced** — the same number as the pill
  above. Reinforces that the answer came from 5 source chunks.
* **🛠 MCP trace: 3 tool calls** — the same number as the
  pill above. Reinforces that the answer involved 3 tool steps.

This card exists so the operator doesn't lose track of the
evidence breadcrumb as the chat gets longer. The detailed
citations and the tool-call timeline are also surfaced as
first-class panels in the **right-hand workspace column** (see
the next screenshot, `03-workspace-panels.png`). The Evidence
card here is the inline-in-message version; the workspace
panels are the full versions.

### 5. The chat input (bottom)

The same `Ask the copilot…` input from the previous screen,
now with a red focus border around it. The operator can:

* Ask a follow-up question in the same conversation (this is a
  multi-turn chat — the copilot remembers prior turns).
* Type a brand-new question to start a different investigation.

The input is pinned at the bottom of the chat column so the
operator can keep asking without scrolling.

---

## Where this screen fits in the larger flow

This is the **"answer has been delivered"** screen. It is the
halfway point of the demo:

1. `01-empty-state.png` — operator opens the app.
2. `02-chat-with-incident.png` — **this screen.** The operator
   asked, the copilot answered, the structured incident and
   evidence are visible.
3. `03-workspace-panels.png` — the operator scrolls the right
   column to see the full evidence chain and the editable
   ticket draft.
4. `04-confirmation-modal.png` — the operator reviews the
   ticket one last time and clicks **Approve & create**.
5. `05-ticket-created.png` — the ticket is live in the system.

So if you are demoing to a layman, you can describe this screen
as **"the moment the copilot turns out a structured answer —
complete with citations, confidence, and a draft ticket shape".**

---

## What the confidence and dropped-chunk notes are really telling the operator

Two pieces of the screen are worth pausing on, because they make
the app's **honesty** visible:

* **RAG · LOW** — the copilot is saying *"I found 5 citations,
  but they are not a strong match. Treat the answer as a
  starting point, not a final answer."* This is the system's
  way of warning the operator before they act on the answer.
* **2 document chunks dropped** — the copilot is saying *"I
  noticed some documents were trying to manipulate me, so I
  ignored them. Here is the number, so you know."* The chat
  does not silently skip the dropped chunks; it tells the
  operator about them.

For a layman, the takeaway is: **the app is built to be
honest with the operator about what it knows and what it
doesn't, and to defend itself against bad instructions hidden
in the documents it reads.**

---

## What a layman should take away

If you had to explain this screen in one sentence, it would be:

> *"The copilot answered the question, told the operator how
> confident it was, and produced a structured incident summary
> with related past tickets — all in one chat turn."*

The coloured pills are the operator's at-a-glance dashboard.
The structured incident card is the ticket-to-be. The dropped-
chunk note is the safety receipt.
