# Project understanding — index

> **Why this folder exists.** You're preparing for an ABB round-1
> interview where you'll be asked to explain the
> Incident-and-Ticket-Enrichment-Copilot project and justify its
> design. These docs are your **study guide** — top-down, one
> concept per file, plain language first.

---

## How to read this

1. **One concept per file.** Each doc answers exactly one
   question. You can stop after any one and still have a complete
   answer to that question.
2. **Read top to bottom.** The order is intentional. Later docs
   assume the earlier ones.
3. **Bottom of every doc has two things:**
   - **"If asked in the interview"** — 2-3 likely questions with
     a 2-sentence answer.
   - **"Open questions for next time"** — gaps to fill. These
     become our next discussion slice.
4. **No code dumps here.** I'll name files and functions so you
   can find them in the IDE. Big snippets belong in the source
   itself, not in your study notes.
5. **Source of truth is `docs/`.** This folder rephrases
   `docs/architecture.md`, `docs/design-decisions.md`,
   `docs/rag-design.md`, `docs/mcp-tool-catalog.md`, and the
   `Assignment_Use_Case.md` + `Submission_and_Evaluation_Guidelines.md`
   briefs. When the project changes, those docs change first;
   this folder catches up.

---

## Reading order

| # | File | What it answers | Read time |
|---|---|---|---|
| **00** | `00_INDEX.md` | (this file) | 3 min |
| **01** | `01_what_is_this_project.md` | What is this project, in plain words? | 5 min |
| **02** | `02_the_two_pillars_mcp_and_rag.md` | What is MCP? What is RAG? Why both? | 8 min |
| **03** | `03_high_level_architecture.md` | What are the 12 layers and where do they live? | 8 min |
| **04** | `04_one_request_walkthrough.md` | What happens when the operator types a question? | 10 min |
| **05** | `05_hard_constraints_and_enforcement.md` | The 8 hard constraints, mapped to code that enforces them | 10 min |
| **06** | `06_tech_stack_rationale.md` | Why these libraries and not others? | 8 min |
| **07** | `07_testing_strategy.md` | How do 471 tests fit together? | 7 min |
| **08** | `08_design_decisions_cheatsheet.md` | The 15 decisions in one line each | 8 min |
| **09** | `09_interview_qa_flashcards.md` | Common questions + crisp answers | 8 min |
| **10** | `10_from_demo_to_production.md` | What's hermetic in the demo vs what's wired, and how to talk about it | 10 min |

**Total: ~85 minutes** to read end-to-end. Most people do it in
two or three sittings.

---

## How to use this in the interview

When the interviewer asks "tell me about the project", the
opening arc you want is:

1. **One sentence on the problem.** (Doc 01)
2. **The two pillars — MCP and RAG.** (Doc 02)
3. **The 12 layers as a vocabulary.** (Doc 03)
4. **Walk through one request.** (Doc 04)

That's the first 5 minutes of any good answer. From there, the
interviewer's follow-ups will naturally pull you into docs
05–09.

---

## Status

- [x] 00 — Index
- [x] 01 — What this project is
- [x] 02 — The two pillars
- [x] 03 — High-level architecture
- [x] 04 — One request, end-to-end
- [x] 05 — Hard constraints and enforcement
- [x] 06 — Tech stack rationale
- [x] 07 — Testing strategy
- [x] 08 — Design decisions cheatsheet
- [x] 09 — Interview Q&A
- [x] 10 — From demo to production
