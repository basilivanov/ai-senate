import os
import unittest
import asyncio
import tempfile
import json
import httpx

from app.main import app
from app.runs.storage import init_db
from app.runs import storage as storage_mod


class TestWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cls._old_db = storage_mod.DB_PATH
        storage_mod.DB_PATH = os.path.join(cls._tmpdir, "test_council.db")
        init_db()

    @classmethod
    def tearDownClass(cls):
        storage_mod.DB_PATH = cls._old_db

    def test_health(self):
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                r = await client.get("/api/health")
                self.assertEqual(r.status_code, 200)
                data = r.json()
                self.assertEqual(data["status"], "ok")
                self.assertIn("opencode", data)
        asyncio.run(run_test())

    def test_config(self):
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                r = await client.get("/api/config")
                self.assertEqual(r.status_code, 200)
                data = r.json()
                self.assertIn("perspectives", data)
                self.assertIn("writer", data)
                self.assertIn("juries", data)
        asyncio.run(run_test())

    def test_spa_fallback(self):
        """Non-API paths should return the SPA index.html (or 404 fallback if not built)."""
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                r = await client.get("/")
                self.assertEqual(r.status_code, 200)
                # Either SPA index (has <!doctype html>) or JSON fallback
                body = r.text
                self.assertTrue(
                    "<!doctype html>" in body.lower() or "ai-senate backend running" in body,
                    f"Unexpected response: {body[:200]!r}",
                )
        asyncio.run(run_test())

    def test_create_run_and_list(self):
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                payload = {
                    "spec_text": "# Test spec",
                    "owner_input": "Some changes",
                    "new_document": False,
                    "max_rounds": 1,
                    "auto_stop_if_clean": True,
                }
                r = await client.post("/api/runs", json=payload)
                self.assertEqual(r.status_code, 200)
                created = r.json()
                self.assertIn("id", created)
                self.assertEqual(created["status"], "queued")

                r = await client.get("/api/runs")
                self.assertEqual(r.status_code, 200)
                self.assertIsInstance(r.json(), list)
        asyncio.run(run_test())

    def test_run_endpoints_404(self):
        """Unknown run should 404 on detail endpoints."""
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                r = await client.get("/api/runs/this-does-not-exist")
                self.assertEqual(r.status_code, 404)
                r = await client.get("/api/runs/this-does-not-exist/findings")
                self.assertEqual(r.status_code, 404)
        asyncio.run(run_test())
