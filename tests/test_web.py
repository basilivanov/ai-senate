import os
import unittest
import asyncio
import tempfile
import httpx

from app.main import app
from app.runs.storage import init_db
from app.runs import storage as storage_mod


class TestWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use a temp DB so tests don't clobber dev data
        cls._tmpdir = tempfile.mkdtemp()
        cls._old_db = storage_mod.DB_PATH
        storage_mod.DB_PATH = os.path.join(cls._tmpdir, "test_council.db")
        init_db()

    @classmethod
    def tearDownClass(cls):
        storage_mod.DB_PATH = cls._old_db

    def test_index_page(self):
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("AI Senate", response.text)
        asyncio.run(run_test())

    def test_fragments_with_real_run(self):
        """Creates a real run row in the (temp) DB, then queries fragment endpoints."""
        run_id = "testrun-20260101-000000"
        storage_mod.create_run(run_id, new_document=False, max_rounds=2, auto_stop_if_clean=True)
        # Touch all the files the fragments look for, with empty content
        run_dir = os.path.join(os.path.dirname(storage_mod.DB_PATH), "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "consensus.json"), "w") as f:
            f.write('{"summary": "Consensus Summary", "status": "accepted", "counts": {}, "agent_status": {}, "decision_votes": {}, "required_actions": [], "unresolved_questions": []}')
        with open(os.path.join(run_dir, "findings.json"), "w") as f:
            f.write('{"blockers": [], "major_risks": [], "risks": [], "suggestions": [], "questions": [], "infos": []}')
        with open(os.path.join(run_dir, "updated-spec.md"), "w") as f:
            f.write("# Updated Spec\n")
        with open(os.path.join(run_dir, "changes.json"), "w") as f:
            f.write('{"added": [], "changed": [], "removed": [], "kept_unresolved": []}')
        with open(os.path.join(run_dir, "run.json"), "w") as f:
            f.write('{"round_log": []}')

        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                for ep, needle in [
                    ("/runs/" + run_id + "/consensus-fragment", "Consensus Summary"),
                    ("/runs/" + run_id + "/findings-fragment", "Findings"),
                    ("/runs/" + run_id + "/updated-spec-fragment", "Updated Spec"),
                    ("/runs/" + run_id + "/changes-fragment", "Changes Summary"),
                    ("/runs/" + run_id + "/round-log-fragment", "Round Log"),
                ]:
                    r = await client.get(ep)
                    self.assertEqual(r.status_code, 200, f"{ep} returned {r.status_code}")
                    self.assertIn(needle, r.text, f"{ep} missing {needle!r}")
        asyncio.run(run_test())
