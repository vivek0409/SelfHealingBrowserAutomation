import os
import re
from datetime import datetime
from typing import Optional, Dict
from core.schema import FlowSchema, RunReport, DiagnosisReport
from core import storage
from agents import script_generator, execution_agent, error_diagnosis, adaptive_repair, regression_monitor

GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generated")


def _parse_step_selectors(script: str) -> Dict[int, Optional[str]]:
    """Extract {step_id: selector} from current_step / current_selector pairs in a generated script."""
    result = {}
    step_id = None
    for line in script.splitlines():
        s = line.strip()
        m = re.match(r'current_step\s*=\s*(\d+)', s)
        if m:
            step_id = int(m.group(1))
            continue
        if step_id is not None:
            m = re.match(r'current_selector\s*=\s*"(.*)"', s)
            if m:
                result[step_id] = m.group(1)
                step_id = None
                continue
            if re.match(r'current_selector\s*=\s*None', s):
                result[step_id] = None
                step_id = None
    return result


def _sync_flow_steps_from_script(flow: FlowSchema, script: str) -> bool:
    """Update flow.steps selectors to match what the repaired script uses. Returns True if anything changed."""
    new_selectors = _parse_step_selectors(script)
    changed = False
    for step in flow.steps:
        if step.step_id in new_selectors:
            new_sel = new_selectors[step.step_id]
            if new_sel != step.selector:
                step.selector = new_sel
                changed = True
    return changed

def run_orchestrated_flow(
    flow_id: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    max_repair_attempts: int = 3
) -> RunReport:
    """
    Orchestrates the running of a flow:
    - Generates script (if not exists)
    - Runs script
    - If failure: diagnoses -> repairs -> reruns (up to max_repair_attempts)
    - Saves final run report and visual comparison
    """
    flow = storage.get_flow(flow_id)
    if not flow:
        raise ValueError(f"Flow with ID {flow_id} not found in database.")
        
    script_path = os.path.join(GENERATED_DIR, f"{flow_id}.py")
    
    # 1. Ensure script exists, otherwise generate
    if not os.path.exists(script_path):
        print(f"Generating script for flow: {flow.flow_name}")
        script_content = script_generator.generate_script(flow, api_key, provider, base_url, model)
    else:
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()
            
    # 2. Run the script
    print(f"Executing run for flow: {flow.flow_name}")
    run_report = execution_agent.execute_run(flow_id, script_content, browser, headless)
    storage.save_run(run_report)
    
    # 3. Auto-healing / Self-repair loop
    attempt = 0
    while run_report.status == "fail" and attempt < max_repair_attempts:
        attempt += 1
        print(f"Run failed. Starting self-repair attempt {attempt}/{max_repair_attempts}...")
        
        # Diagnose the run
        try:
            diagnosis = error_diagnosis.diagnose_run(
                run_report, flow, script_content, api_key, provider, base_url, model
            )
            storage.save_diagnosis(diagnosis)
            print(f"Diagnosis complete: {diagnosis.error_type} - {diagnosis.explanation}")
            
            if not diagnosis.repair_eligible:
                print("Error is not eligible for automatic repair (e.g. server_error, auth_failure). Escalating.")
                break
                
            # Repair script
            print("Applying code patch...")
            patched_script = adaptive_repair.repair_script(
                flow_id, script_content, diagnosis, api_key, provider, base_url, model
            )
            script_content = patched_script

            # Sync updated selectors back to the FlowSchema so the UI shows the
            # repaired step (e.g. the new selector replacing the broken one).
            if _sync_flow_steps_from_script(flow, patched_script):
                print("Flow steps updated with repaired selectors.")
                storage.save_flow(flow)

            # Execute again
            print("Executing patched script...")
            run_report = execution_agent.execute_run(flow_id, script_content, browser, headless)
            storage.save_run(run_report)
            
        except Exception as e:
            print(f"Error during self-repair loop: {e}")
            break
            
    # 4. Perform visual diff if a baseline is configured and run succeeded or failed with visual artifact
    baseline = storage.get_baseline(flow_id)
    if baseline and run_report.artifacts.screenshot:
        try:
            run_dir = os.path.dirname(run_report.artifacts.screenshot)
            comparison = regression_monitor.compare_screenshots(
                baseline["screenshot_path"],
                run_report.artifacts.screenshot,
                run_dir
            )
            print(f"Visual diff complete: Diff percentage = {comparison['diff_percentage']}%")
        except Exception as e:
            print(f"Visual diff failed: {e}")
            
    return run_report
