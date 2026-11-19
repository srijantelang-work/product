# AI Task Extraction & Schedule Slip Cascade Engine

Extracts action items from unstructured, multilingual meeting notes (Hindi / Gujarati / English), validates business logic, routes through human approval, and simulates schedule slip cascades across an in-memory Dependency DAG with IST-compliant Slack alerts.

See [BUILD_PLAN.md](file:///Users/srijantelang27/Desktop/Personal/product/BUILD_PLAN.md) for production architecture, data model, buy vs. build, and runbook.

---

## Quickstart

### Prerequisites
- Python 3.9+
- [Groq API Key](https://console.groq.com/)

### Setup
```bash
git clone https://github.com/srijantelang-work/product.git
cd product
python3 -m venv .venv
source .venv/bin/activate
pip install groq pydantic python-dotenv
echo "GROQ_API_KEY=your_key_here" > .env
```

---

## Reproduction Commands

Run these 5 commands from the project root:

### 1. Multilingual Task Extraction
Ingests meeting notes, runs extraction with `openai/gpt-oss-20b`, validates schema and business rules, and stages tasks:
```bash
PYTHONPATH=. ./.venv/bin/python src/pipeline.py
```

### 2. Human Approval Workflow
Interactive review to approve, edit, or reject proposed tasks:
```bash
PYTHONPATH=. ./.venv/bin/python src/approve.py
# Or non-interactive scripted mode:
PYTHONPATH=. ./.venv/bin/python src/approve.py --auto
```

### 3. Schedule Slip Cascade Simulation
Runs 4 scenarios through the dependency DAG, separating task duration from schedule slack to evaluate downstream buffer erosion and IST-windowed Slack alerts:
```bash
PYTHONPATH=. ./.venv/bin/python src/test_scenarios.py
```

### 4. Safety Net & Self-Correction Test Hook
Injects corrupt data (circular dependency + unknown owner) to verify business-rule interception and automatic model self-correction:
```bash
PYTHONPATH=. ./.venv/bin/python src/pipeline.py --simulate-break
```

### 5. Multi-Run Consistency Benchmark
Runs 5 consecutive extractions to benchmark output stability and relative date resolution:
```bash
PYTHONPATH=. ./.venv/bin/python src/benchmark_5runs.py
```

---

## Project Structure

```
.
├── BUILD_PLAN.md           # Production architecture, data model, runbook & cost
├── DECISIONS.md            # v1 vs v2 scope boundaries & assumptions
├── config/                 # Prompt templates, model routing, JSON schema
├── data/                   # Meeting notes, team roster, goals, approved tasks
├── logs/                   # Run telemetry, simulation outputs, benchmark logs
└── src/                    # Pipeline, validation, approval, graph & test scripts
```
