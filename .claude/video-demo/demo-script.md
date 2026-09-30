# Demo video script — Incident and Ticket Enrichment Copilot

**Target length:** ~3:40 (cut from 5:40 — voice-overs only).
**Audience:** technical recruiter / engineering interviewer (ABB round-1).
**Tone:** confident, calm, demo-focused. Speak to the camera as if
walking the reviewer through the live product.

> **Source material.** Every screen-specific line in this script is
> drawn from the screen walkthroughs under
> `.claude/app-functional-understanding/`. Use those files as the
> in-depth reference if a reviewer asks a follow-up question after
> the video.

---

## How to use this script

* Each section has a **time budget**. The first column on the
  left is the elapsed time; the second is the section length.
* The blue callouts are **stage directions** — what is on the
  screen while you talk.
* The black paragraphs are the **voice-over** — what you say
  verbatim.

---

## Section 0 — Title card (0:00 – 0:08)

**Time:** 0:00 → 0:08 (8 seconds).

**On screen:** A simple title slide — *"Incident and Ticket
Enrichment Copilot — Round 1 demo"* — with the repo URL
`github.com/sumitdas1984/Incident-and-Ticket-Enrichment-Copilot`
subtitled below.

**Voice-over:**

> *"This is the Incident and Ticket Enrichment Copilot — round-1 demo."*

---

## Section 1 — High-level intro (0:08 – 0:35)

**Time:** 0:08 → 0:35 (27 seconds).

**On screen:** The high-level block diagram at
`docs/screenshots/high-level-architecture.svg`. Open it in
any browser (or convert to PNG via your video editor's file
import — SVG is widely supported). The three columns to point
at are:

1. **Operator** (the human in the chair).
2. **Copilot** (the GUI + backend orchestrator) — with the
   two pillars MCP and RAG inside.
3. **Knowledge** (the alarm system on the top, the document
   store on the bottom).

**Voice-over:**

> *"Imagine an engineer gets paged about a recurring alarm.
> Today they dig through the alarm system, read the procedure,
> draft a ticket, and copy evidence between windows. This
> copilot collapses that workflow into a single chat.*
>
> *Under the hood, two pillars. The first is **MCP** — the only
> way the copilot can talk to the alarm system. The second is
> **RAG** — retrieval-augmented generation — which grounds every
> answer in the operating procedures. The two are combined in
> every answer: no free-form guessing, citations and a trace on
> every response."*

---

## Section 2 — Screen 1: empty state (0:35 – 0:55)

**Time:** 0:35 → 0:55 (20 seconds).

**On screen:** The browser at `http://localhost:5173`, with
`docs/screenshots/01-empty-state.png` as the talking reference.

**Voice-over:**

> *"Three columns. A sidebar with three example prompts, an
> empty chat in the middle, and a workspace on the right. Notice
> the **Create ticket** button at the bottom is greyed out — the
> system refuses to create a ticket out of nothing. A ticket
> always starts from an investigation."*

---

## Section 3 — Screen 2: chat with incident (0:55 – 1:40)

**Time:** 0:55 → 1:40 (45 seconds).

**On screen:** First, click the top suggested prompt —
*"Investigate recurring high-severity alarms on Boiler B-101
over the last 90 days."* Then wait for the copilot reply. The
final state matches `docs/screenshots/02-chat-with-incident.png`.

**Voice-over, while the reply is loading:**

> *"The operator asks the canonical question — recurring
> high-severity alarms on a specific asset over a specific
> window."*

**Voice-over, after the reply lands:**

> *"The reply comes back with four pills. The first is the
> copilot's reformulated intent. The second is **RAG confidence**
> — red, LOW, because the top match scored only 0.13. The third
> shows **5 citations**. The fourth shows **3 tool steps**.*
>
> *Notice the inline note: '2 document chunks were dropped by
> the prompt-injection blocklist.' That's the safety layer
> quietly dropping documents that try to manipulate the system —
> and telling the operator about it.*
>
> *Below the body, the Structured Incident card turns the answer
> into a ticket-shaped object — title, severity, likely cause,
> and a row of similar-ticket pills."*
>
> *The chat column also shows a small
> Evidence card — 5 citations, 3 tool calls — as an inline
> reminder of the evidence breadcrumb.*

---

## Section 4 — Screen 3: workspace panels (1:40 – 2:15)

**Time:** 1:40 → 2:15 (35 seconds).

**On screen:** Scroll right to focus the workspace column, or
just narrate over the right-hand side of the page. The final
state matches `docs/screenshots/03-workspace-panels.png`.

**Voice-over:**

> *"The workspace column is the operator's working area. Two
> cards: the **Incident summary** — the canonical view of the
> structured incident — and the **Editable ticket draft**.*
>
> *The fields are pre-filled from the incident: title, severity,
> body, and auto-generated labels like `severity:low` and
> `related:TKT-…` for each similar ticket. The operator can edit
> any field before approving. The pre-fill is a starting point,
> not a final answer."*
>
> *Below the draft, the Citations panel
> renders each of the 5 sources as its own card with metadata
> chips — document name, section heading, relevance score. And
> below that, the MCP trace timeline lists the 3 tool calls
> the copilot made, with timing and outcome. Both are out of
> frame in this screenshot, but they're one scroll away.*

