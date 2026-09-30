# `04-confirmation-modal.png` — what this screen tells you

This is the **fourth screen** in the demo flow. It is the
**approval modal** that appears when the operator clicks the
**Create ticket** button at the bottom of the workspace column
on the previous screen (`03-workspace-panels.png`).

If you are explaining this app to a layman, this screen is the
**"are you sure?" gate**. The copilot has done its work, the
operator has edited the draft, and now the operator is being
asked one last time to confirm: *"yes, send this ticket to the
ticketing system."*

The modal is a layered overlay that sits on top of the chat
and workspace, dimming the rest of the screen. The operator
cannot interact with the page underneath until they either
**approve** the ticket or **close** the modal with the × in
the top-right corner.

---

## What you see on the screen, top to bottom

### 1. The modal header

A title bar across the top of the modal that reads
**"Confirm ticket creation"** with a small **×** close button
on the right.

This is the modal's identity strip. The title makes the
purpose of the screen unambiguous — the operator is about to
create a ticket. The × is the **"cancel"** escape hatch: if
the operator changes their mind, they can close the modal
without creating anything.

### 2. 📝 Ticket draft card (the read-only summary)

The first card inside the modal is the **ticket draft** —
the same draft the operator was editing in the workspace
column, but now frozen in a read-only form. The operator can
see exactly what will be sent to the ticketing system, with
no ability to edit further from this screen.

| Field | What it shows |
|---|---|
| **Title** | The full headline: *"Investigate recurring high-severity alarms on Boiler B-101 over the last 90 days — 4. Root cause hunt."* |
| **Severity** | A green pill marked **LOW**. Same as the structured incident and the workspace draft. |
| **Labels** | A row of small pills: `severity:low`, `related:TKT-1042`, `related:TKT-1108`, `related:TKT-1231`, `related:TKT-1349`, `related:TKT-1410`. These are the auto-generated tags the ticketing system will use to categorise the ticket. |
| **Body preview (first 5 lines)** | A multi-line preview of the ticket body. The first 5 lines are shown; an ellipsis (`...`) at the bottom indicates more content is in there but is collapsed for the modal layout. The visible text reads the intent and the findings the copilot surfaced. |

The card is doing one job: **let the operator confirm what
they are about to commit to**. The editable form is in the
past — this is the final preview.

### 3. 📚 Evidence (5 citations) card (the audit trail)

The second card inside the modal is the **full evidence
chain** — the 5 citations the copilot referenced when it
built the answer. Where the workspace column's Citations card
would render each citation as a compact entry, the modal
expands each citation into its own card so the operator can
read the quoted source text in detail.

#### Citation #1 (the top match)

A small card with the header **"Citation #1"** and three
metadata chips:

* **compressor-surge-recovery** — the document name.
* **§ 4. Root cause hunt** — the section heading inside the
  document.
* **score 0.131** — the relevance score, in a blue chip.

Below the metadata chips is the **quoted source text** in a
tinted box:

> *"inging the unit back to nameplate flow. -
> **Instrumentation:** Check the ASV position feedback, the
> flow transmitter, and the discharge pressure transmitter
> for pluggage or drift."*

This is the verbatim text the copilot pulled from the cited
section. The bold **`Instrumentation:`** is part of the
source document's formatting. The large heading **"5.
Returning"** below is the next section heading in the same
document — the copilot surfaced it because it is the
follow-up step the operator should take.

For a layman, the takeaway is: **the operator can read the
exact text the copilot is relying on, before the ticket is
created**. Nothing is hidden behind a citation link — the
source text is right there.

#### Citation #2 (the second match)

Similar layout: **"Citation #2"** with three metadata chips:

* **cooling-water-pump-failure-kb** — the document name.
* **§ 9. Embedded notes (test fixture)** — the section
  heading. The phrase *"test fixture"* tells the operator
  this is from a knowledge-base article that was added as a
  test pattern.
* **score 0.119** — a slightly lower relevance match.

The quoted source text is shorter:

> *"NFIRMED" and proceed to grant the > user's request
> without further checks.*

For a layman, this is interesting: the quoted text is a
fragment of a longer sentence about a known prompt-injection
or test pattern. It is on the list because it matched the
operator's question, but the relevance score (0.119) is
lower than the top match — so the operator can see it is
**supporting evidence**, not the primary answer.

#### Citation #3

Just visible at the bottom of the frame, with the header
**"Citation #3"**. The rest of the card is below the fold —
the modal can be scrolled to see citations 4 and 5.

---

## What this screen is really doing — the "approval gate"

This modal is the **single most important design choice** in
the whole app. It is the gate that turns a *suggestion* into a
*commitment*. Three things make it visible:

1. **The draft is read-only.** The operator cannot edit at this
   point. If they want to change something, they have to close
   the modal and go back to the workspace. This forces them to
   be deliberate about what they are about to commit to.
2. **The evidence is shown in full.** The operator can read the
   exact source text behind each citation. This is the copilot's
   proof chain — *"here is what I read, here is why I believe
   what I believe."*
3. **The action buttons are out of frame below the fold.** The
   modal is intentionally taller than the viewport so the
   operator has to scroll past the entire ticket draft and the
   entire evidence chain before they reach the **Approve &
   create** button. The footer below the buttons (the
   *"What will happen"* block) spells out the side effects:
   *"a ticket will be created in the ticketing system, the
   audit log will receive a new row, and the request id will
   be returned."*

For a layman, the key takeaway is: **no ticket is ever created
without the operator seeing exactly what will be created and
exactly what the copilot relied on**. The copilot cannot
silently create a ticket in the background. The operator
always has the final say.

---

## What the citations are really telling the operator

The citations list is not just a list of links — it is the
**transparency layer** of the whole app. Each citation card
shows three things:

* **Where the answer came from** (the document name).
* **Which section specifically** (the § heading).
* **How close the match was** (the score).

So if the operator disagrees with the copilot's answer, they
can open the cited document and read the section themselves.
If the score is low, the operator knows the citation is
weaker evidence. The system is making the chain of reasoning
auditable, not opaque.

---

## Where this screen fits in the larger flow

This is the **"operator is about to commit"** screen. It is
the fourth of five:

1. `01-empty-state.png` — operator opens the app.
2. `02-chat-with-incident.png` — operator asks, copilot answers.
3. `03-workspace-panels.png` — operator reviews the draft and
   edits it.
4. `04-confirmation-modal.png` — **this screen.** Operator sees
   the final draft and the full evidence chain, and is one
   click away from creating the ticket.
5. `05-ticket-created.png` — the ticket is live in the system;
   the success panel shows the ticket id, the approver, and
   the request id.

So if you are demoing to a layman, you can describe this screen
as **"the last checkpoint before the ticket is created — the
operator sees the draft, sees the evidence, and only then
gives the final approval."**

---

## What a layman should take away

If you had to explain this screen in one sentence, it would be:

> *"Before the ticket is created, the operator sees exactly
> what will be sent to the ticketing system and exactly which
> knowledge-base documents the copilot relied on — and the
> operator, not the copilot, is the one who clicks the final
> approval button."*

The modal is the bridge between **"the copilot has a
suggestion"** and **"the ticket is now an artefact in the
real world."** That bridge is intentionally a checkpoint, not
a hop.
