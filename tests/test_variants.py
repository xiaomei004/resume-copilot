"""Prompt 变体解析：底座 + 岗位叠加，缺变体时自动退回。"""

from __future__ import annotations

import unittest

from resume_copilot import agents
from resume_copilot.agents.base import build_messages, load_prompt, resolve_prompts


class TestVariantResolution(unittest.TestCase):
    def test_each_family_has_a_variant(self):
        for family in ("sales", "rnd", "support"):
            chain = resolve_prompts(agents.WRITER, family)
            self.assertEqual(chain, ["writer.md", f"writer.{family}.md"], family)

    def test_unknown_family_falls_back_to_base(self):
        for family in (None, "", "other", "intern"):
            self.assertEqual(resolve_prompts(agents.WRITER, family), ["writer.md"], family)

    def test_agent_without_variants_is_untouched(self):
        self.assertEqual(resolve_prompts(agents.JD_ANALYST, "sales"), ["jd_analyst.md"])

    def test_variant_files_are_non_empty(self):
        for family in ("sales", "rnd", "support"):
            text = load_prompt(f"writer.{family}.md")
            self.assertGreater(len(text), 400, family)


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

    def test_no_placeholder_left(self):
        system = build_messages(agents.WRITER, self.VARS, "support")[0]["content"]
        self.assertNotIn("{{", system)


if __name__ == "__main__":
    unittest.main()
