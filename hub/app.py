"""
PartnerDesk Hub — v0.1
----------------------
Local FastAPI dashboard for PartnerDeskAI. Reuses the same data sources
the CLI scripts use (status._gather_status, summaries/, logs/) and runs
the existing `daily_ops.py` orchestrator via subprocess for actions.

Run:
    uvicorn hub.app:app --reload --port 8787

Open:
    http://127.0.0.1:8787

This file never writes anything on its own — file writes happen inside
the underlying scripts (daily_runner, status_snapshot, morning_summary).
The Hub only reads files and POSTs to those scripts.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


ROOT = Path(__file__).resolve().parent.parent
HUB_DIR = Path(__file__).resolve().parent

# Make automation/ importable so we can reuse status._gather_status().
sys.path.insert(0, str(ROOT / "automation"))
import status as status_mod  # noqa: E402


app = FastAPI(title="PartnerDesk Hub")
app.mount("/static", StaticFiles(directory=str(HUB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(HUB_DIR / "templates"))


# --- Pages -----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


# --- Read-only data endpoints ---------------------------------------------

@app.get("/api/status")
def api_status() -> JSONResponse:
    """Same dict as `python3 automation/status.py --json`."""
    return JSONResponse(status_mod._gather_status())


@app.get("/api/summary")
def api_summary() -> dict:
    """Read today's morning summary markdown, or report it's missing."""
    today = datetime.now().strftime("%Y-%m-%d")
    path = ROOT / "summaries" / f"{today}.md"
    if not path.is_file():
        return {
            "date": today,
            "exists": False,
            "content": (
                f"No summary for {today} yet. Click 'Refresh Summary Only' "
                "to generate one without calling OpenAI, or 'Run Daily Ops' "
                "to generate drafts plus the summary."
            ),
        }
    return {
        "date": today,
        "exists": True,
        "content": path.read_text(encoding="utf-8"),
    }


@app.get("/api/logs/latest")
def api_logs_latest() -> dict:
    """Latest log file's last 80 lines."""
    logs_dir = ROOT / "logs"
    if not logs_dir.is_dir():
        return {"path": None, "lines": [], "message": "No logs/ directory yet."}
    log_files = [p for p in logs_dir.glob("*.log") if p.is_file()]
    if not log_files:
        return {"path": None, "lines": [], "message": "No log files yet."}
    latest = max(log_files, key=lambda p: p.stat().st_mtime)
    text = latest.read_text(encoding="utf-8", errors="replace")
    tail = text.splitlines()[-80:]
    return {
        "path": str(latest.relative_to(ROOT)),
        "modified": datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        "lines": tail,
    }


# --- Action endpoints ------------------------------------------------------

def _run(args: list[str]) -> dict:
    """Run a child process and return {exit_code, stdout, stderr}."""
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.post("/api/run/daily-ops")
def run_daily_ops() -> dict:
    """Full daily sequence: generate (calls OpenAI) + snapshot + summary."""
    return _run([sys.executable, str(ROOT / "automation" / "daily_ops.py")])


@app.post("/api/run/refresh")
def run_refresh() -> dict:
    """Snapshot + summary only. Does NOT call OpenAI."""
    return _run(
        [sys.executable, str(ROOT / "automation" / "daily_ops.py"), "--skip-generate"]
    )