---

## Section 5 — Screen 4: confirmation modal (2:15 – 2:55)

**Time:** 2:15 → 2:55 (40 seconds).

**On screen:** Click **Create ticket** at the bottom of the
workspace column. The modal slides over. Final state matches
`docs/screenshots/04-confirmation-modal.png`.

**Voice-over:**

> *"Clicking Create ticket opens the approval modal — the single
> most important design choice in the app. Nothing is written
> without the operator clicking **Approve** here.*
>
> *Two cards. The read-only **Ticket draft** — exactly what will
> be sent. And the **Evidence** — the 5 citations, each expanded
> with the document name, the section heading, the score, and the
> verbatim quoted source text. The operator can read the exact
> text the copilot is relying on.*
>
> *The Approve button is below the fold — the operator has to
> scroll past everything before they can click it. That's
> intentional."*

**Action:** Click **Approve & create** (out of frame below).

---

## Section 6 — Screen 5: ticket created (2:55 – 3:15)

**Time:** 2:55 → 3:15 (20 seconds).

**On screen:** The approval modal closes, and the success
panel appears in its place. Final state matches
`docs/screenshots/05-ticket-created.png`.

**Voice-over:**

> *"A green banner confirms the ticket is created. Three rows:
> the **ticket id**, the **approved by**, and the **request id**
> — the trace that ties this exact submit click back to the log
> entries. The note at the bottom points to the audit log. Once
> a row is appended, it cannot be quietly removed."*

---

## Section 7 — Wrap-up (3:15 – 3:40)

**Time:** 3:15 → 3:40 (25 seconds).

**On screen:** A return to the title card, or a quick cut to
the repo URL.

**Voice-over:**

> *"That's the full flow: investigate, review, edit, approve,
> create — in five screens. The hard constraints from the brief
> are baked in: MCP-only access to the alarm system, retrieval-
> augmented answers with citations and trace, explicit human
> approval for every write, and prompt-injection defence on the
> document side. The code is on GitHub. Happy to walk through any
> piece in detail on a call."*

---

## Quick reference — what's on each screen

| Time | Screen | File |
|---|---|---|
| 0:35 – 0:55 | Empty state, three columns, suggested prompts, disabled Create button. | `docs/screenshots/01-empty-state.png` |
| 0:55 – 1:40 | Operator's question, copilot's reply with 4 pills, citations list, structured incident card. | `docs/screenshots/02-chat-with-incident.png` |
| 1:40 – 2:15 | Right column: incident summary, editable draft form, citations / trace below the fold. | `docs/screenshots/03-workspace-panels.png` |
| 2:15 – 2:55 | Modal: read-only ticket draft + full evidence with quoted source text. | `docs/screenshots/04-confirmation-modal.png` |
| 2:55 – 3:15 | Green success banner: ticket id, approved by, request id, audit log note. | `docs/screenshots/05-ticket-created.png` |

---

## Quick reference — the eight hard constraints (mention if asked)

1. **MCP-only alarm path.** The orchestrator never calls the
   alarm API directly — it goes through the MCP server.
2. **MCP + RAG in one workflow.** Every answer is grounded in
   retrieved documents *and* corroborated by alarm-system calls.
3. **Explicit ticket approval.** No ticket is created without
   the operator clicking the final Approve button.
4. **Citations + trace on every answer.** The four coloured
   pills and the citation list are the visible side of this.
5. **No hard-coded secrets.** All configuration via
   `.env.example`; the CI server fails any `os.getenv` outside
   the config module.
6. **Prompt-injection defence.** The retrieval service drops
   documents that match the blocklist before they reach the
   prompt — and tells the operator it did so.
7. **Synthetic data only.** The alarm API and the ticketing
   API are inside the docker stack; no real customer data.
8. **General planner.** The intent extractor is an NL→slots
   function, not a fixed script — the canonical question is
   preserved verbatim, not pattern-matched.

---

## Recording tips

* **Pacing.** The voice-over sections are written at roughly
  170 words per minute. If you read at that pace, the times
  will land comfortably. Read slower and you'll fill the
  budgets; read faster and you'll have slack for emphasis.
* **Screen recording.** Capture the browser at 1080p, full
  window, with the cursor visible. Move the cursor slowly
  to the click target before clicking — viewers follow the
  cursor.
* **No music.** The brief is for an engineering audience.
  Let the voice and the screen do the work.
* **Pause for the copilot reply.** After clicking the
  suggested prompt, give the screen 5–8 seconds to show the
  loading state. The reply takes about a second in real life.
* **Don't apologise for the test-fixture citation.** The
  mid-rank citation has the phrase *"test fixture"* in its
  section heading. That is a documentation pattern, not a
  bug. If a reviewer asks, the answer is *"the corpus
  includes some annotated knowledge-base entries that mark
  themselves as test fixtures, so the dataset can be audited
  for determinism."*
