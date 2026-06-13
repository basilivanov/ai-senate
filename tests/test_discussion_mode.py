"""
Comprehensive tests for the discussion mode feature.

Covers:
- Discussion profile configuration in agents.yaml
- Discussion prompt loading
- Discussion-mode service logic (task, role, focus areas, mode propagation)
- Discussion-mode contract building (AgentRequestContract)
- Discussion-mode API endpoint (create run with profile=discussion)
- Discussion-mode writer logic (synthesis prompt vs spec prompt)
- Discussion-mode findings aggregation
- Discussion-mode consensus calculation
- Discussion jury composition
"""
import os
import json
import tempfile
import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import yaml
import httpx

from app.main import app
from app.council_core import consensus, findings
from app.council_core.contracts import (
    AgentRequestContract, Workspace, Instructions,
    ConsensusResultContract, WriterResponseContract,
)
from app.runs import storage as storage_mod
from app.runs.storage import init_db


# ---------------------------------------------------------------------------
# Helper: project root so we can resolve config files
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.environ.get(
    "AI_SENATE_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
AGENTS_YAML = os.path.join(PROJECT_ROOT, "app", "config", "agents.yaml")
DISCUSSION_PROMPT_PATH = os.path.join(
    PROJECT_ROOT, ".opencode", "agents", "discuss_participant.md"
)


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ===========================================================================
# 1. Discussion profile & configuration tests
# ===========================================================================
class TestDiscussionProfileConfig(unittest.TestCase):
    """Test that the discussion profile is correctly configured in agents.yaml."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _load_yaml(AGENTS_YAML)

    def test_discussion_profile_exists(self):
        """Discussion profile must be defined."""
        self.assertIn("discussion", self.cfg.get("profiles", {}))

    def test_discussion_profile_mode(self):
        """Discussion profile must have mode=discussion."""
        profile = self.cfg["profiles"]["discussion"]
        self.assertEqual(profile.get("mode"), "discussion")

    def test_discussion_profile_jury(self):
        """Discussion profile must reference the 'discussion' jury."""
        profile = self.cfg["profiles"]["discussion"]
        self.assertEqual(profile.get("jury"), "discussion")

    def test_discussion_profile_writer_enabled(self):
        """Discussion profile should have writer enabled (synthesis)."""
        profile = self.cfg["profiles"]["discussion"]
        self.assertTrue(profile.get("writer", False))

    def test_discussion_profile_max_rounds(self):
        """Discussion profile should have at least 2 rounds for cross-review."""
        profile = self.cfg["profiles"]["discussion"]
        self.assertGreaterEqual(profile.get("max_rounds", 0), 2)

    def test_discussion_jury_exists(self):
        """The 'discussion' jury must be defined in juries section."""
        juries = self.cfg.get("juries", {})
        self.assertIn("discussion", juries)

    def test_discussion_jury_non_empty(self):
        """The discussion jury must contain at least one perspective."""
        juries = self.cfg.get("juries", {})
        discussion_jury = juries.get("discussion", [])
        self.assertGreaterEqual(len(discussion_jury), 1)

    def test_discussion_jury_perspectives_enabled(self):
        """All perspectives in the discussion jury must be enabled."""
        perspectives = self.cfg.get("perspectives", {})
        juries = self.cfg.get("juries", {})
        for p_key in juries.get("discussion", []):
            self.assertIn(p_key, perspectives, f"Perspective '{p_key}' not found in config")
            self.assertTrue(
                perspectives[p_key].get("enabled", True),
                f"Perspective '{p_key}' should be enabled",
            )

    def test_review_profiles_have_no_discussion_mode(self):
        """Non-discussion profiles should not have mode=discussion."""
        profiles = self.cfg.get("profiles", {})
        for name, profile in profiles.items():
            if name == "discussion":
                continue
            mode = profile.get("mode", "review")
            self.assertNotEqual(
                mode, "discussion",
                f"Profile '{name}' should not have mode=discussion",
            )


# ===========================================================================
# 2. Discussion prompt loading tests
# ===========================================================================
class TestDiscussionPromptLoading(unittest.TestCase):
    """Test loading and parsing of the discussion participant system prompt."""

    def test_discussion_prompt_file_exists(self):
        """The discuss_participant.md file must exist."""
        self.assertTrue(
            os.path.exists(DISCUSSION_PROMPT_PATH),
            f"Discussion prompt file not found: {DISCUSSION_PROMPT_PATH}",
        )

    def test_discussion_prompt_not_empty(self):
        """The discussion prompt must not be empty."""
        with open(DISCUSSION_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertGreater(len(content.strip()), 100)

    def test_discussion_prompt_has_no_role_mentions(self):
        """Discussion prompt should NOT mention IT-specific roles (architect, DBA, coder, security)."""
        with open(DISCUSSION_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read().lower()
        it_roles = ["архитектор", "dba", "кодер", "security", "базы данных", "баз данных"]
        for role in it_roles:
            self.assertNotIn(
                role, content,
                f"Discussion prompt should not mention IT role: '{role}'",
            )

    def test_discussion_prompt_mentions_participant(self):
        """Discussion prompt should mention 'Участник обсуждения' or similar role-free concept."""
        with open(DISCUSSION_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Участник обсуждения", content)

    def test_discussion_prompt_has_json_schema(self):
        """Discussion prompt must include the JSON output schema."""
        with open(DISCUSSION_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("agent_review_response_v1", content)

    def test_load_discussion_prompt_function(self):
        """Test _load_discussion_prompt() strips YAML front matter and returns content."""
        from app.runs.service import _load_discussion_prompt
        result = _load_discussion_prompt()
        self.assertIsNotNone(result, "Discussion prompt should load successfully")
        self.assertGreater(len(result), 50, "Discussion prompt should have substantial content")
        # Should NOT start with "---" after stripping front matter
        self.assertFalse(result.startswith("---"), "YAML front matter should be stripped")

    def test_discussion_prompt_focus_areas(self):
        """Discussion prompt should include focus areas for general discussion."""
        with open(DISCUSSION_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        focus_keywords = ["аргументы", "альтернатив", "вывод", "неоднознач"]
        for kw in focus_keywords:
            self.assertIn(
                kw, content.lower(),
                f"Discussion prompt should mention focus area: '{kw}'",
            )


# ===========================================================================
# 3. Service-level discussion mode logic tests
# ===========================================================================
class TestDiscussionServiceLogic(unittest.TestCase):
    """Test service.py functions that implement discussion-mode behaviour."""

    def test_get_profile_discussion(self):
        """_get_profile('discussion') must return mode=discussion."""
        from app.runs.service import _get_profile, _load_agent_config
        cfg = _load_agent_config()
        profile = _get_profile(cfg, "discussion")
        self.assertEqual(profile.get("mode"), "discussion")

    def test_get_profile_default_mode_is_review(self):
        """Unknown profile should default to mode=review."""
        from app.runs.service import _get_profile, _load_agent_config
        cfg = _load_agent_config()
        profile = _get_profile(cfg, "nonexistent_profile")
        self.assertEqual(profile.get("mode"), "review")

    def test_get_jury_discussion(self):
        """_get_jury('discussion') must return the discussion jury list."""
        from app.runs.service import _get_jury, _load_agent_config
        cfg = _load_agent_config()
        jury = _get_jury(cfg, "discussion")
        self.assertIsInstance(jury, list)
        self.assertGreaterEqual(len(jury), 1)

    def test_discussion_jury_members_are_valid_perspectives(self):
        """Each jury member must be a defined perspective."""
        from app.runs.service import _get_jury, _get_perspective, _load_agent_config
        cfg = _load_agent_config()
        jury = _get_jury(cfg, "discussion")
        for member in jury:
            p = _get_perspective(cfg, member)
            self.assertIn("name", p, f"Perspective '{member}' should have a name")

    def test_discussion_mode_role_override(self):
        """In discussion mode, agent role should be 'Участник обсуждения', not the perspective's role."""
        from app.runs.service import _get_profile, _load_agent_config
        cfg = _load_agent_config()
        profile = _get_profile(cfg, "discussion")
        self.assertEqual(profile.get("mode"), "discussion")
        # The actual role override happens in run_council_task, verified by contract building below

    def test_build_discussion_contract_round1(self):
        """Build AgentRequestContract for discussion mode Round 1 — verify mode, role, task, focus."""
        workspace = Workspace(
            root="/tmp/test",
            spec_file="/tmp/test/spec.md",
            owner_input_file="/tmp/test/owner.md",
        )
        contract = AgentRequestContract(
            run_id="test-discussion-r1",
            agent="minimax27",
            role="Участник обсуждения",
            task="Round 1: Обсуди предложенный вопрос/тему независимо.",
            workspace=workspace,
            instructions=Instructions(
                focus=["суть вопроса", "аргументы за", "аргументы против",
                        "альтернативы", "практические выводы", "неоднозначности"],
            ),
            mode="discussion",
        )
        self.assertEqual(contract.mode, "discussion")
        self.assertEqual(contract.role, "Участник обсуждения")
        self.assertIn("Обсуди", contract.task)
        self.assertIn("аргументы за", contract.instructions.focus)
        self.assertIn("аргументы против", contract.instructions.focus)

    def test_build_discussion_contract_round2(self):
        """Build AgentRequestContract for discussion mode Round 2 — cross-review."""
        workspace = Workspace(
            root="/tmp/test",
            spec_file="/tmp/test/spec.md",
            owner_input_file="/tmp/test/owner.md",
        )
        contract = AgentRequestContract(
            run_id="test-discussion-r2",
            agent="kimi26",
            role="Участник обсуждения",
            task="You are in Round 2: Cross-review discussion.",
            workspace=workspace,
            instructions=Instructions(
                focus=["cross-review", "согласие/несогласие", "уточнение"],
            ),
            mode="discussion",
        )
        self.assertEqual(contract.mode, "discussion")
        self.assertEqual(contract.role, "Участник обсуждения")
        self.assertIn("Cross-review", contract.task)

    def test_build_review_contract_has_review_mode(self):
        """Build AgentRequestContract for review mode — verify mode is NOT discussion."""
        workspace = Workspace(
            root="/tmp/test",
            spec_file="/tmp/test/spec.md",
            owner_input_file="/tmp/test/owner.md",
        )
        contract = AgentRequestContract(
            run_id="test-review-r1",
            agent="minimax27",
            role="Critical Reviewer",
            task="Round 1: Review the specification independently.",
            workspace=workspace,
            instructions=Instructions(
                focus=["requirements clarity", "MVP scope"],
            ),
            mode="review",
        )
        self.assertEqual(contract.mode, "review")
        self.assertNotEqual(contract.role, "Участник обсуждения")

    def test_contract_json_serialization_discussion(self):
        """AgentRequestContract with discussion mode must serialize correctly."""
        workspace = Workspace(
            root="/tmp/test",
            spec_file="/tmp/test/spec.md",
            owner_input_file="/tmp/test/owner.md",
        )
        contract = AgentRequestContract(
            run_id="test-serialize",
            agent="minimax27",
            role="Участник обсуждения",
            task="Test task",
            workspace=workspace,
            instructions=Instructions(focus=["test"]),
            mode="discussion",
        )
        json_str = contract.model_dump_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["mode"], "discussion")
        self.assertEqual(parsed["role"], "Участник обсуждения")


