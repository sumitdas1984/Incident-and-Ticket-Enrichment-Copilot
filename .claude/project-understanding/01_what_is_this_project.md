# 01 — What this project is

> **Read this first.** If you can answer "what is this project"
> in 30 seconds, the rest of the conversation has somewhere to
> go. If you can't, nothing else will land.

---

## The one-sentence answer

A chat app that helps an industrial service engineer turn a
high-severity alarm into an evidence-backed incident ticket,
combining live data from an alarm system with operating
procedure documents — and never writes a ticket without the
engineer's explicit approval.

---

## The problem (in plain words)

When a critical alarm fires on a piece of industrial equipment
("Boiler B-101 is overheating"), the on-call engineer today
spends 20–30 minutes gathering the context they need to write a
good incident ticket:

- Which asset is this? What's its history?
- Have we seen this alarm before? On what other equipment?
- What's the relevant operating procedure? What does it say
  to check first?
- What's a recommended next action?

Today, that means opening four or five browser tabs, copy-pasting
between the alarm system and the procedure PDFs, and writing the
ticket by hand. It's slow, error-prone, and the evidence
("why did I write *this* action?") usually disappears.

---

## What the copilot does

The engineer types one question into a chat box, e.g.:

> *"Investigate recurring high-severity alarms for Boiler B-101
> over the last 90 days."*

The copilot does the four manual steps automatically:

1. **Looks up the asset and its alarm history** through the
   alarm-management API (wrapped behind MCP — never directly).
2. **Searches the operating-procedure documents** for the
   most relevant troubleshooting guides.
3. **Drafts a structured incident** — title, severity, likely
   cause, recommended actions, similar past tickets.
4. **Pre-fills a ticket draft** the engineer can edit.

Then the engineer reviews, edits, and clicks **Approve** — only
then does the ticket get created. This last bit is non-negotiable
per the brief.

---

## Who uses it

A service engineer or plant operator who:

- Already knows what an "alarm" and an "asset" are.
- Doesn't need an AI to "explain" the basics — they need the AI
  to do the gathering, not the thinking.
- Is accountable for the ticket they create, so the AI must
  show its work and let them edit before anything is written.

---

## What "good" looks like in the demo

A reviewer watches a 3-5 minute walkthrough where:

1. The engineer types the canonical question.
2. The copilot returns an answer with **citations** (which
   procedure docs it used) and an **execution trace** (which
   alarm-system calls it made).
3. The engineer edits the ticket draft, clicks Approve, and a
   ticket ID appears.
4. The whole flow works against in-container simulators — no
   real industrial system, no API keys.

That's the assignment. Everything else is in service of those
five things being true.

---

## If asked in the interview

**Q: "What does your project do?"**

> It's an enterprise copilot that turns an alarm-system question
> into an evidence-backed incident ticket. The alarm data comes
> in via MCP, the procedure docs come in via RAG, and every
> ticket is gated by explicit operator approval.

**Q: "Who is it for?"**

> Industrial service engineers who today spend 20-30 minutes
> gathering context across the alarm system and procedure docs.
> The copilot does the gathering; the engineer still owns the
> decision.

**Q: "What's the headline metric?"**

> Time from alarm to actionable ticket draft drops from
> 20-30 minutes to under a minute, with every recommended action
> backed by a citation the engineer can read.

---

## Open questions for next time

- *What's the canonical question?* — Doc 04 walks through it
  step-by-step. Skim it once you've read docs 02 and 03.
- *Why is "approval before write" so important?* — Doc 05
  covers the hard constraint and the audit trail behind it.
- *Why two pillars (MCP + RAG) and not one?* — Doc 02.
