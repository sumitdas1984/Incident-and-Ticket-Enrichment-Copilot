# Incident-and-Ticket-Enrichment-Copilot

## Consolidated Project Overview

**Project:** Incident-and-Ticket-Enrichment-Copilot
**Assignment:** Senior Software Engineer – Copilot Integration (ABB)
**Purpose:** Project Understanding & Implementation Reference

---

# 1. Introduction

The **Incident-and-Ticket-Enrichment-Copilot** is an AI-powered enterprise assistant that helps service engineers investigate industrial alarms and prepare high-quality incident tickets.

Instead of manually collecting information from multiple systems, the copilot automatically gathers alarm information, retrieves supporting documents, searches historical incidents, and prepares a structured incident report with supporting evidence.

The project demonstrates the integration of modern AI technologies with enterprise systems, including:

* Model Context Protocol (MCP)
* Retrieval-Augmented Generation (RAG)
* Enterprise API Integration
* LLM-based reasoning
* Modern Web UI
* Production-oriented software architecture

---

# 2. Business Problem

When a critical industrial alarm occurs, service engineers typically perform several manual activities before creating a support ticket.

A typical workflow involves:

* Finding the affected asset
* Understanding the alarm
* Looking for similar historical incidents
* Reading troubleshooting manuals
* Checking recommended operator actions
* Writing an incident report
* Creating a support ticket

This process is slow, repetitive, and requires switching between multiple systems.

The objective of this project is to automate this workflow using an AI Copilot.

---

# 3. Project Goal

Build an AI Copilot that accepts a natural language request and automatically:

* Retrieves alarm information
* Collects asset context
* Searches related incidents
* Retrieves relevant documents
* Generates a grounded incident summary
* Creates a ticket draft
* Requests user approval before ticket creation

The final response should be evidence-backed and explain how the information was collected.

---

# 4. High-Level Workflow

The complete workflow can be visualized as:

```text
User

↓

Natural Language Request

↓

AI Copilot

↓

MCP Tool Discovery

↓

Alarm Management APIs

+

Document Retrieval (RAG)

↓

Combine Results

↓

Generate Incident Summary

↓

Prepare Ticket Draft

↓

User Approval

↓

Create Ticket
```

This demonstrates an end-to-end enterprise AI workflow rather than isolated AI features.

---

# 5. Major Components

## 5.1 User Interface

The GUI provides the primary interaction point for users.

Responsibilities:

* Accept user queries
* Display incident summaries
* Show document citations
* Show MCP execution trace
* Display editable ticket draft
* Ask confirmation before ticket creation

---

## 5.2 Copilot Backend

The backend acts as the orchestration layer.

Responsibilities:

* Understand user intent
* Plan execution steps
* Invoke MCP tools
* Retrieve documents
* Combine structured and unstructured information
* Generate final AI response

Think of this as the "brain" of the application.

---

## 5.3 Alarm Management API Simulator

ABB does not provide access to a real industrial system.

Instead, the assignment provides Postman collections that define the complete API contract.

The candidate must implement a simulator that behaves exactly like the specified Alarm Management API.

The simulator becomes the enterprise source system used throughout the project.

---

## 5.4 MCP Server

The assignment requires implementing at least one working MCP server.

The MCP server wraps the Alarm Management API and exposes its capabilities as AI tools.

Instead of allowing the LLM to call REST APIs directly, the LLM interacts with standardized MCP tools.

Example tools include:

* Search Asset
* Retrieve Alarm
* Alarm Summary
* Alarm Trends
* Alarm Correlation
* Priority Score
* Operator Recommendation

The MCP server is responsible for:

* Input validation
* Authentication
* Error handling
* Retry logic
* Trace propagation
* API abstraction

---

## 5.5 MCP Client

The Copilot communicates with enterprise systems through an MCP Client.

Responsibilities include:

* Tool discovery
* Tool selection
* Tool invocation
* Multi-step orchestration
* Passing outputs between tools
* Displaying execution trace

The Copilot must not call the Alarm API directly.

