import os
import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx


class OpencodeError(Exception):
    pass


class OpencodeClient:
    """
    Async HTTP client for the opencode REST API.
    Single entry point for all agent invocations.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout_sec: float = 180.0,
    ):
        self.base_url = (base_url or os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096")).rstrip("/")
        self.username = username or os.environ.get("OPENCODE_USER", "opencode")
        self.password = password or os.environ.get("OPENCODE_PASSWORD", "")
        self.timeout_sec = timeout_sec
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None or self._client.is_closed:
                auth = None
                if self.username and self.password:
                    auth = (self.username, self.password)
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    auth=auth,
                    timeout=self.timeout_sec,
                )
            return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        try:
            c = await self._get_client()
            r = await c.get("/global/health")
            return r.status_code == 200
        except Exception:
            return False

    async def create_session(self, directory: Optional[str] = None) -> str:
        c = await self._get_client()
        body: Dict[str, Any] = {}
        if directory:
            body["directory"] = directory
        r = await c.post("/session", json=body)
        if r.status_code not in (200, 201):
            raise OpencodeError(f"create_session failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        sid = data.get("id")
        if not sid:
            raise OpencodeError(f"create_session: no id in response: {data}")
        return sid

    async def list_sessions(self) -> list:
        c = await self._get_client()
        r = await c.get("/session")
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, list):
            return data
        return data.get("sessions", data.get("data", []))

    async def abort_all_sessions(self) -> int:
        sessions = await self.list_sessions()
        count = 0
        for s in sessions:
            sid = s.get("id") if isinstance(s, dict) else str(s)
            if sid:
                try:
                    await self.abort_session(sid)
                    count += 1
                except Exception:
                    pass
        return count

    async def send_message(
        self,
        session_id: str,
        text: str,
        agent: str,
        provider_id: str,
        model_id: str,
        system: Optional[str] = None,
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Sends a user text message to the given session and returns the parsed assistant response.

        Response shape from opencode:
        {
          "info": { "id": "msg_...", "role": "assistant", "error": ..., "tokens": ..., ... },
          "parts": [
            {"type": "step-start", ...},
            {"type": "text", "text": "...", ...},
            {"type": "step-finish", ...}
          ]
        }
        """
        c = await self._get_client()
        body: Dict[str, Any] = {
            "model": {"providerID": provider_id, "modelID": model_id},
            "agent": agent,
            "parts": [{"type": "text", "text": text}],
        }
        if system:
            body["system"] = system

        req_timeout = timeout_sec or self.timeout_sec
        r = await c.post(f"/session/{session_id}/message", json=body, timeout=req_timeout)
        if r.status_code != 200:
            raise OpencodeError(
                f"send_message failed ({r.status_code}): {r.text[:500]}"
            )
        data = r.json()
        return data

    @staticmethod
    def extract_text(response: Dict[str, Any]) -> str:
        """Concatenates text parts from a message response."""
        parts = response.get("parts") or []
        out: List[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "text":
                t = p.get("text")
                if isinstance(t, str):
                    out.append(t)
        return "".join(out)

    @staticmethod
    def get_error(response: Dict[str, Any]) -> Optional[str]:
        info = response.get("info") or {}
        err = info.get("error")
        if not err:
            return None
        if isinstance(err, dict):
            name = err.get("name") or err.get("type") or "Error"
            msg = err.get("message") or err.get("data", {}).get("message") or ""
            return f"{name}: {msg}".strip(": ")
        return str(err)

    async def run_perspective(
        self,
        agent: str,
        provider_id: str,
        model_id: str,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        directory: Optional[str] = None,
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Convenience: create session, send message, extract text, cleanup.
        Returns: {"text": str, "error": Optional[str], "tokens": dict, "raw": dict}
        """
        start = time.time()
        sid = await self.create_session(directory=directory)
        try:
            resp = await self.send_message(
                session_id=sid,
                text=user_prompt,
                agent=agent,
                provider_id=provider_id,
                model_id=model_id,
                system=system_prompt,
                timeout_sec=timeout_sec,
            )
            text = self.extract_text(resp)
            err = self.get_error(resp)
            info = resp.get("info") or {}
            return {
                "session_id": sid,
                "text": text,
                "error": err,
                "tokens": info.get("tokens") or {},
                "model": {"providerID": info.get("providerID"), "modelID": info.get("modelID")},
                "agent": info.get("agent"),
                "duration_ms": int((time.time() - start) * 1000),
                "raw": resp,
            }
        finally:
            await self.abort_session(sid)


_default_client: Optional[OpencodeClient] = None


def get_client() -> OpencodeClient:
    global _default_client
    if _default_client is None:
        _default_client = OpencodeClient()
    return _default_client


async def close_default() -> None:
    global _default_client
    if _default_client is not None:
        await _default_client.aclose()
        _default_client = None
