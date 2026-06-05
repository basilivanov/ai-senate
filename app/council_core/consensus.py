from typing import Dict, Any, List
from app.council_core.contracts import ConsensusResultContract

def calculate_consensus(run_id: str, agent_runs: Dict[str, Dict[str, Any]]) -> ConsensusResultContract:
    """
    Calculates deterministic consensus based on agent runs.
    
    agent_runs: Dict[agent_name, agent_run_status_dict]
    agent_run_status_dict looks like:
    {
        "agent": "codex",
        "status": "done" | "failed" | "failed_parse" | "timeout",
        "parsed_output": { ... } or None,
        "error": "..." or None
    }
    """
    total_agents = len(agent_runs)
    
    # Initialize status counts
    status_counts = {
        "total": total_agents,
        "done": 0,
        "failed": 0,
        "failed_parse": 0,
        "timeout": 0
    }
    
    # Initialize finding counts
    finding_counts = {
        "info": 0,
        "suggestion": 0,
        "risk": 0,
        "major_risk": 0,
        "blocker": 0,
        "question": 0
    }
    
    # Initialize decision votes
    decision_votes = {
        "accept": 0,
        "accept_with_changes": 0,
        "needs_more_info": 0,
        "reject": 0,
        "block": 0
    }
    
    required_actions = []
    unresolved_questions = []
    
    # Process each agent's run
    for agent_name, run_info in agent_runs.items():
        status = run_info.get("status", "failed")
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts["failed"] += 1
            
        if status == "done" and run_info.get("parsed_output"):
            parsed = run_info["parsed_output"]
            
            # Count decision
            decision = parsed.get("decision")
            if decision in decision_votes:
                decision_votes[decision] += 1
            else:
                decision_votes["needs_more_info"] += 1
                
            # Aggregate findings
            items = parsed.get("items", [])
            for item in items:
                ftype = item.get("type")
                if ftype in finding_counts:
                    finding_counts[ftype] += 1
                    
            # Aggregate actions and questions
            open_qs = parsed.get("open_questions", [])
            for q in open_qs:
                if q not in unresolved_questions:
                    unresolved_questions.append(q)
                    
            req_actions = parsed.get("required_actions", [])
            for action in req_actions:
                if action not in required_actions:
                    required_actions.append(action)
                    
    # Calculate deterministic status based on mathematical rules from config/consensus.yaml
    import os
    import yaml

    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "app", "config", "consensus.yaml")
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            pass

    thresholds = config.get("thresholds", {})
    rules = config.get("rules", {})

    failed_ratio_threshold = thresholds.get("failed_agents_ratio", 0.5)
    questions_threshold = thresholds.get("many_questions_count", 3)
    accept_ratio_threshold = thresholds.get("accept_vote_ratio", 0.5)

    active_agents = total_agents
    failed_agents = status_counts["failed"] + status_counts["failed_parse"] + status_counts["timeout"]
    failed_ratio = failed_agents / active_agents if active_agents > 0 else 0.0

    # 1. Blocker check
    if finding_counts["blocker"] > 0:
        consensus_status = rules.get("blocker_status", "blocked")
        summary = "Блокирующие замечания: в исходном ТЗ найдены критические нестыковки (blockers)."
        
    # 2. Timeout/Failed check (failed ratio threshold exceeded)
    elif failed_ratio > failed_ratio_threshold:
        consensus_status = rules.get("failed_majority_status", "needs_followup")
        summary = "Недостаточно данных для принятия решения: слишком много агентов завершились с ошибкой или таймаутом."
        
    # 3. Major risk check
    elif finding_counts["major_risk"] > 0:
        consensus_status = rules.get("major_risk_status", "accepted_with_changes")
        summary = "Документ принят с исправлениями: обнаружены важные риски (major risks), требующие устранения."
        
    # 4. Questions check
    elif (finding_counts["question"] + len(unresolved_questions)) >= questions_threshold:
        consensus_status = rules.get("many_questions_status", "needs_followup")
        summary = "Требуется уточнение вопросов: найдено много открытых вопросов (questions), требующих участия человека."
        
    # 5. Accept / Accept with changes check
    elif status_counts["done"] > 0 and (decision_votes["accept"] + decision_votes["accept_with_changes"]) > (status_counts["done"] * accept_ratio_threshold):
        consensus_status = "accepted"
        summary = "Документ согласован консилиумом агентов."
        
    # 6. Fallback
    else:
        consensus_status = rules.get("default_uncertain_status", "needs_human_decision")
        summary = "Требуется ручное решение: голоса агентов разделились, однозначный консенсус не достигнут."

    return ConsensusResultContract(
        schema_version="consensus_result_v1",
        run_id=run_id,
        status=consensus_status,
        summary=summary,
        agent_status=status_counts,
        counts=finding_counts,
        decision_votes=decision_votes,
        required_actions=required_actions,
        unresolved_questions=unresolved_questions
    )
