import os
import sqlite3
import json
from typing import List, Optional
from core.schema import FlowSchema, FlowStep, RunReport, RunArtifacts, RunError, DiagnosisReport

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db.sqlite")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create flows table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS flows (
        flow_id TEXT PRIMARY KEY,
        flow_name TEXT,
        url TEXT,
        steps_json TEXT,
        created_at TEXT,
        target_framework TEXT
    )
    """)
    
    # Create runs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        flow_id TEXT,
        status TEXT,
        duration_ms INTEGER,
        browser TEXT,
        artifacts_json TEXT,
        error_json TEXT,
        timestamp TEXT
    )
    """)
    
    # Create diagnoses table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS diagnoses (
        diagnosis_id TEXT PRIMARY KEY,
        run_id TEXT,
        error_type TEXT,
        confidence REAL,
        affected_step INTEGER,
        affected_selector TEXT,
        suggested_alternatives_json TEXT,
        repair_eligible INTEGER,
        explanation TEXT
    )
    """)
    
    # Create baselines table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS baselines (
        flow_id TEXT PRIMARY KEY,
        screenshot_path TEXT,
        updated_at TEXT
    )
    """)
    
    conn.commit()
    conn.close()

# Initialize DB on import/startup
init_db()

def save_flow(flow: FlowSchema):
    conn = get_connection()
    cursor = conn.cursor()
    steps_list = [step.dict() for step in flow.steps]
    cursor.execute("""
    INSERT OR REPLACE INTO flows (flow_id, flow_name, url, steps_json, created_at, target_framework)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        flow.flow_id,
        flow.flow_name,
        flow.url,
        json.dumps(steps_list),
        flow.created_at,
        flow.target_framework
    ))
    conn.commit()
    conn.close()

def get_flow(flow_id: str) -> Optional[FlowSchema]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM flows WHERE flow_id = ?", (flow_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    
    steps = [FlowStep(**step) for step in json.loads(row["steps_json"])]
    return FlowSchema(
        flow_id=row["flow_id"],
        flow_name=row["flow_name"],
        url=row["url"],
        steps=steps,
        created_at=row["created_at"],
        target_framework=row["target_framework"]
    )

def get_all_flows() -> List[FlowSchema]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM flows ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    flows = []
    for row in rows:
        steps = [FlowStep(**step) for step in json.loads(row["steps_json"])]
        flows.append(FlowSchema(
            flow_id=row["flow_id"],
            flow_name=row["flow_name"],
            url=row["url"],
            steps=steps,
            created_at=row["created_at"],
            target_framework=row["target_framework"]
        ))
    return flows

def save_run(run: RunReport):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO runs (run_id, flow_id, status, duration_ms, browser, artifacts_json, error_json, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run.run_id,
        run.flow_id,
        run.status,
        run.duration_ms,
        run.browser,
        json.dumps(run.artifacts.dict()),
        json.dumps(run.error.dict() if run.error else None),
        run.timestamp
    ))
    conn.commit()
    conn.close()

def get_run(run_id: str) -> Optional[RunReport]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    
    artifacts = RunArtifacts(**json.loads(row["artifacts_json"]))
    err_data = json.loads(row["error_json"])
    error = RunError(**err_data) if err_data else None
    
    return RunReport(
        run_id=row["run_id"],
        flow_id=row["flow_id"],
        status=row["status"],
        duration_ms=row["duration_ms"],
        browser=row["browser"],
        artifacts=artifacts,
        error=error,
        timestamp=row["timestamp"]
    )

def get_runs_by_flow(flow_id: str) -> List[RunReport]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs WHERE flow_id = ? ORDER BY timestamp DESC", (flow_id,))
    rows = cursor.fetchall()
    conn.close()
    
    runs = []
    for row in rows:
        artifacts = RunArtifacts(**json.loads(row["artifacts_json"]))
        err_data = json.loads(row["error_json"])
        error = RunError(**err_data) if err_data else None
        runs.append(RunReport(
            run_id=row["run_id"],
            flow_id=row["flow_id"],
            status=row["status"],
            duration_ms=row["duration_ms"],
            browser=row["browser"],
            artifacts=artifacts,
            error=error,
            timestamp=row["timestamp"]
        ))
    return runs

def get_all_runs() -> List[RunReport]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()
    
    runs = []
    for row in rows:
        artifacts = RunArtifacts(**json.loads(row["artifacts_json"]))
        err_data = json.loads(row["error_json"])
        error = RunError(**err_data) if err_data else None
        runs.append(RunReport(
            run_id=row["run_id"],
            flow_id=row["flow_id"],
            status=row["status"],
            duration_ms=row["duration_ms"],
            browser=row["browser"],
            artifacts=artifacts,
            error=error,
            timestamp=row["timestamp"]
        ))
    return runs

def save_diagnosis(diagnosis: DiagnosisReport):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO diagnoses (diagnosis_id, run_id, error_type, confidence, affected_step, affected_selector, suggested_alternatives_json, repair_eligible, explanation)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        diagnosis.diagnosis_id,
        diagnosis.run_id,
        diagnosis.error_type,
        diagnosis.confidence,
        diagnosis.affected_step,
        diagnosis.affected_selector,
        json.dumps(diagnosis.suggested_alternatives),
        1 if diagnosis.repair_eligible else 0,
        diagnosis.explanation
    ))
    conn.commit()
    conn.close()

def get_diagnosis(run_id: str) -> Optional[DiagnosisReport]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM diagnoses WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    
    return DiagnosisReport(
        diagnosis_id=row["diagnosis_id"],
        run_id=row["run_id"],
        error_type=row["error_type"],
        confidence=row["confidence"],
        affected_step=row["affected_step"],
        affected_selector=row["affected_selector"],
        suggested_alternatives=json.loads(row["suggested_alternatives_json"]),
        repair_eligible=bool(row["repair_eligible"]),
        explanation=row["explanation"]
    )

def save_baseline(flow_id: str, screenshot_path: str, timestamp: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO baselines (flow_id, screenshot_path, updated_at)
    VALUES (?, ?, ?)
    """, (flow_id, screenshot_path, timestamp))
    conn.commit()
    conn.close()

def get_baseline(flow_id: str) -> Optional[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM baselines WHERE flow_id = ?", (flow_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)
