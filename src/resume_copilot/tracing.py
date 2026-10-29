"""留痕：每个 Agent 的输入输出都落盘，便于复盘与排错。

产出两份：
- trace.jsonl  机器可读的事件流（含耗时、token、权限）
- trace.log    人可读的时间线
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Trace:
    root: Path
    events: list[dict] = field(default_factory=list)
    _t0: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.root / "trace.jsonl"
        self.log_path = self.root / "trace.log"

    def event(self, stage: str, **fields: Any) -> dict:
        record = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "t": round(time.time() - self._t0, 2),
            "stage": stage,
            **fields,
        }
        self.events.append(record)
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        bits = [f"[{record['ts']}] {stage}"]
        if "agent" in record:
            bits.append(f"({record['agent']})")
        if "status" in record:
            bits.append(f"<{record['status']}>")
        if "seconds" in record:
            bits.append(f"{record['seconds']}s")
        for key, value in record.items():
            if key in {"ts", "t", "stage", "agent", "status", "seconds"}:
                continue
            bits.append(f"{key}={value}")
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(" ".join(bits) + "\n")
        return record

    def summary(self) -> dict:
        return {
            "events": len(self.events),
            "total_seconds": round(time.time() - self._t0, 2),
            "arts": [e["artifact"] for e in self.events if e.get("artifact")],
        }
