"""LLM 输出解析工具。

模型经常返回 ```json 围栏、中文引号、尾逗号，或把 JSON 包在一段解释里。
这里提供零依赖的容错解析，避免因为格式问题让整条流水线失败。
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.+?)```", re.S)


class JsonParseError(ValueError):
    """模型输出无法解析为 JSON。"""


def _strip_fence(text: str) -> str:
    m = _FENCE.search(text)
    return m.group(1) if m else text


def _slice_object(text: str) -> str:
    """从任意文本里截出第一个平衡的 {...} 或 [...]。"""
    text = text.strip()
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start < 0:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text


def _fix_common(text: str) -> str:
    # 中文引号 / 中文冒号 / 尾逗号
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = re.sub(r"\n\s*\n", "\n", text)
    return text


def loads_loose(text: str) -> Any:
    """尽最大努力把模型输出解析成 Python 对象。"""
    if text is None:
        raise JsonParseError("空输出")
    raw = _strip_fence(text).strip()
    for candidate in (raw, _slice_object(raw), _fix_common(_slice_object(raw))):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise JsonParseError(f"无法解析为 JSON，前 200 字：{raw[:200]!r}")


def get(obj: Any, path: str, default: Any = None) -> Any:
    """按 'a.b.0.c' 取值，取不到返回 default。"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        else:
            return default
    return cur


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [value]


def as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return default
