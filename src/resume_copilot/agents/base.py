"""Agent 基础设施：角色声明、权限、Prompt 渲染、调用与留痕。

一个 Agent = 一份 prompt 模板 + 一组权限 + 一个输入装配函数。
编排器只认 AgentSpec，不认具体是谁，这样加一个新角色不用改流水线。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Callable

PROMPT_DIR = "prompts"
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_PROMPT_CACHE: dict[str, str] = {}


# ---------------- 权限 ----------------
class Perm:
    READ_JD = "read_jd"
    READ_FACTS = "read_facts"
    READ_RESUME = "read_resume"
    READ_RESEARCH = "read_research"
    SEARCH_WEB = "search_web"
    WRITE_RESUME = "write_resume"
    CRITIQUE = "critique"


@dataclass
class AgentSpec:
    key: str
    title: str
    prompt_file: str
    permissions: tuple[str, ...] = ()
    temperature: float | None = None
    note: str = ""

    def describe(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "prompt": self.prompt_file,
            "permissions": list(self.permissions),
            "note": self.note,
        }


def load_prompt(name: str) -> str:
    """从包内 prompts/ 读取模板（同时兼容源码目录运行与安装后运行）。"""
    if name in _PROMPT_CACHE:
        return _PROMPT_CACHE[name]
    try:
        text = resources.files("resume_copilot").joinpath(PROMPT_DIR, name).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        fallback = Path(__file__).resolve().parent.parent / PROMPT_DIR / name
        text = fallback.read_text(encoding="utf-8")
    _PROMPT_CACHE[name] = text
    return text


def render_prompt(template: str, variables: dict[str, Any]) -> str:
    """{{name}} 替换；未提供的变量填空字符串，避免把占位符发给模型。"""

    def repl(m: re.Match) -> str:
        key = m.group(1)
        value = variables.get(key, "")
        if isinstance(value, (dict, list)):
            import json

            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    return _PLACEHOLDER.sub(repl, template)


def build_messages(spec: AgentSpec, variables: dict[str, Any]) -> list[dict]:
    common = load_prompt("system_common.md")
    role = render_prompt(load_prompt(spec.prompt_file), variables)
    return [
        {"role": "system", "content": common + "\n\n---\n\n" + role},
        {"role": "user", "content": "请按上述角色与 schema 输出 JSON。"},
    ]


@dataclass
class Step:
    agent: str
    title: str
    status: str  # ok | fail | skip
    seconds: float = 0.0
    detail: str = ""
    artifact: str = ""
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "title": self.title,
            "status": self.status,
            "seconds": round(self.seconds, 2),
            "detail": self.detail,
            "artifact": self.artifact,
            **({"meta": self.meta} if self.meta else {}),
        }


def call_agent(
    spec: AgentSpec,
    ctx: Any,
    variables: dict[str, Any],
    *,
    post: Callable[[dict, Any], tuple[dict, dict]] | None = None,
) -> dict:
    """调一次 Agent：渲染 prompt → 请求 JSON → 可选规范化 → 留痕。

    `post` 返回 (raw, normalized)；流水线统一拿 raw 做留档、normalized 做下游输入。
    """
    started = time.time()
    messages = build_messages(spec, variables)
    raw = ctx.llm.json(messages, purpose=spec.key, temperature=spec.temperature)
    elapsed = time.time() - started
    if post is not None:
        raw, normalized = post(raw, ctx)
    else:
        normalized = raw
    ctx.trace.event(
        stage=spec.key,
        agent=spec.title,
        seconds=round(elapsed, 2),
        permissions=spec.permissions,
    )
    return {"raw": raw, "data": normalized, "seconds": elapsed}
