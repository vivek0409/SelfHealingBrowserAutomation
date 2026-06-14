import uuid
import os
import json
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from core.schema import RunReport, DiagnosisReport, FlowSchema
from core.llm import get_llm

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

CRITICAL — for `broken_selector` errors, also determine the `root_cause`:
- `"redesign"`: The selector broke because the site's design changed (element renamed,
  restructured, or moved), BUT a functionally equivalent element DOES still exist somewhere
  in the DOM snapshot — same text, same role/purpose, or nearby in the DOM. Set
  `repair_eligible` to true; the selector can be swapped.
- `"element_removed"`: The element AND the functionality it represented are COMPLETELY GONE
  from the page. No equivalent element exists anywhere in the DOM snapshot. The site has
  removed this feature entirely. Set `repair_eligible` to false; the entire flow must be
  re-discovered against the updated site.
- `"other"`: The failure is not about a missing or changed element (e.g. timeout, auth,
  network). Set `repair_eligible` according to the error type as normal.

When classifying `root_cause` for `broken_selector`:
1. Search the DOM snapshot thoroughly for any element with the same visible text, aria-label,
   placeholder, role, or nearby structural position as the failing selector.
2. If you find at least one candidate — classify as `"redesign"` and list it in
   `suggested_alternatives`.
3. If the DOM snapshot has no trace of anything functionally equivalent — classify as
   `"element_removed"` and leave `suggested_alternatives` empty.

Format the response strictly as a JSON object matching this schema:
{{
  "error_type": "broken_selector | timeout | navigation_failure | assertion_failure | server_error | auth_failure | unknown",
  "confidence": 0.9,
  "affected_step": 2,
  "affected_selector": "#selector-that-failed",
  "suggested_alternatives": [".suggested-class", "[data-testid='btn']"],
  "repair_eligible": true,
  "root_cause": "redesign | element_removed | other",
  "explanation": "Brief explanation of why it failed and how to fix it."
}}

Do not wrap response in markdown code blocks. Return raw JSON.
"""

_DIAGNOSE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", (
        "Flow Name: {flow_name}\n"
        "Steps: {steps}\n\n"
        "Original Generated Script:\n{script}\n\n"
        "Execution Run Error:\n{error}\n\n"
        "Run Logs:\n{logs}\n\n"
        "DOM Snapshot (Truncated if large):\n{dom}"
    )),
])


def diagnose_run(
    run: RunReport,
    flow: FlowSchema,
    script_content: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> DiagnosisReport:
    log_content = ""
    if run.artifacts.log and os.path.exists(run.artifacts.log):
        with open(run.artifacts.log, "r", encoding="utf-8") as f:
            log_content = f.read()

    dom_content = ""
    if run.artifacts.dom_snapshot and os.path.exists(run.artifacts.dom_snapshot):
        with open(run.artifacts.dom_snapshot, "r", encoding="utf-8") as f:
            dom_content = f.read()[:50000]

    llm = get_llm(api_key, provider, base_url, model)
    # JsonOutputParser strips markdown fences and parses JSON automatically
    chain = _DIAGNOSE_PROMPT | llm | JsonOutputParser()

    diag_data = chain.invoke({
        "flow_name": flow.flow_name,
        "steps": json.dumps([step.dict() for step in flow.steps], indent=2),
        "script": script_content,
        "error": json.dumps(run.error.dict() if run.error else {}, indent=2),
        "logs": log_content,
        "dom": dom_content,
    })

    return DiagnosisReport(
        diagnosis_id=str(uuid.uuid4()),
        run_id=run.run_id,
        error_type=diag_data.get("error_type", "unknown"),
        confidence=diag_data.get("confidence", 0.5),
        affected_step=diag_data.get("affected_step", 1),
        affected_selector=diag_data.get("affected_selector"),
        suggested_alternatives=diag_data.get("suggested_alternatives", []),
        repair_eligible=diag_data.get("repair_eligible", False),
        root_cause=diag_data.get("root_cause", "other"),
        explanation=diag_data.get("explanation", "Unknown error"),
    )
