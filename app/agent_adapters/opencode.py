import os
import time
import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.opencode import get_client
from app.agent_adapters.base import parse_review_response


PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / ".opencode" / "agents"


class OpencodeAgentAdapter:
    """
    Unified adapter for all agent invocations via the opencode REST API.
    Replaces CliAgentAdapter, ApiAgentAdapter, and MockAgentAdapter.

    Configuration:
        {
          "agent": "architect",             # perspective name = .md file basename
          "provider": "cliproxy",
          "model": "claude-sonnet-4-6",
          "opencode_agent": "plan",         # which opencode subagent to invoke (default: plan, tool-less)
          "timeout_sec": 240,
          "system_override": "..."          # optional: bypass perspective .md file
        }
    """

    name: str = "opencode"
    status: str = "queued"

    def __init__(self, agent_key: str, config: Dict[str, Any]):
        self.agent_key = agent_key
        self.config = config or {}
        self.name = agent_key

    async def run(self, request_contract_json: str) -> Dict[str, Any]:
        start = time.time()
        provider = self.config.get("provider", "cliproxy")
        model = self.config.get("model", "claude-sonnet-4-6")
        timeout = float(self.config.get("timeout_sec", 240))
        opencode_agent = self.config.get("opencode_agent", "plan")
        system_override = self.config.get("system_override")

        client = get_client()

        try:
            contract = json.loads(request_contract_json) if request_contract_json else {}
        except Exception as e:
            return self._fail(start, f"Invalid request contract JSON: {e}")

        system_prompt = self._load_system_prompt(system_override)
        user_prompt = self._build_user_prompt(contract, request_contract_json)

        try:
            res = await client.run_perspective(
                agent=opencode_agent,
                provider_id=provider,
                model_id=model,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                timeout_sec=timeout,
            )
        except Exception as e:
            return self._fail(start, f"opencode call failed: {e}", exit_code=-1)

        duration_ms = res.get("duration_ms", int((time.time() - start) * 1000))
        text = res.get("text", "")
        err = res.get("error")
        tokens = res.get("tokens", {}) or {}

        if err:
            return {
                "agent": self.name,
                "status": "failed",
                "duration_ms": duration_ms,
                "exit_code": -1,
                "timeout": False,
                "stdout": text,
                "stderr": err,
                "raw_output": text,
                "parsed_output": None,
                "error": err,
                "tokens": tokens,
            }

        parsed = parse_review_response(text)
        # Fallback for writer-style agents that return plain text instead of JSON
        if parsed.get("_raw") and len(text.strip()) > 200:
            parsed = {
                "schema_version": "writer_response_v1",
                "status": "draft_created",
                "summary": "Writer returned plain text; treated as updated_document_content.",
                "updated_document_content": text,
                "output_file": "",
                "owner_input_processed": True,
                "owner_input_applied": True,
                "unresolved_questions_kept": True,
                "blockers_preserved": True,
                "major_risks_preserved": True,
                "notes": ["writer output was not JSON; auto-wrapped as updated_document_content"],
            }
        elif parsed.get("_raw"):
            return {
                "agent": self.name,
                "status": "failed_parse",
                "duration_ms": duration_ms,
                "exit_code": 200,
                "timeout": False,
                "stdout": text,
                "stderr": parsed.get("summary", ""),
                "raw_output": text,
                "parsed_output": None,
                "error": parsed.get("summary", "parse failed"),
                "tokens": tokens,
            }

        parsed.setdefault("schema_version", "agent_review_response_v1")
        parsed.setdefault("agent", self.name)
        if "role" not in parsed and contract.get("role"):
            parsed["role"] = contract["role"]
        parsed.setdefault("decision", "needs_more_info")
        parsed.setdefault("confidence", 0.5)
        parsed.setdefault("summary", "")
        parsed.setdefault("items", [])
        parsed.setdefault("open_questions", [])
        parsed.setdefault("required_actions", [])

        return {
            "agent": self.name,
            "status": "done",
            "duration_ms": duration_ms,
            "exit_code": 200,
            "timeout": False,
            "stdout": text,
            "stderr": "",
            "raw_output": text,
            "parsed_output": parsed,
            "error": None,
            "tokens": tokens,
        }

    def _load_system_prompt(self, override: Optional[str]) -> str:
        if override:
            return override
        path = PROMPTS_DIR / f"{self.agent_key}.md"
        if not path.exists():
            return (
                f"You are acting as a reviewer named '{self.agent_key}'. "
                "Return only valid JSON matching agent_review_response_v1."
            )
        try:
            content = path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content
        except Exception:
            return ""

    def _build_user_prompt(self, contract: Dict[str, Any], raw_contract_json: str) -> str:
        workspace = contract.get("workspace", {}) or {}
        spec_path = workspace.get("spec_file")
        owner_path = workspace.get("owner_input_file")
        documents = workspace.get("documents", []) or []
        project = workspace.get("project")
        git_diff = workspace.get("git_diff")

        instructions = contract.get("instructions", {}) or {}
        focus = instructions.get("focus", []) or []
        focus_str = ", ".join(focus) if focus else "general review"

        parts = []

        # Multi-doc or single-doc
        if documents:
            for doc in documents:
                fname = doc.get("filename", "doc")
                role = doc.get("role", "")
                content = doc.get("content", "")
                role_str = f" ({role})" if role else ""
                parts.append(f"=== Документ: {fname}{role_str} ===\n{content}")
        else:
            spec_content = self._read_file(spec_path)
            parts.append(f"--- CURRENT SPECIFICATION ---\n{spec_content or '[No current specification / starting from scratch]'}")

        # Owner input
        owner_content = self._read_file(owner_path)
        parts.append(f"\n--- OWNER INPUT (USER COMMENT) ---\n{owner_content or '[No comments provided]'}")

        # Project context
        if project:
            parts.append(f"\n=== PROJECT: {project.get('path', '')} ===")
            tree = project.get("tree", "")
            if tree:
                parts.append(f"=== PROJECT TREE ===\n{tree}")
            for f in project.get("files", []) or []:
                parts.append(f"\n=== FILE: {f.get('filename', '')} ===\n{f.get('content', '')}")
            if project.get("truncated"):
                parts.append("\n[Project digest was truncated due to token limit]")

        # Git diff
        if git_diff and git_diff.get("diff_content"):
            fc = git_diff.get("files_changed", 0)
            ins = git_diff.get("insertions", 0)
            dels = git_diff.get("deletions", 0)
            parts.append(f"\n=== GIT DIFF ({fc} files, +{ins}/-{dels} lines) ===")
            parts.append(git_diff["diff_content"])
            if git_diff.get("truncated"):
                parts.append("\n[Diff was truncated due to line limit]")
            parts.append("=== END GIT DIFF ===")
            parts.append("Review these changes against the specification and codebase.")

        # Instructions
        parts.append(f"\n--- INSTRUCTIONS ---")
        parts.append(f"You are acting as: {contract.get('role', 'reviewer')}")
        parts.append(f"Task: {contract.get('task', 'Review the specification.')}")
        parts.append(f"Agent key: {self.agent_key}")
        parts.append(f"Language: {instructions.get('language', 'ru')}")
        parts.append(f"Owner input priority: {instructions.get('owner_input_priority', 'high')}")
        parts.append(f"Focus areas: {focus_str}")
        parts.append(f"Schema: {contract.get('output_schema', 'agent_review_response_v1')}")
        parts.append(f"- Return ONLY a valid JSON object matching agent_review_response_v1.")
        parts.append(f"- Do NOT include any prose before or after the JSON.")
        parts.append(f"- If you must wrap JSON in a code block, use ```json fences.")

        parts.append(f"""
Required JSON shape:
{{
  "schema_version": "agent_review_response_v1",
  "agent": "<your agent key>",
  "role": "<your role>",
  "decision": "accept | accept_with_changes | needs_more_info | reject | block",
  "confidence": 0.0,
  "summary": "...",
  "items": [
    {{
      "id": "<agent>-finding-001",
      "type": "info | suggestion | risk | major_risk | blocker | question",
      "category": "...",
      "severity": "low | medium | high",
      "title": "...",
      "description": "...",
      "evidence": "...",
      "recommendation": "...",
      "confidence": 0.0
    }}
  ],
  "open_questions": ["..."],
  "required_actions": ["..."]
}}""")

        return "\n".join(parts)

    @staticmethod
    def _read_file(path: Optional[str]) -> str:
        if not path:
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def _fail(self, start: float, msg: str, exit_code: int = -1) -> Dict[str, Any]:
        return {
            "agent": self.name,
            "status": "failed",
            "duration_ms": int((time.time() - start) * 1000),
            "exit_code": exit_code,
            "timeout": False,
            "stdout": "",
            "stderr": msg,
            "raw_output": "",
            "parsed_output": None,
            "error": msg,
        }
