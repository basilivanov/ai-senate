import json
import re
from typing import Any, Dict, Optional


_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*|\s*```$", re.MULTILINE)


def clean_json_string(raw: str) -> str:
    """Strip markdown fences, leading/trailing whitespace, and slice to the outermost JSON object."""
    if raw is None:
        return ""
    text = raw.strip()
    text = _FENCE_RE.sub("", text).strip()
    if not text:
        return ""
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        return text[first:last + 1]
    return text


def parse_review_response(raw_text: str) -> Dict[str, Any]:
    """
    Parses an agent review response from raw text.
    Returns a dict that satisfies the agent_review_response_v1 contract, with sensible defaults.
    """
    if not raw_text:
        return _empty_review(error="empty response")

    cleaned = clean_json_string(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        return _empty_review(error=f"JSON parse error: {e}", raw=raw_text[:500])


def _empty_review(error: str = "", raw: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "schema_version": "agent_review_response_v1",
        "decision": "needs_more_info",
        "confidence": 0.0,
        "summary": f"Adapter parse failure: {error}",
        "items": [],
        "open_questions": [],
        "required_actions": [],
    }
    if raw is not None:
        out["_raw"] = raw
    return out
