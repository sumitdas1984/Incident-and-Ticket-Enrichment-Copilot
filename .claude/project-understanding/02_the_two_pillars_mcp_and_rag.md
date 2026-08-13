# 02 — The two pillars: MCP and RAG

> **What this answers.** When someone says "this project uses
> MCP and RAG," you should be able to define each, explain why
> they're used together, and point at the file each one lives
> in.

---

## Mental model in 30 seconds

Imagine the copilot is a human expert answering the engineer's
question. To do that well, the expert needs two completely
different kinds of information:

1. **Live system data** — what's happening *right now* in the
   alarm system. This is structured, queried, and changes every
   minute.
2. **Reference knowledge** — what's been *written down* in
   operating procedures, troubleshooting guides, and past
   resolution notes. This is unstructured prose that mostly
   stays the same.

One needs an **API**. The other needs **document search**.
They are different problems with different solutions. That's why
this project has two pillars.

- **MCP** (Model Context Protocol) is how the copilot talks to
  the alarm API.
- **RAG** (Retrieval-Augmented Generation) is how the copilot
  pulls relevant procedure docs into its context.

---

## Pillar 1 — MCP

**MCP** is an open protocol, originally from Anthropic, that
defines how an LLM-based agent calls external tools in a
structured way. Think of it as a "USB-C port for AI tools" —
any client that speaks MCP can call any server that speaks MCP,
without either side knowing about the other.

In this project, MCP is the **only** way the copilot reaches the
alarm system. The orchestrator (the copilot's brain) does not
make raw HTTP calls to the alarm API. It calls MCP tools. The
MCP server then translates those tool calls into HTTP requests
against the alarm API.

**Why this matters:**

1. **The alarm-system team can swap implementations** (their
   real REST API, a gRPC backend, a vendor SDK) without
   touching the copilot — only the MCP server changes.
2. **The copilot team can swap LLMs or planners** without
   touching the alarm-system integration — only the MCP client
   changes.
3. **Every tool call is structured, typed, and auditable** —
   the orchestrator gets a JSON response with a known schema,
   not a free-form string.
4. **It's the brief's hard constraint #1**: the orchestrator
   *must* call the alarm API exclusively through MCP. A direct
   `httpx.get(...)` to the alarm API in the orchestrator is a
   red flag in code review.

**Where it lives in this repo:**

- **MCP client:** `apps/backend/orchestrator/mcp_client.py`
- **MCP server (alarm-management):** `mcp-servers/alarm-management/`
- **MCP server (ticketing):** `mcp-servers/ticketing/`
- **Tool catalog:** `docs/mcp-tool-catalog.md`

**Tool inventory (alarm-management):** `search_assets`,
`get_alarm`, `summarize_alarms`, `recommend_actions`,
`search_similar_tickets`. Five tools, one alarm system.

---

## Pillar 2 — RAG

**RAG** (Retrieval-Augmented Generation) is the pattern where,
before you ask the LLM to answer a question, you first
**search** a document collection for the most relevant
passages, and then you put those passages into the LLM's
context window along with the question.

In this project, RAG is how the copilot grounds its answers in
your operating procedures. Without RAG, the copilot would either
hallucinate ("here's what a tube leak usually looks like") or
go silent ("I don't know — there's nothing in my training data
about your specific plant"). With RAG, the copilot pulls the
real "Tube Leak Response" procedure from `rag/documents/` and
cites it.

**The RAG pipeline in three steps:**

1. **Ingest** (one-time, offline): Read each markdown document
   → split into chunks → embed each chunk (turn text into a
   numeric vector) → save the vectors to an index file.
   Output: `var/index/v1.pkl`.
2. **Retrieve** (per-request, online): Take the operator's
   question → embed it the same way → find the top-N chunks
   with the closest vectors → run those chunks through a
   prompt-injection filter → return the survivors as citations.
3. **Generate** (per-request, online): Stick the question, the
   retrieved chunks, and the alarm-system data into a prompt →
   ask the LLM to write the answer in the required shape.

**Why it matters here:**

1. **Citations are auditable.** Every claim in the answer is
   tied to a specific document + section + page, with a score.
2. **Prompt-injection defence lives here.** Before retrieved
   chunks reach the LLM, they're passed through a blocklist
   that drops anything matching known injection patterns
   ("ignore previous instructions", "you are now..."). Two
   documents in the corpus deliberately embed such patterns so
   the defence is exercised end-to-end.
3. **Low-confidence is explicit.** If the top match scores
   below a threshold, the answer carries a `RAG · LOW`
   confidence pill rather than a confident (wrong) answer.

**Where it lives in this repo:**

- **Corpus:** `rag/documents/` (six markdown files, five source
  types)
- **Ingestion:** `rag/ingestion/` (loader → chunker → embedder
  → persisted index)
- **Retrieval service:** `rag/retrieval/` (the per-request
  search + citation formatter + injection defence)
- **Design doc:** `docs/rag-design.md`

---

## Why both, together

The two pillars solve different problems and are **complementary,
not redundant**:

| Question | Pillar that answers it | Why |
|---|---|---|
| "What alarms fired on Boiler B-101 yesterday?" | **MCP** | It's structured, real-time data. |
| "What's the standard response for a tube leak?" | **RAG** | It's written-down knowledge. |
| "Has this happened before? What did we do?" | **Both** | Similar past tickets (MCP) + past resolution notes (RAG). |
| "What should I do *right now*?" | **Both** | Live alarm state (MCP) + procedure (RAG). |

Hard constraint #2 from the brief says: *"MCP and RAG must
participate in the same end-to-end business workflow. A
disconnected RAG demo or a disconnected MCP demo is grounds
for rejection."*

So the answer is not "we have MCP" or "we have RAG" — it's
"every answer the copilot produces touches both." That's why
the canonical request lifecycle (Doc 04) interleaves them.

---

## The one mental picture to keep

```
Operator question
       │
       ▼
 ┌─────────────┐         ┌──────────────────┐
 │  MCP layer  │ ◀──────▶│   RAG layer      │
 │ (live data) │         │ (procedure docs) │
 └─────────────┘         └──────────────────┘
       │                          │
       └──────────┬───────────────┘
                  ▼
           Orchestrator
           (plan + compose)
                  │
                  ▼
        Structured incident draft
        (citations + trace attached)
```

Two inputs, one orchestrator, one structured output. That's
the whole shape.

---

## If asked in the interview

**Q: "What's MCP and why did you use it?"**

> MCP is an open protocol for AI agents to call external tools.
> We use it so the orchestrator never talks to the alarm API
> directly — the alarm team can swap implementations without
> touching our code, and every tool call is structured and
> auditable.

**Q: "What's RAG and why did you use it?"**

> RAG is the pattern of searching a document collection and
> putting the relevant passages into the LLM's prompt. We use
> it to ground every answer in our actual operating procedures
> and to attach citable references to each claim.

**Q: "Why both?"**

> They solve different problems. The alarm system is live,
> structured data — that's MCP. The procedures are static,
> unstructured prose — that's RAG. Hard constraint #2 requires
> they appear together in the same workflow.

---

## Open questions for next time

- *What does the MCP tool call actually look like on the wire?*
  → `docs/mcp-tool-catalog.md` has full input/output schemas.
- *How does the prompt-injection defence actually work?* →
  `docs/rag-design.md` § "Prompt-injection defences" + Doc 05.
- *What if the LLM isn't available?* → MockLLMClient is
  covered in Doc 06.
