import os
import re
from typing import Optional, Dict, Literal
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END

from core.schema import FlowSchema, RunReport, DiagnosisReport
from core import storage
from agents import script_generator, execution_agent, error_diagnosis, adaptive_repair, regression_monitor

GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generated")


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class OrchState(TypedDict):
    # Static inputs
    flow_id: str
    max_repair_attempts: int
    api_key: str
    provider: str
    base_url: Optional[str]
    model: Optional[str]
    browser: str
    headless: bool
    # Mutable state updated by nodes
    flow: Optional[FlowSchema]
    script_content: str
    run_report: Optional[RunReport]
    diagnosis: Optional[DiagnosisReport]
    attempt: int   # number of repair attempts completed so far


# ---------------------------------------------------------------------------
# Selector-sync helpers (keep updated step selectors in the DB after repair)
# ---------------------------------------------------------------------------

def _parse_step_selectors(script: str) -> Dict[int, Optional[str]]:
    result: Dict[int, Optional[str]] = {}
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
    new_selectors = _parse_step_selectors(script)
    changed = False
    for step in flow.steps:
        if step.step_id in new_selectors:
            new_sel = new_selectors[step.step_id]
            if new_sel != step.selector:
                step.selector = new_sel
                changed = True
    return changed


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------

def prepare_node(state: OrchState) -> dict:
    """Load flow from DB; load the saved script or generate a new one."""
    flow = storage.get_flow(state["flow_id"])
    if not flow:
        raise ValueError(f"Flow {state['flow_id']} not found in database.")

    script_path = os.path.join(GENERATED_DIR, f"{state['flow_id']}.py")
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            script_content = f.read()
        print(f"[Orchestrator] Loaded existing script for: {flow.flow_name}")
    else:
        print(f"[Orchestrator] Generating script for: {flow.flow_name}")
        script_content = script_generator.generate_script(
            flow, state["api_key"], state["provider"], state["base_url"], state["model"]
        )

    return {"flow": flow, "script_content": script_content}


def execute_node(state: OrchState) -> dict:
    """Run the current script as a subprocess and save the run report."""
    print(f"[Orchestrator] Executing script (repair attempt {state['attempt']})...")
    run_report = execution_agent.execute_run(
        state["flow_id"],
        state["script_content"],
        state["browser"],
        state["headless"],
    )
    storage.save_run(run_report)
    return {"run_report": run_report}


def diagnose_node(state: OrchState) -> dict:
    """Ask the Error Diagnosis agent what went wrong."""
    print(f"[Orchestrator] Diagnosing failure...")
    try:
        diagnosis = error_diagnosis.diagnose_run(
            state["run_report"],
            state["flow"],
            state["script_content"],
            state["api_key"],
            state["provider"],
            state["base_url"],
            state["model"],
        )
        storage.save_diagnosis(diagnosis)
        print(f"[Orchestrator] Diagnosis: {diagnosis.error_type} — {diagnosis.explanation}")
    except Exception as e:
        print(f"[Orchestrator] Diagnosis failed: {e}")
        diagnosis = None
    return {"diagnosis": diagnosis}


def repair_node(state: OrchState) -> dict:
    """Patch the script and sync updated selectors back to the FlowSchema."""
    new_attempt = state["attempt"] + 1
    print(f"[Orchestrator] Repairing script (attempt {new_attempt}/{state['max_repair_attempts']})...")
    try:
        patched = adaptive_repair.repair_script(
            state["flow_id"],
            state["script_content"],
            state["diagnosis"],
            state["api_key"],
            state["provider"],
            state["base_url"],
            state["model"],
        )
        flow = state["flow"]
        if _sync_flow_steps_from_script(flow, patched):
            print("[Orchestrator] Flow steps updated with repaired selectors.")
            storage.save_flow(flow)
        new_script = patched
    except Exception as e:
        print(f"[Orchestrator] Repair failed: {e}; keeping current script.")
        new_script = state["script_content"]

    return {"script_content": new_script, "attempt": new_attempt}


def visual_diff_node(state: OrchState) -> dict:
    """Run a pixel-diff against the stored baseline if one exists."""
    baseline = storage.get_baseline(state["flow_id"])
    run_report = state["run_report"]
    if baseline and run_report and run_report.artifacts.screenshot:
        try:
            run_dir = os.path.dirname(run_report.artifacts.screenshot)
            comparison = regression_monitor.compare_screenshots(
                baseline["screenshot_path"],
                run_report.artifacts.screenshot,
                run_dir,
            )
            print(f"[Orchestrator] Visual diff: {comparison['diff_percentage']}% difference")
        except Exception as e:
            print(f"[Orchestrator] Visual diff failed: {e}")
    return {}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------

def route_after_execute(state: OrchState) -> Literal["diagnose", "visual_diff"]:
    run = state["run_report"]
    if run and run.status == "fail" and state["attempt"] < state["max_repair_attempts"]:
        return "diagnose"
    return "visual_diff"


def route_after_diagnose(state: OrchState) -> Literal["repair", "visual_diff"]:
    diag = state["diagnosis"]
    if diag and diag.repair_eligible:
        return "repair"
    print("[Orchestrator] Error not repair-eligible; escalating.")
    return "visual_diff"


# ---------------------------------------------------------------------------
# Build & compile the LangGraph graph (once at import time)
# ---------------------------------------------------------------------------

def _build_graph():
    g = StateGraph(OrchState)

    g.add_node("prepare",     prepare_node)
    g.add_node("execute",     execute_node)
    g.add_node("diagnose",    diagnose_node)
    g.add_node("repair",      repair_node)
    g.add_node("visual_diff", visual_diff_node)

    g.set_entry_point("prepare")
    g.add_edge("prepare", "execute")

    g.add_conditional_edges(
        "execute",
        route_after_execute,
        {"diagnose": "diagnose", "visual_diff": "visual_diff"},
    )
    g.add_conditional_edges(
        "diagnose",
        route_after_diagnose,
        {"repair": "repair", "visual_diff": "visual_diff"},
    )

    g.add_edge("repair",      "execute")
    g.add_edge("visual_diff", END)

    return g.compile()


_ORCH_GRAPH = _build_graph()


# ---------------------------------------------------------------------------
# Public API — identical signature to the previous implementation
# ---------------------------------------------------------------------------

def run_orchestrated_flow(
    flow_id: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    max_repair_attempts: int = 3,
) -> RunReport:
    """
    Run a flow end-to-end using a LangGraph state machine:
      prepare → execute → (on fail) diagnose → repair → execute …
      → visual_diff → END

    Returns the final RunReport (same as before).
    """
    initial_state: OrchState = {
        "flow_id":             flow_id,
        "flow":                None,
        "script_content":      "",
        "run_report":          None,
        "diagnosis":           None,
        "attempt":             0,
        "max_repair_attempts": max_repair_attempts,
        "api_key":             api_key,
        "provider":            provider,
        "base_url":            base_url,
        "model":               model,
        "browser":             browser,
        "headless":            headless,
    }

    final_state = _ORCH_GRAPH.invoke(initial_state)
    return final_state["run_report"]
