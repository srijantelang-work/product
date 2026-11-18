import os
import json
import time
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

# Pricing per million tokens (Groq On-Demand estimates)
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
    cost = (prompt_tokens / 1_000_000 * pricing["prompt_per_1m"]) + (completion_tokens / 1_000_000 * pricing["completion_per_1m"])
    return round(cost, 6)

def log_run_telemetry(record: Dict[str, Any]):
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
    logger.info(f"Telemetry logged to {RUN_LOG_PATH}")

def call_groq_api(
    client: Groq,
    model_cfg: Dict[str, Any],
    messages: List[Dict[str, str]],
    custom_max_tokens: Optional[int] = None
) -> Tuple[bool, Optional[str], Optional[str], Dict[str, Any]]:
    model_id = model_cfg["id"]
    max_tokens = custom_max_tokens or model_cfg.get("max_completion_tokens", 4096)
    
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
    
    # Retry with exponential backoff on 429/rate-limit
    max_retries = 3
    base_backoff = 2
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(**kwargs)
            duration_sec = round(time.time() - start_time, 3)
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason
            
            usage = response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0
            reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) if usage and usage.completion_tokens_details else 0
            
            cost_usd = calculate_cost(model_id, prompt_tokens, completion_tokens)

            telemetry = {
                "duration_sec": duration_sec,
                "finish_reason": finish_reason,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "reasoning_tokens": reasoning_tokens,
                "cost_usd": cost_usd,
            }
            return True, content, finish_reason, telemetry
        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                wait_time = base_backoff ** (attempt + 1)
                logger.warning(f"Rate limit hit. Backing off {wait_time}s before retry...")
                time.sleep(wait_time)
                continue
            duration_sec = round(time.time() - start_time, 3)
            return False, None, "api_error", {"duration_sec": duration_sec, "error": err_str}
            
    return False, None, "rate_limit_exhausted", {"error": "Rate limit retries exhausted"}

def run_extraction_workflow():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
    client = Groq(api_key=api_key)

    with open("config/models.json") as f: models_cfg = json.load(f)
    with open("config/prompt_v1.txt") as f: prompt_template = f.read()
    with open("config/schema.json") as f: schema_json = f.read()
    with open("data/team.json") as f: team_list = json.load(f)
    with open("data/goals.json") as f: goals_list = json.load(f)
    with open("data/meeting_notes_2026-11-16.md") as f: raw_note = f.read()

    meeting_date = "2026-11-16"
    rendered_prompt = prompt_template.format(
        meeting_date=meeting_date,
        team_json=json.dumps(team_list, indent=2),
        goals_json=json.dumps(goals_list, indent=2),
        schema_json=schema_json,
        meeting_notes=raw_note,
    )

    primary_cfg = models_cfg["primary_model"]
    fallback_cfg = models_cfg["fallback_model"]

    messages = [{"role": "user", "content": rendered_prompt}]
    
    current_model = primary_cfg
    max_tokens = current_model.get("max_completion_tokens", 4096)
    escalated_to_fallback = False
    run_log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "meeting_date": meeting_date,
        "attempts": []
    }

    max_attempts = 3
    final_output = None

    for attempt_idx in range(1, max_attempts + 1):
        logger.info(f"--- Attempt {attempt_idx}: Model={current_model['id']} (max_tokens={max_tokens}) ---")
        success, content, finish_reason, telemetry = call_groq_api(
            client, current_model, messages, custom_max_tokens=max_tokens
        )
        
        attempt_record = {
            "attempt": attempt_idx,
            "model": current_model["id"],
            "finish_reason": finish_reason,
            "telemetry": telemetry,
            "status": "pending",
            "retry_reason": None,
        }

        # 1. Length budget handling: increase budget before escalating
        if finish_reason == "length":
            logger.warning("Attempt hit token budget limit (finish_reason=length).")
            attempt_record["status"] = "failed"
            attempt_record["retry_reason"] = "length_budget_exceeded"
            run_log_entry["attempts"].append(attempt_record)
            
            if not escalated_to_fallback and max_tokens < 8192:
                max_tokens = 8192
                logger.info(f"Expanding token budget to {max_tokens} and retrying primary model.")
            else:
                logger.info("Escalating to fallback model 120B.")
                current_model = fallback_cfg
                escalated_to_fallback = True
                max_tokens = fallback_cfg.get("max_completion_tokens", 4096)
            continue

        # 2. General API error
        if not success or not content:
            attempt_record["status"] = "failed"
            attempt_record["retry_reason"] = f"api_error: {telemetry.get('error')}"
            run_log_entry["attempts"].append(attempt_record)
            logger.warning(f"API call failed: {telemetry.get('error')}. Escalating to fallback.")
            current_model = fallback_cfg
            escalated_to_fallback = True
            continue

        # 3. Pydantic validation
        try:
            parsed_json = json.loads(content)
            validated_pydantic = MeetingExtractionOutput.model_validate(parsed_json)
        except (json.JSONDecodeError, ValidationError) as e:
            attempt_record["status"] = "failed"
            attempt_record["retry_reason"] = f"schema_validation_error: {str(e)}"
            run_log_entry["attempts"].append(attempt_record)
            logger.warning(f"Schema validation failed: {e}. Retrying with feedback.")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"Output violated schema: {str(e)}. Correct and emit strict JSON."})
            continue

        # 4. Business rule validation
        val_result = validate_extraction(
            extraction_data=parsed_json,
            raw_meeting_notes=raw_note,
            team_members=team_list,
            goals=goals_list
        )

        attempt_record["business_rule_validation"] = {
            "is_valid": val_result.is_valid,
            "error_count": len(val_result.errors),
            "errors": [e.model_dump() for e in val_result.errors],
            "warning_count": len(val_result.warnings),
            "warnings": [w.model_dump() for w in val_result.warnings],
        }

        if not val_result.is_valid:
            error_msgs = "; ".join([e.message for e in val_result.errors])
            attempt_record["status"] = "failed"
            attempt_record["retry_reason"] = f"business_rule_violation: {error_msgs}"
            run_log_entry["attempts"].append(attempt_record)
            logger.warning(f"Business rules violated: {error_msgs}. Retrying with feedback.")
            
            feedback = f"Your task extraction has business rule errors: {error_msgs}. Please fix these and return corrected JSON adhering to the schema."
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": feedback})
            continue

        # Success!
        attempt_record["status"] = "success"
        run_log_entry["attempts"].append(attempt_record)
        run_log_entry["final_status"] = "success"
        run_log_entry["selected_model"] = current_model["id"]
        run_log_entry["total_run_cost_usd"] = sum(a["telemetry"].get("cost_usd", 0) for a in run_log_entry["attempts"])
        final_output = validated_pydantic
        break

    log_run_telemetry(run_log_entry)

    if final_output:
        with open("data/extracted_tasks.json", "w", encoding="utf-8") as f:
            f.write(final_output.model_dump_json(indent=2))
        logger.info(f"Successfully extracted and validated {len(final_output.tasks)} tasks!")
        print("\n=== PIPELINE SUCCESSFUL ===")
        print(f"Model used: {run_log_entry['selected_model']}")
        print(f"Attempts: {len(run_log_entry['attempts'])}")
        print(f"Estimated Cost: ${run_log_entry.get('total_run_cost_usd', 0):.6f}")
        print(f"Tasks extracted: {len(final_output.tasks)}")
        print(f"Ignored remarks: {len(final_output.ignored_remarks)}")
    else:
        logger.error("Extraction pipeline failed after max retries.")

if __name__ == "__main__":
    run_extraction_workflow()
