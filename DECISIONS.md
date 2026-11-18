# System Architecture & Build Decisions (v1)

## 1. Scope Definition

### In Scope for v1
- **Meeting Note Ingestion & Task Extraction**: Extract proposed action items, assignees, deadlines, and dependencies from raw meeting transcripts/notes.
- **Human Approval Workflow**: CLI-based or file-based review step allowing humans to approve, modify, or reject proposed tasks before commitment.
- **Dependency Graph Construction**: Build a Directed Acyclic Graph (DAG) of approved tasks to track relationships, prerequisites, and critical paths.
- **Slip Alert Simulation**: Simulate schedule delays on bottleneck tasks and propagate the delay through the DAG to evaluate timeline impact.

### Out of Scope (Deferred to v2)
- **Automated Priority Ranking**: Complex heuristic/ML prioritization algorithms.
- **Real-time Goal Dashboard**: Web UI/dashboard for visual task management and goal progress tracking.
- **Automated Follow-ups**: Automated nudge bots or escalation workflows pinging assignees.

---

## 2. Operating Assumptions
- **Goal Weights**: Set manually by founders on a discrete integer scale from 1 (low) to 3 (critical).
- **Alert Windows**: Alerts and simulated notifications are restricted to business hours: **9:00 AM to 7:00 PM IST, Monday through Saturday**.

---

## 3. Demo Boundary vs. Real Integration Architecture

### Demo Boundary (Proof of Risky Core)
- **Notion Integration**: Represented by local JSON schemas and persistent files (`data/notion_tasks.json`).
- **Slack Notifications**: Represented by structured console logs and local JSON payload logs (`logs/slack_alerts.json`).
- **Rationale**: The risky, differentiating capability is reliable LLM extraction, structured validation, and dependency graph delay propagation—not boilerplate OAuth / third-party API plumbing.

### Production Integration Blueprint (Real System)
- **Notion**: Integrates via Notion REST API (`@notionhq/client` / requests) using database pages with properties matching our Pydantic schema (Assignee, Status, Dependencies Relation, Deadlines, Weight).
- **Slack**: Integrates via Slack Webhooks / Slack Bolt SDK to dispatch block-kit formatted interactive alerts to dedicated project channels or assignee DMs.

---

## 4. Technical Stack Decisions
- **LLM Engine**: Groq API with structured JSON output enforcement.
- **Validation**: Pydantic v2 schemas for all task models, dependencies, and approval states.
- **Graph Engine**: In-memory DAG representation for topological sorting and critical path slip calculation.
- **Configuration**: Declarative settings in `config/` (prompt templates, JSON schema, model configs).
