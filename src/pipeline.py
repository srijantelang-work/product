import os
import json
import time
import hashlib
import logging
from datetime import datetime
from typing import Tuple, Dict, Any, List, Optional
from dotenv import load_dotenv
from groq import Groq
from pydantic import ValidationError

from src.schema import MeetingExtractionOutput
from src.validate import validate_extraction, ValidationResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

RUN_LOG_PATH = "logs/run_log.json"

MODEL_PRICING = {
    "openai/gpt-oss-20b": {
        "prompt_per_1m": 0.075,
        "completion_per_1m": 0.10,
    },
    "openai/gpt-oss-120b": {
        "prompt_per_1m": 0.50,
        "completion_per_1m": 0.80,
    }
}

def calculate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model_id, {"prompt_per_1m": 0.10, "completion_per_1m": 0.15})
    return round((prompt_tokens / 1_000_000 * pricing["prompt_per_1m"]) + 
                 (completion_tokens / 1_000_000 * pricing["completion_per_1m"]), 6)

def compute_input_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

def append_run_log(record: Dict[str, Any]):
    os.makedirs("logs", exist_ok=True)
    logs = []
    if os.path.exists(RUN_LOG_PATH):
        try:
            with open(RUN_LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
    logs.append(record)
    with open(RUN_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)
    logger.info(f"Run log record appended to {RUN_LOG_PATH}")

def call_model_api(
    client: Groq,
    model_cfg: Dict[str, Any],
    messages: List[Dict[str, str]],
    max_tokens: int = 4096
) -> Tuple[bool, Optional[str], Optional[str], Dict[str, Any]]:
    model_id = model_cfg["id"]
    kwargs = {
        "model": model_id,
        "messages": messages,
        "temperature": model_cfg.get("temperature", 0.1),
        "response_format": model_cfg.get("response_format", {"type": "json_object"}),
        "max_completion_tokens": max_tokens,
    }
    if "reasoning_effort" in model_cfg:
        kwargs["reasoning_effort"] = model_cfg["reasoning_effort"]

    start_time = time.time()
    for attempt in range(3):
        try:
            response = client.chat.completions.create(**kwargs)
            duration_sec = round(time.time() - start_time, 3)
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason
            usage = response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            cost = calculate_cost(model_id, prompt_tokens, completion_tokens)
            
            telemetry = {
                "duration_sec": duration_sec,
                "finish_reason": finish_reason,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": usage.total_tokens if usage else 0,
                "cost_usd": cost
            }
            return True, content, finish_reason, telemetry
        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                sleep_sec = 2 ** (attempt + 1)
                time.sleep(sleep_sec)
                continue
            return False, None, "api_error", {"duration_sec": round(time.time() - start_time, 3), "error": err_str}

    return False, None, "rate_limit_exhausted", {"error": "Rate limit exhausted"}

def run_extraction_pipeline(
    simulate_initial_broken_output: bool = False
) -> Tuple[Optional[MeetingExtractionOutput], Dict[str, Any]]:
    """
    Executes the 5-step robust pipeline:
    1. Load configs, prompt, data
    2. Primary model call (temp 0.1)
    3. Pydantic schema validation
    4. Business rule validation
    5. Retry logic (retry with error feedback -> fallback model -> plain language Slack failure)
    """
    # 1. Load files
    with open("config/models.json") as f: models_cfg = json.load(f)
    with open("config/prompt_v1.txt") as f: prompt_raw = f.read()
    with open("config/schema.json") as f: schema_json = f.read()
    with open("data/team.json") as f: team_list = json.load(f)
    with open("data/goals.json") as f: goals_list = json.load(f)
    with open("data/meeting_notes_2026-11-16.md") as f: raw_notes = f.read()

    # Extract prompt version header
    prompt_version = "v1.1.0"
    for line in prompt_raw.splitlines():
        if "Prompt Version:" in line:
            prompt_version = line.split(":", 1)[1].strip()
            break

    meeting_date = "2026-11-16"
    rendered_prompt = prompt_raw.format(
        meeting_date=meeting_date,
        team_json=json.dumps(team_list, indent=2),
        goals_json=json.dumps(goals_list, indent=2),
        schema_json=schema_json,
        meeting_notes=raw_notes,
    )
    input_hash = compute_input_hash(raw_notes)

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    primary_cfg = models_cfg["primary_model"]
    fallback_cfg = models_cfg["fallback_model"]

    messages = [{"role": "user", "content": rendered_prompt}]
    
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0

    run_record: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "prompt_version": prompt_version,
        "input_hash": input_hash,
        "primary_model": primary_cfg["id"],
        "fallback_model": fallback_cfg["id"],
        "attempts": [],
        "outcome": "in_progress",
        "human_decision": None,  # To be filled in Phase 6 / approval step
        "final_output": None,
        "slack_failure_message": None,
    }

    # Pipeline state machine:
    # Stage 1: Primary attempt
    # Stage 2: Retry primary with error feedback
    # Stage 3: Fallback model attempt
    stages = [
        {"stage_name": "primary_initial", "model": primary_cfg},
        {"stage_name": "primary_feedback_retry", "model": primary_cfg},
        {"stage_name": "fallback_model", "model": fallback_cfg},
    ]

    final_validated: Optional[MeetingExtractionOutput] = None

    for idx, stage in enumerate(stages, 1):
        model_cfg = stage["model"]
        stage_name = stage["stage_name"]
        logger.info(f"Executing Pipeline Stage {idx}/{len(stages)}: [{stage_name}] with {model_cfg['id']}")

        # Simulation hook for test verification
        if simulate_initial_broken_output and stage_name == "primary_initial":
            logger.info("--> [TEST SIMULATION] Injecting deliberately broken JSON with circular dependency & fake owner.")
            content = json.dumps({
                "meeting_date": "2026-11-16",
                "tasks": [
                    {
                        "id": "task-A",
                        "title": "Broken task with bad owner and circular dependency",
                        "owner": "Nonexistent Person",
                        "due_date": "2026-11-10",
                        "goal": "goal-1",
                        "depends_on": ["task-B"],
                        "confidence": "high",
                        "needs_confirmation": False,
                        "reason": None,
                        "source_quote": "Fake quote not in text"
                    },
                    {
                        "id": "task-B",
                        "title": "Circular partner",
                        "owner": "Pooja Patel",
                        "due_date": "2026-11-18",
                        "goal": "goal-1",
                        "depends_on": ["task-A"],
                        "confidence": "high",
                        "needs_confirmation": False,
                        "reason": None,
                        "source_quote": "Pooja, finalize and export the high‑res print‑ready artwork files"
                    }
                ],
                "ignored_remarks": []
            })
            success = True
            telemetry = {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200, "cost_usd": 0.00001}
        else:
            success, content, finish_reason, telemetry = call_model_api(client, model_cfg, messages)

        total_prompt_tokens += telemetry.get("prompt_tokens", 0)
        total_completion_tokens += telemetry.get("completion_tokens", 0)
        total_cost += telemetry.get("cost_usd", 0.0)

        attempt_log = {
            "stage": stage_name,
            "model": model_cfg["id"],
            "telemetry": telemetry,
            "status": "pending",
            "validation_errors": []
        }

        if not success or not content:
            attempt_log["status"] = "failed_api"
            attempt_log["validation_errors"] = [telemetry.get("error", "No content returned")]
            run_record["attempts"].append(attempt_log)
            # Escalate directly to fallback if API error
            continue

        # Schema Validation
        try:
            parsed = json.loads(content)
            pydantic_obj = MeetingExtractionOutput.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            attempt_log["status"] = "failed_schema"
            err_msg = f"Schema validation error: {str(e)}"
            attempt_log["validation_errors"] = [err_msg]
            run_record["attempts"].append(attempt_log)
            logger.warning(f"Stage {stage_name} failed schema: {err_msg}")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"Your output violated schema: {err_msg}. Please fix and emit strict JSON."})
            continue

        # Business Rule Validation
        val_result = validate_extraction(
            extraction_data=parsed,
            raw_meeting_notes=raw_notes,
            team_members=team_list,
            goals=goals_list
        )

        if not val_result.is_valid:
            error_list = [f"[{e.rule}] {e.message}" for e in val_result.errors]
            attempt_log["status"] = "failed_business_rules"
            attempt_log["validation_errors"] = error_list
            run_record["attempts"].append(attempt_log)
            logger.warning(f"Stage {stage_name} failed business rules: {'; '.join(error_list)}")
            
            # Feed errors back into conversation
            feedback = (
                f"Your task extraction has {len(error_list)} business rule errors:\n" +
                "\n".join(f"- {err}" for err in error_list) +
                "\nPlease fix each of these issues and return corrected JSON adhering to the schema."
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": feedback})
            continue

        # Passed all validations!
        attempt_log["status"] = "success"
        run_record["attempts"].append(attempt_log)
        run_record["outcome"] = "success" if idx == 1 else "retried"
        run_record["final_model"] = model_cfg["id"]
        run_record["final_output"] = parsed
        final_validated = pydantic_obj
        break

    run_record["total_tokens"] = {
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total": total_prompt_tokens + total_completion_tokens
    }
    run_record["estimated_cost_usd"] = round(total_cost, 6)

    # If all stages failed, craft plain-language Slack failure alert
    if not final_validated:
        run_record["outcome"] = "failed"
        slack_msg = (
            f"🚨 *Extraction Pipeline Alert: Task Extraction Failed*\n"
            f"• *Meeting Date:* {meeting_date}\n"
            f"• *Input Hash:* `{input_hash}`\n"
            f"• *Attempts:* Exhausted {len(stages)} stages (Primary model, Error Feedback Retry, and Fallback 120B model).\n"
            f"• *Root Cause:* Repeated business rule or schema violations that could not be resolved automatically.\n"
            f"• *Action Required:* Meeting transcript requires manual review or prompt tuning."
        )
        run_record["slack_failure_message"] = slack_msg
        logger.error(f"PIPELINE FAILED completely. Slack Alert:\n{slack_msg}")

    append_run_log(run_record)
    return final_validated, run_record

if __name__ == "__main__":
    import sys
    simulate = "--simulate-break" in sys.argv
    print(f"Running pipeline (simulate_initial_broken_output={simulate})...")
    output, rec = run_extraction_pipeline(simulate_initial_broken_output=simulate)
    print(f"\nFinal Outcome: {rec['outcome']}")
    print(f"Attempts Made: {len(rec['attempts'])}")
    print(f"Total Cost: ${rec['estimated_cost_usd']:.6f}")
    if output:
        print(f"Successfully extracted {len(output.tasks)} validated tasks.")
        with open("data/extracted_tasks.json", "w", encoding="utf-8") as f:
            f.write(output.model_dump_json(indent=2))
    else:
        print(f"Pipeline failed. Slack alert generated:\n{rec['slack_failure_message']}")
