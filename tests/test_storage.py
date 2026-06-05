import os
import unittest
from app.runs import storage

class TestStorage(unittest.TestCase):
    def setUp(self):
        storage.DB_PATH = "/opt/ai-lab/ai-senate/data/test_council.db"
        storage.init_db()

    def tearDown(self):
        if os.path.exists(storage.DB_PATH):
            os.remove(storage.DB_PATH)

    def test_create_and_get_run(self):
        storage.create_run("test-run-123", False)
        run = storage.get_run("test-run-123")
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "queued")
        self.assertFalse(run["new_document"])

    def test_update_status(self):
        storage.create_run("test-run-456", True)
        storage.update_run_status("test-run-456", "running")
        run = storage.get_run("test-run-456")
        self.assertEqual(run["status"], "running")
