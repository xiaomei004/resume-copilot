"""Prompt 变体解析：底座 + 岗位叠加，缺变体时自动退回。"""

from __future__ import annotations

import unittest

from resume_copilot import agents
from resume_copilot.agents.base import build_messages, load_prompt, resolve_prompts


class TestVariantResolution(unittest.TestCase):
    def test_writer_has_variant_for_each_family(self):
        for family in ("sales", "rnd", "support"):
            chain = resolve_prompts(agents.WRITER, family)
            self.assertEqual(chain, ["writer.md", f"writer.{family}.md"], family)

    def test_coach_has_variant_for_each_family(self):
        for family in ("sales", "rnd", "support"):
            chain = resolve_prompts(agents.COACH, family)
            self.assertEqual(chain, ["coach.md", f"coach.{family}.md"], family)

    def test_reviser_reuses_writer_variant(self):
        # 修订员复用撰写员的岗位变体，避免"改稿时忘了岗位规则"
        self.assertEqual(resolve_prompts(agents.REVISER, "rnd"), ["reviser.md", "writer.rnd.md"])
        self.assertEqual(resolve_prompts(agents.REVISER, "sales"), ["reviser.md", "writer.sales.md"])
        self.assertEqual(resolve_prompts(agents.REVISER, "other"), ["reviser.md"])

    def test_unknown_family_falls_back_to_base(self):
        for family in (None, "", "other", "intern"):
            self.assertEqual(resolve_prompts(agents.WRITER, family), ["writer.md"], family)

    def test_agent_without_variants_is_untouched(self):
        self.assertEqual(resolve_prompts(agents.JD_ANALYST, "sales"), ["jd_analyst.md"])

    def test_variant_files_are_non_empty(self):
        for stem in ("writer", "coach"):
            for family in ("sales", "rnd", "support"):
                text = load_prompt(f"{stem}.{family}.md")
                self.assertGreater(len(text), 400, f"{stem}.{family}")


class TestMessagesWithVariant(unittest.TestCase):
    VARS = {
        "jd_profile": {"title": "客户经理", "role_family": "sales"},
        "positioning": {"headline": "x"},
        "facts": "F1 ...",
        "research_brief": "（无）",
        "issues": "（无）",
    }

    def test_sales_variant_is_appended(self):
        system = build_messages(agents.WRITER, self.VARS, "sales")[0]["content"]
        self.assertIn("通用底座", system)
        self.assertIn("岗位变体：市场", system)
        self.assertNotIn("岗位变体：研发", system)

    def test_rnd_variant_is_appended(self):
        system = build_messages(agents.WRITER, self.VARS, "rnd")[0]["content"]
        self.assertIn("岗位变体：研发", system)
        self.assertIn("不要写代码行数", system)

    def test_base_only_without_family(self):
        system = build_messages(agents.WRITER, self.VARS, None)[0]["content"]
        self.assertIn("通用底座", system)
        self.assertNotIn("岗位变体：", system)

    def test_coach_variants_carry_their_own_focus(self):
        sales = build_messages(agents.COACH, {
            "jd_profile": {"title": "客户经理"}, "resume_json": {}, "research_brief": "",
        }, "sales")[0]["content"]
        rnd = build_messages(agents.COACH, {
            "jd_profile": {"title": "后端开发"}, "resume_json": {}, "research_brief": "",
        }, "rnd")[0]["content"]
        # 用变体独有的小节标题做断言，避免被底座文案干扰
        self.assertIn("群面 / 辩论", sales)
        self.assertNotIn("技术追问与手撕", sales)
        self.assertIn("技术追问与手撕", rnd)
        self.assertIn("客户现场处置", build_messages(agents.COACH, {
            "jd_profile": {"title": "实施工程师"}, "resume_json": {}, "research_brief": "",
        }, "support")[0]["content"])

    def test_no_placeholder_left(self):
        system = build_messages(agents.WRITER, self.VARS, "support")[0]["content"]
        self.assertNotIn("{{", system)


if __name__ == "__main__":
    unittest.main()
