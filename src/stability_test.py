import os
import json
import time
from dotenv import load_dotenv
from groq import Groq
from src.extract import call_groq_api
from src.validate import validate_extraction

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

with open("config/models.json") as f: models_cfg = json.load(f)
with open("config/prompt_v1.txt") as f: prompt_template = f.read()
with open("config/schema.json") as f: schema_json = f.read()
with open("data/team.json") as f: team_list = json.load(f)
with open("data/goals.json") as f: goals_list = json.load(f)
with open("data/meeting_notes_2026-11-16.md") as f: raw_note = f.read()

rendered = prompt_template.format(
    meeting_date="2026-11-16",
    team_json=json.dumps(team_list, indent=2),
    goals_json=json.dumps(goals_list, indent=2),
    schema_json=schema_json,
    meeting_notes=raw_note,
)

model_cfg = models_cfg["primary_model"]

print("=== Running 3 consecutive stability benchmark runs ===")
results = []
for i in range(1, 4):
    success, content, finish_reason, telemetry = call_groq_api(
        client, model_cfg, [{"role": "user", "content": rendered}]
    )
    if not success or not content:
        print(f"Run {i} failed: {telemetry}")
        continue
    parsed = json.loads(content)
    val = validate_extraction(parsed, raw_note, team_list, goals_list)
    tasks = parsed.get("tasks", [])
    task_keys = [f"{t.get('id')}:{t.get('owner')}:{t.get('due_date')}" for t in tasks]
    cost = telemetry.get("cost_usd", 0)
    print(f"Run {i}: Valid={val.is_valid} | Tasks={len(tasks)} | Ignored={len(parsed.get('ignored_remarks', []))} | Cost=${cost:.6f} | Latency={telemetry.get('duration_sec')}s")
    print("  Task breakdown:", " | ".join(task_keys))
    results.append({
        "run": i,
        "tasks_count": len(tasks),
        "ignored_count": len(parsed.get("ignored_remarks", [])),
        "task_keys": task_keys,
        "is_valid": val.is_valid
    })
    time.sleep(3)

print("\n=== STABILITY SUMMARY ===")
task_counts = [r["tasks_count"] for r in results]
ignored_counts = [r["ignored_count"] for r in results]
print(f"Task count stability across 3 runs: {task_counts}")
print(f"Ignored remarks stability across 3 runs: {ignored_counts}")
all_valid = all(r["is_valid"] for r in results)
print(f"All runs passed business rule validation: {all_valid}")
