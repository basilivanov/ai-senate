import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

import yaml

from app.runs import storage
from app.council_core import consensus, findings, writer as writer_module
from app.agent_adapters import OpencodeAgentAdapter
from app.council_core.contracts import (
    AgentRequestContract, Workspace, Instructions,
    DocumentRef, ProjectContext, GitDiffContext,
)


PROJECT_ROOT = os.environ.get("AI_SENATE_ROOT", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATA_DIR = os.environ.get("AI_SENATE_DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
RUNS_DIR = os.path.join(DATA_DIR, "runs")
AGENTS_YAML = os.path.join(PROJECT_ROOT, "app", "config", "agents.yaml")


def _load_agent_config() -> Dict[str, Any]:
    with open(AGENTS_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _build_adapter_config(perspective_cfg: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "agent": perspective_cfg.get("agent") or perspective_cfg.get("name"),
        "provider": perspective_cfg.get("provider") or defaults.get("provider", "cliproxy"),
        "model": perspective_cfg.get("model") or defaults.get("model", "claude-sonnet-4-6"),
        "opencode_agent": perspective_cfg.get("opencode_agent") or defaults.get("opencode_agent", "plan"),
        "timeout_sec": perspective_cfg.get("timeout_sec") or defaults.get("timeout_sec", 180),
        "temperature": perspective_cfg.get("temperature", defaults.get("temperature", 0.2)),
    }


def update_run_file(run_id: str, data: dict):
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def read_run_file(run_id: str) -> dict:
    path = os.path.join(RUNS_DIR, run_id, "run.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_agent_artifacts(run_id: str, round_num: int, agent_name: str, result: Dict[str, Any]) -> None:
    agent_dir = os.path.join(RUNS_DIR, run_id, f"round-{round_num}", "agents", agent_name)
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, "stdout.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("stdout", "") or "")
    with open(os.path.join(agent_dir, "stderr.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("stderr", "") or "")
    with open(os.path.join(agent_dir, "raw-output.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("raw_output", "") or "")
    if result.get("parsed_output"):
        with open(os.path.join(agent_dir, "parsed-output.json"), "w", encoding="utf-8") as f:
            json.dump(result["parsed_output"], f, indent=2, ensure_ascii=False)
    with open(os.path.join(agent_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump({
            "agent": agent_name,
            "status": result.get("status"),
            "duration_ms": result.get("duration_ms"),
            "exit_code": result.get("exit_code"),
            "timeout": result.get("timeout"),
            "parsed": result.get("status") == "done",
            "error": result.get("error"),
            "role": result.get("role"),
        }, f, indent=2, ensure_ascii=False)


async def _invoke_perspective(
    run_id: str,
    round_num: int,
    perspective_key: str,
    perspective_cfg: Dict[str, Any],
    contract_json: str,
    run_data: dict,
    lock: asyncio.Lock,
) -> Dict[str, Any]:
    async with lock:
        run_data["agents"][perspective_key]["status"] = "running"
        update_run_file(run_id, run_data)

    adapter_cfg = _build_adapter_config(perspective_cfg, _load_agent_config().get("defaults", {}))
    adapter = OpencodeAgentAdapter(perspective_key, adapter_cfg)
    result = await adapter.run(contract_json)
    result["role"] = perspective_cfg.get("role", "reviewer")

    _save_agent_artifacts(run_id, round_num, perspective_key, result)

    async with lock:
        run_data["agents"][perspective_key] = {
            "status": result.get("status", "failed"),
            "duration_ms": result.get("duration_ms", 0),
            "error": result.get("error"),
            "parsed_output": result.get("parsed_output"),
        }
        update_run_file(run_id, run_data)
    return result


def _get_jury(yaml_cfg: Dict[str, Any], name: str = "default") -> List[str]:
    juries = yaml_cfg.get("juries", {}) or {}
    if name in juries:
        return list(juries[name])
    return list((yaml_cfg.get("perspectives") or {}).keys())


def _get_perspective(yaml_cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    perspectives = yaml_cfg.get("perspectives") or {}
    cfg = perspectives.get(name) or {}
    if not cfg:
        return {"name": name}
    cfg = dict(cfg)
    cfg["name"] = name
    cfg.setdefault("agent", name)
    return cfg


def _get_profile(yaml_cfg: Dict[str, Any], profile_name: str) -> Dict[str, Any]:
    profiles = yaml_cfg.get("profiles", {}) or {}
    if profile_name in profiles:
        return profiles[profile_name]
    return {
        "jury": "default",
        "max_rounds": 2,
        "writer": True,
        "auto_stop_if_clean": True,
        "project_context": False,
    }


async def run_council_task(
    run_id: str,
    spec_text: str,
    owner_input: str,
    new_document: bool,
    max_rounds: int = 2,
    auto_stop_if_clean: bool = True,
    profile: str = "full_council",
    documents: Optional[List[Dict[str, str]]] = None,
    project_context: Optional[Dict[str, Any]] = None,
    git_diff_context: Optional[Dict[str, Any]] = None,
):
    yaml_cfg = _load_agent_config()
    profile_cfg = _get_profile(yaml_cfg, profile)
    jury_name = profile_cfg.get("jury", "default")
    jury = _get_jury(yaml_cfg, jury_name)
    writer_enabled = profile_cfg.get("writer", True)

    effective_max_rounds = max_rounds
    effective_auto_stop = auto_stop_if_clean

    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # 1. Save input files & init run state
    storage.update_run_progress(run_id, status="running", phase="round_1_review", current_round=1)
    spec_file = os.path.join(run_dir, "input-spec.md")
    owner_file = os.path.join(run_dir, "owner-input.md")

    if documents:
        input_dir = os.path.join(run_dir, "input")
        os.makedirs(input_dir, exist_ok=True)
        doc_refs = []
        for doc in documents:
            fname = doc.get("filename", "doc.md")
            role = doc.get("role", "")
            content = doc.get("content", "")
            fpath = os.path.join(input_dir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            doc_refs.append(DocumentRef(filename=fname, role=role, content=content))
        # Also write spec_file for backward compat — first doc or combined
        if not spec_text.strip() and doc_refs:
            spec_text = doc_refs[0].content
    else:
        doc_refs = []

    with open(spec_file, "w", encoding="utf-8") as f:
        f.write(spec_text)
    with open(owner_file, "w", encoding="utf-8") as f:
        f.write(owner_input)

    # Build workspace extensions
    project_ctx = None
    if project_context:
        project_ctx = ProjectContext(**project_context)

    git_diff_ctx = None
    if git_diff_context:
        git_diff_ctx = GitDiffContext(**git_diff_context)

    workspace_kwargs = {}
    if doc_refs:
        workspace_kwargs["documents"] = doc_refs
    if project_ctx:
        workspace_kwargs["project"] = project_ctx
    if git_diff_ctx:
        workspace_kwargs["git_diff"] = git_diff_ctx

    run_data = {
        "run_id": run_id,
        "status": "running",
        "phase": "round_1_review",
        "current_round": 1,
        "max_rounds": effective_max_rounds,
        "auto_stop_if_clean": effective_auto_stop,
        "new_document": new_document,
        "started_at": datetime.now().isoformat(),
        "round_log": [],
        "agents": {name: {"status": "queued", "duration_ms": 0, "error": None} for name in jury},
        "profile": profile,
        "project": {
            "path": project_context.get("path") if project_context else None,
            "files_included": len(project_context.get("files", [])) if project_context else 0,
            "truncated": project_context.get("truncated", False) if project_context else False,
        } if project_context else None,
        "git_diff": {
            "diff_type": git_diff_context.get("diff_type") if git_diff_context else None,
            "files_changed": git_diff_context.get("files_changed", 0) if git_diff_context else 0,
        } if git_diff_context else None,
    }
    if writer_enabled and yaml_cfg.get("writer", {}).get("enabled", True):
        run_data["agents"]["writer"] = {"status": "waiting", "duration_ms": 0, "error": None}
    update_run_file(run_id, run_data)

    with open(os.path.join(run_dir, "request.json"), "w", encoding="utf-8") as f:
        json.dump({
            "run_id": run_id,
            "new_document": new_document,
            "profile": profile,
            "jury": jury,
            "spec_length": len(spec_text),
            "owner_input_length": len(owner_input),
            "max_rounds": effective_max_rounds,
            "auto_stop_if_clean": effective_auto_stop,
            "documents_count": len(doc_refs),
            "has_project_context": project_ctx is not None,
            "has_git_diff": git_diff_ctx is not None,
        }, f, indent=2, ensure_ascii=False)

    # ==================== ROUND 1: INDEPENDENT REVIEW ====================
    lock = asyncio.Lock()
    tasks = []
    for name in jury:
        perspective = _get_perspective(yaml_cfg, name)
        workspace = Workspace(
            root=PROJECT_ROOT, spec_file=spec_file, owner_input_file=owner_file,
            **workspace_kwargs,
        )
        contract = AgentRequestContract(
            run_id=run_id,
            agent=name,
            role=perspective.get("role", "reviewer"),
            task="Round 1: Review the specification independently. Return structured findings.",
            new_document=new_document,
            workspace=workspace,
            instructions=Instructions(focus=["requirements clarity", "MVP scope", "architecture",
                                            "missing contracts", "risks", "blockers", "test strategy",
                                            "implementation complexity"]),
        )
        contract_json = contract.model_dump_json(indent=2)
        agent_dir = os.path.join(run_dir, "round-1", "agents", name)
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, "prompt.md"), "w", encoding="utf-8") as f:
            f.write(contract_json)
        tasks.append(_invoke_perspective(run_id, 1, name, perspective, contract_json, run_data, lock))

    await asyncio.gather(*tasks)

    # Round 1 consensus
    storage.update_run_progress(run_id, phase="round_1_consensus")
    run_data["phase"] = "round_1_consensus"
    update_run_file(run_id, run_data)

    r1_agent_runs = _read_round_results(run_dir, 1, jury)
    consensus_res = consensus.calculate_consensus(run_id, r1_agent_runs)
    aggregated_findings = findings.aggregate_findings(r1_agent_runs)

    os.makedirs(os.path.join(run_dir, "round-1"), exist_ok=True)
    with open(os.path.join(run_dir, "round-1", "findings.json"), "w", encoding="utf-8") as f:
        json.dump(aggregated_findings, f, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "round-1", "consensus.json"), "w", encoding="utf-8") as f:
        f.write(consensus_res.model_dump_json(indent=2))

    with open(os.path.join(run_dir, "findings.json"), "w", encoding="utf-8") as f:
        json.dump(aggregated_findings, f, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "consensus.json"), "w", encoding="utf-8") as f:
        f.write(consensus_res.model_dump_json(indent=2))

    r1_summary = {
        "round": 1,
        "phase": "round_1_review",
        "status": consensus_res.status,
        "summary": consensus_res.summary,
        "counts": consensus_res.counts,
        "agent_status": consensus_res.agent_status,
    }
    run_data["round_log"].append(r1_summary)
    update_run_file(run_id, run_data)

    blocker_count = consensus_res.counts.get("blocker", 0)
    major_risk_count = consensus_res.counts.get("major_risk", 0)
    question_count = consensus_res.counts.get("question", 0) + len(consensus_res.unresolved_questions)
    active_count = len(jury)
    failed_count = (consensus_res.agent_status.get("failed", 0)
                    + consensus_res.agent_status.get("failed_parse", 0)
                    + consensus_res.agent_status.get("timeout", 0))
    failed_ratio = failed_count / active_count if active_count > 0 else 0.0
    is_clean = (blocker_count == 0 and major_risk_count == 0 and question_count < 3 and failed_ratio <= 0.5)
    should_stop = (effective_max_rounds == 1) or (effective_auto_stop and is_clean)

    # ==================== ROUND 2: CROSS-REVIEW ====================
    if not should_stop and effective_max_rounds >= 2:
        storage.update_run_progress(run_id, phase="round_2_cross_review", current_round=2)
        run_data["phase"] = "round_2_cross_review"
        run_data["current_round"] = 2
        for name in jury:
            run_data["agents"][name] = {"status": "queued", "duration_ms": 0, "error": None}
        update_run_file(run_id, run_data)

        tasks = []
        for name in jury:
            perspective = _get_perspective(yaml_cfg, name)
            task_desc = (
                "You are in Round 2: Cross-review.\n"
                "Review the findings and consensus of the first round.\n"
                "Confirm blockers/major risks you agree with, dispute or downgrade findings "
                "you consider exaggerated, and add any new important items missed in Round 1.\n"
                "Return a valid JSON object with the same shape as Round 1 "
                "(schema agent_review_response_v1)."
            )
            workspace = Workspace(
                root=PROJECT_ROOT, spec_file=spec_file, owner_input_file=owner_file,
                **workspace_kwargs,
            )
            contract = AgentRequestContract(
                run_id=run_id,
                agent=name,
                role=perspective.get("role", "reviewer"),
                task=task_desc,
                new_document=new_document,
                workspace=workspace,
                instructions=Instructions(focus=["cross-review"]),
            )
            contract_json = contract.model_dump_json(indent=2)
            agent_dir = os.path.join(run_dir, "round-2", "agents", name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, "prompt.md"), "w", encoding="utf-8") as f:
                f.write(contract_json)
            tasks.append(_invoke_perspective(run_id, 2, name, perspective, contract_json, run_data, lock))

        await asyncio.gather(*tasks)

        storage.update_run_progress(run_id, phase="round_2_consensus")
        run_data["phase"] = "round_2_consensus"
        update_run_file(run_id, run_data)

        r2_results = _read_round_results(run_dir, 2, jury)
        merged_findings = _merge_round2(aggregated_findings, r2_results)
        consensus_res = consensus.calculate_consensus(run_id, r2_results)

        with open(os.path.join(run_dir, "round-2", "merged-findings.json"), "w", encoding="utf-8") as f:
            json.dump(merged_findings, f, indent=2, ensure_ascii=False)
        with open(os.path.join(run_dir, "round-2", "consensus.json"), "w", encoding="utf-8") as f:
            f.write(consensus_res.model_dump_json(indent=2))
        with open(os.path.join(run_dir, "findings.json"), "w", encoding="utf-8") as f:
            json.dump(merged_findings, f, indent=2, ensure_ascii=False)
        with open(os.path.join(run_dir, "consensus.json"), "w", encoding="utf-8") as f:
            f.write(consensus_res.model_dump_json(indent=2))

        r2_summary = {
            "round": 2,
            "phase": "round_2_cross_review",
            "status": consensus_res.status,
            "summary": consensus_res.summary,
            "counts": consensus_res.counts,
            "agent_status": consensus_res.agent_status,
        }
        run_data["round_log"].append(r2_summary)
        update_run_file(run_id, run_data)

    # ==================== WRITER ====================
    if writer_enabled:
        storage.update_run_progress(run_id, phase="writer")
        run_data["phase"] = "writer"
        update_run_file(run_id, run_data)

        writer_cfg = yaml_cfg.get("writer", {}).get("enabled", True)
        if writer_cfg:
            async with lock:
                run_data["agents"]["writer"]["status"] = "running"
                update_run_file(run_id, run_data)

            is_multi_doc = len(doc_refs) > 1
            updated_spec_file = os.path.join(run_dir, "updated-spec.md")
            writer_res = await writer_module.run_writer(
                run_id=run_id,
                new_document=new_document,
                spec_file=spec_file,
                owner_input_file=owner_file,
                findings_file=os.path.join(run_dir, "findings.json"),
                consensus_file=os.path.join(run_dir, "consensus.json"),
                agent_outputs_dir=os.path.join(run_dir, "agents"),
                output_file=updated_spec_file,
                documents=doc_refs if is_multi_doc else None,
            )
            _build_changes_summary(run_dir, writer_res, consensus_res)

            async with lock:
                run_data["agents"]["writer"] = {
                    "status": "done" if writer_res.status != "failed" else "failed",
                    "duration_ms": 0,
                    "error": None if writer_res.status != "failed" else writer_res.summary,
                }
                update_run_file(run_id, run_data)

            run_data["round_log"].append({
                "round": "writer",
                "phase": "writer",
                "status": "done" if writer_res.status != "failed" else "failed",
                "summary": writer_res.summary,
            })
            update_run_file(run_id, run_data)

    # ==================== ROUND 3: FINAL CHECK ====================
    if effective_max_rounds >= 3:
        storage.update_run_progress(run_id, phase="round_3_final_check", current_round=3)
        run_data["phase"] = "round_3_final_check"
        run_data["current_round"] = 3
        for name in jury:
            run_data["agents"][name] = {"status": "queued", "duration_ms": 0, "error": None}
        update_run_file(run_id, run_data)

        tasks = []
        for name in jury:
            perspective = _get_perspective(yaml_cfg, name)
            updated_spec_path = os.path.join(run_dir, "updated-spec.md")
            workspace = Workspace(
                root=PROJECT_ROOT, spec_file=updated_spec_path, owner_input_file=owner_file,
                **workspace_kwargs,
            )
            contract = AgentRequestContract(
                run_id=run_id,
                agent=name,
                role=perspective.get("role", "reviewer"),
                task=(
                    "You are in Round 3: Final Writer Check.\n"
                    "Inspect the generated updated-spec.md.\n"
                    "Return a JSON object with these fields: "
                    "passed (bool), lost_owner_input (list), lost_blockers (list), "
                    "lost_major_risks (list), new_issues (list), summary (string)."
                ),
                new_document=new_document,
                workspace=workspace,
                instructions=Instructions(focus=["final-check"]),
            )
            contract_json = contract.model_dump_json(indent=2)
            agent_dir = os.path.join(run_dir, "round-3", "agents", name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, "prompt.md"), "w", encoding="utf-8") as f:
                f.write(contract_json)
            tasks.append(_invoke_perspective(run_id, 3, name, perspective, contract_json, run_data, lock))

        await asyncio.gather(*tasks)
        all_passed, failed_checks, r3_agent_runs = _read_round3_results(run_dir, jury)
        with open(os.path.join(run_dir, "round-3", "final-check.json"), "w", encoding="utf-8") as f:
            json.dump({"all_passed": all_passed, "failed_checks": failed_checks, "details": r3_agent_runs},
                      f, indent=2, ensure_ascii=False)
        if not all_passed:
            consensus_res.status = "needs_followup"
            consensus_res.summary = f"Проверка качества отклонена: {failed_checks[0].get('summary', '')}"
            with open(os.path.join(run_dir, "consensus.json"), "w", encoding="utf-8") as f:
                f.write(consensus_res.model_dump_json(indent=2))
        run_data["round_log"].append({
            "round": 3,
            "phase": "round_3_final_check",
            "status": "passed" if all_passed else "failed",
            "summary": "Проверка качества ТЗ успешна" if all_passed else (
                f"Упущено ТЗ агентом {failed_checks[0].get('agent')}: {failed_checks[0].get('summary', '')}"
            ),
        })
        update_run_file(run_id, run_data)

    # ==================== DONE ====================
    storage.update_run_status(run_id, "done")
    run_data = read_run_file(run_id)
    run_data["status"] = "done"
    run_data["finished_at"] = datetime.now().isoformat()
    update_run_file(run_id, run_data)


def _read_round_results(run_dir: str, round_num: int, jury: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    rdir = os.path.join(run_dir, f"round-{round_num}", "agents")
    for name in jury:
        s = os.path.join(rdir, name, "status.json")
        p = os.path.join(rdir, name, "parsed-output.json")
        if not os.path.exists(s):
            continue
        with open(s, "r", encoding="utf-8") as f:
            sd = json.load(f)
        pd = None
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                pd = json.load(f)
        out[name] = {
            "agent": name,
            "status": sd.get("status"),
            "parsed_output": pd,
            "error": sd.get("error"),
            "role": sd.get("role", "reviewer"),
        }
    return out


def _merge_round2(round1_findings, cross_reviews):
    import copy
    merged = copy.deepcopy(round1_findings)
    seen_ids = {f["id"] for cat in merged.values() for f in cat}
    for agent_name, run in cross_reviews.items():
        parsed = run.get("parsed_output") or {}
        for item in parsed.get("items", []) or []:
            fid = item.get("id") or f"r2-{agent_name}-{len(seen_ids)}"
            if fid in seen_ids:
                continue
            seen_ids.add(fid)
            ftype = item.get("type", "info")
            finding = {
                "id": fid,
                "agent": agent_name,
                "role": run.get("role", "reviewer"),
                "category": item.get("category", "general"),
                "severity": item.get("severity", "medium"),
                "title": item.get("title", "Без названия"),
                "description": item.get("description", ""),
                "evidence": item.get("evidence", ""),
                "recommendation": item.get("recommendation", ""),
                "confidence": item.get("confidence", 1.0),
                "type": ftype,
            }
            bucket = {
                "blocker": "blockers", "major_risk": "major_risks", "risk": "risks",
                "suggestion": "suggestions", "question": "questions", "info": "infos",
            }.get(ftype, "infos")
            merged.setdefault(bucket, []).append(finding)
    return merged


def _read_round3_results(run_dir, jury):
    rdir = os.path.join(run_dir, "round-3", "agents")
    all_passed = True
    failed_checks = []
    details = {}
    for name in jury:
        s = os.path.join(rdir, name, "status.json")
        p = os.path.join(rdir, name, "parsed-output.json")
        if not os.path.exists(s):
            continue
        with open(s, "r", encoding="utf-8") as f:
            sd = json.load(f)
        pd = {}
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                pd = json.load(f)
        details[name] = pd
        if sd.get("status") != "done":
            all_passed = False
            failed_checks.append({
                "agent": name, "lost_blockers": [], "lost_owner_input": [],
                "summary": f"Agent {name} status: {sd.get('status')}",
            })
            continue
        if not pd.get("passed", True):
            all_passed = False
            failed_checks.append({
                "agent": name,
                "lost_blockers": pd.get("lost_blockers", []),
                "lost_owner_input": pd.get("lost_owner_input", []),
                "summary": pd.get("summary", ""),
            })
    return all_passed, failed_checks, details


def _build_changes_summary(run_dir, writer_res, consensus_res):
    changes = {"added": [], "changed": [], "removed": [], "kept_unresolved": []}
    for note in (writer_res.notes or []):
        low = note.lower()
        if "добавлен" in low or "added" in low:
            changes["added"].append(note)
        elif any(w in low for w in ("изменен", "changed", "обновлен", "updated")):
            changes["changed"].append(note)
        elif "удален" in low or "removed" in low:
            changes["removed"].append(note)
        else:
            changes["kept_unresolved"].append(note)
    for action in (consensus_res.required_actions or []):
        changes["kept_unresolved"].append(f"Не решено: {action}")
    if not (changes["added"] or changes["changed"] or changes["removed"]):
        changes["added"].append("Создана начальная спецификация на базе пожеланий")
        changes["kept_unresolved"].append("Перенесены открытые вопросы в спецификацию")
    with open(os.path.join(run_dir, "changes.json"), "w", encoding="utf-8") as f:
        json.dump(changes, f, indent=2, ensure_ascii=False)