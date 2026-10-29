"""七个内置 Agent 的声明与装配逻辑（prompt 见 ../prompts/）。

权限设计的一条原则：**能改简历的不能上网，能上网的不能改简历**。
调研员可以查外部信息但无权写简历；撰写员能写简历但拿不到检索通道，
这样"抄来的漂亮话"进不了简历，也逼着撰写员只用事实库。
"""

from __future__ import annotations

from typing import Any

from .. import schemas
from .base import AgentSpec, Perm

JD_ANALYST = AgentSpec(
    key="jd_analyst",
    title="JD 分析员",
    prompt_file="jd_analyst.md",
    permissions=(Perm.READ_JD,),
    note="只读 JD，产出岗位画像与关键词，不碰简历。",
)

RESEARCHER = AgentSpec(
    key="researcher",
    title="调研员",
    prompt_file="researcher.md",
    permissions=(Perm.READ_JD, Perm.SEARCH_WEB, Perm.READ_RESEARCH),
    temperature=0.2,
    note="唯一有联网权限的角色；只产出带来源的结论，不写简历。",
)

FACT_EXTRACTOR = AgentSpec(
    key="fact_extractor",
    title="事实库构建员",
    prompt_file="fact_extractor.md",
    permissions=(Perm.READ_RESUME,),
    temperature=0.1,
    note="只读旧简历与补充信息，产出可引用的原子事实；不调用模型以外的信息。",
)

STRATEGIST = AgentSpec(
    key="strategist",
    title="定位策略师",
    prompt_file="strategist.md",
    permissions=(Perm.READ_JD, Perm.READ_FACTS, Perm.READ_RESEARCH),
    temperature=0.5,
    note="决定讲哪个故事、删什么；不改写具体句子上线。",
)

WRITER = AgentSpec(
    key="writer",
    title="简历撰写员",
    prompt_file="writer.md",
    permissions=(Perm.READ_JD, Perm.READ_FACTS, Perm.READ_RESEARCH, Perm.WRITE_RESUME),
    temperature=0.35,
    note="唯一有写简历权限的角色；无联网权限，只能引用事实库。",
)

CRITIC = AgentSpec(
    key="critic",
    title="质检员",
    prompt_file="critic.md",
    permissions=(Perm.READ_JD, Perm.READ_FACTS, Perm.READ_RESUME),
    temperature=0.2,
    note="模拟会淘汰人的面试官；只出问题，不给最终稿。",
)

REVISER = AgentSpec(
    key="reviser",
    title="修订员",
    prompt_file="reviser.md",
    permissions=(Perm.READ_JD, Perm.READ_FACTS, Perm.READ_RESUME, Perm.WRITE_RESUME),
    temperature=0.25,
    note="按质检意见定点修改，禁止新增数字；沿用 writer 的岗位变体规则。",
    variant_stem="writer",
)

COACH = AgentSpec(
    key="coach",
    title="面试教练",
    prompt_file="coach.md",
    permissions=(Perm.READ_JD, Perm.READ_RESUME, Perm.READ_RESEARCH),
    temperature=0.6,
    note="只读最终简历，产出速查卡；不改简历。",
)

ALL_AGENTS = (JD_ANALYST, RESEARCHER, FACT_EXTRACTOR, STRATEGIST, WRITER, CRITIC, REVISER, COACH)


# ---------------- 输入装配 + 规范化 ----------------
def jd_vars(ctx: Any) -> dict[str, Any]:
    return {
        "role_hint": ctx.inputs.get("role_hint") or "（未指定，按 JD 自行判断）",
        "jd_text": ctx.inputs.get("jd_text") or "（空）",
        "research_brief": ctx.state.get("research_brief") or "（无）",
    }


def post_jd(raw: dict, ctx: Any) -> tuple[dict, dict]:
    return raw, schemas.normalize_jd_profile(raw, ctx.inputs.get("role_hint", ""))


def research_vars(ctx: Any) -> dict[str, Any]:
    return {
        "jd_profile": ctx.state["jd_profile"],
        "search_results": ctx.state.get("search_results") or "（本机未启用检索或没有结果）",
    }


