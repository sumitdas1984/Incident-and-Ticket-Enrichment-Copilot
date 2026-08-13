# `01-empty-state.png` — what this screen tells you

This is the **first screen** the operator sees when they open the
app. Nothing has been asked yet. The chat is empty, the workspace
on the right is empty, and the sidebar on the left is offering
some helpful starter prompts.

If you are explaining this app to a layman, this screen is the
**"welcome / blank canvas"** screen. It is the moment before any
work has happened — the operator is being invited to start a
conversation.

---

## The overall layout — three columns

The screen is divided into three vertical columns, left to right:

1. **Left rail (sidebar)** — a fixed narrow column with the app
   brand and suggested starter prompts.
2. **Middle column (chat)** — the conversation area where the
   operator types questions and the copilot replies.
3. **Right column (workspace)** — a separate area where the
   structured incident, evidence, and ticket draft will appear
   once the operator has asked a question.

The reason for two columns instead of one is **separation of
concerns**: the chat is a back-and-forth conversation, while the
workspace is a structured working area that grows as the
investigation progresses. The chat and the workspace update
together, but they have different purposes.

---

## Left rail — top to bottom

### 1. 🚨 COPILOT (brand block)

A small heading with a siren icon and the description
*"Industrial incident + RAG copilot."*

This is the app's identity strip. It tells the operator what
kind of tool this is — an assistant for industrial incidents
backed by retrieval-augmented generation (a search-over-documents
technique). No action needed here.

### 2. 💡 TRY ASKING (three suggested prompt cards)

Three clickable question cards. Each one is a realistic
example of what the operator might type — they cover the three
common entry points:

* **Investigate over a time window** — *"Investigate recurring
  high-severity alarms on Boiler B-101 over the last 90 days."*
  This is the canonical demo scenario. The operator hands the
  copilot a specific asset (Boiler B-101), a time window
  (90 days), and a symptom (recurring high-severity alarms).
* **Investigate a current alarm** — *"Prepare an incident for
  the highest-priority active alarm in EastRefinery."* The
  operator hands the copilot a site (EastRefinery) and asks for
  the top live alert.
* **Ask an open-ended diagnostic question** — *"We're seeing
  intermittent high-temperature spikes on the cooling-water
  pump. What could be causing this?"* The operator hands the
  copilot a symptom and asks for likely causes.

For a layman, the important point is: **these cards are not
just decoration**. Clicking any one of them is the same as
typing the question and pressing send. They are a shortcut for
people who don't know what to ask yet.

---

## Middle column — the chat area

### 4. 💬 Start a conversation (empty state card)

A dashed-bordered card with a welcome message:

> *"Ask the copilot about an alarm, an asset, or an operating
> procedure. The workspace on the right will populate with the
> evidence chain."*

This is the **"what do I do here?"** instruction. It tells the
operator:

* What kinds of questions are valid (alarms, assets, operating
  procedures).
* That the workspace on the right **is not broken** — it is
  intentionally empty until the operator asks something.

The phrase *"evidence chain"* is doing a lot of work: it is
telling the operator that answers will come with proof, not just
free-form text.

### 5. Ask the copilot… (the chat input)

A text box at the bottom of the middle column with the
placeholder *"Ask the copilot…"* and a small up-arrow send
button on the right.

This is the **primary input**. The operator types a free-form
question here and presses the arrow (or hits Enter) to send. The
app then fills the middle column with the copilot's reply and
populates the right-hand workspace with the evidence.

---

## Right column — the workspace

### 6. 🛠 WORKSPACE (section header)

The label at the top of the right column. It is the workspace's
identity strip — the same idea as the COPILOT header on the
left, just for the structured-work area.

### 7. 💬 Workspace empty (empty state card)

A dashed-bordered card with the message:

> *"Ask the copilot a question to see the structured incident,
> evidence chain, and editable ticket draft here."*

This is the **"what will appear here?"** instruction. It tells
the operator that three things will materialise in this column
after the first question:

* The **structured incident** — a tidy summary of what the
  investigation found.
* The **evidence chain** — the documents the copilot read to
  arrive at the answer.
* The **editable ticket draft** — a pre-filled form the operator
  can adjust before creating a ticket.

### 8. Create ticket (disabled button)

At the bottom of the right column, a button labelled **"Create
ticket"** is visible but **greyed out** — it cannot be clicked
yet.

This is a deliberate signal. The button is **disabled on
purpose** because the workspace is empty: there is no incident
yet, so there is nothing to ticket. Once the operator asks a
question and the workspace populates, this button will turn
solid and become clickable.

For a layman, the takeaway is: **the app refuses to let you
create a ticket out of nothing**. A ticket always starts life
from an investigation, not a blank form.

---

## What this screen is telling the operator, in one sentence

> *"Nothing has happened yet. Pick a suggested prompt or type
> your own question, and the workspace on the right will fill
> with the structured incident, the evidence, and a draft
> ticket."*

The empty states, the disabled button, and the suggested prompts
all serve the same purpose: **make the next step obvious without
forcing the operator to read a manual**. The app is waiting for
input, and the input is going to come from the chat box at the
bottom of the middle column.
