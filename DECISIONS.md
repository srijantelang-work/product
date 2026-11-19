# System Architecture & Build Decisions (v1)

## 1. Scope
- **In Scope (v1):** Multilingual meeting note ingestion & task extraction, human review/approval staging, dependency DAG construction, and schedule slip cascade simulation with IST alert dispatch.
- **Out of Scope (v2):** Automated priority ranking (deferred to focus on core dependency verification), real-time goal web dashboard, and automated follow-up bots.

## 2. Core Assumptions
- **Goal Weights:** 1 (low) to 3 (critical), assigned manually by founders.
- **Alert Windows:** 9:00 AM – 7:00 PM IST, Monday through Saturday. Off-hours alerts queue until 9:00 AM next business day.
- **Task Durations:** Modeled via `estimated_duration_days` to separate duration from schedule slack.

## 3. Demo Boundary vs. Production
| Component | v1 Prototype (Demo) | Production (v2) |
| :--- | :--- | :--- |
| **Task Database** | Local JSON (`data/approved_tasks.json`) | Notion Tasks Database via REST API |
| **Review UI** | Interactive terminal CLI (`src/approve.py`) | Slack Block Kit cards (Approve / Edit / Reject) |
| **Alerts Channel** | Console logs & JSON payload logs | Slack Webhook / Slack Bolt SDK |
| **Slip Trigger** | CLI argument (`src/test_scenarios.py`) | Notion page webhook + 10-15 min cron worker |

## 4. Technical Stack
- **LLM Engine:** Groq API (`openai/gpt-oss-20b`, fallback `openai/gpt-oss-120b`). Configured via `config/models.json`.
- **Validation:** Pydantic v2 schemas + custom business rule engine (cycle detection, team membership, temporal checks).
- **Graph Engine:** In-memory DAG using topological sorting and forward critical-path propagation.
