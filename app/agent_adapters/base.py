import re
import json
from typing import Dict, Any, Optional

class BaseAgentAdapter:
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config

    async def run(self, request_contract_json: str) -> Dict[str, Any]:
        """Runs the agent and returns standard execution result dict."""
        raise NotImplementedError()

    def clean_json_string(self, raw_output: str) -> str:
        """Robust parser to extract JSON from markdown or raw LLM output."""
        cleaned = raw_output.strip()
        
        # Try to find markdown block ```json ... ``` or ``` ... ```
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()
            
        # Find first '{' and last '}'
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1:
            cleaned = cleaned[start:end+1]
            
        return cleaned

    def parse_response(self, raw_output: str) -> Dict[str, Any]:
        """Parses output string to dict using clean_json_string."""
        cleaned = self.clean_json_string(raw_output)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON from agent output. Raw output length: {len(raw_output)}. Error: {str(e)}")
