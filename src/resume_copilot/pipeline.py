"""编排器：把 7 个 Agent 串成一条可复现的流水线。

    JD + 旧简历 + 补充信息
        │
        ├─ ① JD 分析员        → 岗位画像（硬门槛/加分项/关键词/筛人逻辑）
        ├─ ② 调研员（可选）    → 带来源的调研简报（面试流程、加分信号）
        ├─ ③ 事实库构建员      → 原子事实（每条带来源与数字）
        ├─ ④ 定位策略师        → 主线叙事 / 强调什么 / 删什么
        ├─ ⑤ 简历撰写员        → 结构化简历 JSON
        ├─ ⑥ 质检员 × 机器闸门 → 问题清单（数字溯源、关键词、空话）
        ├─ ⑦ 修订员（循环 ≤N 轮）
        ├─ 渲染器             → DOCX → PDF → PNG，溢出自动收紧
        └─ ⑧ 面试教练          → 一页速查卡

每一步的输入输出都落盘到 `<job>/steps/`，可直接复盘。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import agents, ingest, schemas, verify
from .config import Config
from .llm import LLM, LLMError, MockLLM, Usage
from .render import capabilities, get_theme, render_resume
from .research import build_queries, collect
from .tracing import Trace

STEP_DIR = "steps"


@dataclass
class Job:
    root: Path
    inputs: dict
    state: dict = field(default_factory=dict)
    trace: Trace | None = None
    steps: list[dict] = field(default_factory=list)
    status: str = "pending"
    error: str = ""
    started: float = field(default_factory=time.time)

    @property
    def step_dir(self) -> Path:
        d = self.root / STEP_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, name: str, payload: Any) -> Path:
        path = self.step_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, (dict, list)):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(str(payload), encoding="utf-8")
        return path


class Ctx:
    """Agent 能看到的全部上下文（也是权限边界的物理体现）。"""

    def __init__(self, job: Job, llm):
        self.job = job
        self.inputs = job.inputs
        self.state = job.state
        self.trace = job.trace
        self.llm = llm


def prepare_inputs(
    jd_sources: list[ingest.Source],
    resume_sources: list[ingest.Source],
    info_sources: list[ingest.Source],
    role_hint: str = "",
) -> dict:
    return {
        "jd_text": ingest.join_text(jd_sources),
        "resume_text": ingest.join_text(resume_sources, limit=30000),
        "info_text": ingest.join_text(info_sources, limit=12000),
        "role_hint": role_hint,
        "files": {
            "jd": [s.name for s in jd_sources],
            "resume": [s.name for s in resume_sources],
            "info": [s.name for s in info_sources],
        },
    }


def _issue_brief(report: dict, critique: dict) -> list[dict]:
    issues = list(report.get("issues", []))
    for item in critique.get("issues", []):
        issues.append(
            {
                "severity": item.get("severity", "warn"),
                "kind": item.get("kind", "other"),
                "where": item.get("where", ""),
                "problem": item.get("problem", ""),
                "fix": item.get("fix", ""),
            }
        )
    return issues


def _fmt_issues(issues: list[dict]) -> str:
    if not issues:
        return "（无问题）"
    return "\n".join(f"- [{i['severity']}] {i.get('where', '')}：{i['problem']} → {i.get('fix', '')}" for i in issues)


def run(
    cfg: Config,
    inputs: dict,
    *,
    llm=None,
    out_root: str | Path | None = None,
    photo: str | Path | None = None,
    theme_name: str | None = None,
    on_step: Callable[[dict], None] | None = None,
    mock_fixtures: dict | None = None,
) -> dict:
    """跑完整条流水线，返回结果字典（含产物路径与诊断）。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = Path(out_root or cfg.out_dir) / f"job-{stamp}"
    root.mkdir(parents=True, exist_ok=True)

    job = Job(root=root, inputs=inputs)
    job.trace = Trace(root=root / "logs")
    ctx = Ctx(job, None)

    if llm is None:
        llm = MockLLM(mock_fixtures or {}) if mock_fixtures is not None else LLM(cfg)
    ctx.llm = llm
    if isinstance(llm, MockLLM) and mock_fixtures:
        llm.fixtures = mock_fixtures

    def step(agent, title, status="ok", detail="", artifact="", **meta):
        record = {"agent": agent, "title": title, "status": status, "detail": detail, "artifact": artifact, **meta}
        job.steps.append(record)
        job.trace.event(stage=agent, agent=title, status=status, detail=detail, artifact=artifact, **meta)
        if on_step:
            on_step(record)

    try:
        job.status = "running"
        step("pipeline", "开始", detail=f"输入 {len(inputs['files']['jd'])} 份 JD / {len(inputs['files']['resume'])} 份旧简历")

        # ① JD 分析
        out = agents.call_agent(agents.JD_ANALYST, ctx, agents.jd_vars(ctx), post=agents.post_jd)
        job.state["jd_profile"] = out["data"]
        art = job.save("01_jd_profile.json", out["data"])
        step("jd_analyst", agents.JD_ANALYST.title, detail=f"{out['data']['title']}（{out['data']['role_family']}）", artifact=str(art))

        # ② 调研（可选）
        provider = None
        if cfg.research_ready:
            from .research import get_provider

            provider = get_provider(cfg.tavily_key, cfg.research_enabled)
        if provider is not None and provider.enabled:
            search_text, hits = collect(provider, build_queries(job.state["jd_profile"]))
            job.save("02_search_raw.json", hits)
            ctx.state["search_results"] = search_text
            out = agents.call_agent(agents.RESEARCHER, ctx, agents.research_vars(ctx), post=agents.post_research)
            job.state["research_brief"] = out["data"]
            art = job.save("02_research.json", out["data"])
            step("researcher", agents.RESEARCHER.title, detail=f"{len(out['data']['findings'])} 条结论", artifact=str(art))
        else:
            job.state["research_brief"] = None
            step("researcher", agents.RESEARCHER.title, status="skip", detail="未配置检索 key，自动降级为纯推理")

        # ③ 事实库
        out = agents.call_agent(agents.FACT_EXTRACTOR, ctx, agents.facts_vars(ctx), post=agents.post_facts)
        job.state["facts"] = out["data"]
        art = job.save("03_facts.json", out["data"])
        step("fact_extractor", agents.FACT_EXTRACTOR.title, detail=f"{len(out['data']['facts'])} 条事实", artifact=str(art))

        # ④ 定位
        out = agents.call_agent(agents.STRATEGIST, ctx, agents.strategy_vars(ctx), post=agents.post_strategy)
        job.state["positioning"] = out["data"]
        art = job.save("04_positioning.json", out["data"])
        step("strategist", agents.STRATEGIST.title, detail=out["data"]["headline"][:40], artifact=str(art))

        # ⑤ 起草 + ⑥⑦ 质检循环
        out = agents.call_agent(agents.WRITER, ctx, agents.writer_vars(ctx), post=agents.post_resume)
        current = out["data"]
        job.state["resume"] = current  # 质检/修订阶段都要读它
        job.save("05_resume_draft.json", current)
        step("writer", agents.WRITER.title, detail=f"{schemas.bullet_stats(current)['bullets']} 条要点", artifact=str(job.step_dir / "05_resume_draft.json"))

        best, best_score = current, -1
        rounds = max(0, cfg.max_revision_rounds)
        for round_index in range(rounds + 1):
            report = verify.check_resume(current, job.state["facts"], job.state["jd_profile"])
            ctx.state["issues_text"] = _fmt_issues(report["issues"]) + "\n（见 ../05 草稿，逐条核对）"
            crit = agents.call_agent(agents.CRITIC, ctx, agents.critic_vars(ctx), post=agents.post_critic)
            job.save(f"06_critic_r{round_index + 1}.json", crit["data"])
            issues = _issue_brief(report, crit["data"])
            errors = sum(1 for i in issues if i["severity"] == "error")
            detail = f"第 {round_index + 1} 轮：{errors} 个硬错误 / {len(issues)} 条意见"
            step("critic", f"{agents.CRITIC.title}#{round_index + 1}", detail=detail, artifact=str(job.step_dir / f"06_critic_r{round_index + 1}.json"))

            score = -errors * 10 - len(issues)
            if score > best_score:
                best, best_score, best_report = current, score, report

            if errors == 0 and not issues:
                break
            if round_index == rounds:
                break
            job.state["review_issues"] = issues
            revised = agents.call_agent(agents.REVISER, ctx, agents.reviser_vars(ctx), post=agents.post_resume)
            current = revised["data"]
            job.state["resume"] = current
            job.save(f"07_resume_revised_r{round_index + 1}.json", current)
            step("reviser", f"{agents.REVISER.title}#{round_index + 1}", detail=f"按 {len(issues)} 条意见修订", artifact=str(job.step_dir / f"07_resume_revised_r{round_index + 1}.json"))

        final_resume = best
        job.state["resume"] = final_resume
        job.save("08_resume_final.json", final_resume)

        # 渲染
        theme = get_theme(theme_name, job.state["jd_profile"].get("role_family", "other"))
        render = render_resume(
            final_resume,
            job.root,
            theme,
            stem="resume",
            photo=photo,
            soffice=cfg.soffice,
            want_pdf=capabilities(cfg.soffice)["pdf_convert"],
        )
        job.state["render"] = render
        job.save("09_render.json", render)
        step(
            "renderer",
            "渲染器",
            detail=f"页数={render['pages']} 字号={render['body_pt']} 主题={render['theme']}",
            artifact=render["docx"] or "",
        )

        # ⑧ 速查卡
        out = agents.call_agent(agents.COACH, ctx, agents.coach_vars(ctx), post=agents.post_coach)
        job.state["card"] = out["data"]
        job.save("10_interview_card.json", out["data"])
        md = schemas.card_to_markdown(out["data"], title=f"{job.state['jd_profile']['title']} · 面试速查卡")
        card_path = job.root / "interview_card.md"
        card_path.write_text(md, encoding="utf-8")
        step("coach", agents.COACH.title, detail=f"{len(out['data']['questions'])} 个问题", artifact=str(card_path))

        job.status = "done"
    except LLMError as exc:
        job.status = "failed"
        job.error = f"模型调用失败：{exc}"
        step("error", "失败", status="fail", detail=str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 - 兜底写进报告，别让 web 端只有 500
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        step("error", "失败", status="fail", detail=job.error[:300])

    # 汇总
    usage = getattr(llm, "usage", Usage()).as_dict()
    manifest = {
        "job_id": root.name,
        "status": job.status,
        "error": job.error,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": getattr(getattr(llm, "cfg", None), "model", "mock"),
        "role_family": (job.state.get("jd_profile") or {}).get("role_family"),
        "title": (job.state.get("jd_profile") or {}).get("title"),
        "inputs": inputs.get("files", {}),
        "artifacts": {
            "resume_docx": (job.state.get("render") or {}).get("docx"),
            "resume_pdf": (job.state.get("render") or {}).get("pdf"),
            "resume_png": (job.state.get("render") or {}).get("png"),
            "interview_card": str(job.root / "interview_card.md") if job.state.get("card") else None,
            "report": str(job.root / "report.md"),
        },
        "metrics": {
            **((job.state.get("render") or {}).get("sections") and {"sections": job.state["render"]["sections"]} or {}),
            "bullets": (job.state.get("render") or {}).get("bullets"),
            "pages": (job.state.get("render") or {}).get("pages"),
            "single_page": (job.state.get("render") or {}).get("single_page"),
            "keyword_coverage": (verify.check_resume(job.state["resume"], job.state["facts"], job.state["jd_profile"]).get("metrics", {}) if job.state.get("resume") else {}).get("keyword_coverage"),
        },
        "usage": usage,
        "steps": job.steps,
        "trace": job.trace.summary(),
    }
    (job.root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (job.root / "report.md").write_text(_render_report(job, manifest), encoding="utf-8")
    return {"job": job, "manifest": manifest, "root": str(job.root)}


def _render_report(job: Job, manifest: dict) -> str:
    jd = job.state.get("jd_profile") or {}
    facts = (job.state.get("facts") or {}).get("facts", [])
    resume = job.state.get("resume") or {}
    render = job.state.get("render") or {}
    lines = [
        f"# 简历优化报告 · {jd.get('title', '未命名岗位')}",
        "",
        f"- 状态：**{job.status}**" + (f"（{job.error}）" if job.error else ""),
        f"- 岗位族：`{jd.get('role_family', '-')}`｜筛人逻辑：{jd.get('screening_logic', '-')}",
        f"- 输入：JD {len(job.inputs['files']['jd'])} 份 / 旧简历 {len(job.inputs['files']['resume'])} 份 / 补充 {len(job.inputs['files']['info'])} 份",
        f"- 事实库：{len(facts)} 条｜要点：{render.get('bullets', '-')} 条｜页数：{render.get('pages', '未校验')}",
        "",
        "## 一、定位",
        "",
        f"**{job.state.get('positioning', {}).get('headline', '-')}**",
        "",
        job.state.get("positioning", {}).get("narrative", ""),
        "",
        "## 二、执行时间线",
        "",
        "| 步骤 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for s in job.steps:
        lines.append(f"| {s['title']} | {s['status']} | {str(s.get('detail', ''))[:60]} |")
    lines += [
        "",
        "## 三、产物",
        "",
        f"- 简历 DOCX：`{render.get('docx') or '-'}`",
        f"- 简历 PDF：`{render.get('pdf') or '-'}`",
        f"- 预览图：`{render.get('png') or '-'}`",
        f"- 面试速查卡：`interview_card.md`",
        "",
        "## 四、下一步（需要你人工确认）",
        "",
        "1. 打开预览图/PDF，确认排版是否一页、有没有孤字换行。",
        "2. 检查数字：报告里的硬错误已由机器拦截，但**语义上的夸大**仍需你自己把关。",
        "3. 速查卡里的口播稿请出声念一遍，按 200 字/分钟核对时长。",
        "4. 把 `manifest.json` 里的 `usage` 存档，便于估算后续调用的成本。",
        "",
        f"> 提示：本报告由 resume-copilot 自动生成（模型 `{manifest.get('model')}`），"
        "所有事实均来自你提供的材料；若发现不实内容，说明输入材料本身有误，请回到事实库修正。",
    ]
    return "\n".join(lines)


def run_from_paths(
    cfg: Config,
    jd: list[str],
    resumes: list[str],
    info: list[str] | None = None,
    role_hint: str = "",
    **kwargs,
) -> dict:
    """CLI 友好入口：给路径就跑。"""
    sources_jd = ingest.load_sources(jd, kind="jd")
    sources_resume = ingest.load_sources(resumes, kind="resume")
    sources_info = ingest.load_sources(info or [], kind="info")
    if not sources_jd:
        raise ValueError("至少提供一份 JD（--jd）")
    if not sources_resume and not sources_info:
        raise ValueError("至少提供一份旧简历（--resume）或补充信息（--info）")
    inputs = prepare_inputs(sources_jd, sources_resume, sources_info, role_hint)
    return run(cfg, inputs, **kwargs)
