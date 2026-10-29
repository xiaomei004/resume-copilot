"""配置加载：.env + 环境变量。

设计原则：**不含任何内置密钥**。用户复制 .env.example -> .env 自行填写，
或直接导出环境变量。缺 key 时不做硬失败，而是走 Mock 提示（见 cli doctor）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

TRUTHY = {"1", "true", "yes", "y", "on"}


def load_dotenv(path: str | Path = ".env", override: bool = False) -> dict[str, str]:
    """极简 .env 解析器，避免为一行配置引入 python-dotenv。"""
    path = Path(path)
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY


@dataclass
class Config:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    vision_model: str = ""
    tavily_key: str = ""
    soffice: str = ""
    out_dir: Path = field(default_factory=lambda: Path("./out"))
    temperature: float = 0.4
    max_revision_rounds: int = 2
    research_enabled: bool = True
    language: str = "zh"

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> Config:
        load_dotenv(env_file)
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1").strip().rstrip("/"),
            model=os.environ.get("OPENAI_MODEL", "deepseek-chat").strip(),
            vision_model=os.environ.get("RESUME_VISION_MODEL", "").strip(),
            tavily_key=os.environ.get("TAVILY_API_KEY", "").strip(),
            soffice=os.environ.get("RESUME_SOFFICE", "").strip(),
            out_dir=Path(os.environ.get("RESUME_OUT_DIR", "./out")),
            temperature=float(os.environ.get("RESUME_TEMPERATURE", "0.4")),
            max_revision_rounds=int(os.environ.get("RESUME_MAX_ROUNDS", "2")),
            research_enabled=_bool("RESUME_RESEARCH", True),
        )

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def research_ready(self) -> bool:
        return self.research_enabled and bool(self.tavily_key)

    def masked_key(self) -> str:
        if not self.api_key:
            return "(未配置)"
        return self.api_key[:6] + "..." + self.api_key[-4:] if len(self.api_key) > 12 else "***"
