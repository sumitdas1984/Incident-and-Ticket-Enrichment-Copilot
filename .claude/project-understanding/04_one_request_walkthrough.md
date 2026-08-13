# 04 — One request, end-to-end

> **What this answers.** When the operator types the canonical
> question, *exactly* what happens? This is the most important
> doc in this folder — it's the story you'll tell in the
> interview to show you understand how the pieces fit.

---

## The canonical question

The brief's mandatory § 7 scenario is:

> *"Investigate recurring high-severity alarms for Boiler
> Feed Pump 101 over the last 90 days. Identify likely
> contributing factors. Retrieve the relevant operating
> procedure and return recommended actions."*

In our copilot UI, that's the **first suggested prompt** in the
sidebar — pre-loaded so the demo can start with one click.

What follows is the 8-step journey of that question through
the system. I'll name the file each step lives in, so you can
pull it up in the IDE.

---

## The 8 steps

### Step 0 — Operator clicks the suggested prompt

- **Where:** `apps/frontend/ui.py:render_sidebar()`
- **What happens:** The sidebar's `st.button` click triggers
  `_dispatch_user_message(prompt, client)`. The chat column
  shows the user turn; the workspace column shows the
  "Investigating…" skeleton.
- **Note:** the spinner is *only* visual. The actual work
  happens synchronously inside the same rerun.

### Step 1 — Chat input posts to `/chat`

- **Where:** `apps/frontend/chat_client.py:ChatClient.send`
- **What happens:** A `POST http://localhost:8001/chat` with
  body `{"message": "Investigate recurring...", "conversation_id": null}`.
- **Trace:** A new `x-trace-id` (UUID) is generated on every
  call. It's stored in structlog's contextvar so every log
  line downstream carries it.

### Step 2 — Orchestrator routes the request

- **Where:** `apps/backend/orchestrator/request.py:chat()`
- **What happens:** The FastAPI handler:
  1. Reads the request body into `ChatRequest`.
  2. Generates or reuses a `conversation_id`.
  3. Loads the conversation from the in-memory store (or
     creates a new one).
  4. Appends the user turn.
  5. Calls the **planner**.
  6. Calls the **chain runner**.
  7. Returns a `ChatResponse` envelope.

### Step 3 — Planner extracts intent + slots

- **Where:** `apps/backend/orchestrator/planner.py`
- **What happens:** The `MockPlanner` (default) or `LLMPlanner`
  turns the natural-language question into a structured `Plan`:
  - **intent**: e.g. `investigate_recurring_alarms`
  - **slots**: `{asset: "Boiler B-101", window_days: 90,
    severity_filter: "high|critical"}`
  - **steps**: a list of `PlanStep`s, each tagged with a
    `tool_kind` (`mcp` | `rag` | `llm` | `ticket`).
