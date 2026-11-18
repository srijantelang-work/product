from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class TaskItem(BaseModel):
    id: str = Field(description="Unique task identifier, e.g. task-1, task-2")
    title: str = Field(description="Actionable title of the task")
    owner: Optional[str] = Field(default=None, description="Assigned team member name matching team roster, or null if unassigned")
    due_date: Optional[str] = Field(default=None, description="ISO format date YYYY-MM-DD or null if unspecified/ambiguous")
    goal: Optional[str] = Field(default=None, description="Goal ID or Goal Name matched to goals file, or null")
    depends_on: List[str] = Field(default_factory=list, description="List of task IDs that must be completed before this task can start")
    confidence: Literal["high", "medium", "low"] = Field(description="Extraction confidence level")
    needs_confirmation: bool = Field(description="True if owner is missing, date is ambiguous, or instruction is unclear")
    reason: Optional[str] = Field(default=None, description="Explanation when needs_confirmation is true; null otherwise")
    source_quote: str = Field(description="The exact snippet or sentence from the meeting note that supports this task")

class IgnoredRemark(BaseModel):
    quote: str = Field(description="Exact quote or phrase from the meeting note that was classified as non-actionable chatter")
    reason: str = Field(description="Why this was classified as chatter rather than an actionable task")

class MeetingExtractionOutput(BaseModel):
    meeting_date: str = Field(description="Date of the meeting in ISO format YYYY-MM-DD")
    tasks: List[TaskItem] = Field(default_factory=list, description="List of proposed tasks extracted from the meeting")
    ignored_remarks: List[IgnoredRemark] = Field(default_factory=list, description="List of remarks explicitly ignored as chatter")