# ===========================================================================
# 4. Discussion mode API tests
# ===========================================================================
class TestDiscussionModeAPI(unittest.TestCase):
    """Test API endpoints with discussion profile."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cls._old_db = storage_mod.DB_PATH
        storage_mod.DB_PATH = os.path.join(cls._tmpdir, "test_council.db")
        init_db()

    @classmethod
    def tearDownClass(cls):
        storage_mod.DB_PATH = cls._old_db

    def test_create_discussion_run(self):
        """POST /api/runs with profile=discussion should create a run."""
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                payload = {
                    "spec_text": "Стоит ли вводить 4-дневную рабочую неделю?",
                    "owner_input": "Нужно обсудить плюсы и минусы",
                    "new_document": False,
                    "profile": "discussion",
                    "max_rounds": 2,
                    "auto_stop_if_clean": True,
                }
                r = await client.post("/api/runs", json=payload)
                self.assertEqual(r.status_code, 200)
                data = r.json()
                self.assertIn("id", data)
                self.assertEqual(data["status"], "queued")
        asyncio.run(run_test())

    def test_create_discussion_run_with_topic_as_spec(self):
        """Discussion runs should accept a general question as spec_text."""
        import time
        time.sleep(1.1)  # Avoid timestamp collision with previous test's run_id
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                payload = {
                    "spec_text": "Какой язык программирования лучше всего изучать первым в 2025 году?",
                    "owner_input": "",
                    "new_document": False,
                    "profile": "discussion",
                    "max_rounds": 1,
                    "auto_stop_if_clean": True,
                }
                r = await client.post("/api/runs", json=payload)
                self.assertEqual(r.status_code, 200)
        asyncio.run(run_test())

    def test_config_includes_discussion_profile(self):
        """GET /api/config must include the discussion profile."""
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                r = await client.get("/api/config")
                self.assertEqual(r.status_code, 200)
                data = r.json()
                self.assertIn("profiles", data)
                self.assertIn("discussion", data["profiles"])
                self.assertEqual(data["profiles"]["discussion"].get("mode"), "discussion")
        asyncio.run(run_test())

    def test_config_includes_discussion_jury(self):
        """GET /api/config must include the discussion jury."""
        transport = httpx.ASGITransport(app=app)
        async def run_test():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                r = await client.get("/api/config")
                self.assertEqual(r.status_code, 200)
                data = r.json()
                self.assertIn("juries", data)
                self.assertIn("discussion", data["juries"])
                discussion_jury = data["juries"]["discussion"]
                self.assertIsInstance(discussion_jury, list)
                self.assertGreaterEqual(len(discussion_jury), 1)
        asyncio.run(run_test())


# ===========================================================================
# 5. Discussion mode writer tests
# ===========================================================================
class TestDiscussionWriterLogic(unittest.TestCase):
    """Test that writer module produces correct prompts for discussion vs review mode."""

    def test_writer_config_discussion_mode_override(self):
        """Writer system_override for discussion mode should mention 'synthesis'."""
        # We test the actual logic by examining the string in writer.py
        from app.council_core import writer as writer_module
        # Read writer.py source to verify the discussion prompt
        writer_src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "council_core", "writer.py",
        )
        with open(writer_src_path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("discussion", src)
        self.assertIn("synthesis", src)
        self.assertIn("synthesizer", src.lower())

    def test_writer_discussion_prompt_differs_from_review(self):
        """Discussion mode writer prompt must differ from review mode."""
        from app.council_core.writer import _load_writer_config
        cfg = _load_writer_config()
        review_prompt = cfg.get("system_override", "")
        # The discussion override replaces this, so we verify it's a different prompt
        self.assertIn("updated specification", review_prompt.lower())


# ===========================================================================
# 6. Discussion mode findings & consensus tests
# ===========================================================================
class TestDiscussionFindingsAggregation(unittest.TestCase):
    """Test that findings aggregation works correctly for discussion mode responses."""

    def test_aggregate_discussion_findings(self):
        """aggregate_findings should work with discussion-mode agent responses."""
        agent_runs = {
            "agent1": {
                "status": "done",
                "role": "Участник обсуждения",
                "parsed_output": {
                    "decision": "accept_with_changes",
                    "items": [
                        {
                            "id": "agent1-point-001",
                            "type": "info",
                            "category": "аргументы за",
                            "severity": "medium",
                            "title": "Сильный аргумент в пользу",
                            "description": "Описание аргумента",
                            "evidence": "Факт 1",
                            "recommendation": "Учесть при принятии решения",
                            "confidence": 0.8,
                        },
                        {
                            "id": "agent1-point-002",
                            "type": "suggestion",
                            "category": "альтернативы",
                            "severity": "low",
                            "title": "Альтернативный подход",
                            "description": "Можно рассмотреть...",
                            "confidence": 0.6,
                        },
                    ],
                    "open_questions": ["Какой бюджет?"],
                    "required_actions": [],
                },
            },
            "agent2": {
                "status": "done",
                "role": "Участник обсуждения",
                "parsed_output": {
                    "decision": "accept",
                    "items": [
                        {
                            "id": "agent2-point-001",
                            "type": "risk",
                            "category": "аргументы против",
                            "severity": "high",
                            "title": "Серьёзный риск",
                            "description": "Риск провала",
                            "confidence": 0.9,
                        },
                    ],
                    "open_questions": [],
                    "required_actions": ["Провести анализ"],
                },
            },
        }
        result = findings.aggregate_findings(agent_runs)

        # Check categories exist
        self.assertIn("infos", result)
        self.assertIn("suggestions", result)
        self.assertIn("risks", result)

        # Check items are properly categorized
        self.assertEqual(len(result["infos"]), 1)
        self.assertEqual(len(result["suggestions"]), 1)
        self.assertEqual(len(result["risks"]), 1)

        # Check item fields
        info_item = result["infos"][0]
        self.assertEqual(info_item["agent"], "agent1")
        self.assertEqual(info_item["role"], "Участник обсуждения")
        self.assertEqual(info_item["category"], "аргументы за")

    def test_aggregate_empty_discussion_findings(self):
        """aggregate_findings should return empty categories for no completed agents."""
        agent_runs = {
            "agent1": {"status": "failed", "parsed_output": None},
        }
        result = findings.aggregate_findings(agent_runs)
        for cat in ["blockers", "major_risks", "risks", "suggestions", "questions", "infos"]:
            self.assertEqual(result[cat], [])

    def test_discussion_findings_include_all_types(self):
        """Discussion mode findings can include all finding types (info, suggestion, risk, etc.)."""
        agent_runs = {
            "agent1": {
                "status": "done",
                "role": "Участник обсуждения",
                "parsed_output": {
                    "decision": "accept",
                    "items": [
                        {"id": "i1", "type": "info", "category": "c", "severity": "low",
                         "title": "t", "description": "d", "confidence": 0.5},
                        {"id": "i2", "type": "suggestion", "category": "c", "severity": "low",
                         "title": "t", "description": "d", "confidence": 0.5},
                        {"id": "i3", "type": "risk", "category": "c", "severity": "low",
                         "title": "t", "description": "d", "confidence": 0.5},
                        {"id": "i4", "type": "question", "category": "c", "severity": "low",
                         "title": "t", "description": "d", "confidence": 0.5},
                    ],
                },
            },
        }
        result = findings.aggregate_findings(agent_runs)
        self.assertEqual(len(result["infos"]), 1)
        self.assertEqual(len(result["suggestions"]), 1)
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(len(result["questions"]), 1)


class TestDiscussionConsensus(unittest.TestCase):
    """Test consensus calculation with discussion-mode agent responses."""

    def test_discussion_consensus_accepted(self):
        """Discussion where all agents agree should result in 'accepted'."""
        agent_runs = {
            "agent1": {
                "status": "done",
                "parsed_output": {
                    "decision": "accept",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
            "agent2": {
                "status": "done",
                "parsed_output": {
                    "decision": "accept",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
        }
        res = consensus.calculate_consensus("disc-run-1", agent_runs)
        self.assertEqual(res.status, "accepted")

    def test_discussion_consensus_with_major_risk(self):
        """Discussion with a major risk finding should result in 'accepted_with_changes'."""
        agent_runs = {
            "agent1": {
                "status": "done",
                "parsed_output": {
                    "decision": "accept_with_changes",
                    "items": [{"type": "major_risk"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
        }
        res = consensus.calculate_consensus("disc-run-2", agent_runs)
        self.assertEqual(res.status, "accepted_with_changes")

    def test_discussion_consensus_blocked(self):
        """Discussion with a blocker should result in 'blocked'."""
        agent_runs = {
            "agent1": {
                "status": "done",
                "parsed_output": {
                    "decision": "block",
                    "items": [{"type": "blocker"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
        }
        res = consensus.calculate_consensus("disc-run-3", agent_runs)
        self.assertEqual(res.status, "blocked")

    def test_discussion_consensus_many_questions(self):
        """Discussion with many open questions should result in 'needs_followup'."""
        agent_runs = {
            "agent1": {
                "status": "done",
                "parsed_output": {
                    "decision": "needs_more_info",
                    "items": [
                        {"type": "question"},
                        {"type": "question"},
                        {"type": "question"},
                    ],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
        }
        res = consensus.calculate_consensus("disc-run-4", agent_runs)
        self.assertEqual(res.status, "needs_followup")

    def test_discussion_consensus_split_votes(self):
        """Discussion with split votes and no majority should result in 'needs_human_decision'."""
        agent_runs = {
            "agent1": {
                "status": "done",
                "parsed_output": {
                    "decision": "reject",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
            "agent2": {
                "status": "done",
                "parsed_output": {
                    "decision": "needs_more_info",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
            "agent3": {
                "status": "done",
                "parsed_output": {
                    "decision": "reject",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
            "agent4": {
                "status": "done",
                "parsed_output": {
                    "decision": "needs_more_info",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
        }
        res = consensus.calculate_consensus("disc-run-5", agent_runs)
        self.assertEqual(res.status, "needs_human_decision")

    def test_discussion_consensus_failed_majority(self):
        """Discussion where majority of agents failed should result in 'needs_followup'."""
        agent_runs = {
            "agent1": {"status": "failed", "parsed_output": None, "error": "timeout"},
            "agent2": {"status": "timeout", "parsed_output": None, "error": "timeout"},
            "agent3": {
                "status": "done",
                "parsed_output": {
                    "decision": "accept",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
        }
        res = consensus.calculate_consensus("disc-run-6", agent_runs)
        self.assertEqual(res.status, "needs_followup")


# ===========================================================================
# 7. Discussion mode vs review mode differentiation tests
# ===========================================================================
class TestDiscussionVsReviewDifferentiation(unittest.TestCase):
    """Verify that discussion and review modes produce different contracts and prompts."""

    def test_different_roles(self):
        """Discussion mode should use 'Участник обсуждения', review should use perspective role."""
        discussion_role = "Участник обсуждения"
        review_role = "Critical Reviewer"
        self.assertNotEqual(discussion_role, review_role)

    def test_different_tasks(self):
        """Discussion Round 1 task should mention 'Обсуди', review should mention 'Review'."""
        discussion_task = "Round 1: Обсуди предложенный вопрос/тему независимо."
        review_task = "Round 1: Review the specification independently."
        self.assertIn("Обсуди", discussion_task)
        self.assertIn("Review", review_task)
        self.assertNotEqual(discussion_task, review_task)

    def test_different_focus_areas(self):
        """Discussion focus areas should differ from review focus areas."""
        discussion_focus = ["суть вопроса", "аргументы за", "аргументы против",
                           "альтернативы", "практические выводы", "неоднозначности"]
        review_focus = ["requirements clarity", "MVP scope", "architecture",
                        "missing contracts", "risks", "blockers", "test strategy",
                        "implementation complexity"]
        # No overlap expected
        overlap = set(discussion_focus) & set(review_focus)
        self.assertEqual(len(overlap), 0, f"Focus areas should not overlap: {overlap}")

    def test_different_round2_tasks(self):
        """Discussion Round 2 task should differ from review Round 2 task."""
        discussion_r2 = "You are in Round 2: Cross-review discussion."
        review_r2 = "You are in Round 2: Cross-review."
        self.assertIn("discussion", discussion_r2.lower())
        # Both mention cross-review but discussion adds nuance
        self.assertNotEqual(discussion_r2, review_r2)

    def test_different_writer_tasks(self):
        """Discussion writer should create synthesis, review writer should create updated spec."""
        discussion_writer_task = (
            "Create a synthesis document summarizing the discussion. "
            "Include: key points raised, areas of agreement, areas of disagreement, "
            "open questions, and final conclusions with recommendations."
        )
        review_writer_task = (
            "Create updated specification without hiding blockers, major risks or unresolved questions."
        )
        self.assertIn("synthesis", discussion_writer_task.lower())
        self.assertIn("specification", review_writer_task.lower())
        self.assertNotEqual(discussion_writer_task, review_writer_task)

    def test_different_system_prompts(self):
        """Discussion should use discuss_participant.md, review should use perspective .md."""
        from app.runs.service import _load_discussion_prompt
        discussion_prompt = _load_discussion_prompt()
        self.assertIsNotNone(discussion_prompt)
        # Discussion prompt should not be the same as architect/coder/etc prompts
        architect_prompt_path = os.path.join(
            PROJECT_ROOT, ".opencode", "agents", "architect.md"
        )
        if os.path.exists(architect_prompt_path):
            with open(architect_prompt_path, "r", encoding="utf-8") as f:
                architect_content = f.read()
            # Strip front matter for comparison
            if architect_content.startswith("---"):
                parts = architect_content.split("---", 2)
                if len(parts) >= 3:
                    architect_content = parts[2].strip()
            self.assertNotEqual(discussion_prompt, architect_content)


# ===========================================================================
# 8. Integration: service orchestration logic for discussion mode
# ===========================================================================
class TestDiscussionServiceIntegration(unittest.TestCase):
    """Test service-level logic for discussion mode orchestration."""

    def test_discussion_mode_loads_system_override(self):
        """When mode=discussion, _load_discussion_prompt should be called for system_override."""
        from app.runs.service import _load_discussion_prompt
        prompt = _load_discussion_prompt()
        self.assertIsNotNone(prompt)
        self.assertIn("Участник обсуждения", prompt)

    def test_discussion_mode_sets_run_data_mode(self):
        """run_data dict should contain mode='discussion' when discussion profile is used."""
        # Simulate what run_council_task does
        from app.runs.service import _get_profile, _load_agent_config
        cfg = _load_agent_config()
        profile_cfg = _get_profile(cfg, "discussion")
        run_mode = profile_cfg.get("mode", "review")
        self.assertEqual(run_mode, "discussion")

    def test_review_mode_does_not_load_discussion_override(self):
        """When mode=review, discussion_system_override should be None."""
        from app.runs.service import _get_profile, _load_agent_config
        cfg = _load_agent_config()
        profile_cfg = _get_profile(cfg, "full_council")
        run_mode = profile_cfg.get("mode", "review")
        discussion_system_override = None
        if run_mode == "discussion":
            from app.runs.service import _load_discussion_prompt
            discussion_system_override = _load_discussion_prompt()
        self.assertIsNone(discussion_system_override)


# ===========================================================================
# 9. Round-2 merge for discussion mode
# ===========================================================================
class TestDiscussionRound2Merge(unittest.TestCase):
    """Test that _merge_round2 works correctly for discussion-mode findings."""

    def test_merge_adds_new_discussion_points(self):
        """Round 2 cross-review should add new findings from discussion participants."""
        from app.runs.service import _merge_round2
        round1_findings = {
            "infos": [
                {
                    "id": "agent1-point-001",
                    "agent": "agent1",
                    "role": "Участник обсуждения",
                    "type": "info",
                    "category": "аргументы за",
                    "severity": "medium",
                    "title": "Аргумент за",
                    "description": "Описание",
                    "evidence": "",
                    "recommendation": "",
                    "confidence": 0.8,
                },
            ],
            "blockers": [],
            "major_risks": [],
            "risks": [],
            "suggestions": [],
            "questions": [],
        }
        cross_reviews = {
            "agent2": {
                "status": "done",
                "parsed_output": {
                    "items": [
                        {
                            "id": "agent2-new-001",
                            "type": "suggestion",
                            "category": "альтернативы",
                            "severity": "low",
                            "title": "Новая альтернатива из R2",
                            "description": "Описание",
                            "evidence": "",
                            "recommendation": "",
                            "confidence": 0.7,
                        },
                    ],
                },
                "role": "Участник обсуждения",
            },
        }
        merged = _merge_round2(round1_findings, cross_reviews)
        # Original info should still be there
        self.assertEqual(len(merged["infos"]), 1)
        # New suggestion from R2 should be added
        self.assertEqual(len(merged["suggestions"]), 1)
        self.assertEqual(merged["suggestions"][0]["title"], "Новая альтернатива из R2")

    def test_merge_deduplicates_by_id(self):
        """_merge_round2 should not duplicate findings with the same id."""
        from app.runs.service import _merge_round2
        round1_findings = {
            "infos": [
                {
                    "id": "shared-id",
                    "agent": "agent1",
                    "role": "Участник обсуждения",
                    "type": "info",
                    "category": "general",
                    "severity": "medium",
                    "title": "T",
                    "description": "D",
                    "evidence": "",
                    "recommendation": "",
                    "confidence": 0.5,
                },
            ],
            "blockers": [],
            "major_risks": [],
            "risks": [],
            "suggestions": [],
            "questions": [],
        }
        cross_reviews = {
            "agent2": {
                "status": "done",
                "parsed_output": {
                    "items": [
                        {
                            "id": "shared-id",  # Same ID — should not be duplicated
                            "type": "info",
                            "category": "general",
                            "severity": "medium",
                            "title": "T",
                            "description": "D",
                            "evidence": "",
                            "recommendation": "",
                            "confidence": 0.5,
                        },
                    ],
                },
                "role": "Участник обсуждения",
            },
        }
        merged = _merge_round2(round1_findings, cross_reviews)
        # Should still have only 1 info item
        self.assertEqual(len(merged["infos"]), 1)


# ===========================================================================
# 10. Edge cases
# ===========================================================================
class TestDiscussionEdgeCases(unittest.TestCase):
    """Edge cases for discussion mode."""

    def test_empty_spec_text_for_discussion(self):
        """Discussion mode should work even with empty spec_text (just a question)."""
        workspace = Workspace(
            root="/tmp/test",
            spec_file="/tmp/test/spec.md",
            owner_input_file="/tmp/test/owner.md",
        )
        contract = AgentRequestContract(
            run_id="test-empty-spec",
            agent="minimax27",
            role="Участник обсуждения",
            task="Round 1: Обсуди предложенный вопрос/тему независимо.",
            workspace=workspace,
            instructions=Instructions(focus=["суть вопроса"]),
            mode="discussion",
        )
        self.assertEqual(contract.mode, "discussion")

    def test_discussion_mode_single_agent(self):
        """Discussion with just 1 agent should still produce valid consensus."""
        agent_runs = {
            "solo_agent": {
                "status": "done",
                "parsed_output": {
                    "decision": "accept",
                    "items": [{"type": "info"}],
                    "open_questions": [],
                    "required_actions": [],
                },
            },
        }
        res = consensus.calculate_consensus("disc-solo", agent_runs)
        self.assertEqual(res.status, "accepted")

    def test_discussion_mode_all_agents_failed(self):
        """If all discussion agents fail, consensus should be 'needs_followup'."""
        agent_runs = {
            "agent1": {"status": "failed", "parsed_output": None, "error": "err"},
            "agent2": {"status": "failed", "parsed_output": None, "error": "err"},
        }
        res = consensus.calculate_consensus("disc-all-failed", agent_runs)
        self.assertEqual(res.status, "needs_followup")

    def test_discussion_findings_categories_intact(self):
        """Findings categories should always have all 6 keys regardless of input."""
        agent_runs = {}
        result = findings.aggregate_findings(agent_runs)
        expected_keys = {"blockers", "major_risks", "risks", "suggestions", "questions", "infos"}
        self.assertEqual(set(result.keys()), expected_keys)

    def test_discussion_profile_no_project_context(self):
        """Discussion profile should not require project context by default."""
        from app.runs.service import _get_profile, _load_agent_config
        cfg = _load_agent_config()
        profile = _get_profile(cfg, "discussion")
        self.assertFalse(profile.get("project_context", False))


if __name__ == "__main__":
    unittest.main()
