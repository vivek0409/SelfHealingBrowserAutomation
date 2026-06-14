import os
import sys

# Ensure the project root is importable when launched directly as
# `python api/main.py` (in that case only the api/ dir is on sys.path,
# so `from api.routes ...` would otherwise fail with ModuleNotFoundError).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import flows, runs, regression

app = FastAPI(
    title="Browser Automation AI Agent",
    description="E2E Self-Healing Browser Automation System",
    version="1.0"
)

# Allow CORS for all origins (frontend development support)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include sub-routers
app.include_router(flows.router, prefix="/api/flows", tags=["flows"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(regression.router, prefix="/api/regression", tags=["regression"])

# Define paths
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")
GENERATED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generated")

# Created at startup so a fresh clone (git does not track empty folders) always
# has these directories before the first generate / save / run.
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)

# Mount artifacts folder statically to allow viewing screenshots/logs directly in the browser
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")

# Fallback route to serve frontend app
@app.get("/")
def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Browser Automation AI Agent API is running. Create static/index.html to view dashboard."}

# Mount static directory at last so index fallback works properly
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    # Auto-reload only watches SOURCE folders. The app writes generated scripts and
    # run artifacts at runtime; if the reloader watched those, it would restart the
    # server mid-run and kill in-flight requests (e.g. "Run Automation" doing nothing).
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[
            os.path.join(PROJECT_ROOT, "api"),
            os.path.join(PROJECT_ROOT, "core"),
            os.path.join(PROJECT_ROOT, "agents"),
            os.path.join(PROJECT_ROOT, "static"),
        ],
    )