- **Important:** this is *not* a hard-coded pattern match. It's
  a general NL→slots extractor, so it works on questions the
  author never saw. (Hard constraint #8.)

### Step 4 — Chain runner executes the plan

- **Where:** `apps/backend/orchestrator/chain.py:ChainRunner.run`
- **What happens:** The runner iterates over the `PlanStep`s
  in order (sequential v1; wave-aware structure is in place
  but parallel dispatch is not wired). For each step:
  - `mcp` → calls `mcp_client.invoke(server, tool, args)`.
  - `rag` → calls the retrieval service.
  - `llm` → calls the LLM client with a composed prompt.
  - `ticket` → produces the draft (only on the second request
    flow — `/tickets/draft`, not on `/chat`).

Each step's inputs and outputs are appended to the
`TraceStep` list. **This is what makes the trace visible to the
operator.**

### Step 5 — MCP step: alarm data

- **Where:** `apps/backend/orchestrator/mcp_client.py:invoke`
  → `mcp-servers/alarm-management/server.py`
- **What happens:** For an `investigate_recurring_alarms` plan,
  the runner typically invokes:
  1. `search_assets(query="Boiler B-101")` — resolves the
     asset name to an `asset_id`.
  2. `summarize_alarms(asset_id, since="90d", severity="high|critical")`
     — pulls the alarm history.
  3. `recommend_actions(alarm_id)` — for the worst alarm,
     fetches the priority score + suggested actions.
  4. `search_similar_tickets(asset_class="pump")` — looks up
     past incidents on similar equipment.
- **Each tool call** is logged with `tool`, `duration_ms`,
  `outcome`, `api_status_code`. The trace is the operator's
  window into what happened.

### Step 6 — RAG step: procedure docs

- **Where:** `rag/retrieval/service.py:retrieve`
- **What happens:**
  1. Embed the operator's question using the same embedder
     that built the index.
  2. Cosine-similarity search → top 5 chunks.
  3. **Prompt-injection filter** drops any chunk matching the
     blocklist (e.g. "ignore previous instructions").
  4. **Low-confidence check** — if the top match scores below
     a threshold, the response carries
     `rag_confidence: "low"`.
  5. Format each surviving chunk as a `Citation` (doc_id,
     section, page, score, excerpt).

### Step 7 — LLM step: compose the answer

- **Where:** `apps/backend/orchestrator/answer.py`
- **What happens:** A prompt is composed:
  - **System:** "You are an industrial-incident copilot. Cite
    your sources. Be terse."
  - **User:** the original question.
  - **Context block #1:** the alarm data from Step 5.
  - **Context block #2:** the citations from Step 6.
  - **Output shape:** the structured `Incident` schema.

The LLM returns the answer text + the structured Incident
(the orchestrator asks for both via JSON mode).

### Step 8 — Response envelope

- **Where:** `apps/backend/orchestrator/request.py:ChatResponse`
- **What flows back to the GUI:**
  ```json
  {
    "answer": "Boiler B-101 has had 7 high-severity alarms...",
    "intent": "investigate_recurring_alarms",
    "rag_confidence": "high",
    "dropped_count": 0,
    "citations": [{ "doc_id": "...", "section": "...",
                     "score": 0.81, "excerpt": "..." }, ...],
    "trace": [{ "server": "alarm-management", "tool": "...",
                "outcome": "success", "duration_ms": 234 }, ...],
    "incident": { "id": "INC-9001", "title": "...",
                  "severity": "critical", "recommended_actions": [...],
                  "similar_tickets": [...] },
    "conversation_id": "conv-..."
  }
  ```

The GUI renders:
- The **answer** as the assistant message card.
- The **4 pills** on top: intent, RAG confidence, citation count,
  trace-step count.
- The **structured Incident card** below the answer.
- The **Evidence card** (collapsed) showing the citation count
  and tool-call count.
- The **workspace column** on the right populates with the
  full structured incident, the editable draft form, and the
  citations + trace timeline (one scroll down).

---

## The second request: ticket creation

The chat flow above is **read-only**. To actually create a
ticket, the operator clicks **🛡 Create ticket** in the
workspace. That triggers a *different* flow:

### Step 9 — Preview the ticket draft

- **Where:** `apps/backend/orchestrator/request.py:tickets_preview`
- **What happens:** A `POST /tickets/preview` sends the
  Incident to the ticket-mock, which returns a *projected*
  ticket (title, body, severity, labels) **without persisting
  anything**.
- **Why:** so the operator sees the exact text that will be
  filed, and can edit before the actual write.

### Step 10 — Approve

- **Where:** `apps/frontend/ui.py:_render_confirmation_modal`
- **What happens:** The modal renders:
  - The read-only ticket draft.
  - The Evidence card (citations with verbatim quoted source).
  - A "What will happen" footer.
  - A **Cancel** button.
  - An **Approve & create** button.

The button is *intentionally* below the fold — the operator
has to scroll to confirm they're approving what they read.

### Step 11 — Create the ticket

- **Where:** `apps/backend/orchestrator/request.py:tickets_draft`
- **What happens:** A `POST /tickets/draft` with
  `{"incident": {...}, "approved": true}`. The connector's
  approval gate verifies `approved == true` (otherwise 403).
- **The audit row** is appended to
  `GET /tickets/audit` with `approved_by`, `approved_at`,
  `request_id` — the trace that ties this submit click to the
  log entries.

### Step 12 — Success panel

- **Where:** `apps/frontend/ui.py:_render_ticket_result`
- **What happens:** A green card shows the ticket id, the
  approved-by identity, and the request id. The audit-log note
  is rendered as a subcard.

---

## A second's view of the data flow

```
[ GUI ]─HTTP─▶[ Orchestrator /chat ]─▶[ Planner ]
                  │                       │
                  │                       ▼
                  │                    [ Plan ]
                  │                       │
                  │                       ▼
                  │             [ Chain runner ]──MCP──▶[ alarm-mcp ]──HTTP──▶[ alarm-api sim ]
                  │                  │                                  (MCP is the only path)
                  │                  │
                  │                  └──RAG──▶[ retrieval service ]──read──▶[ var/index/v1.pkl ]
                  │                  │
                  │                  └──LLM──▶[ LLM client ]──HTTP──▶[ OpenAI / Anthropic / Mock ]
                  │                       │
                  │                       ▼
                  │                [ ChatResponse ]
                  │                       │
                  └────HTTP────────────────┘

later, on operator click:

[ GUI ]─HTTP─▶[ /tickets/preview ]──MCP──▶[ ticketing-mcp ]──HTTP──▶[ ticket-mock ]
                                                                  (no write, just projection)

[ GUI ]─HTTP─▶[ /tickets/draft  ]──MCP──▶[ ticketing-mcp ]──HTTP──▶[ ticket-mock ]
                                            │                          │
                                            │                  [ approval gate: 403 if not approved ]
                                            │                          │
                                            │                          ▼
                                            │                  [ persist + audit row ]
```

---

## If asked in the interview

**Q: "Walk me through what happens when the operator types a
question."**

> GUI sends POST /chat to the orchestrator. Planner extracts
> intent + slots. Chain runner executes the plan steps in order:
> MCP calls to the alarm-management server for live data, RAG
> retrieval for procedure docs, then an LLM step composes the
> structured incident. The orchestrator returns a ChatResponse
> envelope with answer, citations, trace, and the incident
> payload. The GUI renders all four.

**Q: "Where does the MCP-only rule get enforced?"**

> In the orchestrator. There's literally no `httpx.get(...)` to
> the alarm API outside `mcp-servers/alarm-management/`. The
> orchestrator only talks to the MCP server. CI even greps for
> it.

**Q: "What's the audit trail for a ticket creation?"**

> Every approved ticket write appends a row to
> `/tickets/audit` with the request id, the approver identity,
> and the timestamp. The success panel surfaces all three back
> to the operator.

---

## Open questions for next time

- *What does the prompt-injection blocklist actually contain?*
  → Doc 05 + `docs/rag-design.md`.
- *What's a "trace_id" vs a "conversation_id"?* →
  `core/logging.py` docstring.
- *Why is the chain runner sequential?* → Decision #3 in
  `docs/design-decisions.md`.
