"""测试公共工具：不依赖 pytest，`python -m unittest discover -s tests` 即可。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def load_fixtures() -> dict:
    return json.loads((EXAMPLES / "mock" / "fixtures.json").read_text(encoding="utf-8"))


def material(name: str) -> Path:
    return EXAMPLES / "materials" / name


def demo_inputs() -> dict:
    from resume_copilot.ingest import read_any
    from resume_copilot.pipeline import prepare_inputs

    jd = [read_any(material("jd.txt"), "jd")]
    resume = [read_any(material("resume_old.md"), "resume")]
    info = [read_any(material("info.md"), "info")]
    return prepare_inputs(jd, resume, info, "客户经理")
