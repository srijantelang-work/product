import unicodedata
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class ValidationErrorDetail(BaseModel):
    rule: str
    message: str
    task_id: Optional[str] = None

class ValidationResult(BaseModel):
    is_valid: bool
    errors: List[ValidationErrorDetail] = []
    warnings: List[ValidationErrorDetail] = []

def normalize_text(text: str) -> str:
    """Normalize Unicode and collapse whitespaces for robust substring matching."""
    if not text:
        return ""
    # NFKC normalizes ligatures and character variations across scripts
    normalized = unicodedata.normalize("NFKC", text)
    # Collapse multiple whitespaces/newlines into single space
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized

def validate_extraction(
    extraction_data: Dict[str, Any],
    raw_meeting_notes: str,
    team_members: List[Dict[str, Any]],
    goals: List[Dict[str, Any]]
) -> ValidationResult:
    errors: List[ValidationErrorDetail] = []
    warnings: List[ValidationErrorDetail] = []

    meeting_date_str = extraction_data.get("meeting_date")
    tasks = extraction_data.get("tasks", [])
    task_ids = {t["id"] for t in tasks if "id" in t}
    team_names = {m["name"] for m in team_members if "name" in m}
    valid_goal_ids = {g["id"] for g in goals if "id" in g}
    
    normalized_note = normalize_text(raw_meeting_notes)

    # 1. Dependency Graph & Cycle Detection (DAG check)
    adj_list: Dict[str, List[str]] = {t["id"]: [] for t in tasks if "id" in t}
    
    for t in tasks:
        tid = t.get("id", "UNKNOWN")
        deps = t.get("depends_on", [])
        
        # Check that dependency IDs actually exist
        for dep in deps:
            if dep not in task_ids:
                errors.append(ValidationErrorDetail(
                    rule="dependency_exists",
                    message=f"Task {tid} depends on nonexistent task ID '{dep}'.",
                    task_id=tid
                ))
            else:
                adj_list[tid].append(dep)

    # Cycle detection using DFS
    visited = {}  # 0 = unvisited, 1 = visiting, 2 = visited
    cycle_detected = False

    def dfs(node: str, path: List[str]):
        nonlocal cycle_detected
        visited[node] = 1
        for neighbor in adj_list.get(node, []):
            if visited.get(neighbor, 0) == 1:
                cycle_detected = True
                cycle_path = " -> ".join(path + [neighbor])
                errors.append(ValidationErrorDetail(
                    rule="no_dependency_cycles",
                    message=f"Circular dependency detected in graph: {cycle_path}",
                    task_id=node
                ))
            elif visited.get(neighbor, 0) == 0:
                dfs(neighbor, path + [neighbor])
        visited[node] = 2

    for tid in task_ids:
        if visited.get(tid, 0) == 0:
            dfs(tid, [tid])

    # 2. Field-level business rules
    for t in tasks:
        tid = t.get("id", "UNKNOWN")
        owner = t.get("owner")
        due_date = t.get("due_date")
        goal = t.get("goal")
        source_quote = t.get("source_quote", "")
        needs_confirm = t.get("needs_confirmation", False)

        # Rule: Owner must exist in team list if specified
        if owner is not None:
            if owner not in team_names:
                errors.append(ValidationErrorDetail(
                    rule="owner_in_team",
                    message=f"Task {tid} has owner '{owner}' not in team roster {list(team_names)}.",
                    task_id=tid
                ))

        # Rule: Due date must be on or after meeting date
        if due_date and meeting_date_str:
            if due_date < meeting_date_str:
                errors.append(ValidationErrorDetail(
                    rule="due_date_not_past",
                    message=f"Task {tid} has due date {due_date} before meeting date {meeting_date_str}.",
                    task_id=tid
                ))

        # Rule: Goal must exist in goals list if specified
        if goal is not None and goal not in valid_goal_ids:
            errors.append(ValidationErrorDetail(
                rule="goal_exists",
                message=f"Task {tid} references goal '{goal}' not found in goals list {list(valid_goal_ids)}.",
                task_id=tid
            ))

        # Rule: Verbatim source quote check (normalized)
        if source_quote:
            norm_quote = normalize_text(source_quote)
            if norm_quote not in normalized_note:
                warnings.append(ValidationErrorDetail(
                    rule="source_quote_verbatim",
                    message=f"Task {tid} source quote could not be matched verbatim in meeting note.",
                    task_id=tid
                ))
        else:
            errors.append(ValidationErrorDetail(
                rule="source_quote_required",
                message=f"Task {tid} is missing source quote.",
                task_id=tid
            ))

        # Rule: If owner is null or due_date is null, needs_confirmation must be True
        if (owner is None or due_date is None) and not needs_confirm:
            errors.append(ValidationErrorDetail(
                rule="unassigned_needs_confirmation",
                message=f"Task {tid} is missing owner or due date but needs_confirmation is False.",
                task_id=tid
            ))

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

