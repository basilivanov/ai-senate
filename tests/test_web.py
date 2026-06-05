import unittest
import asyncio
import httpx
from app.main import app
from app.runs.storage import init_db

class TestWeb(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_index_page(self):
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("AI Senate", response.text)
        asyncio.run(run_test())

    def test_fragments(self):
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                # Test consensus-fragment
                response = await client.get("/runs/20260529-102617/consensus-fragment")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Consensus Summary", response.text)

                # Test findings-fragment
                response = await client.get("/runs/20260529-102617/findings-fragment")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Findings", response.text)

                # Test updated-spec-fragment
                response = await client.get("/runs/20260529-102617/updated-spec-fragment")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Updated Spec", response.text)

                # Test changes-fragment
                response = await client.get("/runs/20260529-102617/changes-fragment")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Changes Summary", response.text)

                # Test round-log-fragment
                response = await client.get("/runs/20260529-102617/round-log-fragment")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Round Log", response.text)
        asyncio.run(run_test())
