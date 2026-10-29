"""LLM 客户端：任何 OpenAI 兼容的 /chat/completions 服务都能用。

刻意只用标准库（urllib）发请求，不依赖 openai SDK —— 用户 clone 下来
装一个 python-docx 就能跑，不必再拉一个大包。
"""

from __future__ import annotations

import base64
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .jsonx import JsonParseError, loads_loose


class LLMError(RuntimeError):
    """调用模型失败（网络 / 鉴权 / 限流 / 返回异常）。"""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    def add(self, usage: dict | None) -> None:
        self.calls += 1
        if not usage:
            return
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
        }


class LLM:
    """OpenAI 兼容客户端。"""

    def __init__(self, cfg: Config, timeout: int = 120):
        if not cfg.api_key:
            raise LLMError("未配置 OPENAI_API_KEY：请复制 .env.example 为 .env 并填写，或先加 --mock 跑通流程。")
        self.cfg = cfg
        self.timeout = timeout
        self.usage = Usage()

    # ---------- 低层 ----------
    def _post(self, payload: dict) -> dict:
        url = f"{self.cfg.base_url}/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg.api_key}",
            },
            method="POST",
        )
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:  # 4xx/5xx
                detail = exc.read().decode("utf-8", "ignore")[:400]
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    last_err = LLMError(f"HTTP {exc.code}: {detail}")
                    time.sleep(2**attempt + random.random())
                    continue
                raise LLMError(f"HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_err = LLMError(f"网络错误: {exc}")
                if attempt < 2:
                    time.sleep(2**attempt + random.random())
                    continue
                raise last_err from exc
        raise last_err or LLMError("未知错误")

    # ---------- 高层 ----------
    def chat(
        self,
        messages: list[dict],
        *,
        purpose: str = "",
        temperature: float | None = None,
        model: str | None = None,
        json_mode: bool = True,
        max_tokens: int = 4096,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post(payload)
        self.usage.add(data.get("usage"))
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMError(f"返回体缺少 content（purpose={purpose}）: {str(data)[:300]}") from exc

    def json(self, messages: list[dict], *, purpose: str = "", **kwargs) -> dict:
        """要求模型输出 JSON；解析失败时把它自己的输出回喂一次做修复。"""
        text = self.chat(messages, purpose=purpose, **kwargs)
        try:
            obj = loads_loose(text)
        except JsonParseError:
            repair = messages + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": "上面的输出不是合法 JSON。请只输出一个合法 JSON 对象，不要任何解释、不要 markdown 代码围栏。",
                },
            ]
            text = self.chat(repair, purpose=f"{purpose}:repair", **kwargs)
            obj = loads_loose(text)  # 再失败就让异常冒泡，由上层记录
        if not isinstance(obj, dict):
            raise LLMError(f"{purpose}: 期望 JSON 对象，实际得到 {type(obj).__name__}")
        return obj

    def vision(self, prompt: str, image_path: str | Path) -> str:
        """把图片塞进 messages 做多模态识别（需要 vision_model）。"""
        if not self.cfg.vision_model:
            raise LLMError("未配置 RESUME_VISION_MODEL，无法识别图片版 JD。请把 JD 文字贴成 .txt/.md。")
        data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        suffix = Path(image_path).suffix.lower().lstrip(".") or "png"
        mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{data}"}},
                ],
            }
        ]
        return self.chat(messages, purpose="vision", model=self.cfg.vision_model, json_mode=False)

    def ping(self) -> dict:
        data = self._post(
            {
                "model": self.cfg.model,
                "messages": [{"role": "user", "content": "只回复 pong"}],
                "max_tokens": 8,
                "temperature": 0,
            }
        )
        return {
            "ok": True,
            "model": data.get("model", self.cfg.model),
            "reply": (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip(),
        }


class MockLLM:
    """离线跑通用：按 purpose 返回预置 JSON，便于测试与免 key 演示。"""

    def __init__(self, fixtures: dict[str, Any], usage: Usage | None = None):
        self.fixtures = fixtures
        self.usage = usage or Usage()
        self.cfg = Config()

    def chat(self, messages, *, purpose: str = "", **kwargs) -> str:
        self.usage.calls += 1
        if purpose in self.fixtures:
            return json.dumps(self.fixtures[purpose], ensure_ascii=False)
        if "vision" in purpose:
            return "（mock）图片识别跳过"
        raise LLMError(f"MockLLM 没有 purpose={purpose!r} 的预置输出")

    def json(self, messages, *, purpose: str = "", **kwargs) -> dict:
        self.usage.calls += 1
        payload = self.fixtures.get(purpose)
        if payload is None:
            raise LLMError(f"MockLLM 没有 purpose={purpose!r} 的预置输出")
        if isinstance(payload, str):
            payload = loads_loose(payload)
        return payload

    def vision(self, prompt: str, image_path) -> str:
        return ""

    def ping(self) -> dict:
        return {"ok": True, "model": "mock", "reply": "pong"}
