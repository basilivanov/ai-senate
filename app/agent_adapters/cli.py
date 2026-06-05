import os
import sys
import json
import asyncio
import time
from typing import Dict, Any
from app.agent_adapters.base import BaseAgentAdapter

class CliAgentAdapter(BaseAgentAdapter):
    async def run(self, request_contract_json: str) -> Dict[str, Any]:
        command_config = self.config.get("command", {})
        binary = command_config.get("binary")
        args = command_config.get("args", [])
        working_dir = self.config.get("working_dir", "/opt/ai-lab/ai-senate")
        timeout = self.config.get("timeout_sec", 120)
        
        if not binary:
            raise ValueError(f"No binary specified for CLI agent {self.name}")
            
        env = os.environ.copy()
        env.pop("TERM", None)  # Unset TERM to bypass TUI confirmation checks
        
        # Adaptive argument and stdin mapping
        exec_args = list(args)
        stdin_data = request_contract_json.encode('utf-8')
        
        if binary in ["agya", "agy-shared", "agy-api"]:
            # agya is the shared Codex-backed CLI. Run it non-interactively via exec.
            if not exec_args or exec_args[0] not in ["exec", "e"]:
                exec_args = ["exec"] + exec_args
            if "--dangerously-bypass-approvals-and-sandbox" not in exec_args:
                exec_args = [exec_args[0], "--dangerously-bypass-approvals-and-sandbox"] + exec_args[1:]
            exec_args = exec_args + [request_contract_json]
            stdin_data = b""
        elif binary == "agy":
            # Native Antigravity CLI uses --print for non-interactive output.
            if not any(arg in ["--print", "-p", "--prompt"] for arg in exec_args):
                exec_args = ["--print"] + exec_args
            if "--dangerously-skip-permissions" not in exec_args:
                exec_args = exec_args + ["--dangerously-skip-permissions"]
            exec_args = exec_args + [request_contract_json]
            stdin_data = b""
        elif binary == "codexa":
            # codexa is Codex-backed and runs non-interactively via exec.
            if not exec_args or exec_args[0] not in ["exec", "e"]:
                exec_args = ["exec"] + exec_args
            if "--dangerously-bypass-approvals-and-sandbox" not in exec_args:
                exec_args = [exec_args[0], "--dangerously-bypass-approvals-and-sandbox"] + exec_args[1:]
            exec_args = exec_args + [request_contract_json]
            stdin_data = b""
        elif binary == "claude":
            # claude requires -p and the request contract prompt
            exec_args = ["-p", request_contract_json, "--permission-mode", "dontAsk", "--output-format", "json"] + list(args)
            stdin_data = b""
            
        start_time = time.time()
        
        try:
            process = await asyncio.create_subprocess_exec(
                binary,
                *exec_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=stdin_data),
                timeout=timeout
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            exit_code = process.returncode
            
            stdout_str = stdout.decode('utf-8', errors='ignore')
            stderr_str = stderr.decode('utf-8', errors='ignore')
            
            try:
                parsed = self.parse_response(stdout_str)
                parse_error = None
            except Exception as e:
                parsed = None
                parse_error = str(e)
                
            return {
                "agent": self.name,
                "status": "done" if exit_code == 0 and parsed else ("failed_parse" if parse_error else "failed"),
                "duration_ms": duration_ms,
                "exit_code": exit_code,
                "timeout": False,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "raw_output": stdout_str,
                "parsed_output": parsed,
                "error": parse_error if parse_error else (f"Exit code {exit_code}" if exit_code != 0 else None)
            }
            
        except asyncio.TimeoutError:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "agent": self.name,
                "status": "timeout",
                "duration_ms": duration_ms,
                "exit_code": -1,
                "timeout": True,
                "stdout": "",
                "stderr": "Execution timed out",
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
