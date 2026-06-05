import os
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from app.runs import storage, service
from app.opencode import get_client
from app.council_core.contracts import AgentResponseContract, ConsensusResultContract


log = logging.getLogger("ai_senate.api")
router = APIRouter(prefix="/api")


PROJECT_ROOT = os.environ.get(
    "AI_SENATE_ROOT",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
DATA_DIR = os.environ.get("AI_SENATE_DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
RUNS_DIR = os.path.join(DATA_DIR, "runs")
SPEC_FILE = os.path.join(DATA_DIR, "spec.md")
AGENTS_YAML = os.path.join(PROJECT_ROOT, "app", "config", "agents.yaml")
CONSENSUS_YAML = os.path.join(PROJECT_ROOT, "app", "config", "consensus.yaml")


# ----------------------- Models -----------------------

class CreateRunBody(BaseModel):
    spec_text: str = ""
    owner_input: str = ""
    new_document: bool = False
    max_rounds: int = 2
    auto_stop_if_clean: bool = True


class SpecBody(BaseModel):
    content: str


# ----------------------- Helpers -----------------------

def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _load_perspectives_config() -> Dict[str, Any]:
    if not os.path.exists(AGENTS_YAML):
        return {"perspectives": [], "writer": None, "juries": {"default": [], "synthesis": []}}
    try:
        with open(AGENTS_YAML, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}

    perspectives = []
    for key, p in (cfg.get("perspectives") or {}).items():
        if not p:
            continue
        perspectives.append({
            "key": key,
            "role": p.get("role", "reviewer"),
            "provider": p.get("provider", "cliproxy"),
            "model": p.get("model", ""),
            "enabled": bool(p.get("enabled", True)),
            "timeout_sec": p.get("timeout_sec", 180),
        })

    writer_cfg = cfg.get("writer") or {}
    writer = None
    if writer_cfg:
        writer = {
            "key": "writer",
            "role": writer_cfg.get("role", "Writer"),
            "provider": writer_cfg.get("provider", "cliproxy"),
            "model": writer_cfg.get("model", ""),
            "enabled": bool(writer_cfg.get("enabled", True)),
            "timeout_sec": writer_cfg.get("timeout_sec", 600),
        }

    juries = cfg.get("juries") or {"default": [], "synthesis": []}
    return {"perspectives": perspectives, "writer": writer, "juries": juries}


# ----------------------- Health & config -----------------------

@router.get("/health")
async def health():
    client = get_client()
    try:
        ok = await client.health()
    except Exception:
        ok = False
    return {
        "status": "ok",
        "opencode": {"reachable": ok, "base_url": client.base_url},
        "time": datetime.now().isoformat(),
    }


@router.get("/config")
async def get_config():
    return _load_perspectives_config()


# ----------------------- Spec file -----------------------

@router.get("/spec")
async def get_spec():
    return {"content": _read_text(SPEC_FILE)}


@router.put("/spec")
async def put_spec(body: SpecBody):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SPEC_FILE, "w", encoding="utf-8") as f:
        f.write(body.content or "")
    return {"status": "ok"}


# ----------------------- Runs -----------------------

@router.get("/runs")
async def list_runs():
    return storage.list_runs()


@router.post("/runs")
async def create_run(body: CreateRunBody, background_tasks: BackgroundTasks):
    if body.new_document and not (body.owner_input or "").strip():
        raise HTTPException(status_code=400, detail="owner_input required when new_document=true")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    storage.create_run(
        run_id,
        body.new_document,
        max_rounds=max(1, min(3, body.max_rounds)),
        auto_stop_if_clean=body.auto_stop_if_clean,
    )
    background_tasks.add_task(
        service.run_council_task,
        run_id=run_id,
        spec_text=body.spec_text,
        owner_input=body.owner_input,
        new_document=body.new_document,
        max_rounds=body.max_rounds,
        auto_stop_if_clean=body.auto_stop_if_clean,
    )
    return storage.get_run(run_id)


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str):
    """Removes DB row and best-effort removes run files."""
    conn_path = storage.DB_PATH
    import sqlite3
    conn = sqlite3.connect(conn_path)
    try:
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()
    import shutil
    run_dir = os.path.join(RUNS_DIR, run_id)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir, ignore_errors=True)
    return Response(status_code=204)


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run_file = os.path.join(RUNS_DIR, run_id, "run.json")
    data = _read_json(run_file, None)
    if not data:
        db_run = storage.get_run(run_id)
        if not db_run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {
            "run_id": db_run["id"],
            "status": db_run["status"],
            "phase": db_run["phase"],
            "current_round": db_run["current_round"],
            "max_rounds": db_run["max_rounds"],
            "auto_stop_if_clean": db_run["auto_stop_if_clean"],
            "new_document": db_run["new_document"],
            "started_at": db_run["created_at"],
            "finished_at": db_run.get("updated_at") if db_run["status"] == "done" else None,
            "agents": {},
            "round_log": [],
        }
    return data


