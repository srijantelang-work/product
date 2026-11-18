import os
import json
import logging
from typing import Tuple, Dict, Any
from dotenv import load_dotenv
from groq import Groq
from pydantic import ValidationError

from src.schema import MeetingExtractionOutput

# Configure logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

def load_file(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

def extract_tasks_with_model(
    client: Groq,
    model_config: Dict[str, Any],
    prompt: str
) -> Tuple[bool, Any]:
    model_id = model_config["id"]
    logger.info(f"Invoking Groq model: {model_id} ({model_config.get('name')})")
    
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            response_format=model_config.get("response_format", {"type": "json_object"}),
            temperature=model_config.get("temperature", 0.1),
        )
        raw_content = response.choices[0].message.content
        logger.info(f"Model {model_id} responded. Content length: {len(raw_content)} chars.")
        
        parsed_json = json.loads(raw_content)
        validated_output = MeetingExtractionOutput.model_validate(parsed_json)
        return True, validated_output
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(f"Validation or JSON parsing failed for model {model_id}: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"API call failed for model {model_id}: {e}")
        return False, str(e)

def run_extraction_pipeline():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
    
    client = Groq(api_key=api_key)

    # 1. Load configs & context
    models_cfg = json.loads(load_file("config/models.json"))
    prompt_template = load_file("config/prompt_v1.txt")
    schema_json = load_file("config/schema.json")
    team_json = load_file("data/team.json")
    goals_json = load_file("data/goals.json")
    meeting_notes = load_file("data/meeting_notes_2026-11-16.md")
    
    meeting_date = "2026-11-16"

    # 2. Inject context into prompt template
    rendered_prompt = prompt_template.format(
        meeting_date=meeting_date,
        team_json=team_json,
        goals_json=goals_json,
        schema_json=schema_json,
        meeting_notes=meeting_notes,
    )

    # 3. Try primary model first (cost-optimized routing)
    primary_cfg = models_cfg["primary_model"]
    logger.info(f"Attempting extraction with primary model: {primary_cfg['id']}")
    success, result = extract_tasks_with_model(client, primary_cfg, rendered_prompt)

    # 4. Fallback to larger model if primary fails validation or parse
    if not success:
        fallback_cfg = models_cfg["fallback_model"]
        logger.warning(f"Primary model failed. Falling back to high-capacity model: {fallback_cfg['id']}")
        success, result = extract_tasks_with_model(client, fallback_cfg, rendered_prompt)
        if not success:
            logger.error("Both primary and fallback models failed extraction.")
            return

    # 5. Persist output
    output_path = "data/extracted_tasks.json"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.model_dump_json(indent=2))
    logger.info(f"Successfully saved extracted and validated tasks to {output_path}")

    print("\n--- EXTRACTION SUMMARY ---")
    print(f"Meeting Date: {result.meeting_date}")
    print(f"Extracted Tasks ({len(result.tasks)}):")
    for t in result.tasks:
        print(f"  - [{t.id}] {t.title} | Owner: {t.owner} | Due: {t.due_date} | Depends on: {t.depends_on} | Needs Confirm: {t.needs_confirmation}")
    print(f"\nIgnored Remarks ({len(result.ignored_remarks)}):")
    for r in result.ignored_remarks:
        print(f"  - \"{r.quote}\" -> Reason: {r.reason}")

if __name__ == "__main__":
    run_extraction_pipeline()
