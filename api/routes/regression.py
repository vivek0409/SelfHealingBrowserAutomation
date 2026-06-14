from fastapi import APIRouter, HTTPException, Body
from typing import Optional
from core import storage
from agents import regression_monitor
import shutil
import os
from datetime import datetime

router = APIRouter()
BASELINES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "artifacts", "baselines")
os.makedirs(BASELINES_DIR, exist_ok=True)

@router.post("/baseline")
def set_baseline_endpoint(
    flow_id: str = Body(..., embed=True),
    run_id: str = Body(..., embed=True)
):
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
        
    if not run.artifacts.screenshot or not os.path.exists(run.artifacts.screenshot):
        raise HTTPException(status_code=400, detail="Specified run does not have a valid screenshot artifact")
        
    # Copy run screenshot to permanent baseline storage
    baseline_filename = f"{flow_id}.png"
    baseline_path = os.path.join(BASELINES_DIR, baseline_filename)
    
    try:
        shutil.copy2(run.artifacts.screenshot, baseline_path)
        timestamp = datetime.utcnow().isoformat() + "Z"
        storage.save_baseline(flow_id, baseline_path, timestamp)
        return {"status": "success", "baseline_path": f"/artifacts/baselines/{baseline_filename}", "updated_at": timestamp}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set baseline: {str(e)}")

@router.get("/{flow_id}")
def get_baseline_endpoint(flow_id: str):
    baseline = storage.get_baseline(flow_id)
    if not baseline:
        return {"status": "not_set"}
    
    baseline_filename = f"{flow_id}.png"
    return {
        "status": "active",
        "baseline_path": f"/artifacts/baselines/{baseline_filename}",
        "updated_at": baseline["updated_at"]
    }
