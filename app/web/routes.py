import os
import json
import shutil
from datetime import datetime
from fastapi import APIRouter, Request, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.runs import storage, service

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

DATA_DIR = "/opt/ai-lab/ai-senate/data"
SPEC_FILE_PATH = os.path.join(DATA_DIR, "spec.md")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Renders the main control page, loading current spec.md content if available."""
    spec_content = ""
    if os.path.exists(SPEC_FILE_PATH):
        with open(SPEC_FILE_PATH, "r", encoding="utf-8") as f:
            spec_content = f.read()
            
    runs = storage.list_runs()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "spec_content": spec_content,
            "runs": runs
        }
    )

@router.post("/runs", response_class=HTMLResponse)
async def start_run(
    request: Request,
    background_tasks: BackgroundTasks,
    new_document: bool = Form(False),
    spec_text: str = Form(""),
    owner_input: str = Form(""),
    max_rounds: int = Form(2),
    auto_stop_if_clean: bool = Form(True)
):
    """Starts a council run, schedules background task execution, and returns status fragment."""
    if new_document and not owner_input.strip():
        run_id = "validation-error"
        run_data = {
            "run_id": run_id,
            "status": "failed",
            "error": "Owner Input не может быть пустым при создании нового документа",
            "agents": {}
        }
        return templates.TemplateResponse(
            "partials/agent_status.html",
            {
                "request": request,
                "run_id": run_id,
                "run": run_data
            }
        )
        
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    
    # Register in DB
    storage.create_run(run_id, new_document, max_rounds=max_rounds, auto_stop_if_clean=auto_stop_if_clean)
    
    # Run the council process in background task
    background_tasks.add_task(
        service.run_council_task,
        run_id=run_id,
        spec_text=spec_text,
        owner_input=owner_input,
        new_document=new_document,
        max_rounds=max_rounds,
        auto_stop_if_clean=auto_stop_if_clean
    )
    
    run_data = {
        "run_id": run_id,
        "status": "queued",
        "agents": {}
    }
    
    return templates.TemplateResponse(
        "partials/agent_status.html",
        {
            "request": request,
            "run_id": run_id,
            "run": run_data
        }
    )

@router.get("/runs/{run_id}/status-fragment", response_class=HTMLResponse)
async def get_run_status(request: Request, run_id: str):
    """Returns the agent status fragment, dynamically instructing HTMX to poll or fetch results."""
    run_data = service.read_run_file(run_id)
    if not run_data:
        db_run = storage.get_run(run_id)
        if db_run:
            run_data = {
                "run_id": run_id,
                "status": db_run["status"],
                "agents": {}
            }
        else:
            raise HTTPException(status_code=404, detail="Запуск консилиума не найден")
            
    return templates.TemplateResponse(
        "partials/agent_status.html",
        {
            "request": request,
            "run_id": run_id,
            "run": run_data
        }
    )

@router.get("/runs/{run_id}/results-fragment", response_class=HTMLResponse)
async def get_run_results(request: Request, run_id: str):
    """Fetches and displays findings, consensus decisions, and synthesized specifications."""
    run_dir = os.path.join(DATA_DIR, "runs", run_id)
    
    findings_path = os.path.join(run_dir, "findings.json")
    consensus_path = os.path.join(run_dir, "consensus.json")
    updated_spec_path = os.path.join(run_dir, "updated-spec.md")
    
    findings_data = {}
    if os.path.exists(findings_path):
        with open(findings_path, "r", encoding="utf-8") as f:
            findings_data = json.load(f)
            
    consensus_data = {}
    if os.path.exists(consensus_path):
        with open(consensus_path, "r", encoding="utf-8") as f:
            consensus_data = json.load(f)
            
    updated_spec = ""
    if os.path.exists(updated_spec_path):
        with open(updated_spec_path, "r", encoding="utf-8") as f:
            updated_spec = f.read()
            
    return templates.TemplateResponse(
        "partials/results.html",
        {
            "request": request,
            "run_id": run_id,
            "findings": findings_data,
            "consensus": consensus_data,
            "updated_spec": updated_spec
        }
    )

@router.get("/runs/{run_id}/consensus-fragment", response_class=HTMLResponse)
async def get_run_consensus(request: Request, run_id: str):
    """Fetches and displays the consensus summary."""
    run_dir = os.path.join(DATA_DIR, "runs", run_id)
    consensus_path = os.path.join(run_dir, "consensus.json")
    
    consensus_data = {}
    if os.path.exists(consensus_path):
        with open(consensus_path, "r", encoding="utf-8") as f:
            consensus_data = json.load(f)
            
    return templates.TemplateResponse(
        "partials/consensus_summary.html",
        {
            "request": request,
            "run_id": run_id,
            "consensus": consensus_data
        }
    )

@router.get("/runs/{run_id}/findings-fragment", response_class=HTMLResponse)
async def get_run_findings(request: Request, run_id: str):
    """Fetches and displays findings/risks."""
    run_dir = os.path.join(DATA_DIR, "runs", run_id)
    findings_path = os.path.join(run_dir, "findings.json")
    
    findings_data = {}
    if os.path.exists(findings_path):
        with open(findings_path, "r", encoding="utf-8") as f:
            findings_data = json.load(f)
            
    return templates.TemplateResponse(
        "partials/findings.html",
        {
            "request": request,
            "run_id": run_id,
            "findings": findings_data
        }
    )

@router.get("/runs/{run_id}/updated-spec-fragment", response_class=HTMLResponse)
async def get_run_updated_spec(request: Request, run_id: str):
    """Fetches and displays synthesized specification."""
    run_dir = os.path.join(DATA_DIR, "runs", run_id)
    updated_spec_path = os.path.join(run_dir, "updated-spec.md")
    
    updated_spec = ""
    if os.path.exists(updated_spec_path):
        with open(updated_spec_path, "r", encoding="utf-8") as f:
            updated_spec = f.read()
            
    return templates.TemplateResponse(
        "partials/updated_spec.html",
        {
            "request": request,
            "run_id": run_id,
            "updated_spec": updated_spec
        }
    )

@router.get("/runs/{run_id}/changes-fragment", response_class=HTMLResponse)
async def get_run_changes(request: Request, run_id: str):
    """Fetches and displays the Changes Summary."""
    run_dir = os.path.join(DATA_DIR, "runs", run_id)
    changes_path = os.path.join(run_dir, "changes.json")
    
    changes_data = {}
    if os.path.exists(changes_path):
        with open(changes_path, "r", encoding="utf-8") as f:
            changes_data = json.load(f)
            
    return templates.TemplateResponse(
        "partials/changes_summary.html",
        {
            "request": request,
            "run_id": run_id,
            "changes": changes_data
        }
    )

@router.get("/runs/{run_id}/round-log-fragment", response_class=HTMLResponse)
async def get_run_round_log(request: Request, run_id: str):
    """Fetches and displays the Round Log."""
    run_dir = os.path.join(DATA_DIR, "runs", run_id)
    run_file = os.path.join(run_dir, "run.json")
    
    round_log = []
    if os.path.exists(run_file):
        with open(run_file, "r", encoding="utf-8") as f:
            run_data = json.load(f)
            round_log = run_data.get("round_log", [])
            
    return templates.TemplateResponse(
        "partials/round_log.html",
        {
            "request": request,
            "run_id": run_id,
            "round_log": round_log
        }
    )

@router.post("/runs/{run_id}/accept", response_class=HTMLResponse)
async def accept_spec(request: Request, run_id: str):
    """Accepts the run's synthesized specification, copying it to data/spec.md."""
    run_dir = os.path.join(DATA_DIR, "runs", run_id)
    updated_spec_path = os.path.join(run_dir, "updated-spec.md")
    
    if not os.path.exists(updated_spec_path):
        raise HTTPException(status_code=404, detail="Синтезированное ТЗ не найдено")
        
    os.makedirs(DATA_DIR, exist_ok=True)
    shutil.copy2(updated_spec_path, SPEC_FILE_PATH)
    
    return HTMLResponse(content="""
        <div class="alert alert-success mt-4 animate-fade-in" id="accept-banner">
            <h4 class="alert-heading">✓ Новая спецификация принята!</h4>
            <p>Файл успешно скопирован в <code>data/spec.md</code> и назначен как текущий.</p>
        </div>
    """)
