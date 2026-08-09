
# What is this project?

Imagine ABB gives you this real-life problem:

> "An operator sees a critical alarm in a refinery. Before creating a support ticket, they want AI to gather all relevant information automatically."

Today, an engineer might spend 20–30 minutes doing this manually:

* Look up the alarm
* Find the asset details
* Check similar past incidents
* Read troubleshooting manuals
* Write an incident ticket

ABB wants an **AI Copilot** that does this in seconds.

That is exactly what you're building. 

---

# Think of it as ChatGPT for industrial alarms

Instead of asking:

> "Explain transformers"

the user asks:

> "Prepare an incident for the highest-priority active alarm in EastRefinery."

Your application should understand the request and automatically collect everything needed.

---

# What should the AI do?

Suppose this is the user request.

> Prepare an incident for the highest-priority active alarm in EastRefinery.

The AI should perform something like this internally:

```
Step 1
Find highest priority alarm

↓

Step 2
Get alarm details

↓

Step 3
Get asset information

↓

Step 4
Find similar tickets

↓

Step 5
Search troubleshooting manuals

↓

Step 6
Write ticket draft

↓

Step 7
Ask user:
"Do you want me to create the ticket?"

↓

Step 8
If yes,
create ticket
```

That is the entire assignment in one picture.

---

# Where does MCP come in?

This is probably the biggest new concept.

Normally an AI application would call APIs directly.

```
LLM
   │
   ▼
Alarm API
```

ABB **doesn't want that**.

Instead they want

```
LLM

↓

MCP Client

↓

MCP Server

↓

Alarm API
```

Why?

Because MCP acts like a **tool layer**.

The LLM never knows how to call REST APIs.

Instead it says

> "Use tool Search Asset"

The MCP server then converts that into

```
GET /assets/search
```

and returns structured data.

So your job is to build that MCP server. The assignment explicitly requires that the copilot uses the Alarm Management API **through the MCP server**, not by calling the API directly.

---

# Then what is RAG?

Not every answer comes from APIs.

Suppose the operator asks

> "What is the recommended troubleshooting procedure?"

That information doesn't live in the Alarm API.

It lives inside PDFs like

* Troubleshooting Guide
* Operating Procedure
* Maintenance Manual
* Knowledge Articles

Those documents are indexed into a RAG system.

```
PDF

↓

Chunks

↓

Embeddings

↓

Vector DB
```

When the LLM needs documentation, it retrieves the relevant chunks and cites them. The assignment requires document ingestion, retrieval, grounded answers, and citations.

---

# So the AI combines two worlds

## Structured Data

From APIs

```
Alarm

Asset

Priority

Recommendations
```

## Unstructured Data

From documents

```
PDF

Manual

Procedure

Knowledge article
```

Then combines them into one answer.

Example:

```
Incident Summary

Alarm:
High Pressure Alarm

Asset:
Boiler Feed Pump 101

Likely Cause:
Pressure sensor drift

Recommended Action:
Replace pressure sensor

Troubleshooting Procedure:
Maintenance Guide Section 4.2

Source:
maintenance_manual.pdf
```

This combined workflow is one of the core requirements of the assignment.

---

# Why do they ask for a GUI?

Because they don't want only backend APIs.

They want something usable.

Something like

```
+--------------------------------------+
| Incident Copilot                     |
+--------------------------------------+

User:

Prepare ticket for highest alarm

----------------------------------------

Alarm

Priority

Asset

Recommended Action

----------------------------------------

Troubleshooting Documents

✓ maintenance.pdf

✓ SOP.pdf

----------------------------------------

Ticket Draft

----------------------------------------

[Approve]

[Edit]

[Create Ticket]

----------------------------------------

MCP Execution Trace

Search Asset

Get Alarm

Get Metadata

Retrieve Documents
```

The GUI should also show document citations and the MCP execution trace.

---

# Why do they ask for a Ticket API?

Because your AI shouldn't just answer questions.

It should also perform actions.

For example

```
Create Incident
```

But before creating the ticket,

the AI must ask

> "Do you want to create this ticket?"

Only after user confirmation should it perform the write operation. That approval step is explicitly required.

---

# Why the Alarm API Simulator?

ABB doesn't give you their real industrial system.

Instead they give you Postman collections that define the API contract.

You need to implement a fake backend that behaves exactly like that API, and then have your MCP server connect to it. The collections include endpoints for asset search, alarm retrieval, summaries, trends, correlation, recommendations, calculations, and more.

---

# Putting everything together

```
              User
                │
                ▼
          Chat Interface
                │
                ▼
         Copilot Backend
                │
      ┌─────────┴─────────┐
      │                   │
      ▼                   ▼
  MCP Client          RAG Retriever
      │                   │
      ▼                   ▼
  MCP Server         Vector Database
      │                   │
      ▼                   ▼
 Alarm API         PDF Documents

      │                   │
      └─────────┬─────────┘
                ▼
        AI Generates Answer
                │
                ▼
      Incident Draft + Citations
```

---

# Project Deliverables

* Build an MCP server around an external API.
* Build a RAG pipeline over documents.
* Orchestrate both together in a single workflow.
* Present everything through a usable GUI.
* Produce an evidence-backed response with citations and an MCP execution trace.
* Package, test, and document the solution professionally.

## My one-sentence summary

This project is **to build an AI support engineer**: a copilot that understands a natural-language incident request, gathers live alarm data through an MCP server, retrieves supporting knowledge from documents using RAG, combines both into a grounded incident draft with citations, and—after explicit user approval—creates a support ticket.
