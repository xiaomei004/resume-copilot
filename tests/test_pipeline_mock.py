"""端到端：用 mock 模型跑完整条流水线（不需要 key、不联网）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from resume_copilot import agents
from resume_copilot.config import Config
from resume_copilot.ingest import read_any
from resume_copilot.pipeline import prepare_inputs, run
from tests._support import demo_inputs, load_fixtures, material


class TestPipelineMock(unittest.TestCase):
    def test_full_run(self):
        fixtures = load_fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(api_key="", out_dir=Path(tmp), max_revision_rounds=1, research_enabled=False)
            result = run(cfg, demo_inputs(), mock_fixtures=fixtures)

            manifest = result["manifest"]
            self.assertEqual(manifest["status"], "done", msg=manifest.get("error"))
            self.assertEqual(manifest["title"], "客户经理")
            self.assertEqual(manifest["role_family"], "sales")

            root = Path(result["root"])
            self.assertTrue((root / "manifest.json").is_file())
            self.assertTrue((root / "report.md").is_file())
            self.assertTrue((root / "interview_card.md").is_file())
            for name in ("01_jd_profile.json", "03_facts.json", "04_positioning.json", "08_resume_final.json"):
                self.assertTrue((root / "steps" / name).is_file(), name)

            docx = manifest["artifacts"]["resume_docx"]
            self.assertIsNotNone(docx)
            self.assertTrue(Path(docx).is_file())

            report = (root / "report.md").read_text(encoding="utf-8")
            self.assertIn("定位", report)
            self.assertIn("执行时间线", report)

            card = (root / "interview_card.md").read_text(encoding="utf-8")
            self.assertIn("自我介绍", card)
            self.assertIn("高频问题", card)

            # 检索关闭时应记录为 skipped 而不是失败
            statuses = {s["agent"]: s["status"] for s in manifest["steps"]}
            self.assertEqual(statuses.get("researcher"), "skip")


class TestPipelineGuards(unittest.TestCase):
    def test_missing_inputs_raise(self):
        cfg = Config(out_dir=Path(tempfile.mkdtemp()))
        with self.assertRaises(ValueError):
            from resume_copilot.pipeline import run_from_paths

            run_from_paths(cfg, jd=[], resumes=[])

    def test_jd_text_joined(self):
        jd = read_any(material("jd.txt"), "jd")
        info = read_any(material("info.md"), "info")
        inputs = prepare_inputs([jd], [], [info], "客户经理")
        self.assertIn("客户经理", inputs["jd_text"])
        self.assertIn("CET-6", inputs["info_text"])
        self.assertEqual(inputs["files"]["jd"], ["jd.txt"])

    def test_mock_llm_unknown_purpose(self):
        from resume_copilot.llm import LLMError, MockLLM

        llm = MockLLM({"writer": {"a": 1}})
        with self.assertRaises(LLMError):
            llm.json([], purpose="critic")


class TestAgentSpecs(unittest.TestCase):
    def test_permissions_are_disjoint_for_writer_and_researcher(self):
        self.assertIn(agents.Perm.SEARCH_WEB, agents.RESEARCHER.permissions)
        self.assertNotIn(agents.Perm.SEARCH_WEB, agents.WRITER.permissions)
        self.assertIn(agents.Perm.WRITE_RESUME, agents.WRITER.permissions)
        self.assertNotIn(agents.Perm.WRITE_RESUME, agents.CRITIC.permissions)

    def test_every_prompt_file_exists(self):
        from resume_copilot.agents.base import load_prompt

        for spec in agents.ALL_AGENTS:
            text = load_prompt(spec.prompt_file)
            self.assertGreater(len(text), 200, spec.prompt_file)

    def test_prompt_rendering_leaves_no_placeholder(self):
        from resume_copilot.agents.base import build_messages, render_prompt

        messages = build_messages(
            agents.JD_ANALYST,
            {"role_hint": "客户经理", "jd_text": "招聘客户经理", "research_brief": "无"},
        )
        system = messages[0]["content"]
        self.assertNotIn("{{", system)
        self.assertIn("客户经理", system)
        self.assertEqual(render_prompt("a{{x}}b", {"x": ""}), "ab")


if __name__ == "__main__":
    unittest.main()
