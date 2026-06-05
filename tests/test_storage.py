import os
import tempfile
import unittest
from app.runs import storage


class TestStorage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = storage.DB_PATH
        storage.DB_PATH = os.path.join(self._tmp, "test_council.db")
        storage.init_db()

    def tearDown(self):
        storage.DB_PATH = self._old
        if os.path.exists(self._tmp):
            import shutil
            shutil.rmtree(self._tmp, ignore_errors=True)

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
