import os
import json
import httpx
import time
import asyncio
from typing import Dict, Any
from app.agent_adapters.base import BaseAgentAdapter

class ApiAgentAdapter(BaseAgentAdapter):
    async def run(self, request_contract_json: str) -> Dict[str, Any]:
        """API adapter parses the request contract, reads files, and calls the API."""
        start_time = time.time()
        
        try:
            request_contract_dict = json.loads(request_contract_json)
        except Exception as e:
            return {
                "agent": self.name,
                "status": "failed",
                "duration_ms": 0,
                "exit_code": -1,
                "timeout": False,
                "stdout": "",
                "stderr": f"Failed to parse request contract: {str(e)}",
                "raw_output": "",
                "parsed_output": None,
                "error": f"Bad request contract: {str(e)}"
            }
            
        base_url = self.config.get("base_url")
        api_key_env = self.config.get("api_key_env")
        model = self.config.get("model")
        temperature = self.config.get("temperature", 0.2)
        timeout = self.config.get("timeout_sec", 120)
        
        if not base_url or not api_key_env or not model:
            return {
                "agent": self.name,
                "status": "failed",
                "duration_ms": 0,
                "exit_code": -1,
                "timeout": False,
                "stdout": "",
                "stderr": "API Agent is missing base_url, api_key_env, or model.",
                "raw_output": "",
                "parsed_output": None,
                "error": "Configuration error"
            }
            
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            return {
                "agent": self.name,
                "status": "failed",
                "duration_ms": 0,
                "exit_code": -1,
                "timeout": False,
                "stdout": "",
                "stderr": f"Missing API key in environment: {api_key_env}",
                "raw_output": "",
                "parsed_output": None,
                "error": f"API key environment variable {api_key_env} is not set."
            }
            
        # Read files from workspace path inside contract
        workspace = request_contract_dict.get("workspace", {})
        spec_file_path = workspace.get("spec_file")
        owner_input_path = workspace.get("owner_input_file")
        
        spec_content = ""
        if spec_file_path and os.path.exists(spec_file_path):
            with open(spec_file_path, "r", encoding="utf-8") as f:
                spec_content = f.read()
                
        owner_input_content = ""
        if owner_input_path and os.path.exists(owner_input_path):
            with open(owner_input_path, "r", encoding="utf-8") as f:
                owner_input_content = f.read()
                
        # Build System & User Prompt
        prompt = f"""You are acting as: {request_contract_dict.get("role")}
Task: {request_contract_dict.get("task")}

--- CURRENT SPECIFICATION ---
{spec_content if spec_content else "[No current specification / starting from scratch]"}

--- OWNER INPUT (USER COMMENT) ---
{owner_input_content if owner_input_content else "[No comments provided]"}

--- INSTRUCTIONS ---
- Language: {request_contract_dict.get("instructions", {}).get("language", "ru")}
- Owner Input Priority: {request_contract_dict.get("instructions", {}).get("owner_input_priority", "high")}
- Focus Areas: {", ".join(request_contract_dict.get("instructions", {}).get("focus", []))}

You MUST return a valid JSON matching the schema `agent_review_response_v1`.
Do not include any chat prefix or markdown formatting outside the JSON if possible, but if you do, wrap it in a code block.

JSON Schema format:
{{
  "schema_version": "agent_review_response_v1",
  "agent": "{self.name}",
  "role": "{request_contract_dict.get("role")}",
  "decision": "accept | accept_with_changes | needs_more_info | reject | block",
  "confidence": 0.0 to 1.0,
  "summary": "human summary of changes/findings",
  "items": [
    {{
      "id": "{self.name}-finding-001",
      "type": "info | suggestion | risk | major_risk | blocker | question",
      "category": "architecture | requirements | implementation | ...",
      "severity": "low | medium | high",
      "title": "Short title",
      "description": "Detailed description",
      "evidence": "evidence from spec",
      "recommendation": "how to resolve",
      "confidence": 0.0 to 1.0
    }}
  ],
  "open_questions": ["question 1"],
  "required_actions": ["action 1"]
}}
"""
        
        headers = {}
        body = {}
        
        # Detect standard Anthropic API endpoint or Claude model / Anthropic provider
        is_anthropic = "anthropic.com" in base_url.lower() or "claude" in model.lower() or self.config.get("provider") == "anthropic"
        
        if is_anthropic:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            if base_url.rstrip('/').endswith("/v1"):
                url = f"{base_url.rstrip('/')}/messages"
            else:
                url = f"{base_url.rstrip('/')}/v1/messages"
            body = {
                "model": model,
                "max_tokens": 4000,
                "system": "You are a professional software architect. You MUST return JSON only.",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature
            }
        else:
            # OpenAI compatible
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            if base_url.endswith("/chat/completions") or base_url.endswith("/chat/completions/"):
                url = base_url
            else:
                url = f"{base_url.rstrip('/')}/chat/completions"
                
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a professional software architect. You MUST return JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature
            }
            
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=body)
                duration_ms = int((time.time() - start_time) * 1000)
                
                if response.status_code != 200:
                    return {
                        "agent": self.name,
                        "status": "failed",
                        "duration_ms": duration_ms,
                        "exit_code": response.status_code,
                        "timeout": False,
                        "stdout": "",
                        "stderr": response.text,
                        "raw_output": response.text,
                        "parsed_output": None,
                        "error": f"API request failed with status code {response.status_code}"
                    }
                    
                response_json = response.json()
                
                if is_anthropic:
                    raw_text = response_json.get("content", [{}])[0].get("text", "")
                else:
                    raw_text = response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                try:
                    parsed = self.parse_response(raw_text)
                    parse_error = None
                except Exception as e:
                    parsed = None
                    parse_error = str(e)
                    
                return {
                    "agent": self.name,
                    "status": "done" if parsed else "failed_parse",
                    "duration_ms": duration_ms,
                    "exit_code": 200,
                    "timeout": False,
                    "stdout": raw_text,
                    "stderr": "",
                    "raw_output": raw_text,
                    "parsed_output": parsed,
                    "error": parse_error
                }
                
        except httpx.TimeoutException:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": self.name,
                "status": "timeout",
                "duration_ms": duration_ms,
                "exit_code": -1,
                "timeout": True,
                "stdout": "",
                "stderr": "API request timed out",
                "raw_output": "",
                "parsed_output": None,
                "error": "Timeout"
            }
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": self.name,
                "status": "failed",
                "duration_ms": duration_ms,
                "exit_code": -1,
                "timeout": False,
                "stdout": "",
                "stderr": str(e),
                "raw_output": "",
                "parsed_output": None,
                "error": str(e)
            }
