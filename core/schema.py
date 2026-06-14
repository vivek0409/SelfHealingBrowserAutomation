from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime

class FlowStep(BaseModel):
    step_id: int
    action: str  # click | fill | navigate | select | hover | assert
    selector: Optional[str] = None
    selector_strategy: Optional[str] = None  # css | xpath | text | role | testid
    value: Optional[str] = None
    description: Optional[str] = None
    timeout_ms: int = 5000

class FlowSchema(BaseModel):
    flow_id: str
    flow_name: str
    url: str
    steps: List[FlowStep]
    created_at: str
    target_framework: str = "playwright"

class RunArtifacts(BaseModel):
    log: str
    screenshot: Optional[str] = None
    video: Optional[str] = None
    dom_snapshot: Optional[str] = None

class RunError(BaseModel):
    type: str
    message: str
    step_id: Optional[int] = None
    selector: Optional[str] = None

class RunReport(BaseModel):
    run_id: str
    flow_id: str
    status: str  # pass | fail | error | skipped
    duration_ms: int
    browser: str  # chromium | firefox | webkit
    artifacts: RunArtifacts
    error: Optional[RunError] = None
    timestamp: str

class DiagnosisReport(BaseModel):
    diagnosis_id: str
    run_id: str
    error_type: str  # broken_selector | timeout | navigation_failure | assertion_failure | server_error | auth_failure | unknown
    confidence: float
    affected_step: int
    affected_selector: Optional[str] = None
    suggested_alternatives: List[str] = []
    repair_eligible: bool
    explanation: str