def post_research(raw: dict, ctx: Any) -> tuple[dict, dict]:
    findings = []
    for item in raw.get("findings") or []:
        if isinstance(item, dict) and item.get("claim"):
            findings.append(
                {
                    "claim": str(item.get("claim", "")).strip(),
                    "source": str(item.get("source", "")).strip(),
                    "date": str(item.get("date", "")).strip(),
                    "reliability": str(item.get("reliability", "low")).strip() or "low",
                }
            )
    data = {
        "findings": findings,
        "interview_process": [str(x) for x in raw.get("interview_process") or [] if str(x).strip()],
        "screening_signals": [str(x) for x in raw.get("screening_signals") or [] if str(x).strip()],
        "resume_hints": [str(x) for x in raw.get("resume_hints") or [] if str(x).strip()],
        "questions_to_ask": [str(x) for x in raw.get("questions_to_ask") or [] if str(x).strip()],
        "gaps": [str(x) for x in raw.get("gaps") or [] if str(x).strip()],
    }
    return raw, data


def facts_vars(ctx: Any) -> dict[str, Any]:
    return {
        "resume_text": ctx.inputs.get("resume_text") or "（空）",
        "info_text": ctx.inputs.get("info_text") or "（空）",
    }


def post_facts(raw: dict, ctx: Any) -> tuple[dict, dict]:
    return raw, schemas.normalize_facts(raw)


def strategy_vars(ctx: Any) -> dict[str, Any]:
    return {
        "jd_profile": ctx.state["jd_profile"],
        "facts": schemas.facts_as_prompt(ctx.state["facts"]),
        "research_brief": ctx.state.get("research_brief") or "（无）",
    }


def post_strategy(raw: dict, ctx: Any) -> tuple[dict, dict]:
    return raw, schemas.normalize_positioning(raw)


def writer_vars(ctx: Any) -> dict[str, Any]:
    return {
        "jd_profile": ctx.state["jd_profile"],
        "positioning": ctx.state["positioning"],
        "facts": schemas.facts_as_prompt(ctx.state["facts"]),
        "research_brief": ctx.state.get("research_brief") or "（无）",
        "issues": ctx.state.get("issues_text") or "（首轮无意见）",
    }


def post_resume(raw: dict, ctx: Any) -> tuple[dict, dict]:
    return raw, schemas.normalize_resume(raw)


def critic_vars(ctx: Any) -> dict[str, Any]:
    return {
        "jd_profile": ctx.state["jd_profile"],
        "resume_json": ctx.state["resume"],
        "facts": schemas.facts_as_prompt(ctx.state["facts"]),
        "deterministic": ctx.state.get("issues_text") or "（机器检查未发现问题）",
    }


def post_critic(raw: dict, ctx: Any) -> tuple[dict, dict]:
    data = {
        "pass": bool(raw.get("pass")),
        "verdict": str(raw.get("verdict", "")).strip(),
        "issues": [
            {
                "severity": str(i.get("severity", "warn")),
                "kind": str(i.get("kind", "other")),
                "where": str(i.get("where", "")),
                "problem": str(i.get("problem", "")),
                "fix": str(i.get("fix", "")),
            }
            for i in raw.get("issues") or []
            if isinstance(i, dict)
        ],
        "strengths": [str(x) for x in raw.get("strengths") or []],
        "top_fix": str(raw.get("top_fix", "")),
    }
    return raw, data


def reviser_vars(ctx: Any) -> dict[str, Any]:
    return {
        "resume_json": ctx.state["resume"],
        "issues": ctx.state.get("review_issues") or [],
        "facts": schemas.facts_as_prompt(ctx.state["facts"]),
        "jd_profile": ctx.state["jd_profile"],
        "missing_keywords": ctx.state.get("missing_keywords") or [],
    }


def coach_vars(ctx: Any) -> dict[str, Any]:
    return {
        "jd_profile": ctx.state["jd_profile"],
        "resume_json": ctx.state["resume"],
        "research_brief": ctx.state.get("research_brief") or "（无）",
    }


def post_coach(raw: dict, ctx: Any) -> tuple[dict, dict]:
    return raw, schemas.normalize_card(raw)
