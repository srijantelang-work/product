# AI Task Extraction & Schedule Slip Cascade Engine

> An intelligent operations engine that extracts commitments from unstructured, multilingual startup meeting notes (Hindi / Gujarati / English), validates business logic, routes through human review, and simulates schedule slip cascades across an in-memory Dependency DAG with IST-compliant Slack alerts.

Built as a production-grade prototype for early-stage startup engineering and product operations.

---

## 1. System Overview

Startups move fast and make dozens of commitments across informal, multilingual syncs. However, tracking dependencies manually leads to silent deadline slips that compound into missed product launches.

This system solves this challenge via five deterministic stages:
1. **Multilingual Extraction:** Groq-powered extraction using `openai/gpt-oss-20b` configured with tuned token budgets and low reasoning effort to eliminate silent truncation.
2. **Deterministic Business Validation:** Strict Pydantic v2 schemas and programmatic business checks (cycle detection, team roster validation, verbatim source-quote matching, and temporal bounds).
3. **Resilient Retry & Escalation Chain:** Catches schema failures, feeds errors back to the primary model for zero-shot self-correction, and falls back to `openai/gpt-oss-120b` if errors persist.
4. **Human-in-the-Loop Staging:** Interactive terminal UI allowing operators to approve, edit, or reject extracted tasks before committing them to the organizational graph.
5. **Dependency DAG & Slip Cascade Simulation:** In-memory topological graph engine separating **task duration** from **schedule buffer/slack** to simulate delays, compute goal roll-ups, and generate actionable Slack alerts formatted for Indian Standard Time (IST) business hours.

---

## 2. Repository Layout

```
.
├── BUILD_PLAN.md               # Detailed architecture spec, empirical findings, and v2 roadmap
├── DECISIONS.md                # System assumptions, demo boundaries, and scope constraints
├── README.md                   # Quickstart, reproduction instructions, and system tour
├── config/
│   ├── models.json             # Primary and fallback model routing parameters
│   ├── prompt_v1.txt           # Versioned extraction prompt (speaker-assignee rules, relative dates)
│   └── schema.json             # Auto-generated JSON schema for structured LLM decoding
├── data/
│   ├── approved_tasks.json     # Curated committed tasks (with estimated_duration_days)
│   ├── example_extraction_output.json # Validated reference extraction sample
│   ├── expected_extraction_key.md     # Ground truth answer key for accuracy evaluation
│   ├── extracted_tasks.json    # Output from live extraction pipeline
│   ├── goals.json              # Company milestones with weights and target dates
│   ├── meeting_notes_2026-11-16.md    # Benchmark multilingual meeting transcript
│   └── team.json               # Canonical organizational team roster
├── logs/
│   ├── run_log.json            # Telemetry audit log (tokens, latencies, USD cost, error feedback)
│   ├── simulation_scenarios.json # Output of all 4 slip cascade scenarios
│   └── stability_5runs.json    # 5-run empirical consistency benchmark results
└── src/
    ├── approve.py              # Interactive human-in-the-loop CLI review tool
    ├── benchmark_5runs.py      # Automated 5-run extraction consistency benchmark
    ├── graph.py                # In-memory DAG, topological sort, and cascade propagation engine
    ├── pipeline.py             # 3-tier extraction pipeline with self-correction retry
    ├── schema.py               # Pydantic v2 schemas for tasks and meeting output
    ├── test_scenarios.py       # 4-scenario cascade validation test suite
    └── validate.py             # Business rule validation engine (DFS cycle detection, etc.)
```

---

## 3. Quickstart & Setup

