import os
import shutil
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from core.schema import DiagnosisReport
from core.llm import get_llm

SYSTEM_PROMPT = """
You are the Adaptive Repair Agent. Your task is to auto-patch a broken Playwright Python script based on a DiagnosisReport.

Guidelines:
1. ONLY modify the line(s) causing the failure (e.g., replace the incorrect selector with one of the suggested alternatives, or increase a timeout).
2. NEVER modify assertion logic, test flow ordering, or other steps that are passing.
3. Keep the overall script structure, import statements, try-except harness, and argument parsing exactly the same.
4. Ensure the output is a valid, compilable Python script.
5. OVERLAY / "intercepts pointer events" failures: if the diagnosis or explanation says an
   overlay, modal, popover, or cookie/consent banner is intercepting the click (rather than
   the element being missing), DO NOT just increase the timeout — that will not help. Instead,
   immediately BEFORE the failing click, insert code to dismiss the blocking overlay, then
   click. Prefer, in order: (a) click the close/accept button selector named in the diagnosis
   (e.g. `page.click("<close_selector>", timeout=2000)` wrapped in try/except), (b)
   `page.keyboard.press("Escape")`, then (c) as a last resort change the failing click to a
   forced click by adding `force=True` (e.g. `page.click(selector, timeout=timeout, force=True)`).
   If the script already defines a `safe_click`/`dismiss_overlays` helper, route the failing
   click through `safe_click(page, selector, timeout)` instead of `page.click(...)`.
   Wrap any best-effort dismissal in try/except so it never crashes the run.

Output ONLY the fully patched Python script code. Do not wrap the response in markdown code blocks (like ```python) or include extra text.
"""

_REPAIR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", (
        "Original Script content:\n{script}\n\n"
        "Diagnosis Report:\n"
        "- Error Type: {error_type}\n"
        "- Affected Step: {affected_step}\n"
        "- Affected Selector: {affected_selector}\n"
        "- Suggested Selector/Wait Alternatives: {suggested_alternatives}\n"
        "- Explanation: {explanation}\n\n"
        "Please provide the corrected script content."
    )),
])


def _strip_fences(code: str) -> str:
    code = code.strip()
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
    return code.strip()


def repair_script(
    flow_id: str,
    original_script: str,
    diagnosis: DiagnosisReport,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    generated_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generated")
    original_path = os.path.join(generated_dir, f"{flow_id}.py")
    if os.path.exists(original_path):
        backup_path = os.path.join(generated_dir, f"{flow_id}_backup.py")
        shutil.copy2(original_path, backup_path)
        print(f"Backed up original script to {backup_path}")

    llm = get_llm(api_key, provider, base_url, model)
    chain = _REPAIR_PROMPT | llm | StrOutputParser()

    patched_code = chain.invoke({
        "script": original_script,
        "error_type": diagnosis.error_type,
        "affected_step": diagnosis.affected_step,
        "affected_selector": diagnosis.affected_selector,
        "suggested_alternatives": diagnosis.suggested_alternatives,
        "explanation": diagnosis.explanation,
    })

    patched_code = _strip_fences(patched_code)

    try:
        compile(patched_code, "<patched_script>", "exec")
    except SyntaxError as e:
        print(f"Repair produced invalid Python (line {e.lineno}: {e.msg}); keeping original script.")
        return original_script

    return patched_code
