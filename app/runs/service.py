import os
import json
import yaml
import asyncio
from datetime import datetime
from app.runs import storage
from app.council_core import consensus, findings, writer
from app.agent_adapters.cli import CliAgentAdapter
from app.agent_adapters.api import ApiAgentAdapter
from app.council_core.contracts import AgentRequestContract, Workspace, Instructions

RUNS_DIR = "/opt/ai-lab/ai-senate/data/runs"

def update_run_file(run_id: str, data: dict):
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    file_path = os.path.join(run_dir, "run.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def read_run_file(run_id: str) -> dict:
    file_path = os.path.join(RUNS_DIR, run_id, "run.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

async def execute_agent(run_id: str, agent_name: str, agent_config: dict, request_contract_json: str, run_data: dict, lock: asyncio.Lock):
    """Executes a single agent, logs its outcome and updates the run.json metadata file."""
    # Update agent state to running
    async with lock:
        run_data["agents"][agent_name]["status"] = "running"
        update_run_file(run_id, run_data)
        
    # Instantiate adapter
    agent_type = agent_config.get("type", "cli")
    if agent_type == "cli":
        adapter = CliAgentAdapter(agent_name, agent_config)
    else:
        adapter = ApiAgentAdapter(agent_name, agent_config)
        
    # Execute adapter
    result = await adapter.run(request_contract_json)
    
    # Save logs inside agent's folder in runs
    agent_dir = os.path.join(RUNS_DIR, run_id, "agents", agent_name)
    os.makedirs(agent_dir, exist_ok=True)
    
    with open(os.path.join(agent_dir, "stdout.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("stdout", ""))
    with open(os.path.join(agent_dir, "stderr.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("stderr", ""))
    with open(os.path.join(agent_dir, "raw-output.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("raw_output", ""))
    if result.get("parsed_output"):
        with open(os.path.join(agent_dir, "parsed-output.json"), "w", encoding="utf-8") as f:
            json.dump(result["parsed_output"], f, indent=2)
            
    with open(os.path.join(agent_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump({
            "agent": agent_name,
            "status": result.get("status"),
            "duration_ms": result.get("duration_ms"),
            "exit_code": result.get("exit_code"),
            "timeout": result.get("timeout"),
            "parsed": result.get("status") == "done",
            "error": result.get("error")
        }, f, indent=2)
        
    # Update run state under lock
    async with lock:
        run_data["agents"][agent_name] = {
            "status": result.get("status", "failed"),
            "duration_ms": result.get("duration_ms", 0),
            "error": result.get("error"),
            "parsed_output": result.get("parsed_output")
        }
        update_run_file(run_id, run_data)

async def run_council_task(run_id: str, spec_text: str, owner_input: str, new_document: bool, max_rounds: int = 2, auto_stop_if_clean: bool = True):
    """Background task orchestrating the multi-round AI Council run process."""
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    
    # 1. Update SQLite progress
    storage.update_run_progress(run_id, status="running", phase="round_1_review", current_round=1)
    
    spec_file = os.path.join(run_dir, "input-spec.md")
    owner_file = os.path.join(run_dir, "owner-input.md")
    
    with open(spec_file, "w", encoding="utf-8") as f:
        f.write(spec_text)
    with open(owner_file, "w", encoding="utf-8") as f:
        f.write(owner_input)
        
    # 2. Load agent configs
    config_path = "/opt/ai-lab/ai-senate/app/config/agents.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        yaml_config = yaml.safe_load(f)
        
    all_agents = yaml_config.get("agents", {})
    reviewers = {name: cfg for name, cfg in all_agents.items() if name != "writer" and cfg.get("enabled", True)}
    
    # Initialize run.json structure
    run_data = {
        "run_id": run_id,
        "status": "running",
        "phase": "round_1_review",
        "current_round": 1,
        "max_rounds": max_rounds,
        "auto_stop_if_clean": auto_stop_if_clean,
        "new_document": new_document,
        "started_at": datetime.now().isoformat(),
        "round_log": [],
        "agents": {
            name: {"status": "queued", "duration_ms": 0, "error": None}
            for name in reviewers
        }
    }
    
    # Add writer as waiting
    if "writer" in all_agents:
        run_data["agents"]["writer"] = {"status": "waiting", "duration_ms": 0, "error": None}
        
    update_run_file(run_id, run_data)
    
    # Write initial request.json to run folder
    with open(os.path.join(run_dir, "request.json"), "w", encoding="utf-8") as f:
        json.dump({
            "run_id": run_id,
            "new_document": new_document,
            "spec_length": len(spec_text),
            "owner_input_length": len(owner_input),
            "max_rounds": max_rounds,
            "auto_stop_if_clean": auto_stop_if_clean
        }, f, indent=2)
        
    # ==================== ROUND 1: INDEPENDENT REVIEW ====================
    lock = asyncio.Lock()
    tasks = []
    
    for name, cfg in reviewers.items():
        contract = AgentRequestContract(
            run_id=run_id,
            agent=name,
            role=cfg.get("role", "reviewer"),
            task="Review current spec and owner input independently. Return structured findings.",
            new_document=new_document,
            workspace=Workspace(
                root="/opt/ai-lab/ai-senate",
                spec_file=spec_file,
                owner_input_file=owner_file
            ),
            instructions=Instructions(
                focus=[
                    "requirements clarity",
                    "MVP scope",
                    "architecture",
                    "missing contracts",
                    "risks",
                    "blockers",
                    "test strategy",
                    "implementation complexity"
                ]
            )
        )
        contract_json = contract.json(indent=2)
        
        # Save prompt under round-1 agent subfolder
        agent_dir = os.path.join(run_dir, "round-1", "agents", name)
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, "prompt.md"), "w", encoding="utf-8") as f:
            f.write(contract_json)
            
        tasks.append(
            execute_agent_round(run_id, 1, name, cfg, contract_json, run_data, lock)
        )
        
    await asyncio.gather(*tasks)
    
    # Transition to consensus phase
    storage.update_run_progress(run_id, phase="round_1_consensus")
    run_data = read_run_file(run_id)
    run_data["phase"] = "round_1_consensus"
    update_run_file(run_id, run_data)
    
    # Calculate Round 1 Consensus & Aggregate Findings
    r1_agent_runs = {}
    r1_dir = os.path.join(run_dir, "round-1", "agents")
    for name in reviewers:
        status_file = os.path.join(r1_dir, name, "status.json")
        parsed_file = os.path.join(r1_dir, name, "parsed-output.json")
        if os.path.exists(status_file):
            with open(status_file, "r", encoding="utf-8") as f:
                s_data = json.load(f)
            parsed_data = None
            if os.path.exists(parsed_file):
                with open(parsed_file, "r", encoding="utf-8") as f:
                    parsed_data = json.load(f)
            r1_agent_runs[name] = {
                "agent": name,
                "status": s_data.get("status"),
                "parsed_output": parsed_data,
                "error": s_data.get("error"),
                "role": s_data.get("role", "reviewer")
            }
            
    consensus_res = consensus.calculate_consensus(run_id, r1_agent_runs)
    aggregated_findings = findings.aggregate_findings(r1_agent_runs)
    
    # Save Round 1 artifacts
    os.makedirs(os.path.join(run_dir, "round-1"), exist_ok=True)
    with open(os.path.join(run_dir, "round-1", "findings.json"), "w", encoding="utf-8") as f:
        json.dump(aggregated_findings, f, indent=2)
    with open(os.path.join(run_dir, "round-1", "consensus.json"), "w", encoding="utf-8") as f:
        f.write(consensus_res.json(indent=2))
        
    # By default, set these as root files
    with open(os.path.join(run_dir, "findings.json"), "w", encoding="utf-8") as f:
        json.dump(aggregated_findings, f, indent=2)
    with open(os.path.join(run_dir, "consensus.json"), "w", encoding="utf-8") as f:
        f.write(consensus_res.json(indent=2))
        
    # Append to round log
    r1_summary = {
        "round": 1,
        "phase": "round_1_review",
        "status": consensus_res.status,
        "summary": consensus_res.summary,
        "counts": consensus_res.counts,
        "agent_status": consensus_res.agent_status
    }
    run_data["round_log"].append(r1_summary)
    update_run_file(run_id, run_data)
    
    # Auto-stop clean check
    blocker_count = consensus_res.counts.get("blocker", 0)
    major_risk_count = consensus_res.counts.get("major_risk", 0)
    question_count = consensus_res.counts.get("question", 0) + len(consensus_res.unresolved_questions)
    
    active_count = len(reviewers)
    failed_count = consensus_res.agent_status.get("failed", 0) + consensus_res.agent_status.get("failed_parse", 0) + consensus_res.agent_status.get("timeout", 0)
    failed_ratio = failed_count / active_count if active_count > 0 else 0.0
    
    is_clean = (blocker_count == 0 and major_risk_count == 0 and question_count < 3 and failed_ratio <= 0.5)
    should_stop = (max_rounds == 1) or (auto_stop_if_clean and is_clean)
    
    # ==================== ROUND 2: CROSS-REVIEW ====================
    if not should_stop and max_rounds >= 2:
        storage.update_run_progress(run_id, phase="round_2_cross_review", current_round=2)
        run_data = read_run_file(run_id)
        run_data["phase"] = "round_2_cross_review"
        run_data["current_round"] = 2
        
        # Reset reviewers status to queued for R2
        for name in reviewers:
            run_data["agents"][name] = {"status": "queued", "duration_ms": 0, "error": None}
        update_run_file(run_id, run_data)
        
        tasks = []
        for name, cfg in reviewers.items():
            # Build Cross-review Prompt Task
            serialized_findings = json.dumps(aggregated_findings, indent=2, ensure_ascii=False)
            serialized_consensus = consensus_res.json(indent=2)
            
            task_desc = f"""You are in Round 2: Cross-review.
Your task is to review the findings and consensus of the first round.

Here is the Round 1 findings list:
{serialized_findings}

Here is the Round 1 consensus result:
{serialized_consensus}

Review the findings of other agents:
1. Confirm blockers or major risks that you agree are critical.
2. Dispute or downgrade findings you consider exaggerated or not applicable to MVP.
3. Suggest resolutions or add any new important items missed in Round 1.

You MUST return a valid JSON matching the schema `agent_cross_review_response_v1`."""

            # We format the prompt with cross-review instructions
            prompt_instruct = f"""You MUST return a valid JSON matching the schema `agent_cross_review_response_v1`.
Format:
{{
  "schema_version": "agent_cross_review_response_v1",
  "agent": "{name}",
  "round": 2,
  "confirm": [
    {{
      "finding_id": "r1-item-id",
      "verdict": "confirm",
      "recommended_type": "blocker | major_risk",
      "reason": "Why you agree"
    }}
  ],
  "dispute": [
    {{
      "finding_id": "r1-item-id",
      "verdict": "downgrade | resolve",
      "recommended_type": "suggestion | risk",
      "reason": "Why you dispute/downgrade"
    }}
  ],
  "new_items": [
    {{
      "id": "r2-{name}-new-item-001",
      "type": "blocker | major_risk | risk | suggestion | question",
      "category": "architecture | requirements | test_strategy | ...",
      "severity": "low | medium | high",
      "title": "Title",
      "description": "Description",
      "evidence": "evidence",
      "recommendation": "recommendation",
      "confidence": 1.0
    }}
  ],
  "summary": "Summary of cross-review"
}}"""

            # Build request
            contract_json = json.dumps({
                "schema_version": "agent_request_v1",
                "run_id": run_id,
                "agent": name,
                "role": cfg.get("role", "reviewer"),
                "task": task_desc,
                "new_document": new_document,
                "workspace": {
                    "root": "/opt/ai-lab/ai-senate",
                    "spec_file": spec_file,
                    "owner_input_file": owner_file
                },
                "instructions": {
                    "language": "ru",
                    "output_format": "json",
                    "must_return_valid_json": True,
                    "do_not_modify_files": True,
                    "focus": ["cross-review"]
                },
                "output_schema": prompt_instruct
            }, indent=2, ensure_ascii=False)
            
            agent_dir = os.path.join(run_dir, "round-2", "agents", name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, "prompt.md"), "w", encoding="utf-8") as f:
                f.write(contract_json)
                
            tasks.append(
                execute_agent_round(run_id, 2, name, cfg, contract_json, run_data, lock)
            )
            
        await asyncio.gather(*tasks)
        
        # Transition to Round 2 consensus
        storage.update_run_progress(run_id, phase="round_2_consensus")
        run_data = read_run_file(run_id)
        run_data["phase"] = "round_2_consensus"
        update_run_file(run_id, run_data)
        
        # Parse Round 2 responses
        r2_agent_runs = {}
        r2_dir = os.path.join(run_dir, "round-2", "agents")
        for name in reviewers:
            status_file = os.path.join(r2_dir, name, "status.json")
            parsed_file = os.path.join(r2_dir, name, "parsed-output.json")
            if os.path.exists(status_file):
                with open(status_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                parsed_data = None
                if os.path.exists(parsed_file):
                    with open(parsed_file, "r", encoding="utf-8") as f:
                        parsed_data = json.load(f)
                r2_agent_runs[name] = parsed_data or {}
                
        # Merge Round 1 findings with Round 2 cross-reviews
        merged_findings = findings.merge_findings(aggregated_findings, r2_agent_runs)
        
        # Convert parsed status for calculate_consensus
        consensus_status_runs = {}
        for name in reviewers:
            s_file = os.path.join(r2_dir, name, "status.json")
            with open(s_file, "r", encoding="utf-8") as f:
                s_data = json.load(f)
            consensus_status_runs[name] = {
                "agent": name,
                "status": s_data.get("status"),
                "parsed_output": {
                    "schema_version": "agent_review_response_v1",
                    "agent": name,
                    "role": s_data.get("role", "reviewer"),
                    "decision": "needs_more_info" if any(len(items) > 0 for items in merged_findings.values()) else "accept",
                    "confidence": 0.9,
                    "summary": "Cross-reviewed",
                    "items": sum(merged_findings.values(), []),
                    "open_questions": [q.get("description", "") for q in merged_findings.get("questions", []) if isinstance(q, dict)],
                    "required_actions": [a.get("recommendation", "") for a in sum(merged_findings.values(), []) if isinstance(a, dict) and a.get("recommendation")]
                },
                "error": s_data.get("error"),
                "role": s_data.get("role", "reviewer")
            }
            
        consensus_res = consensus.calculate_consensus(run_id, consensus_status_runs)
        
        # Save Round 2 artifacts
        os.makedirs(os.path.join(run_dir, "round-2"), exist_ok=True)
        with open(os.path.join(run_dir, "round-2", "merged-findings.json"), "w", encoding="utf-8") as f:
            json.dump(merged_findings, f, indent=2)
        with open(os.path.join(run_dir, "round-2", "consensus.json"), "w", encoding="utf-8") as f:
            f.write(consensus_res.json(indent=2))
            
        # Overwrite root findings & consensus with Round 2 merged results
        with open(os.path.join(run_dir, "findings.json"), "w", encoding="utf-8") as f:
            json.dump(merged_findings, f, indent=2)
        with open(os.path.join(run_dir, "consensus.json"), "w", encoding="utf-8") as f:
            f.write(consensus_res.json(indent=2))
            
        # Add Round 2 summary to round log
        r2_summary = {
            "round": 2,
            "phase": "round_2_cross_review",
            "status": consensus_res.status,
            "summary": consensus_res.summary,
            "counts": consensus_res.counts,
            "agent_status": consensus_res.agent_status
        }
        run_data["round_log"].append(r2_summary)
        update_run_file(run_id, run_data)
        
    # ==================== WRITER AGENT ====================
    storage.update_run_progress(run_id, phase="writer")
    run_data = read_run_file(run_id)
    run_data["phase"] = "writer"
    update_run_file(run_id, run_data)
    
    if "writer" in all_agents:
        async with lock:
            run_data["agents"]["writer"]["status"] = "running"
            update_run_file(run_id, run_data)
            
        updated_spec_file = os.path.join(run_dir, "updated-spec.md")
        findings_file = os.path.join(run_dir, "findings.json")
        consensus_file = os.path.join(run_dir, "consensus.json")
        
        writer_res = await writer.run_writer(
            run_id=run_id,
            new_document=new_document,
            spec_file=spec_file,
            owner_input_file=owner_file,
            findings_file=findings_file,
            consensus_file=consensus_file,
            agent_outputs_dir=os.path.join(run_dir, "agents"),
            output_file=updated_spec_file
        )
        
        # Build structured changes.json file
        changes_data = {
            "added": [],
            "changed": [],
            "removed": [],
            "kept_unresolved": []
        }
        
        if writer_res.notes:
            for note in writer_res.notes:
                if "добавлен" in note.lower() or "added" in note.lower():
                    changes_data["added"].append(note)
                elif "изменен" in note.lower() or "changed" in note.lower() or "обновлен" in note.lower():
                    changes_data["changed"].append(note)
                elif "удален" in note.lower() or "removed" in note.lower():
                    changes_data["removed"].append(note)
                else:
                    changes_data["kept_unresolved"].append(note)
                    
        # Load unresolved items from consensus
        for action in consensus_res.required_actions:
            changes_data["kept_unresolved"].append(f"Не решено: {action}")
            
        if not changes_data["added"] and not changes_data["changed"] and not changes_data["removed"]:
            # Fallback if notes are empty
            changes_data["added"].append("Создана начальная спецификация на базе пожеланий")
            changes_data["kept_unresolved"].append("Перенесены открытые вопросы в спецификацию")
            
        with open(os.path.join(run_dir, "changes.json"), "w", encoding="utf-8") as f:
            json.dump(changes_data, f, indent=2, ensure_ascii=False)
            
        async with lock:
            run_data["agents"]["writer"] = {
                "status": "done" if writer_res.status != "failed" else "failed",
                "duration_ms": 0,
                "error": None if writer_res.status != "failed" else writer_res.summary
            }
            update_run_file(run_id, run_data)
            
        # Add writer event to round log
        writer_log = {
            "round": "writer",
            "phase": "writer",
            "status": "done" if writer_res.status != "failed" else "failed",
            "summary": writer_res.summary
        }
        run_data["round_log"].append(writer_log)
        update_run_file(run_id, run_data)
        
    # ==================== ROUND 3: FINAL WRITER CHECK ====================
    if max_rounds >= 3:
        storage.update_run_progress(run_id, phase="round_3_final_check", current_round=3)
        run_data = read_run_file(run_id)
        run_data["phase"] = "round_3_final_check"
        run_data["current_round"] = 3
        
        # Reset reviewers status to queued for R3
        for name in reviewers:
            run_data["agents"][name] = {"status": "queued", "duration_ms": 0, "error": None}
        update_run_file(run_id, run_data)
        
        tasks = []
        for name, cfg in reviewers.items():
            task_desc = f"""You are in Round 3: Final Writer Check.
Your task is to inspect the generated `updated-spec.md` specification file.

Confirm that:
1. Owner input changes were successfully incorporated.
2. Blockers and major risks identified in previous rounds were not hidden.
3. Unresolved questions and notes are preserved.
4. The generated spec is a full, valid spec document, not just a summary.

You MUST return a valid JSON matching the schema `agent_final_check_response_v1`."""

            prompt_instruct = f"""You MUST return a valid JSON matching the schema `agent_final_check_response_v1`.
Format:
{{
  "schema_version": "agent_final_check_response_v1",
  "agent": "{name}",
  "round": 3,
  "passed": true | false,
  "lost_owner_input": ["List any lost user requirements or empty strings if none"],
  "lost_blockers": ["List any lost blockers or empty strings if none"],
  "lost_major_risks": ["List any lost major risks or empty strings if none"],
  "new_issues": [],
  "summary": "Your final assessment of the generated specification"
}}"""

            contract_json = json.dumps({
                "schema_version": "agent_request_v1",
                "run_id": run_id,
                "agent": name,
                "role": cfg.get("role", "reviewer"),
                "task": task_desc,
                "new_document": new_document,
                "workspace": {
                    "root": "/opt/ai-lab/ai-senate",
                    "spec_file": os.path.join(run_dir, "updated-spec.md"), # We check the updated-spec!
                    "owner_input_file": owner_file
                },
                "instructions": {
                    "language": "ru",
                    "output_format": "json",
                    "must_return_valid_json": True,
                    "do_not_modify_files": True,
                    "focus": ["final-check"]
                },
                "output_schema": prompt_instruct
            }, indent=2, ensure_ascii=False)
            
            agent_dir = os.path.join(run_dir, "round-3", "agents", name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, "prompt.md"), "w", encoding="utf-8") as f:
                f.write(contract_json)
                
            tasks.append(
                execute_agent_round(run_id, 3, name, cfg, contract_json, run_data, lock)
            )
            
        await asyncio.gather(*tasks)
        
        # Parse Round 3 results
        r3_agent_runs = {}
        r3_dir = os.path.join(run_dir, "round-3", "agents")
        all_passed = True
        failed_checks = []
        
        for name in reviewers:
            status_file = os.path.join(r3_dir, name, "status.json")
            parsed_file = os.path.join(r3_dir, name, "parsed-output.json")
            if os.path.exists(status_file):
                with open(status_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                parsed_data = None
                if os.path.exists(parsed_file):
                    with open(parsed_file, "r", encoding="utf-8") as f:
                        parsed_data = json.load(f)
                
                r3_agent_runs[name] = parsed_data or {}
                if parsed_data and not parsed_data.get("passed", True):
                    all_passed = False
                    failed_checks.append({
                        "agent": name,
                        "lost_blockers": parsed_data.get("lost_blockers", []),
                        "lost_owner_input": parsed_data.get("lost_owner_input", []),
                        "summary": parsed_data.get("summary", "")
                    })
                    
        # Write Round 3 quality check artifact
        with open(os.path.join(run_dir, "round-3", "final-check.json"), "w", encoding="utf-8") as f:
            json.dump({
                "all_passed": all_passed,
                "failed_checks": failed_checks,
                "details": r3_agent_runs
            }, f, indent=2, ensure_ascii=False)
            
        # Overwrite final consensus status if Round 3 failed
        if not all_passed:
            consensus_res.status = "needs_followup"
            consensus_res.summary = f"Проверка качества отклонена: агенты нашли критические упущения во Writer! {failed_checks[0]['summary']}"
            with open(os.path.join(run_dir, "consensus.json"), "w", encoding="utf-8") as f:
                f.write(consensus_res.json(indent=2))
                
        # Append Round 3 to round log
        r3_log = {
            "round": 3,
            "phase": "round_3_final_check",
            "status": "passed" if all_passed else "failed",
            "summary": "Проверка качества ТЗ успешна" if all_passed else f"Упущено ТЗ агентом {failed_checks[0]['agent']}: {failed_checks[0]['summary']}"
        }
        run_data["round_log"].append(r3_log)
        update_run_file(run_id, run_data)
        
    # ==================== DONE ====================
    storage.update_run_progress(run_id, status="done")
    run_data = read_run_file(run_id)
    run_data["status"] = "done"
    run_data["finished_at"] = datetime.now().isoformat()
    update_run_file(run_id, run_data)

async def execute_agent_round(run_id: str, round_num: int, agent_name: str, agent_config: dict, request_contract_json: str, run_data: dict, lock: asyncio.Lock):
    """Executes a single agent under a specific round directory and updates run_data status."""
    async with lock:
        run_data["agents"][agent_name]["status"] = "running"
        update_run_file(run_id, run_data)
        
    agent_type = agent_config.get("type", "cli")
    if agent_type == "cli":
        adapter = CliAgentAdapter(agent_name, agent_config)
    else:
        adapter = ApiAgentAdapter(agent_name, agent_config)
        
    result = await adapter.run(request_contract_json)
    
    agent_dir = os.path.join(RUNS_DIR, run_id, f"round-{round_num}", "agents", agent_name)
    os.makedirs(agent_dir, exist_ok=True)
    
    with open(os.path.join(agent_dir, "stdout.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("stdout", ""))
    with open(os.path.join(agent_dir, "stderr.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("stderr", ""))
    with open(os.path.join(agent_dir, "raw-output.txt"), "w", encoding="utf-8") as f:
        f.write(result.get("raw_output", ""))
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
            "role": agent_config.get("role", "reviewer")
        }, f, indent=2)
        
    async with lock:
        run_data["agents"][agent_name] = {
            "status": result.get("status", "failed"),
            "duration_ms": result.get("duration_ms", 0),
            "error": result.get("error"),
            "parsed_output": result.get("parsed_output")
        }
        update_run_file(run_id, run_data)