### Prerequisites
- Python 3.9+
- A [Groq Cloud API Key](https://console.groq.com/)

### Installation
1. Clone the repository and navigate into the workspace:
   ```bash
   cd /Users/srijantelang27/Desktop/Personal/product
   ```

2. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install project dependencies:
   ```bash
   pip install groq pydantic python-dotenv
   ```

4. Configure your `.env` file in the project root:
   ```bash
   GROQ_API_KEY=your_groq_api_key_here
   ```

---

## 4. Step-by-Step Reproduction Guide

Run each step in order from the repository root:

### Step 1: Run Live Multilingual Extraction Pipeline
Extracts structured tasks from `data/meeting_notes_2026-11-16.md` using the primary `openai/gpt-oss-20b` model:
```bash
PYTHONPATH=. ./.venv/bin/python src/pipeline.py
```
- **What happens:** Ingests notes, validates output against Pydantic schema and business rules, logs token usage to `logs/run_log.json`, and writes staging tasks to `data/extracted_tasks.json`.
- **Cost:** ~$0.00032 USD per run.

---

### Step 2: Interactive Human Approval Step
Launches the human-in-the-loop review interface:
```bash
PYTHONPATH=. ./.venv/bin/python src/approve.py
```
- **Interactive Controls:**
  - `a`: Approve task as proposed.
  - `e`: Edit assignee or committed deadline.
  - `r`: Reject task (prompts for rationale).
- **Automated Mode (For non-interactive CI/CD runs):**
  ```bash
  PYTHONPATH=. ./.venv/bin/python src/approve.py --auto
  ```

---

### Step 3: Run Schedule Slip Cascade Simulation
Executes 4 comprehensive slip scenarios through the in-memory dependency DAG:
```bash
PYTHONPATH=. ./.venv/bin/python src/test_scenarios.py
```
- **Scenario A (1-day root slip):** Demonstrates distinct status differentiation along the chain:
  - `task-2`: 🔴 **BROKEN** (zero slack; misses deadline by 1 day)
  - `task-3`: 🟡 **AT_RISK** (buffer erodes to 1 day; ≤ threshold)
  - `task-4`: 🟢 **SAFE** (7 days of slack absorbs delay cleanly)
  - **Goal-1:** 🟡 **AT_RISK** (schedule compressed, but final launch achievable)
- **Scenario B (4-day root slip):** Multi-task cascade failure with queued off-hours Slack alerts.
- **Scenario C (Mid-chain 2-day slip):** Demonstrates **ABSORBED** delay where downstream slack consumes the slip.
- **Scenario D (Leaf task slip):** Tests no-downstream scenario where final launch date is missed (**OFF_TRACK**).

---

### Step 4: Verify Safety Net & Self-Correction Hook
Simulates a corrupted LLM response containing a circular dependency and an unknown team owner:
```bash
PYTHONPATH=. ./.venv/bin/python src/pipeline.py --simulate-break
```
- **What happens:** 
  1. Attempt 1 deliberately injects corrupt data.
  2. `src/validate.py` intercepts the circular dependency and unknown owner.
  3. The pipeline captures the exact validation errors and feeds them back into the LLM.
  4. The LLM self-corrects on Attempt 2, resolving the cycle and passing all checks cleanly.
  5. Telemetry verifies the retry event in `logs/run_log.json`.

---

### Step 5: Multi-Run Stability Benchmark
Runs 5 consecutive extractions to evaluate consistency on multilingual text:
```bash
PYTHONPATH=. ./.venv/bin/python src/benchmark_5runs.py
```
- Evaluates task count wobble, relative date normalization, and chatter filtering across runs. Output is saved to `logs/stability_5runs.json`.

---

## 5. Key Architecture Highlights

### Separation of Duration and Slack
Traditional simple DAGs compute buffer merely as `child_due - parent_due`. If treated as duration, zero slack exists by construction, meaning any 1-day slip breaks the entire universe. 

Our engine models:
$$\text{Earliest Start} = \max(\text{Upstream Projected Finishes})$$
$$\text{Projected Finish} = \text{Earliest Start} + \text{Duration}$$
$$\text{Slack Remaining} = \text{Committed Due Date} - \text{Projected Finish}$$

- If $\text{Slack} < 0$: 🔴 **BROKEN** (misses committed milestone).
- If $0 \le \text{Slack} \le 1\text{ day}$: 🟡 **AT_RISK** (safety margin eroded).
- If $\text{Slack} > 1\text{ day}$: 🟢 **SAFE** (delay absorbed without downstream risk).

### Alert Windows (IST)
Startup team members should not be spammed late at night. The alerting module enforces business hours:
- **Active Window:** Monday – Saturday, 9:00 AM – 7:00 PM IST.
- If a slip is detected after hours (e.g., 10:30 PM IST), alerts are tagged `⏰ [QUEUED UNTIL NEXT ALERT WINDOW]` for 9:00 AM the next business day.

---

## 6. Video Walkthrough Narrative (Loom Structure)

When recording the 5-minute video walkthrough, follow this structured story:

1. **Problem & Multilingual Context (0:00 - 1:00):** Show `data/meeting_notes_2026-11-16.md`. Point out mixed Hindi/Gujarati phrases ("pachhi j bulk production", "Friday tak ready ho jayega") and relative dates.
2. **Extraction & 20B Model Configuration (1:00 - 2:00):** Run `src/pipeline.py`. Explain how `reasoning_effort="low"` resolved token starvation. Show `logs/run_log.json` ($0.00032 cost).
3. **Safety Net Demonstration (2:00 - 2:45):** Run `src/pipeline.py --simulate-break`. Show bad output caught by business rules, fed back, and self-corrected on Attempt 2.
4. **Human Review & Honest Disclosure (2:45 - 3:30):** Show `src/approve.py`. Transparently state: *"For the downstream demo, I hand-curated `approved_tasks.json` because human review is an intentional requirement, as evidenced by our 5-run stability benchmark."*
5. **DAG Cascade & Slack Separation (3:30 - 4:45):** Run `src/test_scenarios.py`. Walk through Scenario A showing broken, at-risk, and safe downstream tasks and IST Slack alert queuing.
6. **Wrap-up & Production Roadmap (4:45 - 5:00):** Summarize v2 integration path (Notion webhooks, Slack Bolt SDK).
