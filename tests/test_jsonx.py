"""容错 JSON 解析与取值工具。"""

from __future__ import annotations

import unittest

from resume_copilot.jsonx import JsonParseError, as_list, as_text, get, loads_loose


class TestLoadsLoose(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(loads_loose('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        raw = '好的，结果如下：\n```json\n{"a": [1, 2]}\n```\n希望有帮助'
        self.assertEqual(loads_loose(raw), {"a": [1, 2]})

    def test_trailing_comma(self):
        self.assertEqual(loads_loose('{"a": 1, "b": [1,2,],}'), {"a": 1, "b": [1, 2]})

    def test_chinese_quotes(self):
        self.assertEqual(loads_loose('{“a”: “b”}'), {"a": "b"})

    def test_noise_around(self):
        raw = '前言 {"a": "含有 { 花括号 } 的字符串"} 后记'
        self.assertEqual(loads_loose(raw), {"a": "含有 { 花括号 } 的字符串"})

    def test_array_root(self):
        self.assertEqual(loads_loose("[1, 2, 3]"), [1, 2, 3])

    def test_error(self):
        with self.assertRaises(JsonParseError):
            loads_loose("完全不是 JSON")


class TestHelpers(unittest.TestCase):
    def test_get_nested(self):
        obj = {"a": {"b": [{"c": 7}]}}
        self.assertEqual(get(obj, "a.b.0.c"), 7)
        self.assertIsNone(get(obj, "a.x.y"))

    def test_as_list_and_text(self):
        self.assertEqual(as_list(None), [])
        self.assertEqual(as_list("x"), ["x"])
        self.assertEqual(as_text("  hi "), "hi")
        self.assertEqual(as_text(3), "3")
        self.assertEqual(as_text(None, "d"), "d")


if __name__ == "__main__":
    unittest.main()