All interactions must pass through the MCP layer.

---

## 5.6 Document RAG

Not every answer exists inside APIs.

Operational knowledge is stored in documents such as:

* Troubleshooting guides
* Operating procedures
* Knowledge articles
* Maintenance manuals
* Resolution notes
* Escalation procedures

These documents are processed into a searchable knowledge base.

Typical RAG pipeline:

Documents

↓

Text Extraction

↓

Chunking

↓

Embedding Generation

↓

Vector Database

↓

Semantic Retrieval

↓

LLM Grounded Response

Every generated answer must include citations showing the retrieved document sources.

---

## 5.7 Ticketing System

The project also demonstrates AI-assisted ticket creation.

Possible integrations include:

* Jira
* ServiceNow
* Azure DevOps
* GitHub Issues
* Candidate-built Mock API

The AI prepares a ticket draft but must always obtain explicit user approval before performing any write operation.

---

# 6. End-to-End Example

User asks:

> Prepare an incident for the highest-priority active alarm in EastRefinery.

The Copilot performs the following sequence:

1. Identify the user's intent.
2. Discover available MCP tools.
3. Retrieve active alarms.
4. Select the highest-priority alarm.
5. Retrieve asset metadata.
6. Retrieve operator recommendations.
7. Search similar historical tickets.
8. Retrieve troubleshooting documents through RAG.
9. Combine all collected information.
10. Generate an incident summary.
11. Present an editable ticket draft.
12. Request user confirmation.
13. Create the ticket after approval.

---

# 7. Technologies Demonstrated

This assignment showcases several enterprise AI concepts working together.

### AI

* Large Language Models
* Prompt Engineering
* AI Planning
* Tool Calling
* Grounded Generation

### Enterprise Integration

* REST APIs
* Model Context Protocol (MCP)
* Multi-step API orchestration
* Authentication
* Trace propagation

### RAG

* Document ingestion
* Chunking
* Embeddings
* Vector Search
* Citation generation

### Backend

* FastAPI
* Python
* Async programming

### Frontend

* React / Streamlit / Gradio

### DevOps

* Docker
* Docker Compose
* GitHub Actions
* Environment configuration

---

# 8. Primary Evaluation Areas

The assignment is evaluated across six major dimensions:

* Overall architecture and design
* MCP server implementation
* MCP client integration
* Document RAG implementation
* Software quality and testing
* Documentation and packaging

The strongest submissions demonstrate a complete, integrated workflow rather than individual technology demonstrations.

---

# 9. Key Architectural Principle

The project revolves around combining two different sources of knowledge.

### Structured Enterprise Data

Obtained through MCP tools:

* Assets
* Alarms
* Alarm summaries
* Recommendations
* Ticket information

### Unstructured Knowledge

Obtained through RAG:

* Procedures
* Manuals
* Knowledge articles
* Troubleshooting guides

The AI combines both sources into a single evidence-backed response.

---

# 10. Overall Architecture

```text
                   User
                     │
                     ▼
             Chat-Based Frontend
                     │
                     ▼
             Copilot Backend
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
      MCP Client          RAG Retrieval
          │                     │
          ▼                     ▼
      MCP Server         Vector Database
          │                     │
          ▼                     ▼
 Alarm API Simulator     Document Corpus
          │                     │
          └──────────┬──────────┘
                     ▼
          AI Grounded Response
                     │
                     ▼
 Incident Summary + Citations +
 Ticket Draft + MCP Execution Trace
```

---

# 11. Key Takeaways

This assignment is not about building a chatbot.

It is about building a **production-oriented enterprise AI Copilot** that demonstrates:

* Enterprise system integration through MCP
* Knowledge retrieval using RAG
* Multi-step AI orchestration
* Evidence-backed responses
* Human approval before write operations
* Production-quality software engineering practices

In simple terms:

> **Build an AI support engineer that automatically investigates industrial alarms, gathers relevant enterprise knowledge, prepares an incident ticket with supporting evidence, and creates the ticket only after user approval.**
