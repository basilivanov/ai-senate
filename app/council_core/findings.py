from typing import Dict, Any, List

def aggregate_findings(agent_runs: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Collects findings from all completed agent runs and groups them by severity/type.
    
    Returns a dictionary structured as:
    {
        "blockers": [...],
        "major_risks": [...],
        "risks": [...],
        "suggestions": [...],
        "questions": [...],
        "infos": [...]
    }
    """
    categories = {
        "blockers": [],
        "major_risks": [],
        "risks": [],
        "suggestions": [],
        "questions": [],
        "infos": []
    }
    
    for agent_name, run_info in agent_runs.items():
        if run_info.get("status") == "done" and run_info.get("parsed_output"):
            parsed = run_info["parsed_output"]
            items = parsed.get("items", [])
            for item in items:
                ftype = item.get("type", "info")
                
                # Standardize item structure for reliable UI rendering
                finding = {
                    "id": item.get("id", f"{agent_name}-item"),
                    "agent": agent_name,
                    "role": run_info.get("role", "reviewer"),
                    "category": item.get("category", "general"),
                    "severity": item.get("severity", "medium"),
                    "title": item.get("title", "Без названия"),
                    "description": item.get("description", ""),
                    "evidence": item.get("evidence", ""),
                    "recommendation": item.get("recommendation", ""),
                    "confidence": item.get("confidence", 1.0)
                }
                
                # Sort into mapped categories
                if ftype == "blocker":
                    categories["blockers"].append(finding)
                elif ftype == "major_risk":
                    categories["major_risks"].append(finding)
                elif ftype == "risk":
                    categories["risks"].append(finding)
                elif ftype == "suggestion":
                    categories["suggestions"].append(finding)
                elif ftype == "question":
                    categories["questions"].append(finding)
                else:
                    categories["infos"].append(finding)
                    
    return categories

def merge_findings(round1_findings: Dict[str, List[Dict[str, Any]]], cross_reviews: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Merges Round 1 findings with Round 2 cross-reviews (confirming/disputing/downgrading)
    and any new items found in Round 2.
    """
    all_findings = []
    for cat, items in round1_findings.items():
        for item in items:
            if cat == "blockers":
                item["type"] = "blocker"
            elif cat == "major_risks":
                item["type"] = "major_risk"
            elif cat == "risks":
                item["type"] = "risk"
            elif cat == "suggestions":
                item["type"] = "suggestion"
            elif cat == "questions":
                item["type"] = "question"
            else:
                item["type"] = "info"
            all_findings.append(item)

    findings_dict = {f["id"]: f for f in all_findings}

    # Count votes for confirm/dispute
    votes = {}
    for agent_name, review in cross_reviews.items():
        if not review:
            continue
        # Process confirms
        confirms = review.get("confirm", [])
        for c in confirms:
            fid = c.get("finding_id")
            if fid:
                if fid not in votes:
                    votes[fid] = {"confirm": 0, "dispute": 0, "recommended_types": []}
                votes[fid]["confirm"] += 1
                
        # Process disputes
        disputes = review.get("dispute", [])
        for d in disputes:
            fid = d.get("finding_id")
            rec_type = d.get("recommended_type")
            if fid:
                if fid not in votes:
                    votes[fid] = {"confirm": 0, "dispute": 0, "recommended_types": []}
                votes[fid]["dispute"] += 1
                if rec_type:
                    votes[fid]["recommended_types"].append(rec_type)

    # Apply votes
    for fid, f in findings_dict.items():
        if fid in votes:
            v = votes[fid]
            if v["dispute"] > v["confirm"]:
                if v["recommended_types"]:
                    most_common_type = max(set(v["recommended_types"]), key=v["recommended_types"].count)
                    f["type"] = most_common_type
                else:
                    if f["type"] == "blocker":
                        f["type"] = "major_risk"
                    elif f["type"] == "major_risk":
                        f["type"] = "risk"
                    elif f["type"] == "risk":
                        f["type"] = "suggestion"

    # Add new items
    for agent_name, review in cross_reviews.items():
        if not review:
            continue
        new_items = review.get("new_items", [])
        for item in new_items:
            ftype = item.get("type", "info")
            new_id = item.get("id", f"r2-{agent_name}-{ftype}")
            finding = {
                "id": new_id,
                "agent": agent_name,
                "role": "reviewer",
                "category": item.get("category", "general"),
                "severity": item.get("severity", "medium"),
                "title": item.get("title", "Без названия"),
                "description": item.get("description", ""),
                "evidence": item.get("evidence", ""),
                "recommendation": item.get("recommendation", ""),
                "confidence": item.get("confidence", 1.0),
                "type": ftype
            }
            findings_dict[new_id] = finding

    # Re-group into categories
    categories = {
        "blockers": [],
        "major_risks": [],
        "risks": [],
        "suggestions": [],
        "questions": [],
        "infos": []
    }
    for f in findings_dict.values():
        ftype = f.get("type", "info")
        if ftype == "blocker":
            categories["blockers"].append(f)
        elif ftype == "major_risk":
            categories["major_risks"].append(f)
        elif ftype == "risk":
            categories["risks"].append(f)
        elif ftype == "suggestion":
            categories["suggestions"].append(f)
        elif ftype == "question":
            categories["questions"].append(f)
        else:
            categories["infos"].append(f)

    return categories