@router.get("/runs/{run_id}/findings")
async def get_findings(run_id: str):
    path = os.path.join(RUNS_DIR, run_id, "findings.json")
    data = _read_json(path, None)
    if not data:
        raise HTTPException(status_code=404, detail="findings not found")
    return data


@router.get("/runs/{run_id}/consensus")
async def get_consensus(run_id: str):
    path = os.path.join(RUNS_DIR, run_id, "consensus.json")
    data = _read_json(path, None)
    if not data:
        raise HTTPException(status_code=404, detail="consensus not found")
    return data


@router.get("/runs/{run_id}/updated-spec")
async def get_updated_spec(run_id: str):
    path = os.path.join(RUNS_DIR, run_id, "updated-spec.md")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="updated-spec not found")
    return {"content": _read_text(path)}


@router.get("/runs/{run_id}/changes")
async def get_changes(run_id: str):
    path = os.path.join(RUNS_DIR, run_id, "changes.json")
    data = _read_json(path, None)
    if not data:
        raise HTTPException(status_code=404, detail="changes not found")
    return data


@router.get("/runs/{run_id}/round-log")
async def get_round_log(run_id: str):
    data = _read_json(os.path.join(RUNS_DIR, run_id, "run.json"), {}) or {}
    return {"round_log": data.get("round_log", [])}


@router.get("/runs/{run_id}/agents")
async def get_agents(run_id: str):
    """Aggregated agent status rows across all rounds."""
    rows: List[Dict[str, Any]] = []
    rounds_dir = os.path.join(RUNS_DIR, run_id)
    for entry in sorted(os.listdir(rounds_dir)) if os.path.isdir(rounds_dir) else []:
        if not entry.startswith("round-"):
            continue
        try:
            round_num = int(entry.split("-")[1])
        except (ValueError, IndexError):
            continue
        agents_dir = os.path.join(rounds_dir, entry, "agents")
        if not os.path.isdir(agents_dir):
            continue
        for agent in sorted(os.listdir(agents_dir)):
            status_path = os.path.join(agents_dir, agent, "status.json")
            if not os.path.isfile(status_path):
                continue
            sd = _read_json(status_path, {}) or {}
            sd["agent"] = agent
            sd["round"] = round_num
            rows.append(sd)
    # Also writer if present
    writer_dir = os.path.join(rounds_dir, "agents", "writer")
    if os.path.isdir(writer_dir):
        sd = _read_json(os.path.join(writer_dir, "status.json"), {}) or {}
        sd["agent"] = "writer"
        sd["round"] = "writer"
        rows.append(sd)
    return rows


@router.get("/runs/{run_id}/rounds/{round_num}/agents/{agent}")
async def get_agent_artifact(run_id: str, round_num: int, agent: str):
    if round_num == 0:
        base = os.path.join(RUNS_DIR, run_id, "agents", agent)
    else:
        base = os.path.join(RUNS_DIR, run_id, f"round-{round_num}", "agents", agent)
    status = _read_json(os.path.join(base, "status.json"), None)
    parsed = _read_json(os.path.join(base, "parsed-output.json"), None)
    raw = _read_text(os.path.join(base, "raw-output.txt"))
    user_prompt = _read_text(os.path.join(base, "prompt.md"))
    if not status:
        raise HTTPException(status_code=404, detail="agent artifact not found")
    return {
        "agent": agent,
        "round": round_num,
        "status": status.get("status"),
        "duration_ms": status.get("duration_ms"),
        "error": status.get("error"),
        "raw_output": raw,
        "parsed_output": parsed,
        "user_prompt": user_prompt,
    }


@router.post("/runs/{run_id}/accept")
async def accept_run(run_id: str):
    src = os.path.join(RUNS_DIR, run_id, "updated-spec.md")
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="updated-spec not found")
    os.makedirs(DATA_DIR, exist_ok=True)
    import shutil
    shutil.copy2(src, SPEC_FILE)
    return {"status": "accepted", "spec_file": SPEC_FILE}
