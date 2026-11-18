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

print("=== Running 5-run stability benchmark with 5s pause ===")
runs = []
for i in range(1, 6):
    success, content, finish_reason, telemetry = call_groq_api(
        client, model_cfg, [{"role": "user", "content": rendered}]
    )
    if not success or not content:
        print(f"Run {i} failed API: {telemetry}")
        continue
    parsed = json.loads(content)
    tasks = parsed.get("tasks", [])
    val = validate_extraction(parsed, raw_note, team_list, goals_list)
    runs.append({
        "run": i,
        "task_count": len(tasks),
        "ignored_count": len(parsed.get("ignored_remarks", [])),
        "tasks": tasks,
        "is_valid": val.is_valid
    })
    print(f"Run {i}: Tasks={len(tasks)} | Ignored={len(parsed.get('ignored_remarks', []))} | Valid={val.is_valid}")
    time.sleep(5)

# Save full results for inspection
with open("logs/stability_5runs.json", "w") as f:
    json.dump(runs, f, indent=2)

print("\nBenchmark saved to logs/stability_5runs.json")

