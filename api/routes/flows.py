from fastapi import APIRouter, Header, HTTPException, Body
from typing import Optional, List
from core import storage
from core.schema import FlowSchema
from agents import flow_discovery, script_generator
import os

router = APIRouter()
GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "generated")

@router.post("/discover", response_model=FlowSchema)
def discover_endpoint(
    url: str = Body(..., embed=True),
    goal: str = Body(..., embed=True),
    x_api_key: Optional[str] = Header(None),
    x_api_provider: Optional[str] = Header("openai"),
    x_api_base_url: Optional[str] = Header(None),
    x_api_model: Optional[str] = Header(None)
):
    if not x_api_key:
        raise HTTPException(status_code=400, detail="Missing API Key in headers (X-API-Key)")

    try:
        flow = flow_discovery.discover_flow(
            url=url,
            goal=goal,
            api_key=x_api_key,
            provider=x_api_provider,
            base_url=x_api_base_url,
            model=x_api_model
        )
        storage.save_flow(flow)
        return flow
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Flow discovery failed: {str(e)}")

@router.get("", response_model=List[FlowSchema])
def list_flows():
    return storage.get_all_flows()

@router.get("/{flow_id}", response_model=FlowSchema)
def get_flow(flow_id: str):
    flow = storage.get_flow(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow

@router.post("/{flow_id}/generate")
def generate_endpoint(
    flow_id: str,
    x_api_key: Optional[str] = Header(None),
    x_api_provider: Optional[str] = Header("openai"),
    x_api_base_url: Optional[str] = Header(None),
    x_api_model: Optional[str] = Header(None)
):
    if not x_api_key:
        raise HTTPException(status_code=400, detail="Missing API Key in headers (X-API-Key)")

    flow = storage.get_flow(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    try:
        code = script_generator.generate_script(
            flow=flow,
            api_key=x_api_key,
            provider=x_api_provider,
            base_url=x_api_base_url,
            model=x_api_model
        )
        os.makedirs(GENERATED_DIR, exist_ok=True)
        script_path = os.path.join(GENERATED_DIR, f"{flow_id}.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
        return {"status": "success", "code": code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Script generation failed: {str(e)}")

@router.get("/{flow_id}/script")
def get_script_endpoint(flow_id: str):
    """Return the currently saved generated script (without regenerating via the LLM)."""
    if not storage.get_flow(flow_id):
        raise HTTPException(status_code=404, detail="Flow not found")
    script_path = os.path.join(GENERATED_DIR, f"{flow_id}.py")
    if not os.path.exists(script_path):
        return {"exists": False, "code": ""}
    with open(script_path, "r", encoding="utf-8") as f:
        return {"exists": True, "code": f.read()}

@router.put("/{flow_id}/script")
def save_script_endpoint(flow_id: str, code: str = Body(..., embed=True)):
    """Persist user-edited script content to disk so the next run uses it."""
    if not storage.get_flow(flow_id):
        raise HTTPException(status_code=404, detail="Flow not found")
    if not code or not code.strip():
        raise HTTPException(status_code=400, detail="Script content is empty.")
    # Reject content that isn't valid Python so a bad paste can't break the run.
    try:
        compile(code, "<edited_script>", "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Script has a syntax error at line {e.lineno}: {e.msg}")
    os.makedirs(GENERATED_DIR, exist_ok=True)
    script_path = os.path.join(GENERATED_DIR, f"{flow_id}.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    return {"status": "success"}
