import unittest
from app.council_core import consensus

class TestConsensus(unittest.TestCase):
    def test_consensus_blocked(self):
        agent_runs = {
            "codex": {
                "status": "done",
                "parsed_output": {
                    "decision": "block",
                    "items": [{"type": "blocker"}]
                }
            }
        }
        res = consensus.calculate_consensus("test-run", agent_runs)
        self.assertEqual(res.status, "blocked")

    def test_consensus_accepted_with_changes(self):
        agent_runs = {
            "codex": {
                "status": "done",
                "parsed_output": {
                    "decision": "accept_with_changes",
                    "items": [{"type": "major_risk"}]
                }
            }
        }
        res = consensus.calculate_consensus("test-run", agent_runs)
        self.assertEqual(res.status, "accepted_with_changes")

    def test_consensus_needs_followup_on_questions(self):
        agent_runs = {
            "codex": {
                "status": "done",
                "parsed_output": {
                    "decision": "needs_more_info",
                    "items": [
                        {"type": "question"},
                        {"type": "question"},
                        {"type": "question"}
                    ]
                }
            }
        }
        res = consensus.calculate_consensus("test-run", agent_runs)
        self.assertEqual(res.status, "needs_followup")
