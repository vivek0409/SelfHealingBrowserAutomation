import uuid
import os
from typing import Optional
import json
from core.schema import RunReport, DiagnosisReport, FlowSchema
from core.llm import call_llm

SYSTEM_PROMPT = """
You are the Error Diagnosis Agent. Your job is to analyze browser automation script failures.
You will be given the original FlowSchema, the generated script, the run log, and a DOM snapshot (HTML) at the time of failure.

Determine the type of error. The allowed error types are:
- broken_selector
- timeout
- navigation_failure
- assertion_failure
- server_error
- auth_failure
- unknown

Identify the affected step number (1-indexed), the selector that caused the issue (if any), and provide a confidence rating (0.0 to 1.0).
If the error is a `broken_selector`, suggest alternative selectors that match a REAL element in the DOM snapshot.
- A common root cause is a FABRICATED id built from human text or an href fragment (e.g. the
  failed selector "#Holding_companies" when the page only has a link whose text is
  "Holding companies"). When the target is best identified by its visible label, suggest a
  Playwright TEXT selector using SINGLE quotes so it embeds in the script's double-quoted
  string, e.g. `text='Holding companies'` or `a:has-text('Holding companies')`.
- Prefer, in order: real `#id`, `[data-testid='...']`, `[name='...']`, `[aria-label='...']`,
  then `text='...'`. Never invent an attribute value that is not present in the DOM snapshot.

IMPORTANT — distinguish a real timeout from an intercepted click:
- If the log contains "intercepts pointer events", "element is visible, enabled and stable",
  or mentions an overlay/modal/popover (e.g. a-modal-scroller, a-popover, onetrust,
  cookie/consent banner) covering the target, the element WAS found but a blocking overlay
  prevented the action. Do NOT classify this as a plain `timeout` whose fix is a longer wait.
  Classify it as `timeout` (the allowed type) BUT set the explanation to clearly state an
  overlay is intercepting the click, and put concrete dismissal hints in
  `suggested_alternatives` — e.g. the close/accept button selector visible in the DOM
  snapshot, "press Escape", or "use force click". This steers the repair toward dismissing
  the overlay rather than increasing the timeout.

Classify whether the repair is eligible (we attempt repair for `broken_selector` and `timeout`,
including overlay-interception cases described above).

Format the response strictly as a JSON object matching this schema:
{
  "error_type": "broken_selector | timeout | navigation_failure | assertion_failure | server_error | auth_failure | unknown",
  "confidence": 0.9,
  "affected_step": 2,
  "affected_selector": "#selector-that-failed",
  "suggested_alternatives": [".suggested-class", "[data-testid='btn']"],
  "repair_eligible": true,
  "explanation": "Brief explanation of why it failed and how to fix it."
}

Do not wrap response in markdown code blocks. Return raw JSON.
"""

def diagnose_run(
    run: RunReport,
    flow: FlowSchema,
    script_content: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None
) -> DiagnosisReport:
    # Read the log
    log_content = ""
    if run.artifacts.log and os.path.exists(run.artifacts.log):
        with open(run.artifacts.log, "r", encoding="utf-8") as f:
            log_content = f.read()
            
    # Read DOM snapshot
    dom_content = ""
    if run.artifacts.dom_snapshot and os.path.exists(run.artifacts.dom_snapshot):
        with open(run.artifacts.dom_snapshot, "r", encoding="utf-8") as f:
            # Truncate DOM snapshot to keep LLM context reasonable (e.g. first 50,000 characters)
            dom_content = f.read()[:50000]
            
    user_prompt = f"""
    Flow Name: {flow.flow_name}
    Steps: {json.dumps([step.dict() for step in flow.steps], indent=2)}
    
    Original Generated Script:
    {script_content}
    
    Execution Run Error:
    {json.dumps(run.error.dict() if run.error else {}, indent=2)}
    
    Run Logs:
    {log_content}
    
    DOM Snapshot (Truncated if large):
    {dom_content}
    """
    
    response_text = call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=api_key,
        provider=provider,
        base_url=base_url,
        model=model
    )
    
    # Strip markdown if any
    clean_text = response_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()
    
    diag_data = json.loads(clean_text)
    
    return DiagnosisReport(
        diagnosis_id=str(uuid.uuid4()),
        run_id=run.run_id,
        error_type=diag_data.get("error_type", "unknown"),
        confidence=diag_data.get("confidence", 0.5),
        affected_step=diag_data.get("affected_step", 1),
        affected_selector=diag_data.get("affected_selector"),
        suggested_alternatives=diag_data.get("suggested_alternatives", []),
        repair_eligible=diag_data.get("repair_eligible", False),
        explanation=diag_data.get("explanation", "Unknown error")
    )
