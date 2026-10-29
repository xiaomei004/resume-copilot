"""确定性闸门：数字溯源、关键词覆盖、空话体检。"""

from __future__ import annotations

import unittest

from resume_copilot import schemas, verify


def _resume(texts: list[str]) -> dict:
    return {
        "header": {"name": "林一舟", "objective": {"role": "客户经理"}, "contacts": ["155"]},
        "sections": [
            {
                "id": "s1",
                "title": "实习经历",
                "items": [{"type": "bullet", "lead": "", "text": t, "fact_refs": []} for t in texts],
            }
        ],
    }


def _facts(*texts_and_numbers) -> dict:
    facts = []
    for i, (text, numbers) in enumerate(texts_and_numbers, 1):
        facts.append({"id": f"F{i}", "category": "experience", "text": text, "numbers": numbers, "source": "t", "confidence": "high"})
    return {"facts": facts}


class TestNumbers(unittest.TestCase):
    def test_thousands_separator_is_same_number(self):
        resume = _resume(["外呼约 1,500 通，沉淀 30 条线索"])
        facts = _facts(("外呼 1500 通，30 条线索", ["1500", "30"]))
        self.assertEqual(verify.check_numbers(resume, facts), [])

    def test_unsourced_number_is_error(self):
        resume = _resume(["完成 500 万销售额"])
        facts = _facts(("完成 300 万销售额", ["300"]))
        issues = verify.check_numbers(resume, facts)
        self.assertTrue(issues)
        self.assertEqual(issues[0]["kind"], "unsourced_number")
        self.assertIn("500", issues[0]["problem"])

    def test_no_numbers_no_issue(self):
        self.assertEqual(verify.check_numbers(_resume(["负责客户拜访"]), _facts(("x", []))), [])


class TestFactRefs(unittest.TestCase):
    def test_dangling_ref(self):
        resume = _resume(["某个要点"])
        resume["sections"][0]["items"][0]["fact_refs"] = ["F99"]
        issues = verify.check_fact_refs(resume, _facts(("x", [])))
        self.assertEqual(issues[0]["kind"], "dangling_fact_ref")


class TestLanguage(unittest.TestCase):
    def test_empty_phrase_flagged(self):
        issues = verify.check_language(_resume(["沟通能力强，性格开朗"]))
        kinds = {i["kind"] for i in issues}
        self.assertIn("empty_phrase", kinds)

    def test_too_long_flagged(self):
        issues = verify.check_language(_resume(["字" * 120]))
        self.assertIn("too_long", {i["kind"] for i in issues})


class TestCoverage(unittest.TestCase):
    def test_ratio(self):
        resume = _resume(["政企客户 与 商机 推进"])
        cov = verify.keyword_coverage(resume, ["政企客户", "商机", "招投标", "回款"])
        self.assertEqual(cov["checked"], 4)
        self.assertAlmostEqual(cov["ratio"], 0.5)

    def test_low_coverage_warns(self):
        resume = _resume(["完全不相关的描述"])
        report = verify.check_resume(resume, _facts(("x", [])), {"keywords": ["a1", "b2", "c3", "d4", "e5", "f6"]})
        self.assertIn("low_keyword_coverage", {i["kind"] for i in report["issues"]})


class TestNormalize(unittest.TestCase):
    def test_resume_defaults_fill(self):
        raw = {
            "header": {"name": "张三", "objective": "后端开发", "contacts": ["138"]},
            "sections": [{"title": "项目", "items": [{"type": "bullet", "text": "做了个系统"}]}],
        }
        resume = schemas.normalize_resume(raw)
        self.assertEqual(resume["header"]["objective"]["role"], "后端开发")
        self.assertEqual(resume["sections"][0]["items"][0]["type"], "bullet")

    def test_validate_catches_missing_name(self):
        errors = schemas.validate_resume({"header": {}, "sections": []})
        self.assertTrue(any("name" in e for e in errors))
        self.assertTrue(any("sections" in e for e in errors))

    def test_role_family_guess(self):
        self.assertEqual(schemas.guess_role_family("客户经理（专业不限）"), "sales")
        self.assertEqual(schemas.guess_role_family("技术研发工程师"), "rnd")
        self.assertEqual(schemas.guess_role_family("实施工程师"), "support")


if __name__ == "__main__":
    unittest.main()
